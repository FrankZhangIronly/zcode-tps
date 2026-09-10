#!/usr/bin/env node
// MCP stdio entry point for zcode-tps-overlay.
//
// ZCode launches this with plain `node` (see .mcp.json), because command/args
// there are static strings that cannot express "the host's Python interpreter".
// This shim resolves the interpreter at runtime and hands stdio straight to the
// real Python MCP server, so the JSON-RPC byte stream is untouched.
//
// Zero dependencies.

import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

import { resolveInterpreter, SETUP_HINT } from "../lib/python.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = path.join(HERE, "tps_server.py");

const res = resolveInterpreter({ heal: true });
if (!res.ok) {
  process.stderr.write(`[zcode-tps] ${SETUP_HINT}\n`);
  process.exit(1);
}

const child = spawn(res.path, [SERVER], {
  stdio: "inherit", // MCP stdio passes through byte for byte
  windowsHide: true,
});

for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
  process.on(sig, () => {
    try {
      child.kill(sig);
    } catch {}
  });
}

child.on("error", (err) => {
  process.stderr.write(`[zcode-tps] failed to start ${res.path}: ${err.message}\n`);
  process.exit(1);
});

// Mirror the server's lifetime and exit status so ZCode sees a normal lifecycle.
child.on("exit", (code, signal) => {
  process.exit(signal ? 1 : (code ?? 0));
});
