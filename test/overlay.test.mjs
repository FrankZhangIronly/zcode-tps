// Tests for the overlay/session helpers. Run: node --test

import assert from "node:assert/strict";
import test from "node:test";

import { MCP_TOOLS, pidAlive, sessionStartContext } from "../plugins/zcode-tps-overlay/lib/overlay.mjs";

test("sessionStartContext: autostart off wins over everything else", () => {
  const r = sessionStartContext({ autostart: false, pid: 5, resolved: "/p", started: 6 });
  assert.match(r.state, /autostart off/);
  assert.equal(r.extra, "");
});

test("sessionStartContext: an already-running overlay is reported, not restarted", () => {
  const r = sessionStartContext({ autostart: true, pid: 4242, resolved: null, started: null });
  assert.match(r.state, /already running \(pid 4242\)/);
  assert.equal(r.extra, "");
});

test("sessionStartContext: missing interpreter points the model at the setup skill", () => {
  const r = sessionStartContext({ autostart: true, pid: null, resolved: null, started: null });
  assert.match(r.state, /no usable Python found/);
  // The model must be told which skill to invoke and that a restart is needed:
  // a failed MCP server gives it no other signal.
  assert.match(r.extra, /zcode-tps-overlay:tps-setup/);
  assert.match(r.extra, /restarted/);
});

test("sessionStartContext: a started overlay reports its pid", () => {
  const r = sessionStartContext({ autostart: true, pid: null, resolved: "/p", started: 99 });
  assert.match(r.state, /auto-started \(pid 99\)/);
  assert.equal(r.extra, "");
});

test("sessionStartContext: a launch that never published a pid is flagged", () => {
  const r = sessionStartContext({ autostart: true, pid: null, resolved: "/p", started: null });
  assert.match(r.state, /launch requested/);
  assert.match(r.extra, /tps\.log/);
});

test("MCP_TOOLS lists exactly the five tools", () => {
  const names = MCP_TOOLS.split("/");
  assert.deepEqual(names, [
    "tps_start",
    "tps_stop",
    "tps_status",
    "tps_language",
    "tps_session_stats",
  ]);
});

test("pidAlive rejects meaningless pids and accepts this process", () => {
  assert.equal(pidAlive(0), false);
  assert.equal(pidAlive(-1), false);
  assert.equal(pidAlive(1.5), false);
  assert.equal(pidAlive(process.pid), true);
});
