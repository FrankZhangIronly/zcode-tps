---
name: tps-setup
description: Configure the ZCode TPS floating-window monitor (zcode-tps-overlay) on this host by locating a usable Python interpreter and saving it to ~/.zcode/tps.json. Use when the TPS overlay does not appear, when the tps_* MCP tools are missing from the tool list, when the plugin was just installed or updated, or when the host's Python installation changed (reinstalled, moved, removed a conda env).
when_to_use: The overlay window is missing, the tps_start/tps_status MCP tools are absent, or this plugin was just installed on a new machine.
---

# Configure the TPS monitor's Python interpreter

`zcode-tps-overlay` needs a host Python 3.8+ with **tkinter** (the overlay window) and
**sqlite3** (reading ZCode's usage database). The interpreter is resolved at runtime and
stored in `~/.zcode/tps.json` — it is never hardcoded, so it must be located on each host.

## Step 1 — run the setup script

```bash
node "${ZCODE_SKILL_DIR}/setup.mjs" --start --json
```

`${ZCODE_SKILL_DIR}` is already expanded to this skill's absolute directory, so the command
works as written. `--start` also launches the overlay once a working interpreter is found
(or reports the already-running pid).

Interpret the result:

- **exit code 0** — done. Report the chosen interpreter path, its version, and the overlay
  state to the user, then read **Step 3** (the MCP restart caveat) and pass it on.
- **exit code 1** — no usable interpreter. The JSON lists `attempts` (found but rejected,
  with the reason) and `skipped` (looked like an interpreter but unreadable). Go to Step 2.

Common rejection reasons from `attempts`:

| Reason | Meaning |
|---|---|
| `not found` | Stale path, or a conda env that was removed |
| `missing required module: tkinter` | Real Python, but no Tk — very common for macOS Xcode's `/usr/bin/python3` and slim Linux containers |
| `missing required module: sqlite3` | Python built without SQLite; use a different interpreter |
| `Microsoft Store stub` | The `python.exe` on PATH is the Windows Store alias, not a real interpreter |
| `Python 3.8+ required` | Too old — ZCode's log timestamps need `datetime.fromisoformat` |

## Step 2 — find an interpreter the script could not

First ask the user whether they already know where their Python lives, and offer to search.
Ways to locate it, cheapest first:

- If the user names a path, verify it directly:
  ```bash
  "<path>" -c "import tkinter, sqlite3, sys; print(sys.version)"
  ```
- Look for an environment manager you know is installed (conda/mamba, pyenv, asdf, uv,
  Homebrew, Xcode, a Windows Store install, a portable build):
  ```bash
  conda info --envs          # every conda env, one path per line
  py -0p                     # Windows: all registered interpreters
  which -a python3 python    # POSIX
  ```
- If the user has **no** Python, or none with tkinter, tell them what to install — and
  **ask for their consent before installing anything yourself**:
  - Windows: `winget install Python.Python.3.12`, or the installer from python.org with
    "tcl/tk" left enabled and "Add python.exe to PATH" ticked.
  - macOS: `brew install python-tk`. Do **not** use `/usr/bin/python3` (it has no tkinter).
  - Debian/Ubuntu: `sudo apt install python3-tk`
  - Fedora: `sudo dnf install python3-tkinter`
  - Arch: `sudo pacman -S tk`

Then save whatever you found and start the overlay:

```bash
node "${ZCODE_SKILL_DIR}/setup.mjs" --python "<path>" --start --json
```

An explicit `--python` that fails verification does not write anything — the script falls
back to auto-discovery, so a typo is harmless.

## Step 3 — tell the user about the MCP restart

The overlay window starts immediately, but the **`tps_*` MCP tools only pick up a newly
configured interpreter when the session restarts** — the MCP server process is launched by
ZCode at session start. Say this explicitly when you configured an interpreter for the
first time; otherwise the user will report that the tools are still missing.

After the restart, `tps_status` should report the overlay as running.

## Useful follow-ups

- `node "${ZCODE_SKILL_DIR}/setup.mjs" --json` — re-check the current configuration without
  starting anything. Use this to answer "is the monitor set up on this machine?".
- Manual overrides, in precedence order: `--python <path>`, the `TPS_PYTHON` environment
  variable, then the `python` field in `~/.zcode/tps.json`. If the configured interpreter
  stops working, the script silently re-discovers a replacement and rewrites the config, so
  a moved or deleted conda env self-heals on the next run.

## Notes

- The script only ever writes the single `python` key to `~/.zcode/tps.json`; `language` and
  `autostart` are preserved.
- Only console interpreters are used (`python.exe`, `python3`). The GUI is launched with the
  matching `pythonw.exe` on Windows automatically, so no console window appears.
- Diagnostics land in `~/.zcode/tps.log` (overlay crash/exit records included).
