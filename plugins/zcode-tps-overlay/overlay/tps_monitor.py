"""ZCode TPS floating-window monitor (UI).

Requires tps_core.py (collectors, config, process helpers) next to this file.
Stdlib only. Run: python tps_monitor.py
"""

import os
import sys
import threading
import time
import tkinter as tk

from tps_core import (ACTIVE_TTL, Store, clear_pid, config_mtime, load_config,
                      poll_db, short_base, tail_daily, write_pid)

REFRESH_MS = 500
SNAP = 24              # release within this distance of a screen edge docks
STRIP = 4              # strip (px) left visible while dock-hidden
HOVER_IN = 16          # hover trigger depth inward from the edge (px)
EDGE_OUT = 8           # outward (off-screen) extension of the shown-window zone

BG, FG = "#1e1e2e", "#cdd6f4"
DIM, BLUE, GREEN, YELLOW, RED = "#6c7086", "#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8"

I18N = {
    "en": {
        "avg_hdr": "TPS avg of last 10 (tok/s excl. TTFT)",
        "no_data": " No data yet — waiting for requests…",
        "recent": "Recent requests ({n}/10)",
        "none": " (none)",
        "col_time": "time", "col_model": "model", "col_dur": "dur",
        "col_tps": "tok/s", "col_ttft": "TTFT",
        "avg": "avg", "last": "last",
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
        self.labels = []  # fixed label pool: update text/color only, no rebuild flicker
        self.after(200, self.render)
        self.after(150, self._tick_dock)

    def destroy(self):
        clear_pid()
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

    def _pointer_in_zone(self):
        """Hover zone. Hidden: a band HOVER_IN deep inward from the docked edge
        (no need to hit the few-pixel strip). Shown: the window rect, extended
        only outward (off-screen) so an edge-hugging pointer stays inside."""
        px, py = self.winfo_pointerx(), self.winfo_pointery()
        wx, wy = self.winfo_rootx(), self.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if not self.shown:
            if self.dock == "top":
                return py < STRIP + HOVER_IN and wx <= px < wx + w
            if self.dock == "bottom":
                return py > sh - STRIP - HOVER_IN and wx <= px < wx + w
            if self.dock == "left":
                return px < STRIP + HOVER_IN and wy <= py < wy + h
            if self.dock == "right":
                return px > sw - STRIP - HOVER_IN and wy <= py < wy + h
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
            state["i"] += 1
            if state["i"] >= n:
                self.geometry(f"+{tx}+{ty}")
                self._anim_id = None
                return
            k = 1 - (1 - state["i"] / n) ** 3  # ease-out
            self.geometry(f"+{round(sx + (tx - sx) * k)}+{round(sy + (ty - sy) * k)}")
            self._anim_id = self.after(16, step)

        step()

    def _hide(self):
        x, y = self.winfo_x(), self.winfo_y()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        rx = min(max(x, 0), sw - w)
        ry = min(max(y, 0), sh - h)
        self.shown = False
        if self.dock == "top":
            self._slide(rx, -h + STRIP)
        elif self.dock == "bottom":
            self._slide(rx, sh - STRIP)
        elif self.dock == "left":
            self._slide(-w + STRIP, ry)
        elif self.dock == "right":
            self._slide(sw - STRIP, ry)

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
        self.after(150, self._tick_dock)

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def render(self):
        now = time.time()
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
            for rec in self.store.records:  # close records stuck past TTL (e.g. killed)
                if rec["end"] is None and now - rec["start"] > ACTIVE_TTL:
                    rec["end"] = now
                    rec["dur"] = now - rec["start"]
            records = [dict(r) for r in self.store.records]
        records.sort(key=lambda r: r["start"])

        lines = [(f"⚡ ZCode TPS  {time.strftime('%H:%M:%S')}", BLUE)]
        lines.append(("─" * 56, DIM))
        lines.append((T["avg_hdr"], DIM))
        if history:
            for (base, model), vals in sorted(history.items()):
                avg = sum(v[0] for v in vals) / len(vals)
                ttfts = [v[1] for v in vals if v[1] is not None]
                avg_tt = f"{sum(ttfts) / len(ttfts):4.1f}s" if ttfts else "  --"
                last_tps, last_tt = vals[-1]
                last_tt = f"{last_tt:4.1f}s" if last_tt is not None else "  --"
                lines.append((f" {short_base(base)}", BLUE))
                lines.append((f"   {model}", FG))
                lines.append((f"     {T['avg']} {avg:6.1f} tok/s   TTFT {avg_tt}", GREEN))
                lines.append((f"     {T['last']} {last_tps:6.1f} tok/s   TTFT {last_tt}",
                              GREEN))
        else:
            lines.append((T["no_data"], DIM))
        lines.append(("─" * 56, DIM))
        lines.append((T["recent"].format(n=len(records)), DIM))
        if records:
            model_w = max(5, max(disp_w(r["model"]) for r in records))
            lines.append((f"  {ljust_w(T['col_time'], 8)}  {ljust_w(T['col_model'], model_w)}"
                          f"  {rjust_w(T['col_dur'], 5)} {rjust_w(T['col_tps'], 6)}"
                          f" {rjust_w(T['col_ttft'], 5)}", BLUE))
            for r in records:
                hhmmss = time.strftime("%H:%M:%S", time.localtime(r["start"]))
                model = ljust_w(r["model"], model_w)
                dur = (f"{now - r['start']:5.1f}" if r["end"] is None
                       else f"{r['dur']:5.1f}")
                tps = f"{r['tps']:6.1f}" if r["tps"] else "    --"
                tt = f"{r['ttft']:5.1f}" if r["ttft"] is not None else "   --"
                if r["end"] is None:
                    mark, color = "●", YELLOW
                elif r["failed"]:
                    mark, color = "✗", RED
                else:
                    mark, color = "✓", FG
                lines.append((f"{mark} {hhmmss}  {model}  {dur} {tps} {tt}", color))
        else:
            lines.append((T["none"], DIM))

        max_w = max([disp_w(t) for t, _ in lines if not t.startswith("─")] or [40])
        sep = "─" * (max_w + 2)
        lines = [(sep if t.startswith("─") else t, c) for t, c in lines]
        while len(self.labels) < len(lines):
            lbl = tk.Label(self.frame, bg=BG, anchor="w", font=("Consolas", 9))
            lbl.pack(fill="x")
            self.labels.append(lbl)
        for lbl, (text, color) in zip(self.labels, lines):
            lbl.config(text=text, fg=color)
        for lbl in self.labels[len(lines):]:
            lbl.pack_forget()
        self.after(REFRESH_MS, self.render)


def main():
    write_pid(os.getpid())
    store = Store()
    threading.Thread(target=tail_daily, args=(store,), daemon=True).start()
    threading.Thread(target=poll_db, args=(store,), daemon=True).start()
    Overlay(store).mainloop()


if __name__ == "__main__":
    main()
