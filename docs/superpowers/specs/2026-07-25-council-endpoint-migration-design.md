# Council Endpoint Migration — Design Spec

Date: 2026-07-25

## Background

East Cambridgeshire District Council replaced their old Firmstep-based bin
collection page with a new **AchieveForms** (IEG4) system. The old scraper in
`bin_led_service.py` did a single anonymous `GET` to a Firmstep URL with the
UPRN as a query parameter, then parsed server-rendered `.collectionsrow` HTML
with BeautifulSoup.

Investigation of the new site (captured via browser DevTools) found:

- The new page is a fully client-rendered JS form (jQuery + Dust.js
  templates). There is no server-rendered collection data to scrape.
- The actual data comes back from a `POST` to
  `https://eastcambs-self.achieveservice.com/apibroker/runLookup`, fired by
  the form's JS after the user selects their address.
- That call requires an established session (`PHPSESSID` and related
  cookies) — a request with no cookies is rejected with a clean
  `403 {"result":"logout"}`.
- The call also includes an `AuthenticateResponse` field (almost certainly an
  invisible-reCAPTCHA token — the page loads `google.com/recaptcha/api.js`).
  Testing confirmed this token is genuinely enforced and short-lived/single-use:
  replaying the *exact* original successful request (same cookies, same real
  token, same UPRN) minutes later failed with `500 ['WEBSERVICE']: Lookup
  Error`. A plain `requests`/BeautifulSoup script cannot generate a fresh
  token — that requires real JS execution in a browser.
- The successful response's `integration.transformed.select_data` gives a
  clean, flat list of `{label, value}` pairs, one per collection date, e.g.
  `{"label": "GARDEN WASTE BIN - 27/08/2026", "value": "GARDEN WASTE BIN"}`.
- The bin taxonomy itself changed completely:
  - `OUTDOOR FOOD CADDY` — weekly, every week (functionally the new "ignore,
    it happens every week" bin — the same role `Black Bag` played before).
  - `RUBBISH BIN - 180L` and `GARDEN WASTE BIN` — fall on the **same date**,
    fortnightly ("Green week").
  - `RECYCLING BIN - 240L` — its own fortnightly week ("Blue week").

  Because Rubbish and Garden Waste share a date, the existing tech-debt item
  ("no mixed-colour indication", `bins_due[0]` picks a single colour) is no
  longer a rare hypothetical — it is the normal behaviour of every Green
  week. This design fixes it rather than deferring it further.

## Architecture change

Because a valid `AuthenticateResponse` can only be produced by a real browser
executing the form's JS, and the Pi Zero 2 (512 MB RAM, single core, no
Docker per project constraints) cannot reasonably run a headless browser,
scraping can no longer happen on the Pi. The scrape moves off-device:

```
GitHub Actions (weekly cron)
  └─ Playwright headless Chromium drives the real AchieveForms UI
       └─ intercepts the runLookup network response
       └─ writes data/recycling_schedule.json (bin types + dates only, no PII)
       └─ commits + pushes to the (public) repo
                    │
                    ▼
      raw.githubusercontent.com/.../data/recycling_schedule.json
                    │
                    ▼ plain HTTPS GET (existing retry logic)
Pi: bin_led_service.py (unchanged polling loop, unchanged LED-driving logic
    other than the colour map and the new split-pixel case)
```

The repo is already public, so the raw file needs no auth and the Pi needs no
new dependencies (git, ssh keys, etc.) — just a `GET`, which it already knows
how to do reliably (retry logic already exists in `fetch_data()`).

The published JSON contains no address, postcode, or UPRN — only bin type and
date — so publishing it in a public repo introduces no meaningful privacy
exposure.

### Why drive the UI instead of replaying the raw API payload

The captured `runLookup` request body is tied to specific internal IDs
(`AF-Form-...`, `AF-Field-...`, `stage_id`, etc.) that belong to the current
published version of this specific council form and could change on any
council-side republish. Driving the actual visible form fields (postcode
input, address `<select>`) is what a real user does, and is far more likely
to keep working across unrelated backend changes. The one shortcut taken: the
address `<select>` option's `value` attribute is the UPRN itself, so the
script can select the correct address by value directly rather than matching
address text.

## Component: `bin-led-scraper/`

New top-level directory, parallel to `bin-led-reminder/` and
`bin-led-webui/`:

```
bin-led-scraper/
├── scrape_bins.py       ← Playwright script
├── requirements.txt     ← playwright
└── data/
    └── recycling_schedule.json   ← committed output, weekly
```

`scrape_bins.py`:

1. Launches headless Chromium via Playwright.
2. Navigates to the council's AchieveForms URL (same URL captured during
   investigation).
3. Types `COUNCIL_POSTCODE` (env var / GitHub secret) into the postcode
   field.
4. Waits for the address `<select>` to populate, selects the option whose
   `value` equals `COUNCIL_UPRN` (env var / GitHub secret).
5. Registers a `page.on("response")` listener matching the `apibroker/
   runLookup` URL, waits for the response containing `ScheduledStart` data.
6. Parses `integration.transformed.select_data` from that response. Each
   entry's `label` is `"<BIN TYPE> - DD/MM/YYYY"`; splits on `" - "`,
   re-parses the date.
7. Converts to the existing internal schema (unchanged from today):
   ```json
   {
     "date": "Thu - 30 Jul 2026",
     "date_parsed": "2026-07-30T00:00:00",
     "bin_type": "GARDEN WASTE BIN",
     "day_of_week": "Thursday"
   }
   ```
   (`date` is formatted as `%a - %d %b %Y` to match the format
   `bin_led_service.py` and `main.py` already parse — no downstream date
   parsing changes needed.)
8. Deduplicates/sorts by `date_parsed`, writes `metadata.last_updated` (now
   scraper) + `total_collections`, writes `data/recycling_schedule.json`.

Retries: if the address dropdown or the expected network response doesn't
appear within a timeout, retry the whole flow up to 3 times (fresh page load
each time, since a stale session could plausibly cause a one-off failure)
before failing the job.

### `.github/workflows/scrape-bins.yml`

- Trigger: `schedule` (weekly cron) + `workflow_dispatch` (manual re-run).
- Steps: checkout, set up Python, `pip install -r
  bin-led-scraper/requirements.txt`, `playwright install --with-deps
  chromium`, run `scrape_bins.py` with `COUNCIL_POSTCODE` /
  `COUNCIL_UPRN` from repo secrets, then `git diff --quiet ||
  git commit && git push` for `bin-led-scraper/data/recycling_schedule.json`.
- GitHub's default behaviour (email on workflow failure) is sufficient
  notification if a run fails — no extra alerting needed.

## Pi-side changes: `bin_led_service.py`

- Remove `BeautifulSoup` import and the old `scrape_collections()` /
  `parse_date()` HTML-parsing logic entirely (the `bs4` dependency is
  dropped).
- `fetch_data()`'s retry loop is kept, but now does a plain `GET` against
  `config['base_url']` (repointed to the raw GitHub URL) expecting the JSON
  schema directly — no HTML parsing.
- `save_data()` changes: rather than constructing fresh `metadata` with
  `datetime.now()`, write the fetched JSON to disk as-is. The scraper's own
  `metadata.last_updated` is preserved end-to-end, since it now carries the
  meaningful "last successfully scraped" signal for the staleness indicator.
- `detect_collection_schedule()`: the `"Black Bag" not in bin_type` filter
  becomes `"OUTDOOR FOOD CADDY" not in bin_type`.
- `update_led_display()`: after excluding the ignored bin type,
  `bins_due` can now resolve to 0, 1, or 2 relevant colours:
  - 0 → LEDs cleared (unchanged).
  - 1 → `blinkt.set_all(*colour, brightness)` (unchanged behaviour).
  - 2 → split display: pixels 0–3 get Garden Waste's colour (green),
    pixels 4–7 get Rubbish's colour (orange), via
    `blinkt.set_pixel(i, *colour, brightness)` + `blinkt.show()`. This
    fixed priority order (Garden Waste always LEDs 0–3, Rubbish always
    LEDs 4–7) is used regardless of scrape/list order, so the split is
    stable across runs.
  - >2 (not expected given the known taxonomy, but defensive) → take the
    first two by the same fixed priority order (Garden Waste, then Rubbish,
    then Recycling), log a warning that a third bin type was dropped from
    the display.
  - An unrecognised bin type is still treated as an error (red), as today.

## Colour mapping (`constants.py`)

```python
BIN_COLOURS = {
    'RECYCLING BIN - 240L': COLOUR_BLUE,
    'GARDEN WASTE BIN':     COLOUR_GREEN,
    'RUBBISH BIN - 180L':   COLOUR_ORANGE,
}
```

`OUTDOOR FOOD CADDY` is deliberately absent (never drives LEDs), matching the
precedent `Black Bag` set. `COLOUR_ORANGE` already exists in the palette —
chosen over black/white/grey specifically because true black is
indistinguishable from LEDs-off and full white across 8 LEDs is the exact
brightness/current scenario already flagged as a stability risk.

## Web UI changes

- `bin-led-webui/static/consts.js`: `BIN_COLOURS` keys updated to the three
  new bin-type strings; `COLOUR_BIN_BLACK_BAG` (dual-purpose: ignored-bin
  colour + muted UI text) keeps its muted-grey value but its bin-type key
  changes from `'Black Bag'` to `'OUTDOOR FOOD CADDY'`.
- `bin-led-webui/main.py`: `TEST_COLOURS` keys updated to match; the two
  `if col.get("bin_type") == "Black Bag"` filters (`_leds_active`,
  next-collection lookup) become `"OUTDOOR FOOD CADDY"`.
- `bin-led-webui/static/app.js`: the `UpcomingCollections` filter
  (`c.bin_type !== 'Black Bag'`) becomes `'OUTDOOR FOOD CADDY'`.
- `GET /api/status` gains `last_scraped` (straight passthrough of
  `metadata.last_updated` from the schedule file). Surfaced in the UI status
  card as a small "Last scraped: <date>" line — a plain display of existing
  data, no new polling or alerting logic.
- `GET /api/status`'s singular `next_collection` becomes `next_collections`
  (a list): the loop that previously broke on the first non-ignored match
  instead collects every non-ignored collection sharing the same next
  upcoming date. This keeps the status card honest once Garden Waste and
  Rubbish routinely share a date — otherwise the UI text would silently
  disagree with what the split LEDs are actually showing. The status card
  renders one line per entry in the list instead of a single line.
- The `ConfigPanel` LED strip visualiser (the 8 `led-square` divs mirroring
  the physical Blinkt strip) is the most literal "what are the LEDs showing"
  surface in the UI, so it gets the same treatment: when `next_collections`
  has two entries, squares 0–3 render the first colour and squares 4–7 the
  second, matching the Pi's split-pixel behaviour exactly (same halves, same
  order). With one entry, all 8 squares render that single colour as today.

## Config changes

- `uprn` is removed from `config.json` / `config.example.json` — it has no
  functional role on the Pi anymore (the GitHub Actions secret is now the
  only place it's needed). Removed from any web UI config schema references.
- `base_url` is kept (still read-only via `GET`/`PATCH /api/config`,
  unchanged mechanism) but its value changes to the GitHub raw JSON URL.
- `update_interval_weeks` default drops from `2` to `1`, matching the new
  weekly upstream scrape cadence so the Pi doesn't sit on stale data for two
  weeks between its own checks. Still user-configurable.

## Testing

`bin-led-reminder/tests/test_colours.py`:

- Replace `'Blue Bin'` / `'Green or Brown Bin'` / `'Black Bag'` literals with
  `'RECYCLING BIN - 240L'` / `'GARDEN WASTE BIN'` / `'RUBBISH BIN - 180L'` /
  `'OUTDOOR FOOD CADDY'`.
- Rename `test_black_bag_absent_from_bin_colours` →
  `test_food_caddy_absent_from_bin_colours`.
- Add coverage for the two-colour split-pixel path (`bins_due` containing
  both Garden Waste and Rubbish → asserts `set_pixel` called for both halves
  with the right colours, not `set_all`).
- Add a single-colour Rubbish/Orange test alongside the existing
  Recycling/Blue and Garden/Green ones.

No changes needed to `test_leds.py` (Pi hardware test) — it doesn't reference
bin-type strings.

`bin-led-scraper/` is new browser-automation code that talks to a live
external site; it is not a candidate for a mocked unit-test suite in the same
style as `test_colours.py`. Correctness here is verified by running the
GitHub Actions workflow (`workflow_dispatch` manual trigger) and checking the
committed JSON, not by an offline test suite.

## Documentation

- `README.md`: LED colour table, "Black Bag ignored" note, data source
  description.
- `CLAUDE.md`: repository layout diagram (add `bin-led-scraper/`), LED
  colour logic table, "Data source" section (AchieveForms instead of
  Firmstep, mention the two-step postcode→address flow and the captcha
  constraint that necessitated the architecture change), config table
  (remove `uprn`, describe `base_url`'s new meaning), service architecture
  diagram (add the GitHub Actions → raw URL → Pi flow), and move the
  "No mixed-colour indication" item out of Known Issues since this design
  resolves it.
