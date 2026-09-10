#!/usr/bin/env node
// Register this GitHub repository as a ZCode plugin marketplace (idempotent).
//
// Replaces install.py, whose documented command (`python install.py`) is itself
// unusable on a host with no real Python — the same problem this release fixes.
//
//   node install.mjs
//
// Afterwards: ZCode -> Settings -> Plugin Management -> Discover, refresh, then
// install "zcode-tps-overlay". You can also add the marketplace with "+" using
// the GitHub repo below.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const REPO = "FrankZhangIronly/zcode-tps";
const MARKETPLACE_ID = "zcode-tps";
const PLUGIN_ID = "zcode-tps-overlay@zcode-tps";
const KNOWN = path.join(os.homedir(), ".zcode", "cli", "plugins", "known_marketplaces.json");

let data = { version: 1, marketplaces: [] };
try {
  data = { ...data, ...JSON.parse(fs.readFileSync(KNOWN, "utf8")) };
} catch {}

const now = `${new Date().toISOString().replace(/\.\d{3}Z$/, "")}.000Z`;
const markets = (Array.isArray(data.marketplaces) ? data.marketplaces : []).filter(
  (m) => m && m.id !== MARKETPLACE_ID,
);
markets.push({
  id: MARKETPLACE_ID,
  source: { source: "github", repo: REPO },
  name: MARKETPLACE_ID,
  description: "Open-source ZCode plugins: TPS/TTFT floating-window monitor.",
  addedAt: now,
  pluginCount: 1,
  lastUpdated: now,
});
data.marketplaces = markets;

fs.mkdirSync(path.dirname(KNOWN), { recursive: true });
fs.writeFileSync(KNOWN, `${JSON.stringify(data, null, 2)}\n`, "utf8");

console.log(`registered marketplace '${MARKETPLACE_ID}' (${REPO}) in ${KNOWN}`);
console.log("open ZCode -> Settings -> Plugin Management -> Discover, refresh,");
console.log(`then install "${PLUGIN_ID}".`);
