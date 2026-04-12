// ─── Bin type colours ─────────────────────────────────────────────────────────
export const COLOUR_BIN_BLUE      = '#3b82f6';  // Blue Bin
export const COLOUR_BIN_GREEN     = '#22c55e';  // Green or Brown Bin
export const COLOUR_BIN_BLACK_BAG = '#6b7280';  // Black Bag (also used for muted UI text)

// ─── Service & LED state indicators ───────────────────────────────────────────
// Running dot → COLOUR_BIN_GREEN
// Stopped / error dot → COLOUR_ERROR
export const COLOUR_ERROR      = '#ef4444';  // error state, service stopped, flash red, log errors
export const COLOUR_LEDS_ACTIVE = '#facc15';  // yellow dot when LEDs are on
// LEDs-off dot → COLOUR_BIN_BLACK_BAG

// ─── LED visualiser ────────────────────────────────────────────────────────────
export const COLOUR_LED_OFF    = '#374151';  // dark square when LEDs are off
export const COLOUR_FLASH_WHITE = '#ffffff';  // white flash / unknown bin fallback

// ─── UI feedback messages ──────────────────────────────────────────────────────
export const COLOUR_SUCCESS = '#15803d';  // inline success text
export const COLOUR_FAILURE = '#dc2626';  // inline error messages (distinct from COLOUR_ERROR)

// ─── Muted / placeholder text ──────────────────────────────────────────────────
export const COLOUR_MUTED = '#9ca3af';  // fallback bin colour, log placeholder text

// ─── CSS element colours ───────────────────────────────────────────────────────
export const COLOUR_ERROR_BANNER_BG     = '#fee2e2';
export const COLOUR_ERROR_BANNER_FG     = '#991b1b';
export const COLOUR_ERROR_BANNER_BORDER = '#fca5a5';
export const COLOUR_DAYS_BADGE          = '#e5e7eb';  // days badge text
export const COLOUR_LOG_BG              = '#1a1a2e';  // log container background fallback

// ─── Lookup maps ───────────────────────────────────────────────────────────────
export const BIN_COLOURS = {
  'Blue Bin':         COLOUR_BIN_BLUE,
  'Green or Brown Bin': COLOUR_BIN_GREEN,
  'Black Bag':        COLOUR_BIN_BLACK_BAG,
};

export const TEST_COLOUR_HEX = {
  blue:  COLOUR_BIN_BLUE,
  green: COLOUR_BIN_GREEN,
  red:   COLOUR_ERROR,
  white: COLOUR_FLASH_WHITE,
};

// ─── Apply as CSS custom properties ────────────────────────────────────────────
// Allows index.html CSS to use var(--colour-*) with these as the source of truth.
const _root = document.documentElement;
_root.style.setProperty('--colour-error',                COLOUR_ERROR);
_root.style.setProperty('--colour-bin-black-bag',        COLOUR_BIN_BLACK_BAG);
_root.style.setProperty('--colour-led-off',              COLOUR_LED_OFF);
_root.style.setProperty('--colour-error-banner-bg',      COLOUR_ERROR_BANNER_BG);
_root.style.setProperty('--colour-error-banner-fg',      COLOUR_ERROR_BANNER_FG);
_root.style.setProperty('--colour-error-banner-border',  COLOUR_ERROR_BANNER_BORDER);
_root.style.setProperty('--colour-days-badge',           COLOUR_DAYS_BADGE);
_root.style.setProperty('--colour-log-bg',               COLOUR_LOG_BG);
