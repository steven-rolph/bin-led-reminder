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

**Reminder window:** configurable via `reminder_start_hours_before` (default 24) and
`reminder_end_hours_after` (default 1). At defaults: (collection_date − 24 h) at 00:00 →
collection_date at 01:00. Derived directly from `date_parsed` — no hardcoded day names.
Works automatically for any collection day regardless of bank holiday shifts.

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
| `PATCH` | `/api/config` | Update: `led_brightness`, `check_interval_hours`, `update_interval_weeks`, `log_level`, `reminder_start_hours_before`, `reminder_end_hours_after` |
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

- 🟢 **No mixed-colour indication** — when both Blue and Green bins are due on
  the same collection date only `bins_due[0]` drives the LED colour. In practice
  the council alternates them weekly so this hasn't occurred, but it's not
  handled.
- 🟢 **`manage.sh` uses a relative path for venv activation** — `source
  ../blinkt-env/bin/activate` works when run from `bin-led-reminder/` but fails
  silently if invoked from a different directory. Low real-world risk given the
  standard SSH workflow.

---

## Known gaps / planned work

- No items currently tracked.
