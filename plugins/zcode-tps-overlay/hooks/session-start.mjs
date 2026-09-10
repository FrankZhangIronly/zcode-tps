#!/usr/bin/env node
// SessionStart hook for zcode-tps:
// 1) record the current session id to ~/.zcode/tps.state.json (used by the
//    tps_session_stats MCP tool)
// 2) auto-start the floating overlay unless ~/.zcode/tps.json says
//    { "autostart": false } (default: on); a live pid file prevents duplicates
//
// The Python interpreter is resolved at runtime (never hardcoded). When none is
// usable, this hook is the only channel that can tell the model what to do: a
// failed MCP server surfaces no error to it, only missing tools.

import fs from "node:fs";
import path from "node:path";

import { ZCODE_DIR, resolveInterpreter, readConfig } from "../lib/python.mjs";
import { MCP_TOOLS, readPid, sessionStartContext, startOverlay, waitForPid } from "../lib/overlay.mjs";

const STATE_FILE = path.join(ZCODE_DIR, "tps.state.json");

const sid = process.env.ZCODE_SESSION_ID || process.env.CLAUDE_SESSION_ID || "";
try {
  fs.mkdirSync(ZCODE_DIR, { recursive: true });
  if (sid) fs.writeFileSync(STATE_FILE, JSON.stringify({ sessionId: sid, ts: Date.now() }));
} catch {}

const cfg = readConfig();
const autostart = cfg.autostart !== false;

let state;
let extra = "";
let resolved = null;
let started = null;
const pid = readPid();

if (autostart && !pid) {
  // Keep the whole hook inside its 3s timeout: a configured interpreter probes
  // in ~50ms, and discovery gets a small budget only for the unconfigured case.
  const configured = typeof cfg.python === "string" && cfg.python;
  const res = resolveInterpreter({ heal: true, budgetMs: configured ? 2000 : 1200 });
  if (res.ok) {
    resolved = res.path;
    startOverlay(resolved);
    started = await waitForPid(1200);
  }
}

({ state, extra } = sessionStartContext({ autostart, pid, resolved, started }));

process.stdout.write(
  JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: `[zcode-tps] ready (${state}).${extra} MCP tools: ${MCP_TOOLS}.`,
    },
  }),
);
