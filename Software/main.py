"""
Tap Tap — Rhythm Game  (fixed + optimized + enhanced)
=====================================================
Keys  : D  F  G  H  — hit the four lanes
ESC   : return to menu at any time

Beat files live in ./beatmaps/*.beat  (JSON)
Audio is referenced inside the .beat file via the "mp3" key.
"""

import tkinter as tk
from tkinter import filedialog
import json
import time
import os
import threading
import math

# ── optional audio ─────────────────────────────────────────
try:
    from playsound3 import playsound as _playsound
    def play_audio(path):
        threading.Thread(target=lambda: _playsound(path), daemon=True).start()
except ImportError:
    def play_audio(_path):
        pass   # graceful no-op when playsound3 is absent

# ═══════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════
WIDTH, HEIGHT  = 420, 680
LANE_COUNT     = 4
LANE_WIDTH     = WIDTH // LANE_COUNT      # 105 px
HIT_Y          = HEIGHT - 100             # centre of hit zone
TILE_H         = LANE_WIDTH - 14          # tile height = tile width
TILE_SPEED     = 6                        # px per frame  (≈ 360 px/s @60 fps)
FPS_TARGET     = 60
FRAME_MS       = 1000 // FPS_TARGET       # ≈ 16 ms

# Colours  (neon arcade palette)
BG             = "#0d0d14"
LANE_DARK      = "#13131f"
LANE_LIGHT     = "#1a1a2e"
DIVIDER        = "#2a2a44"
HIT_LINE       = "#ffffff"
TILE_FILL      = "#00c8ff"
TILE_GLOW      = "#60e8ff"
KEY_IDLE       = "#252540"
KEY_ACTIVE     = "#00c8ff"
SCORE_COL      = "#e8e8ff"
COMBO_COL      = "#ffdc00"
PERFECT_COL    = "#00ff9f"
GOOD_COL       = "#ffdc00"
MISS_COL       = "#ff4466"
ACCENT1        = "#00c8ff"
ACCENT2        = "#ff6ec7"
ACCENT3        = "#ffdc00"

LANE_KEYS      = ["D", "F", "G", "H"]
LANE_KEY_SYMS  = {"d": 0, "f": 1, "g": 2, "h": 3}

# ═══════════════════════════════════════════════════════════
#  ROOT & CANVAS
# ═══════════════════════════════════════════════════════════
root = tk.Tk()
root.title("Tap Tap")
root.resizable(False, False)
root.configure(bg=BG)

canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg=BG,
                   highlightthickness=0)
canvas.pack()

# ─── state ─────────────────────────────────────────────────
score        = 0
combo        = 0
max_combo    = 0
judgment     = ""
judg_timer   = 0
tiles        = []          # each tile: [x, y, lane, age]
particles    = []          # hit-burst particles
game_loop_id = None
beat_data    = []
song_start   = None
spawned      = set()
key_glow     = [0, 0, 0, 0]     # per-lane glow countdown (frames)
bg_pulse     = 0                 # global ambient pulse counter
lead_ms      = 0.0               # precomputed tile travel time (ms)

# load offset from config
offset_ms = 0
if os.path.exists("config.json"):
    try:
        with open("config.json") as f:
            offset_ms = json.load(f).get("offset_ms", 0)
    except (json.JSONDecodeError, IOError):
        offset_ms = 0

# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════
def lerp_color(c1, c2, t):
    """Linearly interpolate between two hex colours."""
    r1, g1, b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2, g2, b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"

def spawn_particles(lane, hit_type):
    """Burst of small circles on a successful hit."""
    cx = lane * LANE_WIDTH + LANE_WIDTH // 2
    cy = HIT_Y + TILE_H // 2
    col = PERFECT_COL if hit_type == "PERFECT" else GOOD_COL
    for _ in range(12 if hit_type == "PERFECT" else 7):
        angle = math.radians((_ / (12 if hit_type=="PERFECT" else 7)) * 360)
        speed = 3.5 if hit_type == "PERFECT" else 2.5
        particles.append({
            "x": cx, "y": cy,
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "life": 22, "max": 22,
            "r": 5 if hit_type == "PERFECT" else 4,
            "col": col
        })

def draw_rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Draw a rounded rectangle on the canvas."""
    pts = [
        x1+radius, y1,  x2-radius, y1,
        x2, y1,         x2, y1+radius,
        x2, y2-radius,  x2, y2,
        x2-radius, y2,  x1+radius, y2,
        x1, y2,         x1, y2-radius,
        x1, y1+radius,  x1, y1,
        x1+radius, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kwargs)

def stop_loop():
    global game_loop_id
    if game_loop_id:
        root.after_cancel(game_loop_id)
        game_loop_id = None

def save_offset():
    with open("config.json", "w") as f:
        json.dump({"offset_ms": offset_ms}, f)

# ═══════════════════════════════════════════════════════════
#  MENU
# ═══════════════════════════════════════════════════════════
_menu_widgets = []

def show_menu():
    global _menu_widgets
    stop_loop()
    root.unbind("<KeyPress>")
    canvas.delete("all")
    # destroy any leftover tk widgets embedded in canvas
    for w in _menu_widgets:
        try: w.destroy()
        except Exception: pass
    _menu_widgets = []

    # --- background gradient stripes ---
    for i in range(HEIGHT // 4):
        shade = int(13 + i * 0.08)
        shade = min(shade, 30)
        canvas.create_rectangle(0, i*4, WIDTH, i*4+4,
                                 fill=f"#{shade:02x}{shade:02x}{shade+8:02x}",
                                 outline="")

    # decorative vertical lane lines
    for i in range(1, LANE_COUNT):
        canvas.create_line(i*LANE_WIDTH, 0, i*LANE_WIDTH, HEIGHT,
                           fill=DIVIDER, width=1)

    # title glow layers
    for off, alpha in [(4, "#003040"), (2, "#006070"), (0, ACCENT1)]:
        canvas.create_text(WIDTH//2 + off, 120 + off,
                           text="TAP TAP",
                           fill=alpha, font=("Arial", 44, "bold"))

    canvas.create_text(WIDTH//2, 175, text="R H Y T H M   G A M E",
                       fill=ACCENT2, font=("Arial", 13, "bold"))

    # ── buttons ──
    btn_cfg = [
        ("▶  PLAY BEATMAP",  ACCENT1,  "#0d0d14", 280, pick_beatmap),
        ("✏  OPEN EDITOR",   ACCENT3,  "#0d0d14", 355, open_editor),
        ("⚙  CALIBRATE",     ACCENT2,  "#0d0d14", 430, show_calibration),
    ]
    for text, bg_c, fg_c, y, cmd in btn_cfg:
        btn = tk.Button(root, text=text,
                        font=("Arial", 14, "bold"),
                        bg=bg_c, fg=fg_c, activebackground=bg_c,
                        relief="flat", padx=24, pady=10,
                        cursor="hand2", bd=0,
                        command=cmd)
        w = canvas.create_window(WIDTH//2, y, window=btn)
        _menu_widgets.append(btn)

    canvas.create_text(WIDTH//2, 520,
                       text=f"Offset: {offset_ms} ms",
                       fill="#444466", font=("Arial", 11))

    # lane key hints at bottom
    for i, lbl in enumerate(LANE_KEYS):
        x = i * LANE_WIDTH + LANE_WIDTH // 2
        draw_rounded_rect(canvas,
                          x - 18, HEIGHT - 55,
                          x + 18, HEIGHT - 25,
                          8, fill=KEY_IDLE, outline=DIVIDER)
        canvas.create_text(x, HEIGHT - 40, text=lbl,
                           fill="#7070a0", font=("Arial", 13, "bold"))

def pick_beatmap():
    os.makedirs("beatmaps", exist_ok=True)
    path = filedialog.askopenfilename(
        initialdir="beatmaps",
        filetypes=[("Beat files", "*.beat"), ("All files", "*.*")]
    )
    if path:
        load_and_start(path)

def open_editor():
    import subprocess, sys
    try:
        subprocess.Popen([sys.executable, "editor.py"])
    except FileNotFoundError:
        canvas.create_text(WIDTH//2, HEIGHT//2,
                           text="editor.py not found",
                           fill=MISS_COL, font=("Arial", 14))

# ═══════════════════════════════════════════════════════════
#  CALIBRATION
# ═══════════════════════════════════════════════════════════
calib_flash_time = None
calib_delays     = []
calib_loop_id    = None
CALIB_TOTAL      = 5

def show_calibration():
    global calib_delays, calib_flash_time, calib_loop_id
    calib_delays     = []
    calib_flash_time = None
    stop_loop()
    root.unbind("<KeyPress>")
    canvas.delete("all")
    draw_calib_screen()
    root.bind("<KeyPress>", calib_key)
    _schedule_flash()

def _schedule_flash():
    global calib_loop_id
    calib_loop_id = root.after(1200, _do_flash)

def _do_flash():
    global calib_flash_time
    calib_flash_time = time.perf_counter()
    draw_calib_screen(flash=True)
    root.after(180, lambda: draw_calib_screen(flash=False))

def calib_key(event):
    global offset_ms, calib_flash_time, calib_delays
    if event.keysym.lower() == "escape":
        if calib_loop_id:
            root.after_cancel(calib_loop_id)
        root.unbind("<KeyPress>")
        show_menu()
        return
    if calib_flash_time is None:
        return

    delay = int((time.perf_counter() - calib_flash_time) * 1000)
    calib_delays.append(delay)
    calib_flash_time = None
    remaining = CALIB_TOTAL - len(calib_delays)

    if remaining > 0:
        draw_calib_screen(msg=f"Recorded {delay} ms — {remaining} left")
        _schedule_flash()
    else:
        avg = sum(calib_delays) // len(calib_delays)
        offset_ms = avg
        save_offset()
        root.unbind("<KeyPress>")
        draw_calib_screen(msg=f"Done!  Offset set to {offset_ms} ms", done=True)
        root.after(2200, show_menu)

def draw_calib_screen(flash=False, msg="Press any key in sync with the flash", done=False):
    canvas.delete("all")
    # bg
    canvas.create_rectangle(0, 0, WIDTH, HEIGHT, fill=BG, outline="")

    canvas.create_text(WIDTH//2, 60, text="CALIBRATION",
                       fill=ACCENT2, font=("Arial", 26, "bold"))
    canvas.create_text(WIDTH//2, 100,
                       text=f"Flash {CALIB_TOTAL}× in sync — measures your reaction lag",
                       fill="#6666aa", font=("Arial", 11))

    cx, cy, r = WIDTH//2, 280, 65
    if flash:
        # glow rings
        for gr in range(3, 0, -1):
            canvas.create_oval(cx-(r+gr*10), cy-(r+gr*10),
                                cx+(r+gr*10), cy+(r+gr*10),
                                fill="", outline=lerp_color(ACCENT1, BG, gr/4),
                                width=2)
        canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                            fill=ACCENT1, outline="")
        canvas.create_text(cx, cy, text="HIT", fill=BG,
                           font=("Arial", 20, "bold"))
    else:
        canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                            fill="#1e1e38", outline=DIVIDER, width=2)
        canvas.create_text(cx, cy, text="●",
                           fill=DIVIDER, font=("Arial", 24))

    hits = len(calib_delays)
    for i in range(CALIB_TOTAL):
        ox = WIDTH//2 - (CALIB_TOTAL * 20)//2 + i*22 + 9
        col = PERFECT_COL if i < hits else "#2a2a44"
        canvas.create_oval(ox-9, 390-9, ox+9, 390+9,
                            fill=col, outline="")

    col_msg = PERFECT_COL if done else (ACCENT3 if "Recorded" in msg else "#aaaacc")
    canvas.create_text(WIDTH//2, 440, text=msg,
                       fill=col_msg, font=("Arial", 12))
    canvas.create_text(WIDTH//2, HEIGHT-25, text="ESC → back",
                       fill="#333355", font=("Arial", 10))

# ═══════════════════════════════════════════════════════════
#  GAME — LOAD & START
# ═══════════════════════════════════════════════════════════
def load_and_start(path):
    global score, combo, max_combo, judgment, judg_timer
    global tiles, particles, beat_data, song_start, spawned, key_glow

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        canvas.delete("all")
        canvas.create_text(WIDTH//2, HEIGHT//2,
                           text=f"Failed to load beatmap:\n{e}",
                           fill=MISS_COL, font=("Arial", 13),
                           justify="center")
        root.after(3000, show_menu)
        return

    beat_data  = data.get("beats", [])
    mp3        = data.get("mp3", "")
    score      = 0
    combo      = 0
    max_combo  = 0
    judgment   = ""
    judg_timer = 0
    tiles      = []
    particles  = []
    spawned    = set()
    key_glow   = [0, 0, 0, 0]

    canvas.delete("all")
    root.unbind("<KeyPress>")
    root.bind("<KeyPress>",   game_key_down)
    root.bind("<KeyRelease>", game_key_up)

    # Precompute beat time_ms from BPM if map uses bar/beat format
    bpm = data.get("bpm", None)
    if bpm and beat_data and "bar" in beat_data[0]:
        beats_per_bar = data.get("beats_per_bar", 4)
        ms_per_beat   = 60000.0 / bpm
        for b in beat_data:
            b["time_ms"] = int(
                ((b["bar"] - 1) * beats_per_bar + (b["beat"] - 1)) * ms_per_beat
            )

    # Precompute lead_ms with float precision (px to travel from spawn → hit zone)
    global lead_ms
    lead_ms = (HIT_Y / TILE_SPEED) * (1000.0 / FPS_TARGET)

    # audio_delay_ms: playsound3 takes ~80-150ms before audio is audible.
    # We backdate song_start so tiles visually align with what you hear.
    # Can be overridden per beatmap via the "audio_delay_ms" key.
    AUDIO_DELAY_MS = data.get("audio_delay_ms", 100)

    if mp3 and os.path.exists(mp3):
        play_audio(mp3)
    elif mp3:
        print(f"[warn] audio file not found: {mp3}")

    # Backdate so the clock already accounts for audio startup lag
    song_start = time.perf_counter() - (AUDIO_DELAY_MS / 1000.0)
    game_loop()

# ═══════════════════════════════════════════════════════════
#  GAME — INPUT
# ═══════════════════════════════════════════════════════════
def game_key_down(event):
    key = event.keysym.lower()
    if key == "escape":
        root.unbind("<KeyRelease>")
        show_menu()
        return
    lane = LANE_KEY_SYMS.get(key)
    if lane is not None:
        key_glow[lane] = 8
        check_hit(lane)

def game_key_up(event):
    key = event.keysym.lower()
    lane = LANE_KEY_SYMS.get(key)
    if lane is not None:
        key_glow[lane] = 0

# ═══════════════════════════════════════════════════════════
#  GAME — HIT DETECTION
# ═══════════════════════════════════════════════════════════
def check_hit(lane):
    global score, combo, max_combo, judgment, judg_timer

    # Find the closest tile in this lane
    best = None
    best_diff = float("inf")
    tile_hit_y = HIT_Y + TILE_H // 2          # centre of hit zone

    for tile in tiles:
        if tile[2] != lane:
            continue
        tile_centre = tile[1] + TILE_H // 2
        diff = abs(tile_centre - tile_hit_y)
        if diff < best_diff:
            best_diff = diff
            best = tile

    if best is None:
        return   # no tile in lane → silent (avoid phantom misses)

    if best_diff < 18:
        judgment  = "PERFECT"
        score    += 300 + combo * 10
        combo    += 1
        max_combo = max(max_combo, combo)
        tiles.remove(best)
        spawn_particles(lane, "PERFECT")
        judg_timer = 45
    elif best_diff < 42:
        judgment  = "GOOD"
        score    += 100 + combo * 3
        combo    += 1
        max_combo = max(max_combo, combo)
        tiles.remove(best)
        spawn_particles(lane, "GOOD")
        judg_timer = 40
    elif best_diff < 70:
        # pressed but tile is still far — count as early/late miss on that tile
        tiles.remove(best)
        combo     = 0
        judgment  = "MISS"
        judg_timer = 45
    # else: tile exists but is nowhere near → no feedback yet (wait for it)

# ═══════════════════════════════════════════════════════════
#  GAME — MAIN LOOP
# ═══════════════════════════════════════════════════════════
def game_loop():
    global judg_timer, combo, judgment, game_loop_id, bg_pulse

    # perf_counter gives microsecond resolution vs time.time()'s ~15ms on Windows
    now_ms     = (time.perf_counter() - song_start) * 1000.0
    bg_pulse   = (bg_pulse + 1) % 360
    judg_timer = max(0, judg_timer - 1)

    # ── spawn tiles ──────────────────────────────────────────
    # lead_ms is precomputed in load_and_start with float precision
    for i, beat in enumerate(beat_data):
        if i in spawned:
            continue
        spawn_time = (beat["time_ms"] - offset_ms) - lead_ms
        if now_ms >= spawn_time:
            lane = beat["lane"]
            x    = lane * LANE_WIDTH + 7
            tiles.append([x, -TILE_H, lane, 0])
            spawned.add(i)

    # ── move tiles & detect missed ───────────────────────────
    tile_hit_y = HIT_Y + TILE_H // 2
    for tile in tiles[:]:
        tile[1] += TILE_SPEED
        tile[3] += 1         # age
        # miss: tile has passed the hit line by a clear margin
        if tile[1] > HIT_Y + TILE_H + 30:
            tiles.remove(tile)
            combo      = 0
            judgment   = "MISS"
            judg_timer = 45

    # ── update particles ─────────────────────────────────────
    for p in particles[:]:
        p["x"]   += p["vx"]
        p["y"]   += p["vy"]
        p["vy"]  += 0.18      # gravity
        p["life"] -= 1
        if p["life"] <= 0:
            particles.remove(p)

    # ── key glow decay ───────────────────────────────────────
    for i in range(LANE_COUNT):
        key_glow[i] = max(0, key_glow[i] - 1)

    # ════════════════════════════════════════════════════════
    #  DRAW
    # ════════════════════════════════════════════════════════
    canvas.delete("all")

    # -- background + ambient pulse --
    pulse_val = int(4 + 3 * math.sin(math.radians(bg_pulse)))
    canvas.create_rectangle(0, 0, WIDTH, HEIGHT,
                             fill=BG, outline="")

    # -- lane panels --
    for i in range(LANE_COUNT):
        x0 = i * LANE_WIDTH
        fill = LANE_LIGHT if i % 2 == 0 else LANE_DARK
        canvas.create_rectangle(x0, 0, x0 + LANE_WIDTH - 1, HEIGHT,
                                 fill=fill, outline="")

    # -- lane dividers --
    for i in range(1, LANE_COUNT):
        canvas.create_line(i * LANE_WIDTH, 0, i * LANE_WIDTH, HEIGHT,
                           fill=DIVIDER, width=1)

    # -- approach guide lines (faint horizontal bars) --
    for gy in range(0, HEIGHT, 80):
        canvas.create_line(0, gy, WIDTH, gy, fill="#1f1f30", width=1)

    # -- hit zone glow bar --
    canvas.create_rectangle(0, HIT_Y - 4, WIDTH, HIT_Y + TILE_H + 4,
                             fill="#1a1a3a", outline="")
    canvas.create_line(0, HIT_Y + TILE_H, WIDTH, HIT_Y + TILE_H,
                       fill=HIT_LINE, width=2)
    # subtle glow above hit line
    for gw in range(1, 5):
        alpha = int(30 - gw * 5)
        canvas.create_line(0, HIT_Y + TILE_H - gw,
                           WIDTH, HIT_Y + TILE_H - gw,
                           fill=f"#2{gw:01x}2{gw:01x}5{gw:01x}", width=1)

    # -- key circles --
    for i, lbl in enumerate(LANE_KEYS):
        x0 = i * LANE_WIDTH + 7
        t  = key_glow[i] / 8
        fill = lerp_color(KEY_IDLE, KEY_ACTIVE, t)
        outline = lerp_color(DIVIDER, ACCENT1, t)
        # glow ring when active
        if t > 0.1:
            canvas.create_oval(x0 - 4, HIT_Y - 4,
                                x0 + LANE_WIDTH - 14 + 4, HIT_Y + TILE_H + 4,
                                fill="", outline=lerp_color("#001828", ACCENT1, t),
                                width=3)
        draw_rounded_rect(canvas, x0, HIT_Y, x0 + LANE_WIDTH - 14, HIT_Y + TILE_H,
                          10, fill=fill, outline=outline, width=1)
        canvas.create_text(x0 + (LANE_WIDTH - 14) // 2,
                           HIT_Y + TILE_H // 2,
                           text=lbl,
                           fill=lerp_color("#5060a0", "#ffffff", t),
                           font=("Arial", 14, "bold"))

    # -- tiles --
    for tile in tiles:
        x0, y0, lane = tile[0], tile[1], tile[2]
        x1, y1 = x0 + LANE_WIDTH - 14, y0 + TILE_H
        # proximity fade-in: brighten as tile approaches hit zone
        dist   = abs((y0 + TILE_H // 2) - (HIT_Y + TILE_H // 2))
        bright = max(0.4, 1.0 - dist / HEIGHT)
        fill_c = lerp_color("#003050", TILE_FILL, bright)
        glow_c = lerp_color("#004060", TILE_GLOW, bright)

        # outer glow
        canvas.create_oval(x0 - 3, y0 - 3, x1 + 3, y1 + 3,
                            fill="", outline=lerp_color(LANE_DARK, glow_c, bright * 0.5),
                            width=2)
        # tile body
        draw_rounded_rect(canvas, x0, y0, x1, y1, 10,
                          fill=fill_c, outline=glow_c, width=1)
        # inner highlight
        canvas.create_oval(x0 + 8, y0 + 5, x0 + (LANE_WIDTH - 14) // 2, y0 + 16,
                            fill=lerp_color(fill_c, "#ffffff", 0.35), outline="")

    # -- particles --
    for p in particles:
        t   = p["life"] / p["max"]
        r   = int(p["r"] * t)
        col = lerp_color(BG, p["col"], t)
        if r > 0:
            canvas.create_oval(p["x"] - r, p["y"] - r,
                                p["x"] + r, p["y"] + r,
                                fill=col, outline="")

    # -- HUD --
    # score
    canvas.create_text(12, 14, text=f"{score:,}",
                       fill=SCORE_COL, font=("Arial", 22, "bold"), anchor="nw")
    canvas.create_text(12, 42, text="SCORE",
                       fill="#404070", font=("Arial", 9, "bold"), anchor="nw")

    # combo
    if combo > 1:
        scale = min(1.0, 0.6 + combo * 0.02)
        size  = int(20 * scale)
        canvas.create_text(WIDTH - 12, 14,
                           text=f"×{combo}",
                           fill=COMBO_COL, font=("Arial", size, "bold"),
                           anchor="ne")
        canvas.create_text(WIDTH - 12, 14 + size + 4, text="COMBO",
                           fill="#806020", font=("Arial", 9, "bold"), anchor="ne")

    canvas.create_text(WIDTH - 12, HEIGHT - 14, text="ESC  menu",
                       fill="#2a2a44", font=("Arial", 9), anchor="se")

    # -- judgment text --
    if judg_timer > 0:
        t = judg_timer / 45
        if judgment == "PERFECT":
            col = PERFECT_COL
        elif judgment == "GOOD":
            col = GOOD_COL
        else:
            col = MISS_COL

        # fade + slight scale
        size = int(26 + 8 * (1 - t))
        canvas.create_text(WIDTH // 2, HEIGHT // 2 - 60,
                           text=judgment,
                           fill=lerp_color(BG, col, t ** 0.4),
                           font=("Arial", size, "bold"))

    game_loop_id = root.after(FRAME_MS, game_loop)

# ═══════════════════════════════════════════════════════════
#  BOOT
# ═══════════════════════════════════════════════════════════
show_menu()
root.mainloop()
