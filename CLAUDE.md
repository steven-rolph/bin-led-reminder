# CLAUDE.md — Bin LED Reminder

Context for AI-assisted development on this project. Keep this file up to date
when the structure, stack, or conventions change.

---

## Project purpose

A "set and forget" bin collection reminder for a Raspberry Pi Zero 2 W
(`europa`, user `pizero2`). Scrapes East Cambridgeshire District Council's bin
schedule and drives a Pimoroni Blinkt! (8 × APA102 RGB LEDs on the GPIO header)
to show a colour-coded reminder the evening before collection day.

---

## Repository layout

```
bin-led-reminder/          ← repo root
├── .gitignore
├── README.md
├── CLAUDE.md              ← this file
│
├── bin-led-reminder/      ← core LED service
│   ├── bin_led_service.py
│   ├── bin-led-reminder.service
│   ├── config.example.json
│   ├── config.json        ← gitignored (contains UPRN)
│   ├── requirements.txt
│   ├── install.sh
│   ├── manage.sh
│   └── tests/
│       └── test_leds.py
│
└── bin-led-webui/         ← optional dashboard
    ├── main.py
    ├── bin-led-webui.service
    ├── requirements.txt
    ├── install_web.sh
    └── static/
        ├── index.html
        ├── app.js
        ├── consts.js
        └── pico.min.css
```

### Gitignored runtime files (in `bin-led-reminder/`)

| File | Description |
|---|---|
| `config.json` | Live config — contains home address UPRN |
| `recycling_schedule.json` | Cached scrape output |
| `error_state.json` | Transient error flag written by the LED service |
| `logs/bin_led_service.log` | LED service log |

---

## Hardware

- **Board:** Raspberry Pi Zero 2 W — single-core 1 GHz, 512 MB RAM
- **LEDs:** Pimoroni Blinkt! — 8 × APA102 via SPI (GPIO header)
- **Connectivity:** WLAN only, headless, SSH only
- **Constraint:** No Docker, no Home Assistant, no Tailscale — keep it minimal

---

## Stack

### Core LED service (`bin-led-reminder/`)

| Layer | Detail |
|---|---|
| Language | Python 3.11+ |
| LED driver | `blinkt` (Pimoroni library, piwheels) |
| HTTP scraping | `requests` + `beautifulsoup4` |
| Process manager | systemd (`bin-led-reminder.service`) |
| Virtualenv | `~/blinkt-projects/blinkt-env/` (shared, one level above repo) |

### Web UI (`bin-led-webui/`)

| Layer | Detail |
|---|---|
| Backend | FastAPI, plain `uvicorn` (no extras — avoids OOM on Pi Zero 2) |
| Frontend | Preact/HTM (no build step), Pico CSS v2 |
| Colour constants | `static/consts.js` — single source of truth, exported as ES module and applied as CSS custom properties |
| Install | piwheels pre-built ARM wheels (`--extra-index-url https://www.piwheels.org/simple`) |
| Port | 8000 |
| Startup | On-demand only — **not** auto-started |

---

## Service architecture

```
systemd
  ├── bin-led-reminder.service   ← always running, source of truth
  └── bin-led-webui.service      ← started on demand via manage.sh
```

The web UI reads files written by the LED service. It never writes to
`recycling_schedule.json`. It can write to `config.json` (via `PATCH /api/config`)
and delete `error_state.json` (via `POST /api/service/clear-errors`).

The web UI controls `bin-led-reminder` via `sudo systemctl`. Managing the web UI
itself requires `./manage.sh webui {start|stop|restart}` directly on the device.

---

## LED colour logic

| Colour | Trigger |
|---|---|
| Green | Green or Brown Bin due |
| Blue | Blue Bin (recycling) due |
| Red | Error state (scrape failed, service fault) |
| Off | No collection imminent |

Black Bag collections are intentionally ignored — they happen every week and
don't need a reminder. See `recycling_schedule.json` for bin type strings.

**Reminder window:** (collection_day − 1) at 00:00 → collection_day at 01:00.
Normal week: Tuesday 00:00 → Wednesday 01:00.
Bank holiday week (council shifts by one day): Wednesday 00:00 → Thursday 01:00.
The service detects the shift automatically from the scraped date.

When both a Blue Bin and a Green/Brown Bin fall on the same week, `bins_due[0]`
determines the LED colour (Blue takes priority as it appears first in the
council's schedule output).

**Brightness:** Keep `led_brightness` low (0.05–0.15). The Pi Zero 2 powers the
LEDs directly from GPIO and full brightness across all 8 LEDs can cause
instability.

---

## Web UI API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | LED service state, error state, next collection, LEDs active |
| `GET` | `/api/schedule` | Upcoming collections (past entries filtered out, `days_until` recalculated at request time) |
| `GET` | `/api/config` | Editable config fields (`uprn` and `base_url` are read-only and omitted from `PATCH`) |
| `PATCH` | `/api/config` | Update: `led_brightness`, `check_interval_hours`, `update_interval_weeks`, `log_level` |
| `GET` | `/api/logs?lines=50` | Last N lines of LED service log (max 200) |
| `POST` | `/api/service/{action}` | `start` / `stop` / `restart` / `clear-errors` |
| `POST` | `/api/leds/test` | Flash LEDs a given colour; 409 if LED service is running, 503 in dev mode |

The `POST /api/leds/test` endpoint blocks for ~3 s. Test flash buttons in the
web UI are structurally disabled while the LED service is running to prevent SPI
bus contention.

---

## Data source

The council website is scraped by UPRN (Unique Property Reference Number). The
scraper targets `.collectionsrow` elements, skipping any row containing an
iframe (the address selector). If the council redesigns their page,
`scrape_collections()` in `bin_led_service.py` will need updating.

---

## Error handling

- Network/scrape failures set an error state (`error_state.json`) and turn LEDs red
- Error state persists across restarts until explicitly cleared
- To recover: `./manage.sh clear-errors` (deletes `error_state.json` and restarts)
- In error state the service retries every 5 minutes instead of the normal 1-hour interval

---

## Key conventions

### Deployment workflow

1. Edit files locally or in Claude Code
2. SFTP to `europa` — files transferred via SFTP lose the execute bit; run
   `chmod +x` on any shell scripts after transfer
3. SSH in and use `manage.sh` to restart services

### Development environment

- Always develop offline from the Pi on a separate machine
- Do not assume the dev machine environment matches the Pi — `blinkt` and GPIO
  are Pi-only
- Code is reviewed via VS Code on the dev machine

### Log message naming

Log messages must explicitly name the target service to avoid ambiguity:

```
# Correct
Web UI: LED service restart requested
Web UI: LED service restart succeeded

# Wrong — ambiguous which service
Web UI: service restart requested
```

### `blinkt` import guard

`blinkt` is only available on the Pi. In `main.py` it is imported inside a
`try/except ImportError` block so the web UI can run in dev mode on non-Pi
hardware. The `POST /api/leds/test` endpoint returns `503` in dev mode.

### Config path resolution

`main.py` resolves the LED service directory via the `LED_SERVICE_DIR`
environment variable, defaulting to `/home/pizero2/blinkt-projects/bin-led-reminder`.
Set this when running the web UI in dev mode to point at a local copy of the
data files.

### piwheels

Always install Python dependencies with:
```bash
pip install --extra-index-url https://www.piwheels.org/simple -r requirements.txt
```
This ensures pre-built ARM wheels are used, avoiding on-device compilation which
is slow and can OOM on the Pi Zero 2.

---

## Design principles

- **Core service stability above all else.** The LED service must remain
  unaffected by anything in the web layer. Never modify `bin_led_service.py`
  as a side-effect of a web UI change.
- **Structural solutions over runtime workarounds.** Disable test flash controls
  when the LED service is running rather than adding locks or coordination logic.
- **Resource discipline.** Plain `uvicorn`, on-demand web UI, piwheels — all
  driven by the Pi Zero 2's 512 MB RAM constraint.
- **Web UI is non-authoritative.** `recycling_schedule.json` and the service log
  are read-only from the web UI's perspective. The LED service is the source of
  truth.
- **Spec-first for new features.** Write a Markdown spec before handing off to
  Claude Code for implementation. Used for the web UI and the LED visualiser /
  test flash feature.

---

## Known issues / tech debt

- 🔴 **`load_data` doesn't catch `JSONDecodeError`** — if `recycling_schedule.json`
  is partially written during a power cut the file will be corrupt. The service
  enters error state and retries every 5 minutes but will never self-recover
  because it keeps failing to parse the same corrupt file. Fix: catch
  `json.JSONDecodeError` in `load_data` and return `None`, which triggers a
  fresh scrape.
- 🟡 **`load_config` doesn't catch `JSONDecodeError`** — if `config.json` is
  malformed the service crashes at startup before logging is set up, producing a
  raw traceback. Fix: catch `json.JSONDecodeError` alongside `FileNotFoundError`
  and fall back to defaults.
- 🟡 **Stale docstring in `detect_collection_schedule`** — still mentions
  `reminder_day` in the returns description, which was removed. Cosmetic but
  misleading.
- 🟡 **Stale comment in `update_led_display`** — says "Tuesday 00:00 until
  Wednesday 01:00" but this only describes the normal-week case; the bank
  holiday branch isn't reflected.
- 🟢 **Truncated User-Agent string in `fetch_data`** — the UA string ends at
  `AppleWebKit/537.36` mid-sentence. Not currently causing failures but is
  malformed.
- 🟢 **Invalid log level fails silently** — if `log_level` in `config.json` is
  an unrecognised string, `getattr` returns `None` and logging silently defaults
  to WARNING with no indication of the problem.
- 🟢 **`self.running = False` in `shutdown()` is dead code** — `sys.exit(0)` is
  called on the line before so the assignment is never reached. Harmless but
  misleading.
- 🟢 **No mixed-colour indication** — when both Blue and Green bins are due on
  the same collection date only `bins_due[0]` drives the LED colour. In practice
  the council alternates them weekly so this hasn't occurred, but it's not
  handled.

---

## Known gaps / planned work

- `POST /api/leds/test` actions are not yet written to the LED service log
- Web UI action logging for test flash commands not yet implemented in `main.py`
