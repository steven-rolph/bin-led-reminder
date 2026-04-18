# Single source of truth for LED colour definitions.
# All values are (R, G, B) tuples in 0-255 range.

# ── General palette ────────────────────────────────────────────────────────────
COLOUR_RED    = (255,   0,   0)
COLOUR_GREEN  = (  0, 255,   0)
COLOUR_BLUE   = (  0,   0, 255)
COLOUR_WHITE  = (255, 255, 255)
COLOUR_ORANGE = (255, 165,   0)
COLOUR_PURPLE = (128,   0, 128)
COLOUR_PINK   = (255,  20, 147)
COLOUR_CYAN   = (  0, 255, 255)
COLOUR_YELLOW = (255, 255,   0)

# ── Error / system state ───────────────────────────────────────────────────────
COLOUR_ERROR  = COLOUR_RED   # red LEDs = error state

# ── Bin type → LED colour mapping ─────────────────────────────────────────────
# Keys must match bin_type strings exactly as they appear in recycling_schedule.json.
# Add new bin types here when confirmed by the council.
BIN_COLOURS = {
    'Blue Bin':           COLOUR_BLUE,
    'Green or Brown Bin': COLOUR_GREEN,
}
