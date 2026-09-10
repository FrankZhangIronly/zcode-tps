// Overlay process helpers shared by the SessionStart hook, the tps-setup skill
// and the standalone starter: pid file, liveness, detached launch.
//
// Everything here is cross-platform; the only OS-specific parts are the
// detachment flags and how a process's liveness/identity is established.

import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { IS_WIN, ZCODE_DIR, windowlessExe } from "./python.mjs";

export const PID_PATH = path.join(ZCODE_DIR, "tps.pid");
const HERE = path.dirname(fileURLToPath(import.meta.url));
export const OVERLAY_PATH = path.join(HERE, "..", "overlay", "tps_monitor.py");

/** True if a process with this pid exists and is signalable by us. */
export function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    // EPERM means it exists but belongs to another user; still "alive".
    return err && err.code === "EPERM";
  }
}

/** The image name of a running pid, or null when it cannot be determined. */
function processName(pid) {
  try {
    if (IS_WIN) {
      const r = spawnSync("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], {
        encoding: "utf8",
        timeout: 5000,
        windowsHide: true,
      });
      const m = /"([^"]+)"/.exec(r.stdout || "");
      return m ? m[1].toLowerCase() : null;
    }
    const r = spawnSync("ps", ["-p", String(pid), "-o", "comm="], {
      encoding: "utf8",
      timeout: 5000,
    });
    if (r.error) return null;
    const name = (r.stdout || "").trim().split("/").pop();
    return name ? name.toLowerCase() : null;
  } catch {
    return null;
  }
}

/**
 * Overlay pid from the pid file, or null. Guards against pid reuse by requiring
 * the process to actually be a Python interpreter, and clears stale entries.
 */
export function readPid() {
  let pid;
  try {
    pid = parseInt(fs.readFileSync(PID_PATH, "utf8").trim(), 10);
  } catch {
    return null;
  }
  if (!pidAlive(pid)) {
    clearPid();
    return null;
  }
  const name = processName(pid);
  if (name && !/^python/.test(name)) {
    clearPid(); // pid was recycled by an unrelated process
    return null;
  }
  return pid;
}

export function writePid(pid) {
  try {
    fs.mkdirSync(ZCODE_DIR, { recursive: true });
    fs.writeFileSync(PID_PATH, String(pid), "utf8");
  } catch {}
}

export function clearPid() {
  try {
    fs.unlinkSync(PID_PATH);
  } catch {}
}

/**
 * Launch the overlay as a detached GUI process. The interpreter is passed
 * through as-is for POSIX; on Windows windowlessExe() avoids a console window.
 * Returns the spawned child (already unref'd).
 */
export function startOverlay(py) {
  const exe = windowlessExe(py);
  const child = spawn(exe, [OVERLAY_PATH], {
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.unref();
  return child;
}

/** Wait for the detached overlay to publish its pid, up to timeoutMs. */
export async function waitForPid(timeoutMs = 1500) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const pid = readPid();
    if (pid) return pid;
    if (Date.now() >= deadline) return null;
    await new Promise((r) => setTimeout(r, 100));
  }
}

export const MCP_TOOLS =
  "tps_start/tps_stop/tps_status/tps_language/tps_session_stats";

/**
 * The SessionStart hook's model-facing message. Kept as a pure function because
 * the missing-interpreter branch is the only channel that can tell the model why
 * the tps_* tools are absent (a failed MCP server surfaces no error to it), and
 * that branch cannot be exercised on a host that happens to have Python.
 */
export function sessionStartContext({ autostart, pid, resolved, started }) {
  if (!autostart) {
    return { state: "overlay not started (autostart off)", extra: "" };
  }
  if (pid) {
    return { state: `overlay already running (pid ${pid})`, extra: "" };
  }
  if (!resolved) {
    return {
      state: "overlay not started (no usable Python found)",
      extra:
        " No Python 3.8+ with tkinter/sqlite3 was found on this host, so the tps_* MCP tools " +
        "are unavailable. Invoke the 'zcode-tps-overlay:tps-setup' skill to locate and configure " +
        "an interpreter, then tell the user the session must be restarted for the MCP tools to load.",
    };
  }
  return started
    ? { state: `overlay auto-started (pid ${started})`, extra: "" }
    : {
        state: "overlay launch requested",
        extra: " The overlay did not publish a pid file; check ~/.zcode/tps.log.",
      };
}
