# CLAUDE.md — Bin LED Reminder

Context for AI-assisted development on this project. Keep this file up to date
when the structure, stack, or conventions change.

---

## Project purpose

A "set and forget" bin collection reminder for a Raspberry Pi Zero 2 W
(`europa`, user `pizero2`). Fetches East Cambridgeshire District Council's bin
schedule (pre-scraped weekly by `bin-led-scraper/` via GitHub Actions) and
drives a Pimoroni Blinkt! (8 × APA102 RGB LEDs on the GPIO header) to show a
colour-coded reminder the evening before collection day.

---

## Repository layout

```
bin-led-reminder/          ← repo root
├── .gitignore
├── README.md
├── CLAUDE.md              ← this file
├── auto-deploy.sh         ← git pull + restart-if-changed, run by the timer below
├── auto-deploy.service    ← oneshot systemd unit that runs auto-deploy.sh
├── auto-deploy.timer      ← daily schedule for auto-deploy.service
│
├── bin-led-reminder/      ← core LED service
│   ├── bin_led_service.py
│   ├── constants.py       ← LED colour definitions (single source of truth)
│   ├── bin-led-reminder.service
│   ├── config.example.json
│   ├── config.json        ← gitignored
│   ├── requirements.txt
│   ├── install.sh
│   ├── manage.sh
│   └── tests/
│       ├── test_leds.py   ← Pi hardware test (requires blinkt)
│       └── test_colours.py ← unit tests (runs on any machine, mocks blinkt)
│
├── bin-led-webui/         ← optional dashboard
│   ├── main.py
│   ├── bin-led-webui.service
│   ├── requirements.txt
│   ├── install_web.sh
│   └── static/
│       ├── index.html
│       ├── app.js
│       ├── consts.js
│       └── pico.min.css
│
├── bin-led-scraper/       ← weekly GitHub Actions scraper (headless browser)
│   ├── scrape_bins.py
│   ├── requirements.txt
│   └── data/
│       └── recycling_schedule.json   ← committed output, fetched by the Pi
│
└── .github/workflows/
    └── scrape-bins.yml    ← weekly cron + workflow_dispatch, runs the scraper
```

(`config.json` no longer contains a UPRN — see the config table update below.)

### Gitignored runtime files (in `bin-led-reminder/`)

| File | Description |
|---|---|
| `config.json` | Live config |
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
| HTTP fetch | `requests` (fetches pre-scraped JSON; no scraping on the Pi) |
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
GitHub Actions (weekly cron)
  └─ bin-led-scraper/scrape_bins.py → commits
       bin-led-scraper/data/recycling_schedule.json
                    │
                    ▼ Pi fetches via base_url (plain HTTPS GET)
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
| Green | Garden Waste Bin due |
| Orange | Rubbish Bin - 180L (general waste) due |
| Blue | Recycling Bin - 240L due |
| Red | Error state (fetch failed, service fault) |
| Off | No collection imminent |

Outdoor Food Caddy collections are intentionally ignored — they happen every
week and don't need a reminder. See `recycling_schedule.json` for bin type
strings.

**Same-date split display:** Garden Waste and Rubbish routinely share a
collection date (the council's "Green week"). When two bins are due on the
same date, `update_led_display()` splits the 8 LEDs into two colour blocks
(pixels 0–3, pixels 4–7) via `blinkt.set_pixel()` rather than picking one
colour with `bins_due[0]`. Priority order (which bin gets which half) is
fixed: Garden Waste, then Rubbish, then Recycling — see
`bin_led_service.py`'s `update_led_display()`.

**Reminder window:** configurable via `reminder_start_hours_before` (default 24) and
`reminder_end_hours_after` (default 1). At defaults: (collection_date − 24 h) at 00:00 →
collection_date at 01:00. Derived directly from `date_parsed` — no hardcoded day names.
Works automatically for any collection day regardless of bank holiday shifts.

**Brightness:** Keep `led_brightness` low (0.05–0.15). The Pi Zero 2 powers the
LEDs directly from GPIO and full brightness across all 8 LEDs can cause
instability.

---

## Colour constants

Colour definitions live in two parallel files — one per language layer:

- `bin-led-reminder/constants.py` — RGB tuples `(R, G, B)` for the LED service
- `bin-led-webui/static/consts.js` — hex strings for the web UI

When adding a new colour or bin type mapping, update **all three** of:

1. `bin-led-reminder/constants.py` — add RGB tuple to palette; add to `BIN_COLOURS` if a bin type
2. `bin-led-webui/static/consts.js` — add hex value to palette; add to `TEST_COLOUR_HEX`
3. `bin-led-webui/main.py` — add RGB tuple to `TEST_COLOURS`

There is no code generation or shared source — these must be kept in sync manually.

---

## Web UI API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | LED service state, error state, next collections due, LEDs active, last scraped timestamp |
| `GET` | `/api/schedule` | Upcoming collections (past entries filtered out, `days_until` recalculated at request time) |
| `GET` | `/api/config` | Editable config fields (`base_url` is read-only and omitted from `PATCH`) |
| `PATCH` | `/api/config` | Update: `led_brightness`, `check_interval_hours`, `update_interval_weeks`, `log_level`, `reminder_start_hours_before`, `reminder_end_hours_after` |
| `GET` | `/api/logs?lines=50` | Last N lines of LED service log (max 200) |
| `POST` | `/api/service/{action}` | `start` / `stop` / `restart` / `clear-errors` / `force-update` |
| `POST` | `/api/leds/test` | Flash LEDs a given colour; 409 if LED service is running, 503 in dev mode |

The `POST /api/leds/test` endpoint blocks for ~3 s. The test LED colour picker
in the web UI is structurally disabled while the LED service is running to
prevent SPI bus contention.

---

## Data source

East Cambridgeshire District Council's self-service portal (AchieveForms) is
a fully client-rendered form gated by a session + short-lived captcha token —
it cannot be scraped with a plain HTTP request the way the old Firmstep page
could. `bin-led-scraper/scrape_bins.py` drives a real headless browser
(Playwright) through the form on a weekly GitHub Actions schedule
(`.github/workflows/scrape-bins.yml`) and commits the result to
`bin-led-scraper/data/recycling_schedule.json`. `bin_led_service.py` fetches
that file over plain HTTPS via `fetch_schedule_data()` — it no longer scrapes
anything itself. If the council redesigns their form, the Playwright
selectors in `scrape_bins.py` (currently `get_by_label(...)` calls keyed on
the form's field labels) will need updating, not anything in
`bin_led_service.py`.

**Form flow** (as verified against the live site, Jul 2026): the fields live
inside an `<iframe class="achieveforms-iframe">`, not the top-level page, so
Playwright locators must be scoped via `page.frame_locator(...)`. The
sequence is: fill postcode → press Enter → select an address from the
populated dropdown → click the **"Find collection dates"** button that
appears once an address is selected. The schedule lookup
(`POST /apibroker/runLookup` whose response contains `ScheduledStart`) only
fires after that button click — selecting the address alone does nothing.
This exact step was missing from the first implementation and is the most
likely thing to silently break again if the council adjusts the form.

**Debugging the scraper against the live site:** this repo is public, so
GitHub Actions logs and artifacts are publicly visible — never print or
commit real postcode/UPRN/address data to them. Reproduce issues locally
instead, with a throwaway postcode anywhere in the East Cambridgeshire
district and whichever address the dropdown happens to offer; the form's
behaviour doesn't depend on which real address is used. If diagnostics ever
need to run in CI itself, keep them boolean/count-only (e.g. "did the
selection match", "is the button visible") rather than printing the actual
values.

---

## Error handling

- Network/fetch failures set an error state (`error_state.json`) and turn LEDs red
- Error state persists across restarts until explicitly cleared
- To recover: `./manage.sh clear-errors` (deletes `error_state.json` and restarts)
- In error state the service retries every 5 minutes instead of the normal 1-hour interval

---

## Key conventions

### Deployment workflow

`europa` has this repo cloned at `~/blinkt-projects/bin-led-reminder` with
`origin` pointing at this GitHub repo. Deployment is `git pull`, not SFTP —
git preserves file modes, so pulled shell scripts keep their execute bit
(unlike files copied over SFTP).

**Automatic:** `auto-deploy.timer` runs `auto-deploy.sh` daily. It does a
`git pull --ff-only`; if that lands new commits, it restarts
`bin-led-reminder` (and `bin-led-webui` too, if it happens to be running).
No-op if there's nothing new. Managed via `manage.sh`:

```bash
./manage.sh auto-deploy enable     # turn on the daily timer (one-time setup)
./manage.sh auto-deploy status     # timer state + next scheduled run
./manage.sh auto-deploy logs       # live log of pull/restart activity
./manage.sh auto-deploy run-now    # trigger a check immediately
./manage.sh auto-deploy disable    # turn it off
```

`--ff-only` means it never attempts to merge — if the Pi's working tree has
diverged (e.g. something was edited directly on it), the pull fails loudly
and visibly in `manage.sh auto-deploy logs` instead of guessing. The
service runs as `pizero2` and needs passwordless `sudo` for exactly two
commands (`systemctl restart bin-led-reminder` / `bin-led-webui`) — see
`auto-deploy.service`'s `ExecStart` for what actually runs, and grant this
via a scoped `/etc/sudoers.d/` entry (`visudo -f /etc/sudoers.d/auto-deploy`),
not blanket `NOPASSWD:ALL`.

**Manual** (for testing a change immediately, or if you'd rather not wait
for the timer):

1. Edit files locally or in Claude Code, commit, and push to `main`
2. SSH into `europa` and run:
   ```bash
   git -C ~/blinkt-projects/bin-led-reminder pull
   ```
   If this refuses with "local changes would be overwritten," something was
   edited directly on the Pi (or copied over some other way) since the last
   pull — `git stash` before pulling rather than discarding blind, then
   inspect the stash (`git stash show -p`) before dropping it.
3. Use `manage.sh` to restart whichever service(s) changed. `bin-led-reminder`
   and `bin-led-webui` must be redeployed and restarted **together** whenever
   either changes — the web UI's bin-type matching and colour palette have to
   stay in sync with the LED service's taxonomy (see Colour constants above).

Before `auto-deploy.timer` existed, this git clone silently drifted months
out of sync with `main` — if the Pi's behaviour ever doesn't match what's on
`main` again, check `./manage.sh auto-deploy status` (is the timer actually
enabled?) before assuming the code is what you think it is.

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

- 🟢 **`manage.sh` uses a relative path for venv activation** — `source
  ../blinkt-env/bin/activate` works when run from `bin-led-reminder/` but fails
  silently if invoked from a different directory. Fix with `$SCRIPT_DIR`. Low
  real-world risk given the standard SSH workflow.

---

## Known gaps / planned work

### Standard priority

- **Night dimming** — auto-reduce `led_brightness` during a configurable quiet
  window (e.g. 11pm–7am) via two new config fields (`night_dim_start`,
  `night_dim_end`, `night_dim_brightness`). Relevant given Pi Zero 2 power
  concerns at higher brightness.
- **Outdoor Food Caddy opt-in** — Outdoor Food Caddy collections are
  hardcoded-ignored. An `ignore_outdoor_food_caddy` config flag (default
  `true`) would make the project usable for other councils or households that
  want the reminder.
- **Scraper resilience + health check API** — add a `GET /api/health` endpoint
  that reports scraper health: last successful scrape timestamp, row count
  returned, and whether it fell below a minimum threshold. A canary assertion
  (e.g. assert ≥ 4 collection rows returned) would catch council site redesigns
  before the error LED fires. Health endpoint can also be used for external
  uptime monitoring.

### Lower priority

- **Async `POST /api/leds/test`** — currently blocks for ~3 s. Fire-and-forget
  with a status poll endpoint would improve UI responsiveness, though it adds
  coordination complexity.
- **Pico Accordion for logs and config** — collapse the Logs and Config sections
  into Pico CSS v2 `<details>`/Accordion components to reduce page length and
  keep the status card prominent above the fold.
