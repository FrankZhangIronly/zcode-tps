#!/usr/bin/env node
// First-run setup for zcode-tps-overlay: find a usable Python on this host,
// persist it to ~/.zcode/tps.json, and (optionally) start the overlay.
//
// Driven by the tps-setup skill, and usable standalone. Zero dependencies.
//
//   node setup.mjs                     discover, report, configure
//   node setup.mjs --start             ... and start the overlay
//   node setup.mjs --python <path>     use this interpreter
//   node setup.mjs --json              machine-readable result

import path from "node:path";

import {
  IS_WIN,
  readConfig,
  resolveInterpreter,
  SETUP_HINT,
  ZCODE_DIR,
} from "../../lib/python.mjs";
import { readPid, startOverlay, waitForPid } from "../../lib/overlay.mjs";

const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const value = (f) => {
  const i = argv.indexOf(f);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : null;
};

const wantJson = has("--json");
const wantStart = has("--start");
const explicit = value("--python");

// Interpreters that a user can plausibly already have, per platform. Only
// printed as advice when discovery fails; never executed.
const INSTALL_HINT = IS_WIN
  ? "winget install Python.Python.3.12   (or https://www.python.org/downloads/ — " +
    "tick 'Add python.exe to PATH' and leave 'tcl/tk' enabled)"
  : process.platform === "darwin"
    ? "brew install python-tk   (the python.org installer also works; note that " +
      "Xcode's /usr/bin/python3 has no tkinter and cannot be used)"
    : "sudo apt install python3-tk   (Debian/Ubuntu)  ·  " +
      "sudo dnf install python3-tkinter   (Fedora)  ·  sudo pacman -S tk   (Arch)";

const cfgBefore = readConfig();
const res = resolveInterpreter({ explicit, heal: true });

const out = {
  configured: res.ok,
  python: res.ok ? res.path : null,
  source: res.ok ? res.source : null,
  version: res.ok ? res.version : null,
  configPath: path.join(ZCODE_DIR, "tps.json"),
  configBefore: cfgBefore.python ?? null,
  attempts: res.attempts,
  skipped: res.skipped || [],
  overlay: null,
};

if (res.ok && wantStart) {
  const existing = readPid();
  if (existing) {
    out.overlay = { state: "already-running", pid: existing };
  } else {
    startOverlay(res.path);
    const pid = await waitForPid();
    out.overlay = pid ? { state: "started", pid } : { state: "not-confirmed" };
  }
}

if (wantJson) {
  console.log(JSON.stringify(out, null, 2));
} else if (res.ok) {
  if (out.configBefore && out.configBefore !== res.path) {
    console.log(`Updated stale interpreter path in tps.json`);
  }
  console.log(`Python: ${res.path}  (v${res.version}, found via ${res.source})`);
  console.log(`Config: ${out.configPath}`);
  if (out.overlay) {
    const o = out.overlay;
    console.log(
      o.pid
        ? `Overlay: ${o.state} (pid ${o.pid})`
        : `Overlay: ${o.state} — check ~/.zcode/tps.log`,
    );
  }
  const shown = res.attempts.slice(0, 20);
  if (shown.length > 1) {
    console.log(`Probed ${res.attempts.length} candidate(s):`);
    for (const a of shown) {
      console.log(`  ${a.ok ? "ok  " : "fail"}  ${a.path}${a.ok ? "" : `  -> ${a.reason}`}`);
    }
  }
} else {
  console.log("No usable Python found.\n");
  if (res.attempts.length) {
    console.log("Candidates probed and rejected:");
    for (const a of res.attempts) console.log(`  ${a.path}  -> ${a.reason}`);
  } else {
    console.log("No candidates were found on this host.");
  }
  if (out.skipped.length) {
    console.log("\nPaths skipped before probing:");
    for (const s of out.skipped) console.log(`  ${s.path}  ->  ${s.reason}`);
    if (out.skipped.some((s) => s.reason === "EACCES")) {
      console.log(
        "\nNote: EACCES on a python.exe under WindowsApps means it is the Microsoft " +
          "Store stub, not a real interpreter.",
      );
    }
  }
  console.log(`\nInstall one, then re-run this script:\n  ${INSTALL_HINT}`);
  console.log(`\n${SETUP_HINT}`);
}

process.exit(res.ok ? 0 : 1);
