"""zcode-tps MCP server (stdio, hand-rolled JSON-RPC, stdlib only).

Tools for the model:
- tps_start        launch the floating overlay (detached pythonw process)
- tps_stop         stop the overlay
- tps_status       running state + live snapshot (avg/last tok/s & TTFT per model)
- tps_language     get/set overlay UI language ('en' / 'zh')
- tps_session_stats per-request tok/s & TTFT for the current zcode session

Manual smoke test:
  printf '%s\\n' \\
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual","version":"0"}}}' \\
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \\
    | python mcp/tps_server.py
"""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "overlay"))
import tps_core as core  # noqa: E402

SERVER_NAME = "zcode-tps-overlay"
try:
    VERSION = json.loads((Path(__file__).resolve().parent.parent / ".zcode-plugin"
                          / "plugin.json").read_text(encoding="utf-8")).get("version", "0.0.0")
except (OSError, ValueError):
    VERSION = "0.0.0"

TOOLS = [
    {
        "name": "tps_start",
        "description": "Start the ZCode TPS floating-window monitor: an always-on-top overlay "
                       "showing per (baseURL, model) token speed and TTFT. No parameters.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tps_stop",
        "description": "Stop the TPS floating-window monitor overlay process. No parameters.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tps_status",
        "description": "Get monitor status and a live snapshot: whether the overlay is running, "
                       "per (baseURL, model) average/last tok/s and TTFT, in-flight request count. "
                       "No parameters.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tps_language",
        "description": "Get or set the overlay UI language. args: language - 'en' or 'zh'; "
                       "omit to just read the current language.",
        "inputSchema": {
            "type": "object",
            "properties": {"language": {"type": "string", "enum": ["en", "zh"],
                                        "description": "New UI language"}},
        },
    },
    {
        "name": "tps_session_stats",
        "description": "Get token speed and TTFT stats for the current zcode session: the last N "
                       "model requests with duration, tok/s (TTFT excluded) and TTFT each, plus "
                       "averages and total output tokens.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "last_n": {"type": "integer", "minimum": 1, "maximum": 100,
                           "description": "How many recent requests to include (default 20)"},
                "session_id": {"type": "string",
                               "description": "Explicit session id; defaults to the current one"},
            },
        },
    },
]

_store, _collectors = None, False
_collectors_lock = threading.Lock()


def _ensure_collectors():
    """Start the shared collectors once so tps_status can serve a live snapshot."""
    global _store, _collectors
    with _collectors_lock:
        if not _collectors:
            _store = core.Store()
            threading.Thread(target=core.tail_daily, args=(_store,), daemon=True).start()
            threading.Thread(target=core.poll_db, args=(_store,), daemon=True).start()
            _collectors = True
    return _store


def _overlay_path():
    return Path(__file__).resolve().parent.parent / "overlay" / "tps_monitor.py"


def _windowless():
    """Interpreter for the GUI: this same interpreter, but under Windows prefer
    the console-less pythonw.exe next to it when present. mcp/launch.mjs picked
    this interpreter at runtime, so nothing here is host-specific."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pw = exe.with_name("pythonw.exe")
        if pw.exists():
            return pw
    return exe


def _spawn_kwargs():
    """Detach the overlay so it outlives this MCP server on every platform."""
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        if _windowless().name.lower() != "pythonw.exe":
            flags |= 0x08000000  # CREATE_NO_WINDOW: no console for python.exe
        return {"creationflags": flags}
    return {"start_new_session": True}


def tps_start(args):
    pid = core.read_pid()
    if pid:
        return f"Overlay already running (pid {pid})."
    subprocess.Popen([str(_windowless()), str(_overlay_path())], **_spawn_kwargs(),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    time.sleep(1.0)
    pid = core.read_pid()
    if pid:
        return f"Overlay started (pid {pid})."
    return "Overlay launch requested; pid file not written yet, use tps_status to verify."


def tps_stop(args):
    pid = core.read_pid()
    if not pid:
        return "Overlay is not running."
    if sys.platform == "win32":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        ok, detail = r.returncode == 0, (r.stderr or r.stdout).strip()
    else:
        ok, detail = True, ""
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as err:
            ok, detail = False, str(err)
    core.clear_pid()
    if ok:
        return f"Overlay stopped (pid {pid})."
    return f"Failed to stop pid {pid}: {detail}"


def _snapshot_lines():
    store = _ensure_collectors()
    with store.lock:
        history = {k: list(v) for k, v in store.history.items()}
        inflight = sum(1 for r in store.records if r["end"] is None)
    lines = []
    if not history:
        lines.append("(collectors warming up, no completed requests captured yet)")
    for (base, model), vals in sorted(history.items()):
        avg = sum(v[0] for v in vals) / len(vals)
        tt = [v[1] for v in vals if v[1] is not None]
        avg_tt = f"{sum(tt) / len(tt):.1f}s" if tt else "--"
        last_tps, last_tt = vals[-1]
        last_tt_s = f"{last_tt:.1f}s" if last_tt is not None else "--"
        lines.append(f"{core.short_base(base)} | {model}: avg {avg:.1f} tok/s "
                     f"(TTFT {avg_tt}), last {last_tps:.1f} tok/s (TTFT {last_tt_s}), n={len(vals)}")
    lines.append(f"in-flight requests: {inflight}")
    return lines


def tps_status(args):
    cfg = core.load_config()
    pid = core.read_pid()
    running = f"running (pid {pid})" if pid else "not running"
    lines = [f"Overlay: {running}. UI language: {cfg.get('language')}.", "Speed (last 10 each):"]
    lines.extend(_snapshot_lines())
    return "\n".join(lines)


def tps_language(args):
    lang = (args.get("language") or "").strip().lower()
    cfg = core.load_config()
    if lang not in ("en", "zh"):
        return f"Current UI language: {cfg.get('language')}. Pass language 'en' or 'zh' to change it."
    cfg["language"] = lang
    core.save_config(cfg)
    return f"UI language set to '{lang}'. The overlay switches within ~0.5s (no restart needed)."


def tps_session_stats(args):
    n = max(1, min(100, int(args.get("last_n") or 20)))
    sid = (args.get("session_id") or "").strip() or core.read_state_session()
    con = sqlite3.connect(f"file:{core.DB_PATH.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if not sid:
            row = con.execute("select session_id from model_usage"
                              " order by started_at desc limit 1").fetchone()
            sid = row["session_id"] if row else None
        if not sid:
            return "No model usage found in the database yet."
        rows = con.execute(
            "select started_at, model_id, status, duration_ms,"
            " time_to_first_token_ms, output_tokens from model_usage"
            " where session_id = ? and completed_at is not null"
            " order by started_at desc limit ?", (sid, n)).fetchall()
    finally:
        con.close()
    if not rows:
        return f"No completed requests for session {sid}."
    lines = [f"Session {sid} — last {len(rows)} requests (newest first):"]
    tps_list, ttft_list, total_out = [], [], 0
    for r in reversed(rows):  # oldest first so the list reads chronologically
        dur, ttft, out = r["duration_ms"], r["time_to_first_token_ms"], r["output_tokens"]
        ttft_s = (ttft / 1000.0) if isinstance(ttft, (int, float)) and isinstance(dur, (int, float)) \
            and 0 <= ttft < dur else None
        tps = None
        if isinstance(out, (int, float)) and out > 0 and isinstance(dur, (int, float)) and dur > 0:
            span = (dur - ttft) if ttft_s is not None else dur
            tps = out * 1000.0 / span
        when = time.strftime("%H:%M:%S", time.localtime((r["started_at"] or 0) / 1000.0))
        dur_s = f"{dur / 1000.0:.1f}" if isinstance(dur, (int, float)) else "--"
        tps_s = f"{tps:.1f}" if tps is not None else "--"
        tt_s = f"{ttft_s:.1f}s" if ttft_s is not None else "--"
        out_s = f"{int(out)}" if isinstance(out, (int, float)) else "0"
        lines.append(f"  {when}  {r['model_id']}  dur {dur_s}s  {tps_s} tok/s  TTFT {tt_s}  out {out_s}")
        if tps is not None:
            tps_list.append(tps)
        if ttft_s is not None:
            ttft_list.append(ttft_s)
        if isinstance(out, (int, float)):
            total_out += out
    if tps_list:
        summary = f"summary: avg {sum(tps_list) / len(tps_list):.1f} tok/s"
        if ttft_list:
            summary += f", avg TTFT {sum(ttft_list) / len(ttft_list):.1f}s"
        summary += f", total output {total_out} tokens"
        lines.append(summary)
    return "\n".join(lines)


HANDLERS = {
    "tps_start": tps_start,
    "tps_stop": tps_stop,
    "tps_status": tps_status,
    "tps_language": tps_language,
    "tps_session_stats": tps_session_stats,
}


def write_message(message):
    # MCP stdio framing: NEWLINE-DELIMITED JSON - one message per line, no
    # embedded newlines, terminated by "\n". Raw bytes via stdout.buffer so
    # Windows text mode does not translate the trailing newline. (LSP-style
    # "Content-Length" framing is NOT part of the MCP stdio protocol and hangs
    # the client: its parser splits on "\n" and JSON.parse-es each line.)
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(body + b"\n")
    sys.stdout.buffer.flush()


def handle_request(msg):
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if rid is None:
        return  # notification (e.g. initialized)
    if method == "initialize":
        write_message({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": params.get("protocolVersion") or "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": VERSION}}})
    elif method == "ping":
        write_message({"jsonrpc": "2.0", "id": rid, "result": {}})
    elif method == "tools/list":
        write_message({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            write_message({"jsonrpc": "2.0", "id": rid, "error":
                           {"code": -32601, "message": f"Unknown tool: {name}"}})
            return
        try:
            text = handler(params.get("arguments") or {})
            write_message({"jsonrpc": "2.0", "id": rid, "result":
                           {"content": [{"type": "text", "text": text}], "isError": False}})
        except Exception as err:  # report tool errors in-band
            write_message({"jsonrpc": "2.0", "id": rid, "result":
                           {"content": [{"type": "text", "text": f"[zcode-tps] {err}"}],
                            "isError": True}})
    else:
        write_message({"jsonrpc": "2.0", "id": rid, "error":
                       {"code": -32601, "message": f"Method not found: {method}"}})


def serve():
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith(b"content-length:"):
            try:
                length = int(s.split(b":", 1)[1])
            except ValueError:
                continue
            while True:  # consume remaining headers up to the blank line
                hdr = sys.stdin.buffer.readline()
                if not hdr or hdr.strip() == b"":
                    break
            body = sys.stdin.buffer.read(length)
            try:
                msg = json.loads(body)
            except ValueError:
                continue
        else:
            try:
                msg = json.loads(s)
            except ValueError:
                continue
        handle_request(msg)


if __name__ == "__main__":
    serve()
