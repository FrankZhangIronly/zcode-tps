"""Shared core for the ZCode TPS monitor: collectors, config and process helpers.

Data sources:
- ~/.zcode/cli/log/zcode-YYYY-MM-DD.jsonl      request-started events (in-flight rows)
- model_usage table in ~/.zcode/cli/db/db.sqlite  real tokens, duration and
  time_to_first_token_ms (TTFT); read via read-only WAL, safe while zcode runs
- api.commandcode.ai/alpha (undocumented; the same read-only GETs the official
  CLI and web app use) — Command Code 5h/week/month quota meters
- opencode.ai/api/orgs/<org>/go/status (undocumented) — OpenCode Go rolling /
  weekly / monthly usage; opt-in, needs a key in ~/.zcode/tps.json

Stdlib only.
"""

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
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

CC_API = "https://api.commandcode.ai/alpha"  # Command Code quota meters (read-only)
OC_API = "https://opencode.ai/api"  # OpenCode Go usage (console API, undocumented)
OPENCODE_NAME = "OpenCode Go"  # product name, not translated
SOURCE_ORDER = ("commandcode", "opencode")  # display order of the quota sections
USER_AGENT = "zcode-tps-overlay"  # Cloudflare error 1010 rejects Python's default UA
USAGE_POLL_S = 60      # quota refresh interval
USAGE_STALE_S = 300    # drop a source once refreshing it has failed this long
USAGE_TIMEOUT = 8      # s per request

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
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        except (OSError, ValueError, AttributeError):
            return False
        if not h:
            return False
        k.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)  # signal 0 only performs the permission/existence check
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except OSError:
        return False
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
        self.usages = None       # quota sources, one per account (see poll_usage)
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
               "tps": None, "ttft": None, "failed": False, "approx": False,
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
    # Streaming speed is output over generation time, i.e. the wait for the first
    # token is excluded. A response carrying only tool calls gets no first-token
    # timestamp, so that wait is unknown for it: such a row can only be timed from
    # end to end. Flag it so the UI can mark it and keep it out of the averages,
    # rather than silently blending two different measurements into one column.
    approx = ttft_s is None
    tps = None
    if isinstance(out, (int, float)) and out > 0:
        span = dur_ms if approx else (dur_ms - ttft)
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
            if not approx:  # only like-for-like numbers may feed the average
                store.history.setdefault(key, deque(maxlen=10)).append((tps, ttft_s))
            store.model_last[key] = start  # recency used by the UI's per-base cap
    with store.lock:
        rec = _take_pending(store, r["trace_id"], start)
        if rec is None:
            if seed:  # seed-phase old rows do not enter the rolling list
                return
            # no started event (e.g. title-gen sub-requests): append a completed record
            rec = {"start": start, "end": None, "dur": None, "tps": None,
                   "ttft": None, "failed": False, "model": model_id, "approx": False}
            store.records.append(rec)
        rec["model"] = model_id
        rec["dur"] = dur_ms / 1000.0
        rec["end"] = start + rec["dur"]
        rec["tps"] = tps
        rec["ttft"] = ttft_s
        rec["approx"] = approx
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


def _isnum(v):
    """True for real JSON numbers (Python bools are ints)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v):
    """v as a float; numeric strings count too, because the OpenCode API sends
    micro-amounts as strings (they are BigInt on the server)."""
    if _isnum(v):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return 0.0
    return 0.0


def _when(v):
    """Epoch seconds from an ISO-8601 string or an epoch number (s or ms)."""
    at = _iso_epoch(v) if isinstance(v, str) else None
    if at is None and _isnum(v):
        at = v / 1000.0 if v > 1e11 else float(v)
    return at


def commandcode_provider():
    """The configured Command Code provider as {"base", "key"}, or None."""
    try:
        cfg = json.loads(V2_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for prov in (cfg.get("provider") or {}).values():
        opts = prov.get("options") or {}
        base = opts.get("baseURL") or ""
        key = opts.get("apiKey") or ""
        if "commandcode" in base.lower() and key:
            return {"base": base, "key": key}
    return None


def opencode_account(cfg):
    """OpenCode Go credentials from tps.json as {"key", "org", "base"}, or None.

    Opt-in on purpose: OpenCode is not a zcode provider, so its key cannot be read
    from zcode's own config. Until one is configured, nothing here is ever called
    and no request is made."""
    oc = (cfg or {}).get("opencode") or {}
    key = str(oc.get("api_key") or "").strip()
    if not key:
        return None
    return {"key": key,
            "org": str(oc.get("org_id") or "").strip(),
            "base": str(oc.get("api_base") or OC_API).rstrip("/")}


class Unauthorized(Exception):
    """The API key was rejected (or is missing): there is nothing to display,
    which is different from a transient failure worth retrying with the previous
    reading left on screen."""


def _get_json(url, key, extra_headers=None):
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json",
               "User-Agent": USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=USAGE_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise Unauthorized(url) from err
        raise


def _cc_get(path, key):
    return _get_json(f"{CC_API}/{path}", key)


def _iso_epoch(ts):
    """Epoch seconds for an ISO-8601 timestamp, or None."""
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fetch_commandcode(prov):
    """Command Code meters as a quota source, or None. Each window's remaining
    share and reset time (the web page shows the used share, so 100 - used/cap is
    what the overlay wants)."""
    try:
        credits = _cc_get("billing/credits", prov["key"])
        summary = _cc_get("usage/summary", prov["key"])
    except (OSError, ValueError):  # URLError/HTTPError are OSErrors; bad JSON is ValueError
        return None
    if not isinstance(credits, dict) or not isinstance(summary, dict):
        return None
    left, reset = {}, {}
    for window, label in (("fiveHour", "5h"), ("weekly", "week")):
        w = (credits.get("windowLimits") or {}).get(window) or {}
        used, cap = w.get("used"), w.get("cap")
        if _isnum(used) and _isnum(cap) and cap > 0:
            left[label] = max(0.0, min(100.0, 100.0 * (1 - used / cap)))
        if _isnum(w.get("resetAt")):
            reset[label] = w["resetAt"] / 1000.0
    cred = credits.get("credits") or {}
    remaining = 0.0
    for field in ("monthlyCredits", "purchasedCredits", "freeCredits"):
        if _isnum(cred.get(field)):
            remaining += cred[field]
    # The monthly meter is implied: credits left over spending so far this period.
    spent = summary.get("totalCost")
    if remaining > 0 and _isnum(spent) and spent >= 0:
        left["month"] = max(0.0, min(100.0, 100.0 * remaining / (spent + remaining)))
    if not left:
        return None
    # Period totals for the billing month, same payload as the cost above.
    runs, tokens = summary.get("totalCount"), summary.get("totalTokens")
    if "month" in left:
        # Only the subscription knows when the billing period rolls over; a failure
        # here costs the monthly reset date, not the meters themselves.
        try:
            sub = _cc_get("billing/subscriptions", prov["key"]).get("data") or {}
            at = _iso_epoch(sub.get("currentPeriodEnd"))
        except (OSError, ValueError, AttributeError):
            at = None
        if at is not None:
            reset["month"] = at
    return {"id": "commandcode", "name": short_base(prov["base"]),
            "left": left, "reset": reset, "credits": remaining,
            "runs": runs if _isnum(runs) else None,
            "tokens": tokens if _isnum(tokens) else None,
            "ts": time.time()}


def fetch_opencode(acct):
    """OpenCode Go meters as a quota source, or None.

    The console's own client (api.opencode.ai, route /orgs/:orgId/go/status) answers
    with meters.{fiveHour,week,month}, each holding usedMicroCents/limitMicroCents;
    the monthly window takes its reset from the paid period's endsAt. Both the route
    and the credential scheme are undocumented, so every field is treated as
    optional and any surprise leaves the section hidden rather than wrong."""
    path = f"/orgs/{acct['org']}/go/status" if acct["org"] else "/go/status"
    try:
        # x-api-key as well as the bearer header: the API spec declares both schemes
        # and which one a key is issued for cannot be checked from here.
        data = _get_json(acct["base"] + path, acct["key"], {"x-api-key": acct["key"]})
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    meters = data.get("meters")
    if not isinstance(meters, dict):
        return None
    left, reset = {}, {}
    for key, label in (("fiveHour", "5h"), ("week", "week"), ("month", "month")):
        m = meters.get(key)
        if not isinstance(m, dict):
            continue
        used, limit = _num(m.get("usedMicroCents")), _num(m.get("limitMicroCents"))
        if limit > 0:
            left[label] = max(0.0, min(100.0, 100.0 * (1 - used / limit)))
        at = _when(m.get("resetsAt"))
        if at is not None:
            reset[label] = at
    at = _when(data.get("endsAt"))  # monthly rolls over with the paid period
    if at is not None and "month" in left:
        reset["month"] = at
    if not left:
        return None
    return {"id": "opencode", "name": OPENCODE_NAME, "left": left, "reset": reset,
            "ts": time.time()}


def poll_usage(store):
    """Refresh every configured quota source. A source with no credential is simply
    absent; a rejected key drops that source at once; only a transient failure keeps
    its previous reading, and even that is dropped once it goes stale."""
    while True:
        fresh, reject = {}, set()
        prov = commandcode_provider()
        if prov:
            try:
                src = fetch_commandcode(prov)
            except Unauthorized:
                reject.add("commandcode")
            else:
                if src:
                    fresh[src["id"]] = src
        acct = opencode_account(load_config())
        if acct:
            try:
                src = fetch_opencode(acct)
            except Unauthorized:
                reject.add("opencode")
            else:
                if src:
                    fresh[src["id"]] = src
        with store.lock:
            prev = {s["id"]: s for s in (store.usages or [])}
            now = time.time()
            kept = [s for sid, s in prev.items()
                    if sid not in fresh and sid not in reject
                    and now - s["ts"] <= USAGE_STALE_S]
            live = list(fresh.values()) + kept
            live.sort(key=lambda s: SOURCE_ORDER.index(s["id"])
                      if s["id"] in SOURCE_ORDER else len(SOURCE_ORDER))
            store.usages = live or None
        time.sleep(USAGE_POLL_S)


def short_base(base):
    u = urlparse(base if "://" in base else "//" + base)
    return (u.netloc + u.path.rstrip("/")) or base
