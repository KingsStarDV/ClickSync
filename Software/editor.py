"""
Tap Tap — Level Editor  (rewrite)
==================================
Workflow
  1. Load MP3
  2. (Optional) Set BPM for bar-relative export
  3. Start Recording → song plays, press D F G H in time
  4. Undo last beat with Backspace while recording
  5. ESC or song end → stop
  6. Save .beat file

The timeline at the bottom shows every recorded beat as a coloured
tick so you can see density / gaps before saving.
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import time
import json
import os
import threading
import math

# ── optional audio ─────────────────────────────────────────
try:
    from playsound3 import playsound as _playsound
    def play_audio(path):
        threading.Thread(target=lambda: _playsound(path), daemon=True).start()
except ImportError:
    def play_audio(_):
        pass

# ═══════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════
WIDTH, HEIGHT = 480, 660

BG          = "#0d0d14"
PANEL       = "#13131f"
PANEL2      = "#1a1a2e"
DIVIDER     = "#2a2a44"
ACCENT1     = "#00c8ff"   # cyan
ACCENT2     = "#ff6ec7"   # pink
ACCENT3     = "#ffdc00"   # yellow
ACCENT4     = "#00ff9f"   # green
TEXT_HI     = "#e8e8ff"
TEXT_MID    = "#7070a0"
TEXT_LO     = "#333355"
MISS        = "#ff4466"

LANE_COLS   = ["#00c8ff", "#ff6ec7", "#ffdc00", "#00ff9f"]
LANE_KEYS   = {"d": 0, "f": 1, "g": 2, "h": 3}
LANE_LABELS = ["D", "F", "G", "H"]

# ═══════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════
mp3_path   = None
start_time = None          # perf_counter snapshot
recording  = False
beats      = []            # list of {"lane": int, "time_ms": int}
bpm_var    = None          # tk.StringVar
key_flash  = [0, 0, 0, 0] # per-lane visual flash countdown
flash_id   = None          # after() id for flash decay loop
song_dur_ms = 0            # estimated song length for timeline scale

# ═══════════════════════════════════════════════════════════
#  ROOT / CANVAS
# ═══════════════════════════════════════════════════════════
root = tk.Tk()
root.title("Tap Tap — Level Editor")
root.resizable(False, False)
root.configure(bg=BG)

canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT,
                   bg=BG, highlightthickness=0)
canvas.pack()

bpm_var = tk.StringVar(value="120")

# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════
def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    r1,g1,b1 = int(c1[1:3],16),int(c1[3:5],16),int(c1[5:7],16)
    r2,g2,b2 = int(c2[1:3],16),int(c2[3:5],16),int(c2[5:7],16)
    r = int(r1+(r2-r1)*t); g = int(g1+(g2-g1)*t); b = int(b1+(b2-b1)*t)
    return f"#{r:02x}{g:02x}{b:02x}"

def draw_rounded_rect(cvs, x1, y1, x2, y2, r, **kw):
    pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r,
           x2,y2-r, x2,y2, x2-r,y2, x1+r,y2,
           x1,y2, x1,y2-r, x1,y1+r, x1,y1, x1+r,y1]
    return cvs.create_polygon(pts, smooth=True, **kw)

def elapsed_ms():
    if start_time is None:
        return 0
    return (time.perf_counter() - start_time) * 1000.0

# ═══════════════════════════════════════════════════════════
#  DRAW — full UI repaint
# ═══════════════════════════════════════════════════════════
def draw_ui(status="", recording_now=False):
    canvas.delete("all")

    # ── background ──────────────────────────────────────────
    canvas.create_rectangle(0, 0, WIDTH, HEIGHT, fill=BG, outline="")
    # faint vertical grid lines for rhythm feel
    for i in range(1, 6):
        canvas.create_line(i*(WIDTH//6), 0, i*(WIDTH//6), HEIGHT,
                           fill="#16162a", width=1)

    # ── title bar ───────────────────────────────────────────
    canvas.create_rectangle(0, 0, WIDTH, 68, fill=PANEL, outline="")
    canvas.create_line(0, 68, WIDTH, 68, fill=DIVIDER, width=1)
    # glow layers
    for off, col in [(3,"#002030"),(1,"#004060"),(0,ACCENT1)]:
        canvas.create_text(WIDTH//2+off, 36+off, text="LEVEL EDITOR",
                           fill=col, font=("Arial", 26, "bold"))
    canvas.create_text(WIDTH//2, 56, text="T A P   T A P",
                       fill=ACCENT2, font=("Arial", 9, "bold"))

    # ── step 1 — load MP3 ───────────────────────────────────
    _section_label(canvas, 94, "1  —  AUDIO FILE")
    fname = os.path.basename(mp3_path) if mp3_path else "No file loaded"
    fcolor = ACCENT4 if mp3_path else TEXT_MID
    draw_rounded_rect(canvas, 20, 108, WIDTH-20, 144, 8,
                      fill=PANEL2, outline=DIVIDER)
    canvas.create_text(32, 126, text="🎵", font=("Arial", 13), fill=fcolor, anchor="w")
    canvas.create_text(58, 126, text=fname, fill=fcolor,
                       font=("Arial", 11), anchor="w")

    # ── step 2 — BPM ────────────────────────────────────────
    _section_label(canvas, 164, "2  —  BPM  (optional, for bar-relative export)")
    draw_rounded_rect(canvas, 20, 178, 140, 210, 8,
                      fill=PANEL2, outline=DIVIDER)
    canvas.create_text(32, 194, text="BPM", fill=TEXT_MID,
                       font=("Arial", 10, "bold"), anchor="w")
    canvas.create_window(110, 194, window=_bpm_entry())

    # ── step 3 — record ─────────────────────────────────────
    _section_label(canvas, 230, "3  —  RECORD")

    # Lane key pads
    pad_y0, pad_y1 = 246, 296
    pad_w = (WIDTH - 40 - 30) // 4   # 4 pads + 3 gaps
    for i, (lbl, col) in enumerate(zip(LANE_LABELS, LANE_COLS)):
        x0 = 20 + i * (pad_w + 10)
        t  = key_flash[i] / 10
        fill = lerp_color(PANEL2, col, t)
        out  = lerp_color(DIVIDER, col, t)
        draw_rounded_rect(canvas, x0, pad_y0, x0+pad_w, pad_y1, 10,
                          fill=fill, outline=out, width=2)
        canvas.create_text(x0 + pad_w//2, pad_y0 + 28,
                           text=lbl, fill=lerp_color(TEXT_MID,"#ffffff",t),
                           font=("Arial", 18, "bold"))

    # Key hint row
    canvas.create_text(WIDTH//2, 310,
                       text="D  F  G  H  — lanes      Backspace — undo      ESC — stop",
                       fill=TEXT_LO, font=("Arial", 10))

    # ── beat stats ──────────────────────────────────────────
    total = len(beats)
    per_lane = [sum(1 for b in beats if b["lane"]==i) for i in range(4)]
    draw_rounded_rect(canvas, 20, 324, WIDTH-20, 364, 8,
                      fill=PANEL, outline=DIVIDER)
    canvas.create_text(34, 344, text=f"Total beats: {total}",
                       fill=TEXT_HI, font=("Arial", 11, "bold"), anchor="w")
    for i, (n, col) in enumerate(zip(per_lane, LANE_COLS)):
        x = 200 + i * 58
        canvas.create_text(x, 344, text=f"{LANE_LABELS[i]}:{n}",
                           fill=col, font=("Arial", 11, "bold"))

    # ── timeline ────────────────────────────────────────────
    _draw_timeline(canvas, 20, 378, WIDTH-20, 438)

    # ── status ──────────────────────────────────────────────
    if recording_now:
        t_ms = int(elapsed_ms())
        status = f"● REC  {t_ms//60000:02d}:{(t_ms//1000)%60:02d}.{(t_ms//100)%10}   {total} beats"
        scol = MISS
    else:
        scol = ACCENT3 if status else TEXT_MID
        status = status or ("Ready — load an MP3 to begin" if not mp3_path else "Ready to record")

    draw_rounded_rect(canvas, 20, 452, WIDTH-20, 484, 8,
                      fill=PANEL, outline=DIVIDER)
    canvas.create_text(WIDTH//2, 468, text=status,
                       fill=scol, font=("Arial", 12, "bold"))

    # ── action buttons ──────────────────────────────────────
    _action_buttons(canvas, recording_now)


def _section_label(cvs, y, text):
    cvs.create_text(22, y, text=text, fill=TEXT_MID,
                    font=("Arial", 9, "bold"), anchor="w")
    cvs.create_line(22, y+12, WIDTH-22, y+12, fill=DIVIDER, width=1)

_bpm_widget = None
def _bpm_entry():
    """Return (and cache) the BPM Entry widget."""
    global _bpm_widget
    if _bpm_widget is None or not _bpm_widget.winfo_exists():
        _bpm_widget = tk.Entry(root, textvariable=bpm_var, width=5,
                               font=("Arial", 12, "bold"),
                               bg=PANEL2, fg=ACCENT3,
                               insertbackground=ACCENT3,
                               relief="flat", justify="center",
                               highlightthickness=1,
                               highlightcolor=ACCENT1,
                               highlightbackground=DIVIDER)
    return _bpm_widget

_btn_cache = {}
def _make_button(key, text, bg, fg, cmd, width=None):
    """Create-once, reuse button widgets to avoid leaking."""
    if key not in _btn_cache or not _btn_cache[key].winfo_exists():
        kw = dict(font=("Arial", 12, "bold"), bg=bg, fg=fg,
                  activebackground=bg, relief="flat",
                  padx=18, pady=8, cursor="hand2", bd=0)
        if width:
            kw["width"] = width
        _btn_cache[key] = tk.Button(root, text=text, command=cmd, **kw)
    else:
        _btn_cache[key].configure(text=text, bg=bg, command=cmd)
    return _btn_cache[key]

def _action_buttons(cvs, recording_now):
    # Load MP3
    b_load = _make_button("load", "Load MP3", PANEL2, ACCENT1, load_mp3)
    cvs.create_window(76, 524, window=b_load)

    # Record / Stop
    if recording_now:
        b_rec = _make_button("rec", "⏹  Stop", MISS, "#ffffff", stop_recording)
    else:
        b_rec = _make_button("rec", "⏺  Record", ACCENT1, "#0d0d14", start_recording)
    cvs.create_window(240, 524, window=b_rec)

    # Save
    b_save = _make_button("save", "💾  Save", ACCENT4, "#0d0d14", save_beatmap)
    cvs.create_window(400, 524, window=b_save)

    # Clear
    b_clear = _make_button("clear", "Clear", PANEL, MISS, clear_beats)
    cvs.create_window(WIDTH//2, 590, window=b_clear)


def _draw_timeline(cvs, x0, y0, x1, y1):
    """Draw a mini beat timeline between x0,y0 and x1,y1."""
    draw_rounded_rect(cvs, x0, y0, x1, y1, 8, fill=PANEL, outline=DIVIDER)
    cvs.create_text(x0+8, y0+10, text="TIMELINE", fill=TEXT_LO,
                    font=("Arial", 8, "bold"), anchor="w")

    tw = x1 - x0 - 16   # usable width
    th = y1 - y0 - 28
    tx = x0 + 8
    ty = y0 + 22

    if not beats:
        cvs.create_text((x0+x1)//2, (y0+y1)//2+6,
                        text="no beats recorded yet",
                        fill=TEXT_LO, font=("Arial", 10))
        return

    # Scale: max time or a minimum of 10 s
    max_t = max(b["time_ms"] for b in beats)
    scale_ms = max(max_t + 500, 10000)

    # Lane rows
    row_h = th // 4
    for i, col in enumerate(LANE_COLS):
        ry = ty + i * row_h
        # row bg
        cvs.create_rectangle(tx, ry, tx+tw, ry+row_h-2,
                              fill=lerp_color(PANEL, col, 0.06), outline="")
        cvs.create_text(tx+3, ry+row_h//2, text=LANE_LABELS[i],
                        fill=lerp_color(TEXT_LO, col, 0.5),
                        font=("Arial", 8, "bold"), anchor="w")
        # beat ticks
        for b in beats:
            if b["lane"] != i:
                continue
            bx = tx + 14 + int((b["time_ms"] / scale_ms) * (tw - 14))
            cvs.create_rectangle(bx-1, ry+3, bx+1, ry+row_h-5,
                                  fill=col, outline="")

    # playhead if recording
    if recording and start_time is not None:
        now = elapsed_ms()
        px = tx + 14 + int((now / scale_ms) * (tw - 14))
        px = min(px, tx + tw - 2)
        cvs.create_line(px, ty, px, ty+th, fill="#ffffff", width=1)

# ═══════════════════════════════════════════════════════════
#  RECORDING TICKER — updates status + timeline while live
# ═══════════════════════════════════════════════════════════
_ticker_id = None

def _start_ticker():
    global _ticker_id
    _stop_ticker()
    _tick()

def _tick():
    global _ticker_id
    if recording:
        # decay key flashes
        for i in range(4):
            if key_flash[i] > 0:
                key_flash[i] -= 1
        draw_ui(recording_now=True)
        _ticker_id = root.after(80, _tick)   # ~12 fps redraw while recording

def _stop_ticker():
    global _ticker_id
    if _ticker_id:
        root.after_cancel(_ticker_id)
        _ticker_id = None

# ═══════════════════════════════════════════════════════════
#  ACTIONS
# ═══════════════════════════════════════════════════════════
def load_mp3():
    global mp3_path
    path = filedialog.askopenfilename(
        filetypes=[("Audio files", "*.mp3 *.wav *.ogg"), ("All files", "*.*")]
    )
    if path:
        mp3_path = path
        draw_ui(status=f"Loaded: {os.path.basename(path)}")


def start_recording():
    global start_time, recording, beats
    if not mp3_path:
        draw_ui(status="Load an MP3 first!")
        return
    beats      = []
    recording  = True
    start_time = time.perf_counter()

    play_audio(mp3_path)

    root.bind("<KeyPress>",   _record_key)
    root.bind("<Escape>",     lambda e: stop_recording())
    root.bind("<BackSpace>",  _undo_beat)
    _start_ticker()


def _record_key(event):
    key = event.keysym.lower()
    if key in LANE_KEYS and recording:
        lane = LANE_KEYS[key]
        t_ms = int(elapsed_ms())
        beats.append({"lane": lane, "time_ms": t_ms})
        key_flash[lane] = 10   # trigger visual flash


def _undo_beat(event=None):
    """Remove the last recorded beat (Backspace during recording)."""
    if beats:
        beats.pop()
        key_flash[0] = key_flash[1] = key_flash[2] = key_flash[3] = 0


def stop_recording(status=None):
    global recording
    recording = False
    _stop_ticker()
    root.unbind("<KeyPress>")
    root.unbind("<Escape>")
    root.unbind("<BackSpace>")
    msg = status or f"Done — {len(beats)} beats recorded. Ready to save."
    draw_ui(status=msg)


def clear_beats():
    global beats
    if beats and not messagebox.askyesno("Clear beats",
            "Delete all recorded beats?"):
        return
    beats = []
    draw_ui(status="Beats cleared.")


def save_beatmap():
    if not mp3_path:
        draw_ui(status="No MP3 loaded!")
        return
    if not beats:
        draw_ui(status="Nothing recorded yet!")
        return

    os.makedirs("beatmaps", exist_ok=True)
    save_path = filedialog.asksaveasfilename(
        defaultextension=".beat",
        filetypes=[("Beat files", "*.beat")],
        initialdir="beatmaps"
    )
    if not save_path:
        return

    # Build payload — include BPM if provided and valid
    bpm_str = bpm_var.get().strip()
    try:
        bpm_val = float(bpm_str)
        if bpm_val <= 0:
            raise ValueError
    except ValueError:
        bpm_val = None

    # Sort beats chronologically before saving
    sorted_beats = sorted(beats, key=lambda b: b["time_ms"])

    # Optionally annotate each beat with bar/beat position
    if bpm_val:
        ms_per_beat = 60000.0 / bpm_val
        beats_per_bar = 4
        for b in sorted_beats:
            beat_idx  = b["time_ms"] / ms_per_beat
            bar       = int(beat_idx // beats_per_bar) + 1
            beat_pos  = (beat_idx % beats_per_bar) + 1
            b["bar"]  = bar
            b["beat"] = round(beat_pos, 3)

    data = {
        "mp3":    mp3_path,
        "beats":  sorted_beats,
    }
    if bpm_val:
        data["bpm"]            = bpm_val
        data["beats_per_bar"]  = 4

    with open(save_path, "w") as f:
        json.dump(data, f, indent=2)

    draw_ui(status=f"Saved → {os.path.basename(save_path)}")

# ═══════════════════════════════════════════════════════════
#  BOOT
# ═══════════════════════════════════════════════════════════
draw_ui()
root.mainloop()