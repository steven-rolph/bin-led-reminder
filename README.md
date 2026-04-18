# Bin LED Reminder

A "set and forget" bin collection reminder running on a Raspberry Pi Zero 2 W.
Scrapes the East Cambridgeshire District Council collection schedule and drives a
Pimoroni Blinkt! LED strip to show a colour-coded reminder the evening before
collection day.

An optional FastAPI web UI provides a dashboard for monitoring status, viewing
the schedule, and controlling the LED service — started on demand, not always
running.

---

## Hardware

| Component | Detail |
|---|---|
| Board | Raspberry Pi Zero 2 W (`europa`) |
| LEDs | Pimoroni Blinkt! — 8 × APA102 RGB LEDs on GPIO header |
| Connectivity | WLAN only, headless, managed via SSH |

---

## Repository layout

```
bin-led-reminder/          ← repo root
├── .gitignore
├── README.md
├── CLAUDE.md              ← context for AI-assisted development
│
├── bin-led-reminder/      ← core LED service (always running)
│   ├── bin_led_service.py
│   ├── constants.py       ← LED colour definitions (single source of truth)
│   ├── config.example.json
│   ├── requirements.txt
│   ├── install.sh
│   ├── manage.sh
│   └── tests/
│       ├── test_leds.py   ← Pi hardware test (requires blinkt)
│       └── test_colours.py ← unit tests (runs on any machine)
│
└── bin-led-webui/         ← optional dashboard (start on demand)
    ├── main.py
    ├── requirements.txt
    ├── install_web.sh
    └── static/
        ├── index.html
        └── consts.js
```

---

## LED colours

| Colour | Meaning |
|---|---|
| 🟢 Green | Green or Brown Bin due tomorrow |
| 🔵 Blue | Blue Bin (recycling) due tomorrow |
| 🔴 Red | Error state — scrape failed or service fault |
| Off | No collection imminent |

Black Bag collections happen every week and are intentionally ignored — the
reminder is only for the bins that alternate.

The reminder window is configurable (`reminder_start_hours_before` /
`reminder_end_hours_after`). At the defaults it runs from **the day before
collection at 00:00 → collection day at 01:00**. The window is derived directly
from the scraped collection date, so bank holiday shifts are handled automatically
with no hardcoded day names.

---

## Installation

### Prerequisites

- Raspberry Pi OS (Bookworm or later), headless
- Python 3.11+
- Shared virtualenv at `~/blinkt-projects/blinkt-env/`

```bash
cd ~/blinkt-projects
python3 -m venv blinkt-env
```

### Core LED service

```bash
cd ~/blinkt-projects/bin-led-reminder
cp config.example.json config.json
# Edit config.json and set your UPRN
nano config.json

pip install --extra-index-url https://www.piwheels.org/simple -r requirements.txt
chmod +x install.sh manage.sh
./install.sh
```

The service is enabled on boot automatically. Start it immediately with:

```bash
./manage.sh start
```

### Web UI (optional)

```bash
cd ~/blinkt-projects/bin-led-webui
pip install --extra-index-url https://www.piwheels.org/simple -r requirements.txt
chmod +x install_web.sh
./install_web.sh
```

The web UI is **not** started automatically. Start it when you need it:

```bash
# From bin-led-reminder/ — manage.sh handles both services
./manage.sh webui start
```

Access at `http://<pi-ip>:8000`.

---

## Service management

All common operations are wrapped by `manage.sh` in `bin-led-reminder/`:

```bash
./manage.sh start            # Start LED service
./manage.sh stop             # Stop LED service
./manage.sh restart          # Restart LED service
./manage.sh status           # Status + recent logs
./manage.sh logs             # Live log tail
./manage.sh clear-errors     # Clear error state and restart
./manage.sh webui start      # Start web UI
./manage.sh webui stop       # Stop web UI
./manage.sh webui status     # Web UI status
./manage.sh webui logs       # Live web UI log tail
```

---

## Configuration

Copy `config.example.json` to `config.json` and set your values.
`config.json` is gitignored — it contains your home address UPRN.

| Key | Default | Description |
|---|---|---|
| `uprn` | — | Your property's UPRN (from the council URL) |
| `base_url` | East Cambs URL | Collection schedule page |
| `update_interval_weeks` | `2` | How often to re-scrape the schedule |
| `check_interval_hours` | `1` | How often the service checks whether to update LEDs |
| `led_brightness` | `0.1` | Blinkt! brightness, 0.0–1.0 (0.1 is plenty indoors) |
| `log_level` | `"INFO"` | Python logging level |
| `reminder_start_hours_before` | `24` | Hours before midnight of collection day that LEDs turn on |
| `reminder_end_hours_after` | `1` | Hours after midnight of collection day that LEDs turn off |

All keys except `uprn` and `base_url` can be edited via the web UI. Config
fields are disabled while the LED service is running — stop it first, make
changes, then restart.

---

## Web UI API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | LED service state, error state, next collection, LEDs active |
| `GET` | `/api/schedule` | Upcoming collection schedule |
| `GET` | `/api/config` | Current config (UPRN and base\_url omitted) |
| `PATCH` | `/api/config` | Update editable config keys |
| `GET` | `/api/logs?lines=50` | Last N lines of the LED service log (max 200) |
| `POST` | `/api/service/{action}` | `start` / `stop` / `restart` / `clear-errors` / `force-update` |

---

## Design principles

- **Core service stability above all else.** The LED service runs as a `systemd`
  unit and must never be destabilised by changes to the web layer.
- **Structural solutions over runtime workarounds.** For example, test-flash
  controls in the web UI are disabled while the LED service is running,
  eliminating SPI bus contention at the architecture level rather than
  requiring locks.
- **Resource discipline.** Plain `uvicorn` (no extras), on-demand web UI
  startup, and `piwheels` pre-built ARM wheels — all driven by the Pi Zero 2's
  512 MB RAM constraint.
- **Web UI is non-authoritative.** It reads JSON files written by the LED
  service (`recycling_schedule.json`, `config.json`, `error_state.json`) and
  the service log. The LED service is the source of truth.

---

## Data source

East Cambridgeshire District Council bin collection schedule, scraped directly
from their self-service portal. Schedule data is cached in
`recycling_schedule.json` (gitignored) and refreshed every two weeks.
