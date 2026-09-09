"""Register this GitHub repository as a ZCode plugin marketplace (idempotent).

After running, open ZCode -> Settings -> Plugin Management -> Discover, refresh,
and install "zcode-tps-overlay". (You can also add the marketplace manually with
the "+" button using the GitHub repo FrankZhangIronly/zcode-tps.)

Run: python install.py
"""

import json
import time
from pathlib import Path

HOME = Path.home()
ZCODE = HOME / ".zcode"
REPO = "FrankZhangIronly/zcode-tps"
MARKETPLACE_ID = "zcode-tps"
PLUGIN_ID = "zcode-tps-overlay@zcode-tps"
KNOWN = ZCODE / "cli" / "plugins" / "known_marketplaces.json"


def main():
    data = {"version": 1, "marketplaces": []}
    if KNOWN.exists():
        data.update(json.loads(KNOWN.read_text(encoding="utf-8")))
    markets = [m for m in data.get("marketplaces", []) if m.get("id") != MARKETPLACE_ID]
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    markets.append({
        "id": MARKETPLACE_ID,
        "source": {"source": "github", "repo": REPO},
        "name": MARKETPLACE_ID,
        "description": "Open-source ZCode plugins: TPS/TTFT floating-window monitor.",
        "addedAt": now,
        "pluginCount": 1,
        "lastUpdated": now,
    })
    data["marketplaces"] = markets
    KNOWN.parent.mkdir(parents=True, exist_ok=True)
    KNOWN.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"registered marketplace '{MARKETPLACE_ID}' ({REPO}) in {KNOWN}")
    print('open ZCode -> Settings -> Plugin Management -> Discover, refresh,')
    print(f'then install "{PLUGIN_ID}".')


if __name__ == "__main__":
    main()
