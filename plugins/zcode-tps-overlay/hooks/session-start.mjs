#!/usr/bin/env node
// SessionStart hook for zcode-tps:
// 1) record the current session id to ~/.zcode/tps.state.json (used by the
//    tps_session_stats MCP tool)
// 2) auto-start the floating overlay unless ~/.zcode/tps.json says
//    { "autostart": false } (default: on); a live pid file prevents duplicates

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

const home = os.homedir();
const zdir = path.join(home, ".zcode");
const stateFile = path.join(zdir, "tps.state.json");
const cfgFile = path.join(zdir, "tps.json");
const pidFile = path.join(zdir, "tps.pid");

const sid = process.env.ZCODE_SESSION_ID || process.env.CLAUDE_SESSION_ID || "";
try {
  fs.mkdirSync(zdir, { recursive: true });
  if (sid) fs.writeFileSync(stateFile, JSON.stringify({ sessionId: sid, ts: Date.now() }));
} catch {}

function overlayAlive() {
  try {
    const pid = parseInt(fs.readFileSync(pidFile, "utf8").trim(), 10);
    if (!pid) return false;
    // require the pid to actually be a pythonw.exe process (guards against pid reuse)
    const r = spawnSync("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], { encoding: "utf8" });
    return (r.stdout || "").includes('"pythonw.exe"');
  } catch {
    return false;
  }
}

let autostart = true;
try {
  autostart = JSON.parse(fs.readFileSync(cfgFile, "utf8")).autostart !== false;
} catch {}

let started = false;
if (autostart && !overlayAlive()) {
  const overlay = path.join(process.env.ZCODE_PLUGIN_ROOT || "", "overlay", "tps_monitor.py");
  const localPyw = "D:/miniconda3/envs/bonc/pythonw.exe";
  let py = "pythonw";
  try {
    if (fs.existsSync(localPyw)) py = localPyw;
  } catch {}
  try {
    const child = spawn(py, [overlay], { detached: true, stdio: "ignore" });
    child.unref();
    started = true;
  } catch {}
}

const state = started ? "overlay auto-started" : overlayAlive() ? "overlay already running" : "overlay not started (autostart off)";
process.stdout.write(
  JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: `[zcode-tps] ready (${state}). MCP tools: tps_start/tps_stop/tps_status/tps_language/tps_session_stats.`,
    },
  })
);
