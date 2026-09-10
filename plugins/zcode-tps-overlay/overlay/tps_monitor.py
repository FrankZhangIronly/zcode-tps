"""ZCode TPS floating-window monitor (UI).

Requires tps_core.py (collectors, config, process helpers) next to this file.
Stdlib only. Run: python tps_monitor.py
"""

import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback

from tps_core import (ACTIVE_TTL, PID_PATH, Store, ZCODE_DIR, clear_pid,
                      config_mtime, load_config, poll_db, poll_usage, save_config,
                      short_base, tail_daily, write_pid)

FONT = ("Consolas", 9)
REFRESH_MS = 500
SNAP = 24              # release within this distance of a screen edge docks
HIDE_BAND = 20         # px left visible while dock-hidden; equals the hover trigger depth
TOP_BAND_ROWS = 2      # text rows kept visible when collapsed toward the top edge
EDGE_OUT = 8           # outward (off-screen) extension of the shown-window zone

BG, FG = "#1e1e2e", "#cdd6f4"
DIM, BLUE, GREEN, YELLOW, RED = "#6c7086", "#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8"
HEAD_BG = "#252537"    # section header band
CARD_BG = "#313244"    # quota card fill
TRACK_BG = "#45475a"   # quota bar track

CARET_OPEN, CARET_CLOSED = "▾", "▸"
SECTIONS = ("avg", "quota", "recent")
QUOTA_H = 104          # quota canvas height: pill row + card row
CARD_H = 72            # one quota card
CPAD, CGAP = 10, 8     # quota canvas outer padding / gap between cards
QUOTA_MIN_W = 52       # min separator width (chars) that keeps three cards readable
BAR_H = 6              # quota bar thickness

I18N = {
    "en": {
        "avg_hdr": "TPS avg of last 10 (tok/s excl. TTFT)",
        "no_data": " No data yet — waiting for requests…",
        "recent": "Recent requests ({n}/10)",
        "none": " (none)",
        "col_time": "time", "col_model": "model", "col_dur": "dur",
        "col_tps": "tok/s", "col_ttft": "TTFT",
        "avg": "avg", "last": "last",
        "approx": "~ = end-to-end, no TTFT (excluded from avg)",
        "quota_hdr": "Quota · {base}",
        "q_5h": "5-hour left", "q_week": "Weekly left", "q_month": "Monthly left",
        "reset": "resets in {d}",
        "credits": "${v} credits left",
        "exit": "Exit",
    },
    "zh": {
        "avg_hdr": "速度均值（近 10 次，tok/s 已扣除首token延迟）",
        "no_data": " 暂无数据，等待请求完成…",
        "recent": "最近请求 ({n}/10)",
        "none": " （无）",
        "col_time": "时间", "col_model": "模型", "col_dur": "耗时",
        "col_tps": "tok/s", "col_ttft": "TTFT",
        "avg": "均值", "last": "最近",
        "approx": "~ = 含首字等待，未计入均值",
        "quota_hdr": "剩余额度 · {base}",
        "q_5h": "5 小时剩余", "q_week": "每周剩余", "q_month": "每月剩余",
        "reset": "{d} 后重置",
        "credits": "${v} 可用额度",
        "exit": "退出",
    },
}


def disp_w(s):
    """Approximate display width (CJK counts as 2 chars), for column alignment."""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def ljust_w(s, w):
    return s + " " * max(0, w - disp_w(s))


def rjust_w(s, w):
    return " " * max(0, w - disp_w(s)) + s


def short_delta(sec):
    """Compact time until a reset: '9m', '4h10m', '2d6h'."""
    mins = int(max(0, sec) // 60)
    if mins < 1:
        return "<1m"
    if mins < 60:
        return f"{mins}m"
    if mins < 60 * 24:
        h, m = divmod(mins, 60)
        return f"{h}h{m:02d}m"
    d, h = divmod(mins // 60, 24)
    return f"{d}d{h}h" if h else f"{d}d"


def level_color(pct):
    """Remaining-share colour: plenty / getting low / nearly out."""
    if pct >= 50:
        return GREEN
    return YELLOW if pct >= 20 else RED


def fmt_count(v):
    """Compact magnitude the way the usage page writes it: 639.1M, 1.2B."""
    if v >= 1e9:
        return f"{v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.0f}"


def quota_pill(usage, t):
    """The summary line above the cards: credits left, then the billing-period
    totals the usage page shows — how much was spent and how many runs it took."""
    parts = []
    credit = (usage or {}).get("credits")
    if isinstance(credit, (int, float)) and credit > 0:
        parts.append(t["credits"].format(v=f"{credit:.1f}"))
    tokens = (usage or {}).get("tokens")
    if isinstance(tokens, (int, float)) and tokens > 0:
        parts.append(f"{fmt_count(tokens)} tokens")
    runs = (usage or {}).get("runs")
    if isinstance(runs, (int, float)) and runs > 0:
        parts.append(f"{runs:,.0f} runs")  # a count reads better with separators
    return "  ·  ".join(parts)


def quota_view(width, usage, t):
    """Pure input for the quota canvas: (signature, pill text, card list).
    A card is (title, percent text, remaining fraction 0..1, reset text, colour).
    The countdown is built here from the fetch timestamp, so it ticks down on
    its own between the 60s refreshes."""
    left = (usage or {}).get("left") or {}
    reset = (usage or {}).get("reset") or {}
    cards = []
    for key in ("5h", "week", "month"):
        if key not in left:
            continue
        pct = left[key]
        sub = t["reset"].format(d=short_delta(reset[key] - time.time())) if key in reset else ""
        cards.append((t[f"q_{key}"], f"{pct:.0f}%", pct / 100.0, sub, level_color(pct)))
    pill = quota_pill(usage, t)
    return (width, pill, tuple(cards)), pill, cards


def _rrect(canvas, x0, y0, x1, y1, r, **kw):
    """Rounded rectangle: Tk has no such primitive, so a smoothed polygon."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = [x0 + r, y0, x1 - r, y0, x1, y0 + r, x1, y1 - r,
           x1 - r, y1, x0 + r, y1, x0, y1 - r, x0, y0 + r]
    return canvas.create_polygon(pts, smooth=True, **kw)


def draw_quota(canvas, width, pill, cards, fonts):
    """Draw the pill + one card per quota window, side by side, filling width."""
    f_pill, f_title, f_pct, f_sub = fonts
    canvas.delete("all")
    canvas.config(height=QUOTA_H if pill else QUOTA_H - 24)
    y = 4
    if pill:
        cw = f_pill.measure(pill)
        _rrect(canvas, 0, y, cw + 18, y + 18, 9, fill=HEAD_BG, outline="")
        canvas.create_text(9, y + 9, text=pill, anchor="w", font=f_pill, fill=FG)
        y += 24
    if not cards:
        return
    cw = (width - 2 * CPAD - (len(cards) - 1) * CGAP) / len(cards)
    for i, (title, pct_text, frac, sub, color) in enumerate(cards):
        x0 = CPAD + i * (cw + CGAP)
        x1 = x0 + cw
        _rrect(canvas, x0, y, x1, y + CARD_H, 8, fill=CARD_BG, outline="")
        canvas.create_text(x0 + 10, y + 7, text=title, anchor="nw", font=f_title, fill=DIM)
        canvas.create_text(x0 + 10, y + 19, text=pct_text, anchor="nw", font=f_pct, fill=color)
        # Bars are round-capped lines, not smoothed rectangles: at this thickness a
        # smoothed polygon's corner radius swallows the bar and bulges it out in the
        # middle, while a wide line keeps one constant thickness end to end. The caps
        # reach half a width past each endpoint, so the endpoints are inset to keep
        # the bar flush with the text above it.
        bx0, bx1, by = x0 + 10 + BAR_H // 2, x1 - 10 - BAR_H // 2, y + 49
        canvas.create_line(bx0, by, bx1, by, width=BAR_H, fill=TRACK_BG,
                           capstyle=tk.ROUND)
        # zero-length is drawn as a single round dot, so even 0% shows where the
        # bar starts instead of vanishing
        filled = max(0.0, (bx1 - bx0) * max(0.0, min(1.0, frac)))
        canvas.create_line(bx0, by, bx0 + filled, by, width=BAR_H, fill=color,
                           capstyle=tk.ROUND)
        canvas.create_text(x0 + 10, y + 57, text=sub, anchor="nw", font=f_sub, fill=DIM)


def pick_family(root, *names):
    """First installed family from names; the last one is the fallback."""
    have = {f.lower() for f in tkfont.families(root)}
    for name in names:
        if name.lower() in have:
            return name
    return names[-1]


class LabelStack:
    """A pool of labels inside one frame, reused across renders so updates never
    flicker. Lines are always a leading run of the pool: the tail is unpacked and
    unpacked labels reappear at the end, which is where they belong."""

    def __init__(self, parent):
        self.parent = parent
        self.labels = []
        self.visible = 0

    def render(self, lines):
        while len(self.labels) < len(lines):
            self.labels.append(tk.Label(self.parent, bg=BG, anchor="w", font=FONT))
        for i, (lbl, (text, color)) in enumerate(zip(self.labels, lines)):
            if i >= self.visible:
                lbl.pack(fill="x")
            lbl.config(text=text, fg=color)
        for lbl in self.labels[len(lines):]:
            lbl.pack_forget()
        self.visible = len(lines)


def log_line(msg):
    """Append a timestamped line to ~/.zcode/tps.log (crash/event record)."""
    try:
        with open(ZCODE_DIR / "tps.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def install_exception_logging():
    """Log any unhandled exception so a silent pythonw exit leaves evidence."""
    def sys_hook(etype, value, tb):
        log_line("FATAL unhandled exception:\n" + "".join(traceback.format_exception(etype, value, tb)).rstrip())
    def thread_hook(args):
        log_line("FATAL thread exception:\n" + "".join(traceback.format_exception(*args.exc_info)).rstrip())
    sys.excepthook = sys_hook
    threading.excepthook = thread_hook


class Overlay(tk.Tk):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.88)
        except tk.TclError:
            pass
        self.configure(bg=BG)
        self.geometry(f"+{self.winfo_screenwidth() - 520}+80")
        self.lang = load_config().get("language", "en")
        self._cfg_mtime = config_mtime()
        self._menu_lang = None
        self.drag = None
        self._press_at = None
        self.dock = None        # docked edge: "top"/"bottom"/"left"/"right", None = free
        self.shown = True       # whether expanded while docked
        self._anim_id = None    # after-handle of the slide animation
        self._miss = 0          # consecutive out-of-zone readings
        self.bind_all("<Button-1>", self._press)
        self.bind_all("<B1-Motion>", self._move)
        self.bind_all("<ButtonRelease-1>", self._release)
        self.bind_all("<Button-3>", self._popup)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Exit", command=self.destroy)
        self.frame = tk.Frame(self, bg=BG)
        self.frame.pack(fill="both", expand=True)
        # The top strip is measured from a real label rather than the font's
        # linespace: a packed row is taller than its glyphs (border + pady), so
        # linespace alone would leave the second row cut off. Measuring keeps the
        # collapsed window showing exactly the newest rows (the in-flight request
        # and the most recently completed one) at any DPI.
        probe = tk.Label(self.frame, bg=BG, anchor="w", font=FONT)
        row_h = probe.winfo_reqheight() or tkfont.Font(root=self, family=FONT[0],
                                                      size=FONT[1]).metrics("linespace")
        probe.destroy()
        self.top_band = row_h * TOP_BAND_ROWS
        self.collapsed = set(load_config().get("collapsed") or [])
        self._layout_sig = None   # last (quota shown, collapsed sections) combination
        self._quota_w, self._quota_sig = 0, None
        # Card row uses a proportional family (CJK included); the text sections stay
        # monospace, whose fixed advance is what the column alignment is built on.
        fam = pick_family(self, "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI",
                          "PingFang SC", "Noto Sans CJK SC", "DejaVu Sans")
        self.fonts = (tkfont.Font(root=self, family=fam, size=8),    # pill
                      tkfont.Font(root=self, family=fam, size=8),    # card title
                      tkfont.Font(root=self, family=fam, size=15, weight="bold"),
                      tkfont.Font(root=self, family=fam, size=8))    # reset line
        self.head_lbl = tk.Label(self.frame, bg=BG, anchor="w", font=FONT, fg=BLUE)
        self.seps = {k: tk.Label(self.frame, bg=BG, anchor="w", font=FONT, fg=DIM)
                     for k in SECTIONS}
        self.sections, self.stacks, self.quota_canvas = {}, {}, None
        for key in SECTIONS:
            sec = tk.Frame(self.frame, bg=BG)
            head = tk.Label(sec, bg=HEAD_BG, anchor="w", font=FONT, fg=BLUE, padx=3)
            head.pack(fill="x")
            self._bind_toggle(head, key)
            body = tk.Frame(sec, bg=BG)
            body.pack(fill="x")
            self.sections[key] = (sec, head, body)
            if key == "quota":
                self.quota_canvas = tk.Canvas(body, bg=BG, width=1, height=QUOTA_H,
                                              highlightthickness=0, bd=0)
                self.quota_canvas.pack(fill="x")
                self.quota_canvas.bind("<Configure>", self._on_quota_configure)
            else:
                self.stacks[key] = LabelStack(body)
        self.after(200, self.render)
        self.after(150, self._tick_dock)

    def _bind_toggle(self, widget, key):
        """Header click folds/unfolds its section. 'break' keeps bind_all from
        starting a window drag on the same click."""
        def on_click(_event):
            self._toggle(key)
            return "break"
        widget.bind("<Button-1>", on_click)

    def _toggle(self, key):
        self.collapsed.symmetric_difference_update({key})
        cfg = load_config()
        cfg["collapsed"] = sorted(self.collapsed)
        save_config(cfg)
        self._render_once()  # immediate feedback instead of waiting for the tick

    def _on_quota_configure(self, event):
        if event.width != self._quota_w:  # resized -> the cards must be re-laid out
            self._quota_w = event.width
            self._quota_sig = None

    def _apply_layout(self, show_quota):
        """(Re)pack the top-level rows in order. Only called when what is visible
        changes, so the 500ms render never re-packs and never flickers."""
        plan = [(self.head_lbl, True), (self.seps["avg"], True)]
        for key in SECTIONS:
            if key == "quota" and not show_quota:
                continue
            if key != "avg":
                plan.append((self.seps[key], True))
            sec, _head, body = self.sections[key]
            plan.append((sec, True))
            plan.append((body, key not in self.collapsed))
        for widget, _ in plan:
            widget.pack_forget()
        for widget, visible in plan:
            if visible:
                widget.pack(fill="x")
        self.update_idletasks()  # so the canvas knows its width before drawing

    def destroy(self):
        log_line("overlay exit")
        try:  # clear the pid file only if it is ours
            if int(PID_PATH.read_text(encoding="utf-8").strip()) == os.getpid():
                clear_pid()
        except (OSError, ValueError):
            pass
        super().destroy()

    def _press(self, e):
        self._stop_slide()
        self.drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())
        self._press_at = (e.x_root, e.y_root)

    def _move(self, e):
        # require >3px movement to drag, so plain clicks do not nudge the window
        if self.drag and self._press_at is not None:
            if abs(e.x_root - self._press_at[0]) + abs(e.y_root - self._press_at[1]) > 3:
                self.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")

    def _release(self, e):
        if self.drag is None:
            return
        self.drag = None
        x, y = self.winfo_x(), self.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        dists = {"top": y, "left": x, "right": sw - (x + w), "bottom": sh - (y + h)}
        edge, dist = min(dists.items(), key=lambda kv: kv[1])
        if dist <= SNAP:
            self.dock = edge
            self._hide()
        else:
            self.dock = None

    def _band(self, edge):
        """Visible strip along a docked edge, which is also the hover depth.
        The top edge keeps the trailing data rows in view while collapsed."""
        return self.top_band if edge == "top" else HIDE_BAND

    def _pointer_in_zone(self):
        """Hover zone. Hidden: the visible band (as deep inward from the docked
        edge as the strip that stays on screen) is also the trigger area, so what
        you see is what hovers. Shown: the window rect, extended only outward
        (off-screen) so an edge-hugging pointer stays inside."""
        px, py = self.winfo_pointerx(), self.winfo_pointery()
        wx, wy = self.winfo_rootx(), self.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if not self.shown:
            if self.dock == "top":
                return py < self._band("top") and wx <= px < wx + w
            if self.dock == "bottom":
                return py > sh - HIDE_BAND and wx <= px < wx + w
            if self.dock == "left":
                return px < HIDE_BAND and wy <= py < wy + h
            if self.dock == "right":
                return px > sw - HIDE_BAND and wy <= py < wy + h
            return False
        if self.dock == "top":
            return wx <= px < wx + w and wy - EDGE_OUT <= py < wy + h
        if self.dock == "bottom":
            return wx <= px < wx + w and wy <= py < wy + h + EDGE_OUT
        if self.dock == "left":
            return wx - EDGE_OUT <= px < wx + w and wy <= py < wy + h
        if self.dock == "right":
            return wx <= px < wx + w + EDGE_OUT and wy <= py < wy + h
        return (wx <= px < wx + w and wy <= py < wy + h)

    def _stop_slide(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None

    def _slide(self, tx, ty, ms=150):
        """Smoothly slide to target (ease-out), no teleport; interruptible."""
        self._stop_slide()
        sx, sy = self.winfo_x(), self.winfo_y()
        n = max(1, ms // 16)
        state = {"i": 0}

        def step():
            try:
                state["i"] += 1
                if state["i"] >= n:
                    self.geometry(f"+{tx}+{ty}")
                    self._anim_id = None
                    return
                k = 1 - (1 - state["i"] / n) ** 3  # ease-out
                self.geometry(f"+{round(sx + (tx - sx) * k)}+{round(sy + (ty - sy) * k)}")
                self._anim_id = self.after(16, step)
            except Exception:
                log_line("slide error:\n" + traceback.format_exc().rstrip())
                self._anim_id = None

        step()

    def _hide(self):
        x, y = self.winfo_x(), self.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        rx = min(max(x, 0), sw - w)
        ry = min(max(y, 0), sh - h)
        self.shown = False
        if self.dock == "top":
            self._slide(rx, -h + self._band("top"))
        elif self.dock == "bottom":
            self._slide(rx, sh - HIDE_BAND)
        elif self.dock == "left":
            self._slide(-w + HIDE_BAND, ry)
        elif self.dock == "right":
            self._slide(sw - HIDE_BAND, ry)

    def _reveal(self):
        # Reveal flush with the docked edge so the hovering pointer stays inside
        # the window; otherwise it instantly "leaves" and re-hides in a loop
        x, y = self.winfo_x(), self.winfo_y()
        self.shown = True
        if self.dock == "top":
            self._slide(x, 0)
        elif self.dock == "bottom":
            self._slide(x, self.winfo_screenheight() - self.winfo_height())
        elif self.dock == "left":
            self._slide(0, y)
        elif self.dock == "right":
            self._slide(self.winfo_screenwidth() - self.winfo_width(), y)

    def _tick_dock(self):
        self.after(150, self._tick_dock)  # schedule first: errors must not kill the loop
        try:
            # stay idle while animating to avoid mid-flight reversals; judge after
            if self.dock and self.drag is None and self._anim_id is None:
                in_zone = self._pointer_in_zone()
                if in_zone and not self.shown:
                    self._miss = 0
                    self._reveal()
                elif not in_zone and self.shown:
                    self._miss += 1  # hide only after 2 consecutive out-of-zone reads
                    if self._miss >= 2:
                        self._miss = 0
                        self._hide()
                else:
                    self._miss = 0
        except Exception:
            log_line("dock tick error:\n" + traceback.format_exc().rstrip())

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def render(self):
        self.after(REFRESH_MS, self.render)  # schedule first: errors must not kill the loop
        try:
            self._render_once()
        except Exception:
            log_line("render error:\n" + traceback.format_exc().rstrip())

    def _render_once(self):
        now = time.time()
        # pull back into the screen if the window ended up fully outside it
        # (e.g. monitor resolution change); docked windows are exempt
        if self.dock is None and self.drag is None:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x, y = self.winfo_x(), self.winfo_y()
            w, h = self.winfo_width(), self.winfo_height()
            if x + w <= 0 or x >= sw or y + h <= 0 or y >= sh:
                self.geometry(f"+{max(0, sw - w - 40)}+80")
        # hot-reload UI language from ~/.zcode/tps.json
        mtime = config_mtime()
        if mtime != self._cfg_mtime:
            self._cfg_mtime = mtime
            self.lang = load_config().get("language", self.lang)
        T = I18N.get(self.lang, I18N["en"])
        if self._menu_lang != self.lang:
            self._menu_lang = self.lang
            self.menu.entryconfig(0, label=T["exit"])

        with self.store.lock:
            history = {k: list(v) for k, v in self.store.history.items()}
            model_last = dict(self.store.model_last)
            usage = self.store.usage
            for rec in self.store.records:  # close records stuck past TTL (e.g. killed)
                if rec["end"] is None and now - rec["start"] > ACTIVE_TTL:
                    rec["end"] = now
                    rec["dur"] = now - rec["start"]
            records = [dict(r) for r in self.store.records]
        records.sort(key=lambda r: r["start"])

        # Which base the quota cards belong to: the account is per provider, so
        # only the base it was fetched for may show them.
        qbase = usage.get("base") if usage else None
        avg_lines, recent_lines = [], []
        if history:
            base_models = {}
            for base, model in history:
                base_models.setdefault(base, []).append(model)
            for base in sorted(base_models):
                avg_lines.append((f" {short_base(base)}", BLUE))
                models = base_models[base]
                models.sort(key=lambda m: model_last.get((base, m), 0.0), reverse=True)
                for model in models[:2]:  # keep at most the two most recent models per base
                    vals = history[(base, model)]
                    avg = sum(v[0] for v in vals) / len(vals)
                    ttfts = [v[1] for v in vals if v[1] is not None]
                    avg_tt = f"{sum(ttfts) / len(ttfts):4.1f}s" if ttfts else "  --"
                    last_tps, last_tt = vals[-1]
                    last_tt = f"{last_tt:4.1f}s" if last_tt is not None else "  --"
                    avg_lines.append((f"   {model}", FG))
                    avg_lines.append((f"     {T['avg']} {avg:6.1f} tok/s   TTFT {avg_tt}", GREEN))
                    avg_lines.append((f"     {T['last']} {last_tps:6.1f} tok/s   TTFT {last_tt}",
                                      GREEN))
        else:
            avg_lines.append((T["no_data"], DIM))
        if records:
            model_w = max(5, max(disp_w(r["model"]) for r in records))
            recent_lines.append((f"  {ljust_w(T['col_time'], 8)}  {ljust_w(T['col_model'], model_w)}"
                                 f"  {rjust_w(T['col_dur'], 5)} {rjust_w(T['col_tps'], 6)}"
                                 f" {rjust_w(T['col_ttft'], 5)}", BLUE))
            if any(r.get("approx") for r in records):
                recent_lines.append((f"  {T['approx']}", DIM))
            for r in records:
                hhmmss = time.strftime("%H:%M:%S", time.localtime(r["start"]))
                model = ljust_w(r["model"], model_w)
                dur = (f"{now - r['start']:5.1f}" if r["end"] is None
                       else f"{r['dur']:5.1f}")
                # '~' marks a wall-clock measurement: no TTFT, so the wait for the
                # first token is inside the figure. Kept the same width as a plain
                # number so the columns stay aligned.
                tps = ("    --" if not r["tps"] else
                       f"~{r['tps']:5.1f}" if r.get("approx") else f"{r['tps']:6.1f}")
                tt = f"{r['ttft']:5.1f}" if r["ttft"] is not None else "   --"
                if r["end"] is None:
                    mark, color = "●", YELLOW
                elif r["failed"]:
                    mark, color = "✗", RED
                elif r.get("approx"):  # dimmed: a different measurement, not a slow one
                    mark, color = "✓", DIM
                else:
                    mark, color = "✓", FG
                recent_lines.append((f"{mark} {hhmmss}  {model}  {dur} {tps} {tt}", color))
        else:
            recent_lines.append((T["none"], DIM))

        # The separator is sized to the widest content line, so it rules the whole
        # width; the quota cards need a floor of their own to stay side by side.
        content = avg_lines + recent_lines
        max_w = max([disp_w(t) for t, _ in content] or [40])
        if qbase:
            # The cards need a width floor of their own; that same floor (52 chars,
            # ~364px) also clears the widest possible pill (~292px), so the summary
            # line above them never clips.
            max_w = max(max_w, QUOTA_MIN_W - 2)
        sep = "─" * (max_w + 2)

        sections = {"avg": avg_lines, "recent": recent_lines}
        sig = (bool(qbase), tuple(sorted(self.collapsed)))
        if sig != self._layout_sig:
            self._layout_sig = sig
            self._apply_layout(bool(qbase))
        # No caret on the title: it is not collapsible, and a caret would imply it is
        self.head_lbl.config(text=f"⚡ ZCode TPS  {time.strftime('%H:%M:%S')}")
        for key in SECTIONS:
            if key == "quota":
                if not qbase:  # hidden with no quota data; nothing to title
                    continue
                title = T["quota_hdr"].format(base=short_base(qbase))
            else:
                title = T["avg_hdr"] if key == "avg" else T["recent"].format(n=len(records))
            self.sections[key][1].config(
                text=f"{CARET_CLOSED if key in self.collapsed else CARET_OPEN} {title}")
        for key in ("avg", "recent"):
            self.seps[key].config(text=sep)
            self.stacks[key].render(sections[key])
        # The cards are sized from the real canvas width, so a window resize
        # (which resets the signature via <Configure>) re-lays them out.
        width = self.quota_canvas.winfo_width() if qbase else 0
        if width > 1:
            qsig, pill, cards = quota_view(width, usage, T)
            if qsig != self._quota_sig:
                self._quota_sig = qsig
                draw_quota(self.quota_canvas, width, pill, cards, self.fonts)


def main():
    install_exception_logging()
    write_pid(os.getpid())
    log_line(f"overlay start pid={os.getpid()} lang={load_config().get('language', 'en')}")
    store = Store()
    threading.Thread(target=tail_daily, args=(store,), daemon=True).start()
    threading.Thread(target=poll_db, args=(store,), daemon=True).start()
    threading.Thread(target=poll_usage, args=(store,), daemon=True).start()
    Overlay(store).mainloop()


if __name__ == "__main__":
    main()
