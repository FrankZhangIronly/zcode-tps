"""Shared core for the ZCode TPS monitor: collectors, config and process helpers.

Data sources:
- ~/.zcode/cli/log/zcode-YYYY-MM-DD.jsonl      request-started events (in-flight rows)
- model_usage table in ~/.zcode/cli/db/db.sqlite  real tokens, duration and
  time_to_first_token_ms (TTFT); read via read-only WAL, safe while zcode runs

Stdlib only.
"""

import json
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ZCODE_DIR = Path.home() / ".zcode"
DAILY_DIR = ZCODE_DIR / "cli" / "log"        # zcode-YYYY-MM-DD.jsonl
DB_PATH = ZCODE_DIR / "cli" / "db" / "db.sqlite"  # model_usage: tokens/duration/TTFT
V2_CONFIG = ZCODE_DIR / "v2" / "config.json"  # providerId -> baseURL map
CONFIG_PATH = ZCODE_DIR / "tps.json"         # {"language": "en"|"zh", "autostart": bool}
STATE_PATH = ZCODE_DIR / "tps.state.json"    # {"sessionId": ...} from SessionStart hook
PID_PATH = ZCODE_DIR / "tps.pid"             # overlay process id

SEED_WINDOW_MS = 6 * 3600 * 1000             # DB polling lookback window
ACTIVE_TTL = 15 * 60   # record timeout (crash-leftover guard)
PAIR_TOL = 5  # s; a started event pairs with a model_usage row within this start-time tolerance

DEFAULT_CONFIG = {"language": "en", "autostart": True}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def config_mtime():
    try:
        return CONFIG_PATH.stat().st_mtime
    except OSError:
        return 0.0


def read_state_session():
    """Session id recorded by the SessionStart hook, if any."""
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("sessionId") or None
    except (OSError, ValueError):
        return None


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    except (OSError, ValueError):
        return False
    if not h:
        return False
    k.CloseHandle(h)
    return True


def read_pid():
    """Overlay pid from the pid file; stale entries are removed."""
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if not pid_alive(pid):
        try:
            PID_PATH.unlink()
        except OSError:
            pass
        return None
    return pid


def write_pid(pid):
    try:
        PID_PATH.write_text(str(pid), encoding="utf-8")
    except OSError:
        pass


def clear_pid():
    try:
        PID_PATH.unlink()
    except OSError:
        pass


class Store:
    """Shared state; collector threads write, UI/MCP readers take the lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.records = deque(maxlen=10)  # last 10 requests (in-flight + done)
        self.pending = {}                # traceId -> [record, ...] not completed yet
        self.session_model = {}  # sessionId -> last completed modelId (in-flight row label)
        self.history = {}        # (baseURL, modelId) -> deque(maxlen=10) of (tok/s, TTFT s|None)
        self.model_last = {}     # (baseURL, modelId) -> start epoch of its latest request
        self.provider_base = {}  # providerId -> baseURL (from v2/config.json, refreshed on demand)
        self._cfg_mtime = 0.0

    def base_of(self, provider_id):
        if not provider_id:
            return "unknown"
        with self.lock:
            base = self.provider_base.get(provider_id)
            mtime = self._cfg_mtime
        if base:
            return base
        try:
            cur = V2_CONFIG.stat().st_mtime
        except OSError:
            cur = None
        if cur and cur != mtime:
            try:
                cfg = json.loads(V2_CONFIG.read_text(encoding="utf-8"))
                table = {pid: (p.get("options") or {}).get("baseURL") or pid
                         for pid, p in (cfg.get("provider") or {}).items()}
            except (OSError, ValueError):
                table = {}
            with self.lock:
                self._cfg_mtime = cur
                self.provider_base.update(table)
                base = self.provider_base.get(provider_id)
        return base or provider_id


def iso_to_epoch(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return time.time()


def _take_pending(store, trace, target_ts):
    """Take the pending record for a traceId whose start is closest to target_ts (lock held)."""
    lst = store.pending.get(trace)
    if not lst:
        return None
    best = min(lst, key=lambda r: abs(r["start"] - target_ts))
    if abs(best["start"] - target_ts) > PAIR_TOL:
        return None
    lst.remove(best)
    if not lst:
        store.pending.pop(trace, None)
    return best


def handle_daily_event(store, d):
    ev, trace = d.get("event"), d.get("traceId")
    if ev == "model.request.started" and trace:
        rec = {"start": iso_to_epoch(d.get("timestamp")), "end": None, "dur": None,
               "tps": None, "ttft": None, "failed": False,
               "model": store.session_model.get(d.get("sessionId"), "…")}
        with store.lock:
            store.records.append(rec)
            store.pending.setdefault(trace, []).append(rec)
    elif ev in ("model.sdk.stream.completed", "model.request.completed"):
        ctx = d.get("context") or {}
        if d.get("sessionId") and ctx.get("modelId"):
            with store.lock:
                store.session_model[d["sessionId"]] = ctx["modelId"]
    elif ev == "model.request.failed" and trace:
        ts_end = iso_to_epoch(d.get("timestamp"))
        dur = d.get("durationMs")
        target = ts_end - dur / 1000.0 if isinstance(dur, (int, float)) else ts_end
        with store.lock:
            rec = _take_pending(store, trace, target)
            if rec is not None:
                rec["end"] = ts_end
                rec["dur"] = (dur / 1000.0) if isinstance(dur, (int, float)) else ts_end - rec["start"]
                rec["failed"] = True


def handle_db_row(store, r, seed=False):
    """Apply one model_usage row: pure streaming speed (TTFT excluded), update
    averages and the rolling list. seed=True rows only seed averages, not the list."""
    model_id = r["model_id"]
    dur_ms = r["duration_ms"]
    if not model_id or not (isinstance(dur_ms, (int, float)) and dur_ms > 0):
        return
    ttft = r["time_to_first_token_ms"]
    ttft_s = ttft / 1000.0 if isinstance(ttft, (int, float)) and 0 <= ttft < dur_ms else None
    out = r["output_tokens"]
    tps = None
    if isinstance(out, (int, float)) and out > 0:
        span = (dur_ms - ttft) if ttft_s is not None else dur_ms  # exclude TTFT
        tps = out * 1000.0 / span
    base = store.base_of(r["provider_id"])  # locks internally; call before taking lock
    start_ms = r["started_at"]
    start = start_ms / 1000.0 if isinstance(start_ms, (int, float)) else time.time()
    if r["session_id"]:
        with store.lock:
            store.session_model[r["session_id"]] = model_id
    if tps is not None and (r["status"] or "") == "completed":
        with store.lock:
            key = (base, model_id)
            store.history.setdefault(key, deque(maxlen=10)).append((tps, ttft_s))
            store.model_last[key] = start  # recency used by the UI's per-base cap
    with store.lock:
        rec = _take_pending(store, r["trace_id"], start)
        if rec is None:
            if seed:  # seed-phase old rows do not enter the rolling list
                return
            # no started event (e.g. title-gen sub-requests): append a completed record
            rec = {"start": start, "end": None, "dur": None, "tps": None,
                   "ttft": None, "failed": False, "model": model_id}
            store.records.append(rec)
        rec["model"] = model_id
        rec["dur"] = dur_ms / 1000.0
        rec["end"] = start + rec["dur"]
        rec["tps"] = tps
        rec["ttft"] = ttft_s
        rec["failed"] = (r["status"] or "") != "completed"


def read_new_lines(fh, fn):
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line:
            return
        if not line.endswith(b"\n"):  # partial line: rewind and wait
            fh.seek(pos)
            return
        try:
            fn(json.loads(line.decode("utf-8", "replace")))
        except ValueError:
            pass


def tail_daily(store):
    """Follow today's daily log, rolling over at midnight; start from EOF."""
    cur_date, fh = None, None
    while True:
        today = time.strftime("%Y-%m-%d")
        if today != cur_date:
            if fh:
                fh.close()
                fh = None
            cur_date = today
        if fh is None:
            try:
                fh = open(DAILY_DIR / f"zcode-{today}.jsonl", "rb")
                fh.seek(0, 2)
            except OSError:
                time.sleep(1)
                continue
        read_new_lines(fh, lambda d: handle_daily_event(store, d))
        time.sleep(0.2)


def poll_db(store):
    """Poll the model_usage table (read-only WAL, safe while zcode runs).
    First pass seeds averages and recent records; later passes take only new rows."""
    con, processed, first = None, set(), True
    while True:
        try:
            if con is None:
                con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
            since = int(time.time() * 1000) - SEED_WINDOW_MS
            rows = con.execute(
                "select id, trace_id, session_id, provider_id, model_id, status,"
                " started_at, duration_ms, time_to_first_token_ms, output_tokens"
                " from model_usage where completed_at is not null and started_at > ?"
                " order by started_at", (since,)).fetchall()
        except (sqlite3.Error, OSError):
            if con is not None:
                con.close()
                con = None
            time.sleep(2)
            continue
        fresh = [dict(r) for r in rows if r["id"] not in processed]
        processed.update(r["id"] for r in fresh)
        if len(processed) > 2000:  # keep the dedupe set bounded
            processed = set(sorted(processed)[-500:])
        if first:
            first = False
            fresh.sort(key=lambda r: r["started_at"] or 0)
            with store.lock:  # keep in-flight records at the front
                inflight = [rec for lst in store.pending.values() for rec in lst]
                store.records = deque(inflight, maxlen=10)
            for r in fresh[:-10]:  # older rows only seed averages
                handle_db_row(store, r, seed=True)
        for r in (fresh[-10:] if first else fresh):
            handle_db_row(store, r)
        time.sleep(1.5)


def short_base(base):
    u = urlparse(base if "://" in base else "//" + base)
    return (u.netloc + u.path.rstrip("/")) or base
