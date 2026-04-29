# oi — main.py (Pi RPC edition)
# The device frontend for Pi backend via TCP JSONL gateway.
#
# Screens:
#   session idle  — default; shows active session name + status.
#   question      — overlay when a Pi extension_ui_request arrives.
#   session picker — modal; used when no session is active.
#   settings      — modal; BtnA cycles/edits, BtnA.long saves+exits.
#
# Button contract (non-settings screens):
#   BtnA tap      — open command menu (session idle) / answer (question) / ping (no session)
#   BtnA double   — speak last response (session idle) / ping (no session)
#   BtnA hold     — voice input (session idle)
#   BtnB tap      — next session (session idle) / cycle options (question)
#   BtnB long     — settings
#
# Speak is also available as a menu option.

from boot import tft, btnA, btnB, wlan, pmic, audio, mic
import st7789py as st7789
import vga2_8x16 as font_sm
import vga2_bold_16x32 as font_lg
from oi_session_ui import (
    command_count,
    command_is_local,
    command_label,
    command_payload,
    json_headers,
    rpc_command_payload,
    selected_index_for_active,
    session_label,
    session_status,
    sessions_summary,
    visible_window_start,
    wrap_index,
)
from oi_event_render import render_idle_status_line
from oi_interaction import (
    ACTION_ANSWER,
    ACTION_EDIT,
    ACTION_NEXT,
    ACTION_NEXT_SESSION,
    ACTION_OPEN_MENU,
    ACTION_OPEN_SETTINGS,
    ACTION_PING,
    ACTION_SAVE_EXIT,
    ACTION_SPEAK,
    ACTION_VOICE,
    BTN_A,
    BTN_B,
    MODE_IDLE,
    MODE_QUESTION,
    MODE_SESSION,
    MODE_SETTINGS,
    DebouncedPress as Button,
    GestureDetector as ButtonPattern,
    action_for,
)
from pi_rpc_client import PiRpcClient, PiRpcStateMapper

import gc
import re
import urequests
import ujson
import time
import ujson as json_mod   # alias for settings I/O
import secrets

try:
    from version import VERSION as _FW_VERSION
except Exception:
    _FW_VERSION = "?"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Pi RPC gateway (TCP JSONL)
PI_RPC_HOST = getattr(secrets, "PI_RPC_HOST", "gateway.local")
PI_RPC_PORT = getattr(secrets, "PI_RPC_PORT", 8843)

# Legacy HTTP server (retained for audio/TTS until those endpoints are rehosted)
SERVER_URL   = getattr(secrets, "OI_SERVER_URL", "http://gateway.local:8842")
OI_API_TOKEN = getattr(secrets, "OI_API_TOKEN", None)
# Poor-man's feature flag: set SPEAK_DEBUG = True in device-local /secrets.py
# to show step-by-step speak flashes while debugging.
SPEAK_DEBUG  = bool(getattr(secrets, "SPEAK_DEBUG", False))

# Timing
POLL_INTERVAL_MS       = 5_000   # how often to send get_state (awake)
SLEEP_POLL_INTERVAL_MS = 30_000  # poll cadence while display is sleeping
LOOP_SLEEP_MS          =    30   # inner-loop cadence (keeps buttons responsive)
DEBOUNCE_MS            =    30   # button debounce window
SENT_FLASH_MS          = 1_000   # how long to show "sent: <value>" feedback
IDLE_SLEEP_MS          = 30_000  # idle time before display goes to sleep
BAT_REFRESH_MS         = 10_000  # how often to re-read battery (I²C reads are cheap)
REPLY_PREVIEW_TTL_MS   = 30_000  # show last assistant reply for this long on idle screen

# Button pattern timing
BTN_LONG_MS   = 800   # hold ≥ 800ms = long press
BTN_DOUBLE_MS = 400   # second press within 400ms = double press

# Brightness presets (%)
BRIGHTNESS_PRESETS = {"low": 25, "medium": 60, "high": 100}
BRIGHTNESS_PRESET_KEYS = ["low", "medium", "high"]  # cycle order

# Settings file on device flash
SETTINGS_PATH = "/settings.json"

# Display geometry — landscape 240×135
W = 240
H = 135

# Layout zones
# Title row: y=0..32 (font_lg.HEIGHT=32)
# Body rows: y=32..119 (87 px = 5 rows of small font)
# Options/status row: y=119..135 (font_sm.HEIGHT=16)
TEXT_COL_W  = 240   # full screen width for title and body
STATUS_H    = 16    # status bar / options row height (= font_sm.HEIGHT)
STATUS_Y    = H - STATUS_H          # y=119
TITLE_H     = 32    # one large-font row (font_lg.HEIGHT=32)
BODY_Y      = TITLE_H               # body starts immediately below title
BODY_H      = STATUS_Y - BODY_Y     # 87 px — 5 rows of small font

# Battery cache — refreshed at most every BAT_REFRESH_MS to avoid redundant I²C reads.
_bat_pct        = None   # int 0-100, or None if not yet read
_bat_usb        = False  # True if USB power present
_bat_last_ms    = -BAT_REFRESH_MS  # force immediate read on first call

# ---------------------------------------------------------------------------
# Settings — loaded from flash, persisted on change
# ---------------------------------------------------------------------------

_settings = {
    "brightness": "high",    # "low" | "medium" | "high"
    "volume": 100,
    "mute": False,  # legacy setting; mapped to volume=0 on load
    "wake_chirp": False,
}


def load_settings():
    """Load settings from flash. Falls back to defaults silently on any error."""
    global _settings
    try:
        with open(SETTINGS_PATH, "r") as f:
            loaded = json_mod.load(f)
        # Merge: only accept known keys with valid types
        if "brightness" in loaded and loaded["brightness"] in BRIGHTNESS_PRESETS:
            _settings["brightness"] = loaded["brightness"]
        if "volume" in loaded and isinstance(loaded["volume"], int):
            _settings["volume"] = max(0, min(100, loaded["volume"]))
            _settings["mute"] = (_settings["volume"] == 0)
        elif "mute" in loaded and isinstance(loaded["mute"], bool):
            _settings["mute"] = loaded["mute"]
            _settings["volume"] = 0 if loaded["mute"] else 100
        if "wake_chirp" in loaded and isinstance(loaded["wake_chirp"], bool):
            _settings["wake_chirp"] = loaded["wake_chirp"]
    except Exception:
        pass  # file not present or parse error → keep defaults


def save_settings():
    """Persist current settings to flash."""
    try:
        with open(SETTINGS_PATH, "w") as f:
            json_mod.dump(_settings, f)
    except Exception as e:
        print("[main] save_settings error:", e)


# ---------------------------------------------------------------------------
# Brightness helpers
# ---------------------------------------------------------------------------

_brightness_pct = 75   # module-level current brightness percent


def _apply_brightness(pct):
    """Set backlight PWM duty for the given brightness percent (0-100)."""
    global _brightness_pct
    _brightness_pct = max(0, min(100, pct))
    try:
        if tft.backlight is not None:
            tft.backlight.duty_u16(int(_brightness_pct * 65535 // 100))
    except Exception as e:
        print("[main] brightness error:", e)


# ---------------------------------------------------------------------------
# Last seen chirp / speak seq (for one-shot delivery)
# ---------------------------------------------------------------------------

_last_chirp_seq = None
_last_speak_seq = None
_voice_hold_start_ms = None  # time.ticks_ms() when A was first seen pressed (for voice input)

# Colors (re-exported from st7789py for clarity)
BLACK   = st7789.BLACK
WHITE   = st7789.WHITE
GREEN   = st7789.GREEN
RED     = st7789.RED
YELLOW  = st7789.YELLOW
CYAN    = st7789.CYAN

# ---------------------------------------------------------------------------
# Display sleep / wake helpers
# ---------------------------------------------------------------------------

def display_sleep():
    """Turn off backlight and put LCD controller into SLPIN mode."""
    try:
        tft.sleep_mode(True)            # SLPIN command to ST7789
        if tft.backlight is not None:
            tft.backlight.duty_u16(0)   # backlight off (PWM to 0)
    except Exception as e:
        print("[main] display_sleep error:", e)


def display_wake():
    """Wake LCD (SLPOUT requires ~120 ms settle) and restore backlight brightness."""
    try:
        tft.sleep_mode(False)           # SLPOUT command to ST7789
        time.sleep_ms(120)              # datasheet-mandated settle time
        _apply_brightness(_brightness_pct)  # restore last brightness
    except Exception as e:
        print("[main] display_wake error:", e)


# ---------------------------------------------------------------------------
# Text layout helpers
# ---------------------------------------------------------------------------

def _chars_for(font, px):
    """How many characters of `font` fit in `px` pixels wide."""
    return px // font.WIDTH


def _wrap(text, chars_per_line):
    """
    Word-wrap `text` into a list of strings, each at most `chars_per_line`
    characters wide. Breaks on spaces where possible; hard-breaks otherwise.
    """
    if not text:
        return []
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) == 0:
            current = word
        elif len(current) + 1 + len(word) <= chars_per_line:
            current += " " + word
        else:
            lines.append(current)
            current = word
        # Hard-break any word longer than the line width.
        while len(current) > chars_per_line:
            lines.append(current[:chars_per_line])
            current = current[chars_per_line:]
    if current:
        lines.append(current)
    return lines


def _draw_text_block(lines, y_start, font, x=0, col_w=None,
                     fg=WHITE, bg=BLACK, max_lines=None):
    """
    Draw a list of strings from (x, y_start) downward within col_w pixels.
    Returns the y after the last drawn row.
    Clears each row to bg before drawing so old text is erased.
    col_w defaults to W - x (full remaining width).
    """
    if col_w is None:
        col_w = W - x
    cpl = _chars_for(font, col_w)
    drawn = 0
    y = y_start
    for line in lines:
        if max_lines is not None and drawn >= max_lines:
            break
        padded = (line + " " * cpl)[:cpl]
        tft.text(font, padded, x, y, fg, bg)
        y += font.HEIGHT
        drawn += 1
    return y


def _clear_row(y, height, color=BLACK):
    """Fill a horizontal band with a solid colour."""
    tft.fill_rect(0, y, W, height, color)


# ---------------------------------------------------------------------------
# Screen renderers
# ---------------------------------------------------------------------------

def draw_idle():
    """
    Idle screen (landscape 240×135): big centred 'oi', hint row above status
    bar, RSSI status bar at bottom.
    """
    tft.fill(BLACK)

    # Centre "oi" using the large font (16×32 per char) in the full 240 width.
    text = "oi"
    text_w = len(text) * font_lg.WIDTH
    text_h = font_lg.HEIGHT
    x = (W - text_w) // 2
    y = (STATUS_Y - text_h) // 2   # vertically centred in usable area above status bar
    tft.text(font_lg, text, x, y, CYAN, BLACK)

    # Hint row: sits just above the status bar, full width.
    hint_y = STATUS_Y - font_sm.HEIGHT
    cpl = _chars_for(font_sm, W)
    hint = ("B: sessions  A: ping" + " " * cpl)[:cpl]
    tft.text(font_sm, hint, 0, hint_y, WHITE, BLACK)

    _draw_status_bar()


def draw_session_idle(session, state=None):
    """Session-active idle screen: session name + status + latest reply hint."""
    tft.fill(BLACK)
    cpl_lg = _chars_for(font_lg, W)
    cpl_sm = _chars_for(font_sm, W)

    label = session_label(session) if session else "no session"
    tft.text(font_lg, (label + " " * cpl_lg)[:cpl_lg], 0, 0, CYAN, BLACK)

    status = session_status(session) if session else ""
    if status:
        lines = _wrap(status, cpl_sm)
        _draw_text_block(lines[:1], BODY_Y, font_sm)

    # Show model and/or thinking-level from the last setting change, right after idle status.
    if state:
        model_line = ""
        model_change = state.get("last_model_change")
        thinking_change = state.get("last_thinking_change")
        if model_change:
            # Truncate long model IDs like "anthropic/claude-sonnet-4-20250514"
            short = str(model_change).split("/")[-1][:20]
            model_line = "model: " + short
        if thinking_change:
            # Show thinking level on same line if model shown, else alone
            if model_line:
                model_line += "  think: " + str(thinking_change)
            else:
                model_line = "think: " + str(thinking_change)
        if model_line:
            lines = _wrap(model_line, cpl_sm)
            _draw_text_block(lines[:1], BODY_Y + (1 * font_sm.HEIGHT), font_sm, fg=CYAN, bg=BLACK)

    # Show the latest assistant reply (if available) so prompt tests can be
    # verified directly on-device without watching gateway logs.
    if state:
        snap = state.get("snapshot") or {}
        reply = snap.get("msg") or ""
        ts = snap.get("ts")
        show_reply = False
        if reply and ts is not None:
            age_ms = time.ticks_diff(time.ticks_ms(), ts)
            show_reply = (age_ms >= 0 and age_ms <= REPLY_PREVIEW_TTL_MS)
        elif reply:
            # Backward compatibility if ts is missing.
            show_reply = True
        if show_reply:
            preview = "pi: " + str(reply)
            lines = _wrap(preview, cpl_sm)
            _draw_text_block(lines[:2], BODY_Y + (1 * font_sm.HEIGHT), font_sm, fg=GREEN, bg=BLACK)

    # Show high-signal event status (tool running, queue, compaction, etc.)
    event_status = render_idle_status_line(state or {})
    if event_status:
        lines = _wrap(event_status, cpl_sm)
        _draw_text_block(lines[:1], BODY_Y + (3 * font_sm.HEIGHT), font_sm, fg=YELLOW, bg=BLACK)

    hint_y = STATUS_Y - font_sm.HEIGHT
    hint = ("A:menu 2A:say hA:talk" + " " * cpl_sm)[:cpl_sm]
    hint_color = WHITE
    tft.text(font_sm, hint, 0, hint_y, hint_color, BLACK)

    _draw_status_bar()


def _active_session_from_state(state):
    """Return the active session dict from polled state, or None."""
    if not state:
        return None
    sinfo = state.get("sessions")
    if not sinfo:
        return None
    active_id = sinfo.get("active_session_id")
    sessions = sinfo.get("sessions") or []
    for s in sessions:
        if s.get("session_id") == active_id:
            return s
    return sessions[0] if sessions else None


def _next_session(state, current_session):
    """Return the next session in the list after current_session (wraps)."""
    sessions = ((state or {}).get("sessions") or {}).get("sessions") or []
    if len(sessions) <= 1:
        return current_session
    cur_id = (current_session or {}).get("session_id")
    for i, s in enumerate(sessions):
        if s.get("session_id") == cur_id:
            return sessions[(i + 1) % len(sessions)]
    return sessions[0] if sessions else current_session


def _refresh_battery():
    """Re-read battery percent and USB state from PMIC if cache is stale."""
    global _bat_pct, _bat_usb, _bat_last_ms
    now = time.ticks_ms()
    if time.ticks_diff(now, _bat_last_ms) < BAT_REFRESH_MS:
        return
    _bat_last_ms = now
    try:
        _bat_pct = pmic.battery_percent()
        _bat_usb = pmic.usb_connected()
    except Exception as e:
        print("[main] battery read error:", e)
        _bat_pct = None
        _bat_usb = False


def _draw_status_bar():
    """Draw a small status line at the bottom of the screen (y=STATUS_Y, full width).

    Format: 'ready rssi:-60 bat:87%'
    With USB/charging: 'ready rssi:-60 bat:87%+'
    """
    _refresh_battery()

    try:
        rssi = wlan.status("rssi")
        rssi_str = "rssi:{:d}".format(rssi)
    except Exception:
        rssi_str = "rssi:?"

    if _bat_pct is None:
        bat_str = "bat:--"
    else:
        bat_str = "bat:{:d}%".format(_bat_pct)
        if _bat_usb:
            bat_str += "+"

    cpl = _chars_for(font_sm, W)
    line = (_FW_VERSION + " " + rssi_str + " " + bat_str + " " * cpl)[:cpl]
    tft.text(font_sm, line, 0, STATUS_Y, WHITE, BLACK)


def draw_question(state, highlighted):
    """
    Render a question on screen (landscape 240×135).

    Layout:
      Full width (x=0..240):
        [y=0..32]      title  — bold 16×32, up to 2 lines (15 chars each)
        [y=32..119]    body   — small 8×16, up to 5 lines, 30 chars each
        [y=119..135]   options bottom row — small 8×16, horizontal, with
                       highlighted option inverted (yellow bg); arrows when
                       more options exist than fit.
    """
    tft.fill(BLACK)

    title  = state.get("title") or ""
    body   = state.get("body") or ""
    opts   = state.get("options") or []

    # --- Title (large font, full width, 2-line cap) ---
    cpl_lg = _chars_for(font_lg, TEXT_COL_W)   # 240/16 = 15 chars
    title_lines = _wrap(title, cpl_lg)
    _draw_text_block(title_lines, 0, font_lg, x=0, col_w=TEXT_COL_W,
                     fg=WHITE, bg=BLACK, max_lines=2)

    # --- Body (small font, full width, up to 5 rows) ---
    cpl_sm = _chars_for(font_sm, TEXT_COL_W)   # 240/8 = 30 chars
    max_body_rows = BODY_H // font_sm.HEIGHT    # 87/16 = 5 rows
    if body:
        body_lines = _wrap(body, cpl_sm)
        _draw_text_block(body_lines, BODY_Y, font_sm, x=0, col_w=TEXT_COL_W,
                         fg=WHITE, bg=BLACK, max_lines=max_body_rows)

    # --- Options bottom row ---
    _draw_options_bottom(opts, highlighted)

    # --- Status bar only shown when idle; bottom row is the options row here ---


def _draw_options_bottom(opts, highlighted):
    """
    Draw options horizontally in the bottom row (y=STATUS_Y..135, full width).

    Each option is drawn as its label text. The highlighted option gets an
    inverted background (BLACK fg on YELLOW bg). Others are WHITE on BLACK.
    Options are separated by a single space.

    If all options fit in 30 chars (full row width), they are all drawn.
    Otherwise a sliding window is used:
      - The window always includes the highlighted option.
      - A leading '<' appears if options before the window are hidden.
      - A trailing '>' appears if options after the window are hidden.
    """
    # Clear the bottom row first.
    tft.fill_rect(0, STATUS_Y, W, font_sm.HEIGHT, BLACK)

    if not opts:
        return

    labels = [o.get("label", "?") for o in opts]
    n = len(labels)

    # Max chars that fit in the bottom row.
    ROW_CHARS = _chars_for(font_sm, W)   # 240/8 = 30

    # Compute label widths (chars): label text length.
    # Each option takes len(label) chars; options separated by 1 space.
    # Total without separators = sum(lens); separators = n-1.

    def total_width(start, end):
        """Total chars for options[start..end-1] with separators (no arrows)."""
        return sum(len(labels[i]) for i in range(start, end)) + (end - start - 1)

    def total_width_with_arrows(start, end, has_left, has_right):
        """Total chars including '< ' prefix and/or ' >' suffix."""
        w = total_width(start, end)
        if has_left:
            w += 2   # '< '
        if has_right:
            w += 2   # ' >'
        return w

    # Try to fit all options first.
    if total_width(0, n) <= ROW_CHARS:
        # All fit — draw them all.
        start_idx = 0
        end_idx = n
        has_left = False
        has_right = False
    else:
        # Windowed. Find the largest window that includes `highlighted` and fits.
        # Start with a window containing just the highlighted option, then expand.
        start_idx = highlighted
        end_idx = highlighted + 1

        # Try to expand in both directions.
        while True:
            expanded = False
            # Try expanding right.
            if end_idx < n:
                new_has_left  = start_idx > 0
                new_has_right = (end_idx + 1) < n
                if total_width_with_arrows(start_idx, end_idx + 1, new_has_left, new_has_right) <= ROW_CHARS:
                    end_idx += 1
                    expanded = True
            # Try expanding left.
            if start_idx > 0:
                new_has_left  = (start_idx - 1) > 0
                new_has_right = end_idx < n
                if total_width_with_arrows(start_idx - 1, end_idx, new_has_left, new_has_right) <= ROW_CHARS:
                    start_idx -= 1
                    expanded = True
            if not expanded:
                break

        has_left  = start_idx > 0
        has_right = end_idx < n

    # Now render the row.
    x = 0

    if has_left:
        tft.text(font_sm, "< ", x, STATUS_Y, WHITE, BLACK)
        x += 2 * font_sm.WIDTH

    for i in range(start_idx, end_idx):
        label = labels[i]
        if i == highlighted:
            fg, bg = BLACK, YELLOW
        else:
            fg, bg = WHITE, BLACK

        # Draw the label with highlight bg.
        lw = len(label) * font_sm.WIDTH
        tft.fill_rect(x, STATUS_Y, lw, font_sm.HEIGHT, bg)
        tft.text(font_sm, label, x, STATUS_Y, fg, bg)
        x += lw

        # Draw separator space (always normal bg) unless last in window.
        if i < end_idx - 1:
            tft.fill_rect(x, STATUS_Y, font_sm.WIDTH, font_sm.HEIGHT, BLACK)
            tft.text(font_sm, " ", x, STATUS_Y, WHITE, BLACK)
            x += font_sm.WIDTH

    if has_right:
        tft.text(font_sm, " >", x, STATUS_Y, WHITE, BLACK)


def draw_dashboard(snap):
    """
    Dashboard screen (landscape 240×135): ambient agent snapshot.

    Layout:
      [y=0..32]    msg — bold 16×32 font, up to 2 lines (15 chars each)
      [y=32..48]   counts + tokens — small 8×16 font (30 chars)
      [y=48..64]   entry 0 (newest), prefixed ">"
      [y=64..80]   entry 1
      [y=80..96]   entry 2
      [y=96..112]  blank row (spacer)
      [y=119..135] status bar (RSSI)
    """
    tft.fill(BLACK)

    # --- msg (title area, large font, 2-line cap) ---
    cpl_lg = _chars_for(font_lg, TEXT_COL_W)   # 15 chars
    msg = snap.get("msg") or "oi"
    msg_lines = _wrap(msg, cpl_lg)
    if not msg_lines:
        msg_lines = ["oi"]
    _draw_text_block(msg_lines, 0, font_lg, x=0, col_w=TEXT_COL_W,
                     fg=CYAN, bg=BLACK, max_lines=2)

    # --- counts + tokens row (y=32) ---
    cpl_sm = _chars_for(font_sm, TEXT_COL_W)   # 30 chars
    running = snap.get("running")
    waiting = snap.get("waiting")
    tokens = snap.get("tokens_today")

    # Build left and right parts, join with padding.
    left = ""
    if running is not None:
        left += "running:{:d}".format(running)
    if waiting is not None:
        if left:
            left += "  "
        left += "waiting:{:d}".format(waiting)

    right = ""
    if tokens is not None:
        if tokens >= 1000:
            right = "{:d}k tok".format(tokens // 1000)
        else:
            right = "{:d} tok".format(tokens)

    if left or right:
        gap = cpl_sm - len(left) - len(right)
        counts_line = left + " " * max(1, gap) + right
        counts_line = (counts_line + " " * cpl_sm)[:cpl_sm]
    else:
        counts_line = " " * cpl_sm

    tft.text(font_sm, counts_line, 0, BODY_Y, WHITE, BLACK)

    # --- entries (y=48..96, 3 rows) ---
    entries = snap.get("entries") or []
    entry_y = BODY_Y + font_sm.HEIGHT   # y=48
    for i in range(3):
        if i < len(entries):
            prefix = ">" if i == 0 else " "
            raw = str(entries[i])
            # prefix + space + up to (cpl_sm-2) chars of entry
            line = (prefix + " " + raw + " " * cpl_sm)[:cpl_sm]
        else:
            line = " " * cpl_sm
        tft.text(font_sm, line, 0, entry_y + i * font_sm.HEIGHT, WHITE, BLACK)

    # blank spacer row at y=96 — already cleared by tft.fill(BLACK)

    _draw_status_bar()


def draw_offline_indicator():
    """
    Small red 'OFFLINE' tag at the top-right corner.
    In landscape (W=240), 'OFFLINE' is 7 chars × 8 px = 56 px wide.
    """
    label = "OFFLINE"
    x = W - len(label) * font_sm.WIDTH   # 240 - 56 = 184
    tft.fill_rect(x, 0, W - x, font_sm.HEIGHT, RED)
    tft.text(font_sm, label, x, 0, WHITE, RED)


def draw_flash(msg):
    """Full-screen brief status flash (e.g. 'sent: ok'). Centred in landscape."""
    tft.fill(BLACK)
    cpl = _chars_for(font_sm, W)
    padded = (msg + " " * cpl)[:cpl]
    y = (H - font_sm.HEIGHT) // 2
    tft.text(font_sm, padded, 0, y, GREEN, BLACK)


def draw_transcript_preview(transcript):
    """Show transcript text wrapped across the screen body."""
    tft.fill(BLACK)
    cpl_lg = _chars_for(font_lg, W)
    tft.text(font_lg, ("sent:" + " " * cpl_lg)[:cpl_lg], 0, 0, GREEN, BLACK)
    cpl_sm = _chars_for(font_sm, W)
    max_body_lines = (STATUS_Y - BODY_Y) // font_sm.HEIGHT
    lines = _wrap(transcript, cpl_sm)
    _draw_text_block(lines[:max_body_lines], BODY_Y, font_sm)


def draw_sessions_menu(sessions, active_id, highlighted):
    """Render the session picker."""
    tft.fill(BLACK)
    cpl_lg = _chars_for(font_lg, TEXT_COL_W)
    tft.text(font_lg, ("sessions" + " " * cpl_lg)[:cpl_lg], 0, 0, CYAN, BLACK)
    cpl_sm = _chars_for(font_sm, TEXT_COL_W)
    if not sessions:
        tft.text(font_sm, ("no sessions" + " " * cpl_sm)[:cpl_sm], 0, BODY_Y, WHITE, BLACK)
    else:
        max_rows = (STATUS_Y - BODY_Y) // font_sm.HEIGHT
        start_idx = visible_window_start(highlighted, len(sessions), max_rows)
        for row in range(max_rows):
            idx = start_idx + row
            if idx >= len(sessions):
                break
            session = sessions[idx]
            prefix = ">" if idx == highlighted else " "
            active = "*" if session.get("session_id") == active_id else " "
            name = session_label(session)[:12]
            status = session_status(session)[:12]
            line = "%s%s %-12s %s" % (prefix, active, name, status)
            tft.text(font_sm, (line + " " * cpl_sm)[:cpl_sm], 0,
                     BODY_Y + row * font_sm.HEIGHT, WHITE, BLACK)
    hint = "B:next 2B:prev A:sel Ah:cmd"
    tft.text(font_sm, (hint + " " * cpl_sm)[:cpl_sm], 0, STATUS_Y, WHITE, BLACK)


def draw_command_menu(session, highlighted):
    """Render canned command picker — two-column layout.

    Layout (landscape 240×135):
      [y=0..32]    session title (large font)
      [y=32..119]  command grid: 2 columns × N/2 rows
      [y=119..135] hint row
    """
    tft.fill(BLACK)
    cpl_lg = _chars_for(font_lg, TEXT_COL_W)
    title = (session_label(session) or "session")[:15]
    tft.text(font_lg, (title + " " * cpl_lg)[:cpl_lg], 0, 0, CYAN, BLACK)

    n = command_count()
    half = (n + 1) // 2          # ceil division: col 0 gets the extra if odd
    col_w = W // 2                # 120 px per column = 15 chars
    cpl_col = col_w // font_sm.WIDTH
    for i in range(n):
        col = 0 if i < half else 1
        row = i if i < half else i - half
        prefix = "> " if i == highlighted else "  "
        line = prefix + command_label(i)
        fg = YELLOW if i == highlighted else WHITE
        x = col * col_w
        y = BODY_Y + row * font_sm.HEIGHT
        tft.text(font_sm, (line + " " * cpl_col)[:cpl_col], x, y, fg, BLACK)
    hint = "B:next 2B:prev A:send Bh:back"
    cpl_sm = _chars_for(font_sm, TEXT_COL_W)
    tft.text(font_sm, (hint + " " * cpl_sm)[:cpl_sm], 0, STATUS_Y, WHITE, BLACK)


def draw_settings(items, highlighted, edit_mode=False):
    """
    Render the settings menu.

    Layout (landscape 240×135):
      [y=0..32]    "settings" title (large font)
      [y=32..]     item rows (small font, '>' prefix for highlighted)
      [y=119..135] hint row: "BtnB cycle  BtnA edit  hold A: exit"

    items: list of (key, value_str) tuples, e.g. [("brightness", "high"), ...]
    highlighted: index of the currently selected row
    edit_mode: if True, the highlighted row shows with YELLOW fg to indicate editing
    """
    tft.fill(BLACK)

    # Title row
    cpl_lg = _chars_for(font_lg, TEXT_COL_W)
    title_padded = ("settings" + " " * cpl_lg)[:cpl_lg]
    tft.text(font_lg, title_padded, 0, 0, CYAN, BLACK)

    # Item rows (small font, starting at y=BODY_Y=32)
    cpl_sm = _chars_for(font_sm, TEXT_COL_W)
    for i, (key, val) in enumerate(items):
        prefix = "> " if i == highlighted else "  "
        line = prefix + key + ": " + str(val)
        padded = (line + " " * cpl_sm)[:cpl_sm]
        if i == highlighted:
            fg = YELLOW if edit_mode else WHITE
        else:
            fg = WHITE
        tft.text(font_sm, padded, 0, BODY_Y + i * font_sm.HEIGHT, fg, BLACK)

    # Hint row at STATUS_Y
    hint = "B:next A:edit Bh:save"
    hint_padded = (hint + " " * cpl_sm)[:cpl_sm]
    tft.text(font_sm, hint_padded, 0, STATUS_Y, WHITE, BLACK)


# ---------------------------------------------------------------------------
# Pi RPC network helpers
# ---------------------------------------------------------------------------

def rpc_init():
    """Create and connect the global Pi RPC client."""
    client = PiRpcClient(PI_RPC_HOST, PI_RPC_PORT, timeout_ms=4000)
    ok = client.connect()
    if ok:
        # Prime the pipe with a state request
        client.send({"type": "get_state"})
    return client


def rpc_poll_state(client, mapper):
    """
    Send get_state if due, read all available messages, and return the
    latest synthesised state dict (or None if disconnected).
    """
    if client is None or not client.connected():
        return None

    # Read any inbound messages
    msgs = client.poll()
    if msgs:
        mapper.handle_messages(msgs)
        client.reset_backoff()

    return mapper.state()


def rpc_send_get_state(client):
    """Request a fresh state snapshot from Pi RPC."""
    if client is None:
        return False
    return client.send({"type": "get_state"})


def rpc_answer_prompt(client, mapper, prompt_id, value):
    """Answer a pending prompt via extension_ui_response."""
    if client is None:
        return False
    cmd = mapper.prompt_answer_payload(prompt_id, value)
    if cmd is None:
        return False
    ok = client.send(cmd)
    if ok:
        mapper.clear_prompt()
    return ok


def rpc_send_command(client, session_id, command_idx):
    """Send a canned command via Pi RPC."""
    if client is None:
        return False
    cmd = rpc_command_payload(session_id, command_idx)
    if cmd is None:
        return False
    return client.send(cmd)


def rpc_ping(client):
    """Ping via get_state. Returns True if we can send."""
    return rpc_send_get_state(client)


# ---------------------------------------------------------------------------
# Legacy HTTP helpers (retained for audio/TTS only)
# ---------------------------------------------------------------------------

def post_audio(wav_bytes, session_id, submit=False):
    """POST raw WAV to /oi/audio. Returns (transcript, cleaned) tuple or (None, None).

    submit=False: transcribe only, do not create a prompt command.
    submit=True: transcribe and auto-create prompt (legacy behavior).
    """
    try:
        url = SERVER_URL + "/oi/audio?session_id=" + session_id
        if not submit:
            url += "&submit=0"
        headers = {"Content-Type": "audio/wav",
                   "Content-Length": str(len(wav_bytes))}
        r = urequests.post(url, headers=headers, data=wav_bytes, timeout=30)
        if r.status_code == 200:
            result = r.json()
            r.close()
            transcript = result.get("transcript") or ""
            cleaned = result.get("cleaned") or ""
            return (transcript, cleaned)
        r.close()
        return (None, None)
    except Exception as e:
        print("[main] post_audio error:", e)
        return (None, None)


def _speech_clean(text, max_chars=300):
    """Prepare assistant response text for TTS.

    Strips code blocks, markdown formatting, URLs, and list markers.
    Truncates to max_chars at a sentence boundary.
    """
    # Remove fenced code blocks
    text = re.sub(r'```[\s\S]*?```', ' code omitted', text)
    # Remove inline code
    text = re.sub(r'`[^`]+`', ' code omitted', text)
    # Strip markdown links: [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Collapse markdown headers
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    # Collapse markdown bold/italic
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # Simplify bare URLs
    text = re.sub(r'https?://\S+', ' link', text)
    # Strip unordered list markers
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    # Strip ordered list markers
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Collapse multiple newlines
    text = re.sub(r'\n{2,}', '. ', text)
    # Collapse single newlines
    text = re.sub(r'\n', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) <= max_chars:
        return text

    # Truncate at last sentence boundary within limit
    truncated = text[:max_chars]
    last_sent = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_sent > max_chars // 2:
        text = text[:last_sent + 1]
    else:
        text = truncated.rstrip() + '...'
    return text


def _speak_text(text, title):
    """Shared speak pipeline for test and real responses."""
    # Check mute from both audio driver and settings
    if audio is not None and audio.is_muted():
        draw_flash("muted")
        time.sleep_ms(600)
        return
    if _settings.get("volume", 100) == 0:
        draw_flash("muted")
        time.sleep_ms(600)
        return

    if not text:
        draw_flash("nothing to say")
        time.sleep_ms(600)
        return

    draw_flash(title + "...")

    # Ensure speaker codec is ready (guarded reset after mic mode)
    if audio is not None:
        audio.reset()

    try:
        if SPEAK_DEBUG:
            print("[main] speak: POST /oi/speak len=%d" % len(text))
        r = urequests.post(
            SERVER_URL + "/oi/speak",
            json={"text": text},
            headers=json_headers(),
            timeout=10,
        )
        status = r.status_code
        resp_body = r.text if hasattr(r, "text") else ""
        r.close()
        if status != 200:
            if SPEAK_DEBUG:
                draw_flash("POST: %d" % status)
                time.sleep_ms(700)
                if resp_body:
                    draw_flash(resp_body[:16])
                    time.sleep_ms(1200)
            else:
                draw_flash("speak failed")
                time.sleep_ms(1200)
            return
        if SPEAK_DEBUG:
            draw_flash("POST: %d" % status)
            time.sleep_ms(700)
    except Exception as e:
        print("[main] speak POST error:", e)
        draw_flash("POST err")
        time.sleep_ms(1200)
        return

    try:
        r = urequests.get(SERVER_URL + "/oi/speak", timeout=10)
        status = r.status_code
        if status == 200:
            content_length = int(r.headers.get("Content-Length", "0"))
            wav = r.content
            r.close()
            if SPEAK_DEBUG:
                draw_flash("wav: %d" % len(wav))
                time.sleep_ms(700)
            if content_length > 1_500_000:
                draw_flash("too big")
                time.sleep_ms(1200)
                return
            if audio is not None:
                result = audio.play_wav(wav)
                if SPEAK_DEBUG:
                    draw_flash("play: %s" % result)
                    time.sleep_ms(700)
            else:
                draw_flash("no audio")
                time.sleep_ms(1200)
        else:
            r.close()
            draw_flash("GET: %d" % status)
            time.sleep_ms(1200)
    except Exception as e:
        print("[main] speak GET error:", e)
        draw_flash("GET err")
        time.sleep_ms(1200)


def _test_speak():
    """Test TTS pipeline: POST fixed text to /oi/speak, GET WAV, play."""
    _speak_text("Hello, this is the O.I. server speaking test.", "test speak")


def _speak_last_response(state):
    """Send last assistant text to TTS server, then play the audio."""
    if SPEAK_DEBUG:
        draw_flash("speak prep...")
    text = (state or {}).get("last_assistant_text", "")
    if not text:
        draw_flash("nothing to say")
        time.sleep_ms(600)
        return

    # Keep the real path simple for debugging: just trim length instead of
    # doing regex-based cleanup (which can be slow on-device).
    text = text.strip()
    if len(text) > 300:
        text = text[:300]

    _speak_text(text, "speaking")


def _fetch_and_play_speak():
    """Fetch the TTS WAV from server and play it."""
    try:
        r = urequests.get(SERVER_URL + "/oi/speak", timeout=10)
        if r.status_code == 200:
            content_length = int(r.headers.get("Content-Length", "0"))
            MAX_PLAY_WAV = 1_500_000
            if content_length > MAX_PLAY_WAV:
                r.close()
                draw_flash("too long to say")
                time.sleep_ms(600)
                return
            wav = r.content
            r.close()
            if audio is not None:
                result = audio.play_wav(wav)
                print("[main] speak:", result)
            else:
                print("[main] speak: no-audio")
        else:
            r.close()
    except Exception as e:
        print("[main] speak fetch error:", e)


# ---------------------------------------------------------------------------
# Settings/session menu helpers
# ---------------------------------------------------------------------------

def _settings_items():
    """Return list of (key, display_value) for the settings menu."""
    vol = _settings.get("volume", 100)
    vol_label = "mute" if vol == 0 else "%d%%" % vol
    return [
        ("brightness", _settings["brightness"]),
        ("volume",     vol_label),
        ("wake chirp", "on" if _settings["wake_chirp"] else "off"),
    ]


def _settings_cycle(idx):
    """Cycle the value for settings item at index idx. Modifies _settings in-place."""
    if idx == 0:  # brightness
        keys = BRIGHTNESS_PRESET_KEYS
        cur = _settings["brightness"]
        i = keys.index(cur) if cur in keys else 0
        _settings["brightness"] = keys[(i + 1) % len(keys)]
        _apply_brightness(BRIGHTNESS_PRESETS[_settings["brightness"]])
    elif idx == 1:  # volume
        levels = [0, 20, 40, 60, 80, 100]
        cur = _settings.get("volume", 100)
        i = levels.index(cur) if cur in levels else len(levels) - 1
        _settings["volume"] = levels[(i + 1) % len(levels)]
        _settings["mute"] = (_settings["volume"] == 0)
        if audio is not None:
            if hasattr(audio, "set_volume"):
                audio.set_volume(_settings["volume"])
            else:
                audio.set_muted(_settings["mute"])
    elif idx == 2:  # wake chirp
        _settings["wake_chirp"] = not _settings["wake_chirp"]


def _enter_mic_mode():
    """Switch codec from speaker to mic. Call before recording."""
    if mic is not None:
        mic.deinit()   # release any prior I2S RX
    if audio is not None:
        audio.reset()  # release I2S TX, invalidate DAC config


def _leave_mic_mode():
    """Switch codec back to speaker. Call after recording."""
    if mic is not None:
        mic.deinit()    # release I2S RX peripheral
    if audio is not None:
        audio.reset()   # force full DAC re-init on next playback
    gc.collect()        # reclaim mono_buf memory


def run_voice_prompt(session):
    """Record push-to-talk audio, upload, route transcript to session as prompt."""
    sid = session.get("session_id")
    if not sid:
        draw_flash("no session id")
        time.sleep_ms(700)
        return
    if mic is None:
        draw_flash("mic unavailable")
        time.sleep_ms(700)
        return

    draw_flash("speak now...")
    _enter_mic_mode()

    wav = None
    try:
        wav = mic.record_wav_while_held(btnA, max_ms=15000)
    except Exception as e:
        draw_flash("rec ERR")
        print("[main] voice rec error:", e)
        time.sleep_ms(700)
        return
    finally:
        _leave_mic_mode()

    if wav is None:
        draw_flash("cancelled")
        time.sleep_ms(500)
        return

    draw_flash("uploading...")
    transcript, cleaned = post_audio(wav, sid, submit=False)
    # Release WAV memory before further processing
    wav = None
    gc.collect()

    if transcript is None:
        draw_flash("upload failed")
        time.sleep_ms(700)
    elif transcript == "":
        draw_flash("no speech heard")
        time.sleep_ms(700)
    else:
        # Use cleaned transcript (strips leading fillers, adds punctuation)
        message = cleaned or transcript
        draw_transcript_preview(message)
        print("[main] voice ok len=%d" % len(message))
        # Send as Pi RPC prompt command (not via oi-server command queue)
        if rpc_client is not None:
            prompt = {"type": "prompt", "message": message}
            ok = rpc_client.send(prompt)
            if ok:
                draw_flash("sent")
            else:
                draw_flash("send failed")
        else:
            draw_flash("no connection")
        time.sleep_ms(1200)


def run_command_menu(session, btn_a_pat, btn_b_pat):
    """Blocking command menu for a selected session."""
    sid = session.get("session_id")
    if not sid:
        draw_flash("no session id")
        time.sleep_ms(600)
        return
    highlighted = 0
    draw_command_menu(session, highlighted)
    while True:
        a_pat = btn_a_pat.poll()
        b_pat = btn_b_pat.poll()
        if b_pat == "single":
            highlighted = wrap_index(highlighted + 1, command_count())
            draw_command_menu(session, highlighted)
        elif b_pat == "double":
            highlighted = wrap_index(highlighted - 1, command_count())
            draw_command_menu(session, highlighted)
        elif b_pat == "long":
            break
        elif a_pat == "single":
            label = command_label(highlighted)
            if command_is_local(highlighted):
                if label == "voice":
                    run_voice_prompt(session)
                elif label == "speak":
                    _speak_last_response(state or {})
                elif label == "test: speak":
                    _test_speak()
                draw_flash("sent: " + label)
                time.sleep_ms(700)
                break
            else:
                ok = rpc_send_command(rpc_client, sid, highlighted)
                draw_flash(("sent: " if ok else "failed: ") + label)
                time.sleep_ms(700)
                break
        time.sleep_ms(LOOP_SLEEP_MS)


def _run_session_picker(state, btn_a_pat, btn_b_pat):
    """
    Blocking session picker. Returns the selected session dict, or None if
    the user exits without selecting (BtnB long).
    """
    active_id, sessions = sessions_summary(state)
    if not sessions:
        draw_flash("no sessions")
        time.sleep_ms(700)
        return None

    highlighted = selected_index_for_active(sessions, active_id)
    draw_sessions_menu(sessions, active_id, highlighted)

    while True:
        a_pat = btn_a_pat.poll()
        b_pat = btn_b_pat.poll()

        if b_pat == "single":
            highlighted = wrap_index(highlighted + 1, len(sessions))
            draw_sessions_menu(sessions, active_id, highlighted)
        elif b_pat == "double":
            highlighted = wrap_index(highlighted - 1, len(sessions))
            draw_sessions_menu(sessions, active_id, highlighted)
        elif b_pat == "long":
            return None  # exit without selecting
        elif a_pat == "single":
            session = sessions[highlighted]
            # In single-session Pi RPC mode, just focus locally
            return session
        time.sleep_ms(LOOP_SLEEP_MS)


def run_settings_menu(btn_a_pat, btn_b_pat):
    """
    Blocking settings menu. Returns when user long-presses BtnB.
    btn_a_pat and btn_b_pat are ButtonPattern objects.
    """
    highlighted = 0
    items = _settings_items()
    draw_settings(items, highlighted)

    while True:
        a_pat = btn_a_pat.poll()
        b_pat = btn_b_pat.poll()

        a_action = action_for(MODE_SETTINGS, BTN_A, a_pat)
        b_action = action_for(MODE_SETTINGS, BTN_B, b_pat)

        if b_action == ACTION_NEXT:
            # Cycle highlight
            highlighted = (highlighted + 1) % len(items)
            items = _settings_items()
            draw_settings(items, highlighted)

        elif a_action == ACTION_EDIT:
            # Edit/cycle the highlighted item
            _settings_cycle(highlighted)
            items = _settings_items()
            draw_settings(items, highlighted, edit_mode=True)
            time.sleep_ms(200)
            draw_settings(items, highlighted)

        elif b_action == ACTION_SAVE_EXIT:
            # Exit settings — save and return
            save_settings()
            break

        time.sleep_ms(LOOP_SLEEP_MS)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    global rpc_client, _last_chirp_seq, _last_speak_seq

    # Load settings from flash (silently falls back to defaults on error)
    load_settings()
    # Apply loaded brightness
    _apply_brightness(BRIGHTNESS_PRESETS.get(_settings["brightness"], 75))
    # Apply loaded mute
    if audio is not None:
        if hasattr(audio, "set_volume"):
            audio.set_volume(_settings.get("volume", 100))
        else:
            audio.set_muted(_settings["mute"])

    # Wake chirp (off by default, opt-in via settings)
    if _settings.get("wake_chirp") and audio is not None:
        result = audio.chirp("good")
        print("[main] chirp wake:", result)

    def new_button_pattern(pin):
        return ButtonPattern(pin,
                             debounce_ms=DEBOUNCE_MS,
                             long_ms=BTN_LONG_MS,
                             double_ms=BTN_DOUBLE_MS)

    btn_a_pat = new_button_pattern(btnA)
    btn_b_pat = new_button_pattern(btnB)

    # Keep a simple debounced press detector for wake-on-press while asleep.
    btn_a_wake = Button(btnA, debounce_ms=DEBOUNCE_MS)
    btn_b_wake = Button(btnB, debounce_ms=DEBOUNCE_MS)

    # Pi RPC client and state mapper
    rpc_client = rpc_init()
    rpc_mapper = PiRpcStateMapper()

    current_id   = ...   # sentinel: "never seen anything yet"
    highlighted  = 0
    current_opts = []
    offline      = False
    pending_post = False
    state        = None
    active_session = None

    current_snapshot_ts = None
    current_model       = None
    current_thinking    = None
    display_asleep      = False
    last_interaction_ms = time.ticks_ms()
    last_poll_ms        = time.ticks_add(time.ticks_ms(), -POLL_INTERVAL_MS)

    draw_idle()

    while True:
        now = time.ticks_ms()

        # ---- Pi RPC poll (every POLL_INTERVAL_MS / SLEEP_POLL_INTERVAL_MS) -
        active_poll_interval = SLEEP_POLL_INTERVAL_MS if display_asleep else POLL_INTERVAL_MS
        if time.ticks_diff(now, last_poll_ms) >= active_poll_interval:
            last_poll_ms = now
            if rpc_client is None or not rpc_client.connected():
                rpc_client = rpc_init()
            if rpc_client and rpc_client.connected():
                rpc_send_get_state(rpc_client)

        # Always read available messages (non-blocking)
        fetched = rpc_poll_state(rpc_client, rpc_mapper)

        if fetched is None:
            if not offline:
                offline = True
                if not display_asleep:
                    draw_offline_indicator()
        else:
            state = fetched

            # Track active session
            new_active = _active_session_from_state(state)
            new_active_id = (new_active or {}).get("session_id")
            old_active_id = (active_session or {}).get("session_id")
            if new_active_id != old_active_id:
                active_session = new_active

            # Track snapshot updates (e.g. assistant reply text).
            snapshot = state.get("snapshot") or {}
            new_snapshot_ts = snapshot.get("ts")
            snapshot_changed = new_snapshot_ts is not None and new_snapshot_ts != current_snapshot_ts
            if snapshot_changed:
                current_snapshot_ts = new_snapshot_ts

            # Track model/thinking-level changes for redraw.
            new_model = state.get("last_model_change")
            new_thinking = state.get("last_thinking_change")
            setting_changed = (new_model != current_model or new_thinking != current_thinking)
            if setting_changed:
                current_model = new_model
                current_thinking = new_thinking

            if offline:
                offline = False
                if not display_asleep:
                    if state.get("id") is None:
                        if active_session:
                            draw_session_idle(active_session, state)
                        elif snapshot:
                            draw_dashboard(snapshot)
                        else:
                            draw_idle()
                    else:
                        draw_question(state, highlighted)

            new_id = state.get("id")
            if new_id != current_id:
                # State changed — full redraw.
                current_id   = new_id
                highlighted  = 0
                pending_post = False
                current_opts = state.get("options") or []
                if current_id is not None:
                    last_interaction_ms = now
                    if display_asleep:
                        display_wake()
                        display_asleep = False
                    draw_question(state, highlighted)
                else:
                    if not display_asleep:
                        if active_session:
                            draw_session_idle(active_session, state)
                        elif snapshot:
                            draw_dashboard(snapshot)
                        else:
                            draw_idle()
            elif current_id is None and not display_asleep:
                if new_active_id != old_active_id or snapshot_changed or setting_changed:
                    if active_session:
                        draw_session_idle(active_session, state)
                    elif snapshot:
                        draw_dashboard(snapshot)
                    else:
                        draw_idle()

        # ---- Idle-sleep transition -----------------------------------------
        if not display_asleep and current_id is None and (
                btn_a_wake.raw_low() or btn_b_wake.raw_low()):
            last_interaction_ms = now

        if (not display_asleep and current_id is None and
                time.ticks_diff(now, last_interaction_ms) >= IDLE_SLEEP_MS):
            display_sleep()
            display_asleep = True

        # ---- Button handling -----------------------------------------------
        if display_asleep:
            a_wake = btn_a_wake.pressed()
            b_wake = btn_b_wake.pressed()
            if a_wake or b_wake:
                display_wake()
                display_asleep = False
                last_interaction_ms = now
                if current_id is None:
                    if active_session:
                        draw_session_idle(active_session, state)
                    elif state and state.get("snapshot"):
                        draw_dashboard(state.get("snapshot") or {})
                    else:
                        draw_idle()
                else:
                    draw_question(state, highlighted)
                btn_a_pat = new_button_pattern(btnA)
                btn_b_pat = new_button_pattern(btnB)
            time.sleep_ms(LOOP_SLEEP_MS)
            continue

        a_pat = btn_a_pat.poll()
        b_pat = btn_b_pat.poll()

        if a_pat or b_pat:
            last_interaction_ms = now

        # ---- Question mode -------------------------------------------------
        if current_id is not None and current_opts:
            q_a = action_for(MODE_QUESTION, BTN_A, a_pat)
            q_b = action_for(MODE_QUESTION, BTN_B, b_pat)

            if q_b == ACTION_NEXT:
                highlighted = (highlighted + 1) % len(current_opts)
                _draw_options_bottom(current_opts, highlighted)

            elif q_b == ACTION_OPEN_SETTINGS:
                run_settings_menu(btn_a_pat, btn_b_pat)
                if state and state.get("id") == current_id:
                    draw_question(state, highlighted)
                last_interaction_ms = time.ticks_ms()
                btn_a_pat = new_button_pattern(btnA)
                btn_b_pat = new_button_pattern(btnB)

            if q_a == ACTION_ANSWER:
                opt = current_opts[highlighted]
                value = opt.get("value", "")
                label = opt.get("label", "")
                ok = rpc_answer_prompt(rpc_client, rpc_mapper, current_id, value)
                if ok:
                    pending_post = False
                    draw_flash("sent: " + label)
                    time.sleep_ms(SENT_FLASH_MS)
                    current_id = None
                    if active_session:
                        draw_session_idle(active_session, state)
                    elif state and state.get("snapshot"):
                        draw_dashboard(state.get("snapshot") or {})
                    else:
                        draw_idle()
                else:
                    pending_post = True
                    draw_flash("send failed - retry?")
                    time.sleep_ms(800)

        # ---- Session idle mode ---------------------------------------------
        elif active_session:
            # Long-A hold detection for voice input.
            # GestureDetector emits long on release, but push-to-talk needs
            # recording to start while button is still held, so we detect the
            # threshold directly in the main loop.
            global _voice_hold_start_ms
            if btnA.value() == 0:  # pressed (active-low)
                if _voice_hold_start_ms is None:
                    _voice_hold_start_ms = time.ticks_ms()
                elif time.ticks_diff(time.ticks_ms(), _voice_hold_start_ms) > 800:
                    # Long hold detected — start voice input
                    _voice_hold_start_ms = None
                    run_voice_prompt(active_session)
                    draw_session_idle(active_session, state)
                    last_interaction_ms = time.ticks_ms()
                    btn_a_pat = new_button_pattern(btnA)
                    btn_b_pat = new_button_pattern(btnB)
                    time.sleep_ms(LOOP_SLEEP_MS)
                    continue
            else:
                _voice_hold_start_ms = None  # not pressed, reset

            s_a = action_for(MODE_SESSION, BTN_A, a_pat)
            s_b = action_for(MODE_SESSION, BTN_B, b_pat)

            if s_a == ACTION_OPEN_MENU:
                run_command_menu(active_session, btn_a_pat, btn_b_pat)
                draw_session_idle(active_session, state)
                last_interaction_ms = time.ticks_ms()
                btn_a_pat = new_button_pattern(btnA)
                btn_b_pat = new_button_pattern(btnB)
                time.sleep_ms(LOOP_SLEEP_MS)
                continue

            elif s_a == ACTION_SPEAK:
                # Speak last response via TTS
                _speak_last_response(state or {})
                draw_session_idle(active_session, state)

            if s_b == ACTION_NEXT_SESSION:
                nxt = _next_session(state, active_session)
                if nxt and nxt.get("session_id") != active_session.get("session_id"):
                    active_session = nxt
                draw_session_idle(active_session, state)
                last_interaction_ms = time.ticks_ms()

            elif s_b == ACTION_OPEN_SETTINGS:
                run_settings_menu(btn_a_pat, btn_b_pat)
                draw_session_idle(active_session, state)
                last_interaction_ms = time.ticks_ms()
                btn_a_pat = new_button_pattern(btnA)
                btn_b_pat = new_button_pattern(btnB)
                time.sleep_ms(LOOP_SLEEP_MS)
                continue

        # ---- No session — idle ---------------------------------------------
        else:
            i_a = action_for(MODE_IDLE, BTN_A, a_pat)
            i_b_settings = action_for(MODE_IDLE, BTN_B, b_pat) == ACTION_OPEN_SETTINGS

            if i_a == ACTION_PING:
                ok = rpc_ping(rpc_client)
                draw_flash("pinged ok" if ok else "ping failed")
                time.sleep_ms(600)
                draw_idle()

            elif b_pat == "single":
                sel = _run_session_picker(state, btn_a_pat, btn_b_pat)
                if sel:
                    active_session = sel
                    draw_session_idle(active_session, state)
                elif state and state.get("snapshot"):
                    draw_dashboard(state.get("snapshot") or {})
                else:
                    draw_idle()
                last_interaction_ms = time.ticks_ms()
                btn_a_pat = new_button_pattern(btnA)
                btn_b_pat = new_button_pattern(btnB)
                time.sleep_ms(LOOP_SLEEP_MS)
                continue

            elif i_b_settings:
                run_settings_menu(btn_a_pat, btn_b_pat)
                if state and state.get("snapshot") and not active_session:
                    draw_dashboard(state.get("snapshot") or {})
                else:
                    draw_idle()
                last_interaction_ms = time.ticks_ms()
                btn_a_pat = new_button_pattern(btnA)
                btn_b_pat = new_button_pattern(btnB)
                time.sleep_ms(LOOP_SLEEP_MS)
                continue

        time.sleep_ms(LOOP_SLEEP_MS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

main()
