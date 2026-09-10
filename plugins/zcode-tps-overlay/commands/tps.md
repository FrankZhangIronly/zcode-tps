---
description: Show ZCode TPS monitor status snapshot
---

Call the zcode-tps-overlay MCP tool `tps_status` and show its output to the user verbatim in a code block. If the tool reports the overlay is not running and the user seems to want it visible, also call `tps_start` and report the result.

If the `tps_status` tool does not exist at all, this host has not been set up yet: invoke the `zcode-tps-overlay:tps-setup` skill instead of guessing, and pass on its conclusion.
