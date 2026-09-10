#!/usr/bin/env node
// Standalone launcher for the TPS overlay, without installing the plugin.
// Replaces the old start_monitor.bat, which hardcoded one machine's pythonw.exe.
//
//   node start.mjs          start the overlay (detached, no console)
//   node start.mjs --stop   stop it

import { resolveInterpreter, SETUP_HINT } from "./plugins/zcode-tps-overlay/lib/python.mjs";
import { clearPid, readPid, startOverlay, waitForPid } from "./plugins/zcode-tps-overlay/lib/overlay.mjs";

if (process.argv.includes("--stop")) {
  const pid = readPid();
  if (!pid) {
    console.log("Overlay is not running.");
  } else if (process.platform === "win32") {
    const { spawnSync } = await import("node:child_process");
    const r = spawnSync("taskkill", ["/PID", String(pid), "/F"], { encoding: "utf8", windowsHide: true });
    clearPid();
    console.log(r.status === 0 ? `Overlay stopped (pid ${pid}).` : `Failed to stop pid ${pid}.`);
  } else {
    try {
      process.kill(pid, "SIGTERM");
      clearPid();
      console.log(`Overlay stopped (pid ${pid}).`);
    } catch (err) {
      console.log(`Failed to stop pid ${pid}: ${err.message}`);
    }
  }
  process.exit(0);
}

const pid = readPid();
if (pid) {
  console.log(`Overlay already running (pid ${pid}).`);
  process.exit(0);
}

const res = resolveInterpreter({ heal: true });
if (!res.ok) {
  console.error(SETUP_HINT);
  for (const a of res.attempts) console.error(`  ${a.path}  -> ${a.reason}`);
  process.exit(1);
}

startOverlay(res.path);
const started = await waitForPid();
if (started) {
  console.log(`Overlay started (pid ${started}) using ${res.path} (v${res.version}, via ${res.source}).`);
} else {
  console.error("Overlay did not publish a pid file; check ~/.zcode/tps.log.");
  process.exit(1);
}
