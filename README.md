# Bin LED Reminder

A "set and forget" bin collection reminder running on a Raspberry Pi Zero 2 W.
Fetches the East Cambridgeshire District Council collection schedule (scraped
weekly by a separate GitHub Actions job) and drives a Pimoroni Blinkt! LED
strip to show a colour-coded reminder the evening before collection day.

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
├── auto-deploy.sh         ← git pull + restart-if-changed (run by the timer below)
├── auto-deploy.service    ← oneshot systemd unit that runs auto-deploy.sh
├── auto-deploy.timer      ← daily schedule for auto-deploy.service
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
├── bin-led-webui/         ← optional dashboard (start on demand)
│   ├── main.py
│   ├── requirements.txt
│   ├── install_web.sh
│   └── static/
│       ├── index.html
│       └── consts.js
│
└── bin-led-scraper/       ← weekly GitHub Actions scraper (headless browser)
    ├── scrape_bins.py
    ├── requirements.txt
    └── data/
        └── recycling_schedule.json   ← committed output, consumed by the Pi
```

---

## LED colours

| Colour | Meaning |
|---|---|
| 🟢 Green | Garden Waste Bin due tomorrow |
| 🟠 Orange | Rubbish Bin (general waste) due tomorrow |
| 🔵 Blue | Recycling Bin due tomorrow |
| 🔴 Red | Error state — fetch failed or service fault |
| Off | No collection imminent |

When Garden Waste and Rubbish are both due on the same date, the 8 LEDs
split into two colour blocks (4 green, 4 orange) rather than picking one.

Outdoor Food Caddy collections happen every week and are intentionally
ignored — the reminder is only for the bins that alternate.

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
# Edit config.json if you need to override any defaults
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

### Auto-deploy (optional)

`europa` keeps a real git clone of this repo (`origin` → this GitHub repo),
so updates can be pulled automatically instead of deploying by hand each
time. One-time setup:

```bash
cd ~/blinkt-projects/bin-led-reminder

# Grant passwordless sudo for exactly the two restart commands the timer
# needs — do NOT use NOPASSWD:ALL. Check your systemctl path first with
# `which systemctl` (usually /usr/bin/systemctl on Raspberry Pi OS).
sudo visudo -f /etc/sudoers.d/auto-deploy
# add this line, substituting the real path if different:
# pizero2 ALL=(root) NOPASSWD: /usr/bin/systemctl restart bin-led-reminder, /usr/bin/systemctl restart bin-led-webui

sudo cp auto-deploy.service auto-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
./bin-led-reminder/manage.sh auto-deploy enable
```

This installs a daily timer that runs `git pull --ff-only` and restarts
whichever services need it, only if something actually changed. See
`CLAUDE.md`'s "Deployment workflow" section for how it behaves and how to
fall back to a manual `git pull` if you want a change live immediately.

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
./manage.sh auto-deploy enable    # Turn on the daily auto-deploy timer
./manage.sh auto-deploy status    # Timer state + next scheduled run
./manage.sh auto-deploy logs      # Live auto-deploy log tail
./manage.sh auto-deploy run-now   # Trigger a deploy check immediately
./manage.sh auto-deploy disable   # Turn off the timer
```

---

## Configuration

Copy `config.example.json` to `config.json` and adjust if needed.
`config.json` is gitignored.

| Key | Default | Description |
|---|---|---|
| `base_url` | GitHub raw URL | Where the pre-scraped schedule JSON is fetched from (see "Data source" below) |
| `update_interval_weeks` | `1` | How often to re-fetch the schedule |
| `check_interval_hours` | `1` | How often the service checks whether to update LEDs |
| `led_brightness` | `0.1` | Blinkt! brightness, 0.0–1.0 (0.1 is plenty indoors) |
| `log_level` | `"INFO"` | Python logging level |
| `reminder_start_hours_before` | `24` | Hours before midnight of collection day that LEDs turn on |
| `reminder_end_hours_after` | `1` | Hours after midnight of collection day that LEDs turn off |

The council UPRN and postcode used to actually scrape the schedule no longer
live on the Pi at all — they're GitHub Actions repo secrets consumed by
`bin-led-scraper/scrape_bins.py` (see "Data source" below).

All keys except `base_url` can be edited via the web UI. Config fields are
disabled while the LED service is running — stop it first, make changes,
then restart.

---

## Web UI API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | LED service state, error state, next collections due, LEDs active, last scraped timestamp |
| `GET` | `/api/schedule` | Upcoming collection schedule |
| `GET` | `/api/config` | Current config (base\_url omitted) |
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

East Cambridgeshire District Council bin collection schedule. The council's
self-service portal (AchieveForms) is a fully client-rendered form gated by a
session + short-lived captcha token, so it can't be scraped with a plain
HTTP request. Instead, `bin-led-scraper/scrape_bins.py` drives a real headless
browser through the form on a weekly GitHub Actions schedule and commits the
result to `bin-led-scraper/data/recycling_schedule.json` (bin types and dates
only — no address/UPRN). The Pi fetches that file over plain HTTPS and caches
it locally as `recycling_schedule.json` (gitignored), refetching on the
`update_interval_weeks` schedule.
