// Interpreter resolution for the ZCode TPS plugin.
//
// Nothing about the host's Python is hardcoded: the interpreter is resolved at
// runtime and shared by the MCP launcher, the SessionStart hook, the setup
// skill and the standalone starter. Zero dependencies (node: builtins only).
//
// Precedence: explicit path > TPS_PYTHON > ~/.zcode/tps.json "python" > auto.
//
// Only console interpreters are ever resolved: pythonw.exe has no stdout and
// therefore cannot serve MCP's stdio transport. Callers that need to launch the
// GUI derive it separately with windowlessExe().

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

export const IS_WIN = process.platform === "win32";
export const ZCODE_DIR = path.join(os.homedir(), ".zcode");
export const CONFIG_PATH = path.join(ZCODE_DIR, "tps.json");
export const LOG_PATH = path.join(ZCODE_DIR, "tps.log");

const MIN_PY = [3, 8];
const EXE = IS_WIN ? ".exe" : "";
const PROBE_TIMEOUT_MS = 5000;
const MAX_PROBES = 30;
const PROBE_CODE =
  "import sys, tkinter, sqlite3; " +
  "print('.'.join(map(str, sys.version_info[:2]))); " +
  `sys.exit(0 if sys.version_info >= (${MIN_PY[0]}, ${MIN_PY[1]}) else 4)`;

// ---------------------------------------------------------------- config

export function readConfig() {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
    return cfg && typeof cfg === "object" ? cfg : {};
  } catch {
    return {};
  }
}

export function mergeConfig(base, patch) {
  return { ...base, ...patch };
}

export function patchConfig(patch) {
  const cfg = mergeConfig(readConfig(), patch);
  try {
    fs.mkdirSync(ZCODE_DIR, { recursive: true });
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), "utf8");
    return cfg;
  } catch {
    return null;
  }
}

export function logLine(msg) {
  try {
    fs.mkdirSync(ZCODE_DIR, { recursive: true });
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    const ts = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
      `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    fs.appendFileSync(LOG_PATH, `${ts} ${msg}\n`, "utf8");
  } catch {}
}

// ---------------------------------------------------------------- probing

export function classifyFailure(status, stderr) {
  if (status === null || status === undefined) return "timed out or was killed";
  if (status === 49) return "Microsoft Store stub, not a real interpreter";
  const missing = /ModuleNotFoundError: No module named '([^']+)'/.exec(stderr || "");
  if (missing) return `missing required module: ${missing[1]}`;
  if (status === 4) return `Python ${MIN_PY.join(".")}+ required`;
  const last = (stderr || "").split(/\r?\n/).filter((l) => l.trim()).pop();
  return last ? last.trim().slice(-160) : `exit code ${status}`;
}

export function probe(py) {
  if (!py) return { ok: false, reason: "no path" };
  if (/^pythonw(\.exe)?$/i.test(path.basename(py))) {
    return { ok: false, reason: "pythonw.exe has no stdout, so it cannot serve MCP stdio" };
  }
  let r;
  try {
    r = spawnSync(py, ["-c", PROBE_CODE], {
      encoding: "utf8",
      timeout: PROBE_TIMEOUT_MS,
      windowsHide: true,
    });
  } catch (err) {
    return { ok: false, reason: String((err && err.message) || err) };
  }
  if (r.error) {
    const code = r.error.code || "";
    return { ok: false, reason: code === "ENOENT" ? "not found" : code || r.error.message };
  }
  if (r.status === 0) {
    return { ok: true, version: (r.stdout || "").trim() || null };
  }
  return { ok: false, reason: classifyFailure(r.status, r.stderr) };
}

/** Sibling pythonw.exe when it exists, so the GUI starts without a console. */
export function windowlessExe(py) {
  if (!IS_WIN || path.basename(py).toLowerCase() !== "python.exe") return py;
  const w = path.join(path.dirname(py), "pythonw.exe");
  return isFile(w) ? w : py;
}

// ---------------------------------------------------------- candidate sources

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function readdirDirs(base, re) {
  try {
    return fs
      .readdirSync(base)
      .filter((n) => re.test(n))
      .map((n) => path.join(base, n));
  } catch {
    return [];
  }
}

function versionDesc(entries) {
  return entries.slice().sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
}

function fromPath(names) {
  const out = [];
  const dirs = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
  for (const name of names) {
    for (const d of dirs) {
      const p = path.join(d, name + EXE);
      if (isFile(p)) out.push(p);
    }
  }
  return out;
}

function fromPyLauncher() {
  if (!IS_WIN) return [];
  const r = spawnSync("py", ["-0p"], { encoding: "utf8", timeout: PROBE_TIMEOUT_MS, windowsHide: true });
  if (r.error || typeof r.stdout !== "string") return [];
  const out = [];
  for (const line of r.stdout.split(/\r?\n/)) {
    // " -V:3.12 *        C:\path\to\python.exe" — capture from the drive
    // letter on, so paths containing spaces survive.
    const m = /([A-Za-z]:\\.*?)\s*$/.exec(line.trim());
    if (m && /\.exe$/i.test(m[1])) out.push(m[1]);
  }
  return out;
}

function fromStandardInstall() {
  const out = [];
  if (IS_WIN) {
    const roots = [
      process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Programs", "Python"),
      process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Python"),
      process.env["PROGRAMFILES(X86)"] && path.join(process.env["PROGRAMFILES(X86)"], "Python"),
    ].filter(Boolean);
    for (const root of roots) {
      for (const d of versionDesc(readdirDirs(root, /^Python\d/i))) {
        out.push(path.join(d, "python.exe"));
      }
    }
    for (let c = 65; c <= 90; c++) {
      const drive = `${String.fromCharCode(c)}:\\`;
      for (const d of versionDesc(readdirDirs(drive, /^Python3/i))) {
        out.push(path.join(d, "python.exe"));
      }
    }
    return out;
  }
  out.push(
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
    "/usr/local/bin/python",
    "/usr/bin/python",
  );
  for (const d of versionDesc(readdirDirs("/opt", /^python3/i))) {
    out.push(path.join(d, "bin", "python3"));
  }
  for (const d of versionDesc(readdirDirs("/Library/Frameworks/Python.framework/Versions", /^3\./))) {
    out.push(path.join(d, "bin", "python3"));
  }
  return out;
}

// A conda env's interpreter, for a conda *root* or any env dir inside it.
function condaPy(dir) {
  return IS_WIN ? path.join(dir, "python.exe") : path.join(dir, "bin", "python3");
}

function fromConda() {
  const out = [];
  const conda = fromPath(["conda"])[0];
  if (conda) {
    const r = spawnSync(conda, ["info", "--envs"], {
      encoding: "utf8",
      timeout: PROBE_TIMEOUT_MS,
      windowsHide: true,
      shell: /\.(bat|cmd)$/i.test(conda),
    });
    const text = `${r.stdout || ""}\n${r.stderr || ""}`;
    for (const line of text.split(/\r?\n/)) {
      const s = line.trim();
      if (!s || s.startsWith("#")) continue;
      // "myenv   *   C:\path\to\conda\envs\myenv" — the env path is the last column.
      const cols = s.split(/\s{2,}/).map((x) => x.trim()).filter(Boolean);
      const last = cols[cols.length - 1];
      if (last && /[\\/]/.test(last)) out.push(condaPy(last));
    }
  }
  const nameRe = /^(mini|mamba|micro)?(conda|forge|mamba)\d*$/i;
  const bases = [os.homedir(), process.env.LOCALAPPDATA, process.env.PROGRAMDATA, "/opt", "/usr/local"]
    .filter(Boolean);
  const roots = [];
  for (const b of bases) roots.push(...readdirDirs(b, nameRe));
  if (IS_WIN) {
    for (let c = 65; c <= 90; c++) {
      const drive = `${String.fromCharCode(c)}:\\`;
      if (!fs.existsSync(drive)) continue;
      roots.push(...readdirDirs(drive, nameRe));
    }
  }
  for (const root of roots) {
    out.push(condaPy(root)); // base env: the most durable choice
    for (const env of readdirDirs(path.join(root, "envs"), /./).sort()) {
      out.push(condaPy(env));
    }
  }
  return out;
}

/**
 * Candidate interpreters in preference order, plus the paths that looked like
 * interpreters but were skipped. `skipped` exists for diagnosis: on Windows the
 * single most likely reason for "no Python found" is that the only python.exe on
 * PATH is the Microsoft Store alias, which stat() cannot even read (EACCES).
 */
export function candidates() {
  const list = [];
  const skipped = [];
  const seen = new Set();
  const add = (p, source) => {
    if (!p) return;
    let key;
    try {
      key = IS_WIN ? path.resolve(p).toLowerCase() : path.resolve(p);
    } catch {
      return;
    }
    if (seen.has(key)) return;
    seen.add(key);
    let st;
    try {
      st = fs.statSync(p);
    } catch (err) {
      skipped.push({ path: p, source, reason: err.code || String(err) });
      return;
    }
    if (!st.isFile()) {
      skipped.push({ path: p, source, reason: "not a file" });
      return;
    }
    list.push({ path: p, source });
  };
  for (const p of fromPyLauncher()) add(p, "py launcher");
  for (const p of fromPath(IS_WIN ? ["python3", "python"] : ["python3", "python"])) add(p, "PATH");
  for (const p of fromStandardInstall()) add(p, "standard install");
  for (const p of fromConda()) add(p, "conda");
  return { list, skipped };
}

export function discover({ budgetMs = 20000 } = {}) {
  const { list, skipped } = candidates();
  const deadline = Date.now() + budgetMs;
  const tried = [];
  for (const cand of list.slice(0, MAX_PROBES)) {
    if (tried.length && Date.now() > deadline) {
      skipped.push({ path: "", source: "budget", reason: `discovery budget of ${budgetMs}ms exhausted` });
      break;
    }
    const r = probe(cand.path);
    tried.push({ ...cand, ...r });
    if (r.ok) return { ok: true, path: cand.path, source: cand.source, version: r.version, tried, skipped };
  }
  return { ok: false, tried, skipped };
}

// ---------------------------------------------------------------- resolve

/**
 * Resolve a usable interpreter. With heal=true, a working interpreter found by
 * any means is persisted to ~/.zcode/tps.json, which both records the first-run
 * choice and repairs a stale entry (e.g. after the host's Python was removed).
 */
export function resolveInterpreter({ explicit = null, heal = false, budgetMs } = {}) {
  const cfg = readConfig();
  const attempts = [];
  const tryOne = (py, source) => {
    if (!py) return null;
    const r = probe(py);
    attempts.push({ path: py, source, ...r });
    return r.ok ? { path: py, source, version: r.version } : null;
  };

  let hit =
    tryOne(explicit, "flag") ||
    tryOne(process.env.TPS_PYTHON, "env") ||
    tryOne(cfg.python, "config");
  if (!hit) {
    const d = discover(budgetMs === undefined ? {} : { budgetMs });
    attempts.push(...d.tried);
    if (d.ok) hit = { path: d.path, source: d.source, version: d.version };
  }
  if (!hit) return { ok: false, attempts };

  if (heal && hit.source !== "config" && cfg.python !== hit.path) {
    patchConfig({ python: hit.path });
    logLine(`interpreter ${cfg.python ? "re-resolved" : "configured"} (${hit.source}): ${hit.path}`);
  }
  return { ok: true, ...hit, attempts };
}

/** One-line hint pointing at the fix, used by every failure path. */
export const SETUP_HINT =
  "No usable Python found. Ask the model to run the 'zcode-tps-overlay:tps-setup' skill, " +
  "or set TPS_PYTHON to a Python 3.8+ interpreter that has tkinter and sqlite3.";
