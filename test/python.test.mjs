// Unit tests for the interpreter resolver. Run: node --test
//
// These exercise the classification and precedence logic plus a real probe
// against whatever interpreter this host has. Nothing here writes to
// ~/.zcode: every call passes heal=false.

import assert from "node:assert/strict";
import test from "node:test";

import {
  IS_WIN,
  candidates,
  classifyFailure,
  discover,
  mergeConfig,
  probe,
  resolveInterpreter,
  windowlessExe,
} from "../plugins/zcode-tps-overlay/lib/python.mjs";

test("classifyFailure maps exit codes and stderr to a reason", () => {
  assert.match(classifyFailure(49, "Python was not found"), /Store stub/);
  assert.equal(
    classifyFailure(1, "Traceback:\nModuleNotFoundError: No module named 'tkinter'"),
    "missing required module: tkinter",
  );
  assert.match(classifyFailure(4, ""), /3\.8\+ required/);
  assert.match(classifyFailure(null, ""), /timed out/);
  assert.equal(classifyFailure(1, "boom\nlast line here"), "last line here");
});

test("probe rejects a missing interpreter", () => {
  const r = probe(IS_WIN ? "C:\\nope\\python.exe" : "/nope/python3");
  assert.equal(r.ok, false);
  assert.equal(r.reason, "not found");
});

test("probe rejects pythonw, which cannot serve MCP stdio", () => {
  const r = probe(IS_WIN ? "C:\\x\\pythonw.exe" : "/x/pythonw");
  assert.equal(r.ok, false);
  assert.match(r.reason, /pythonw/);
});

test("probe accepts a real interpreter with tkinter and sqlite3", () => {
  const d = discover();
  assert.equal(d.ok, true, `no usable interpreter on this host: ${JSON.stringify(d.tried)}`);
  assert.match(d.version, /^3\.\d+$/);
  const p = probe(d.path);
  assert.equal(p.ok, true);
});

test("candidates are unique and every skip carries a reason", () => {
  const { list, skipped } = candidates();
  const seen = new Set();
  for (const c of list) {
    assert.equal(c.source.length > 0, true);
    const key = IS_WIN ? c.path.toLowerCase() : c.path;
    assert.equal(seen.has(key), false, `duplicate candidate ${c.path}`);
    seen.add(key);
  }
  for (const s of skipped) {
    assert.equal(typeof s.path, "string");
    assert.equal(typeof s.reason, "string");
  }
});

test("mergeConfig keeps unrelated keys, so patching python never drops language", () => {
  const merged = mergeConfig({ language: "zh", autostart: false }, { python: "/p/python3" });
  assert.deepEqual(merged, { language: "zh", autostart: false, python: "/p/python3" });
});

test("an explicit interpreter wins and is reported as source=flag", () => {
  const d = discover();
  assert.equal(d.ok, true);
  const r = resolveInterpreter({ explicit: d.path });
  assert.equal(r.ok, true);
  assert.equal(r.source, "flag");
  assert.equal(r.path, d.path);
  // heal=false: attempts are reported but nothing is persisted
  assert.equal(r.attempts.length, 1);
  assert.equal(r.attempts[0].ok, true);
});

test("a bad explicit path falls through to auto-discovery", () => {
  const bad = IS_WIN ? "C:\\nope\\python.exe" : "/nope/python3";
  const r = resolveInterpreter({ explicit: bad });
  assert.equal(r.ok, true, "auto-discovery should still find an interpreter");
  assert.notEqual(r.source, "flag");
  assert.equal(r.attempts[0].path, bad);
  assert.equal(r.attempts[0].ok, false);
});

test("windowlessExe only swaps a console python.exe for its sibling pythonw.exe", () => {
  assert.equal(windowlessExe("/usr/bin/python3"), "/usr/bin/python3");
  if (IS_WIN) {
    assert.equal(windowlessExe("D:\\x\\pythonw.exe"), "D:\\x\\pythonw.exe");
    // no sibling pythonw next to this path, so it must be returned unchanged
    assert.equal(windowlessExe("C:\\nope\\python.exe"), "C:\\nope\\python.exe");
  }
});
