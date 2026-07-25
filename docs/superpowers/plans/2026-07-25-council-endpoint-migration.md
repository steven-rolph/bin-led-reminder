# Council Endpoint Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the bin-collection data pipeline from the council's old (now-dead) Firmstep HTML scrape to their new AchieveForms system, and fix the LED display so it correctly shows two bins due on the same date instead of arbitrarily picking one.

**Architecture:** A new headless-browser scraper (`bin-led-scraper/`) runs on a weekly GitHub Actions schedule, drives the real AchieveForms UI (session + captcha-gated — cannot be done with a plain HTTP request), and commits the resulting schedule JSON to this public repo. `bin_led_service.py` on the Pi is simplified to `GET` that raw JSON instead of scraping HTML itself, and its LED display logic is extended to split the 8 LEDs into two colour halves when two bins share a date. The web UI is updated to match: new bin colours, a `last_scraped` staleness indicator, and a `next_collections` list (plural) so its status card and LED-strip visualiser stay honest about what the physical LEDs are showing.

**Tech Stack:** Python 3.11+, `requests`, `pytest`, Playwright (new), GitHub Actions, FastAPI, vanilla JS (Preact/HTM, no build step).

## Global Constraints

- Full spec: `docs/superpowers/specs/2026-07-25-council-endpoint-migration-design.md` — read it before starting if anything below is ambiguous.
- `led_brightness` must stay low (0.05–0.15) — do not change brightness-related code beyond what's specified.
- Never modify `bin_led_service.py`'s LED-driving logic as a side effect of a web UI change — all changes to it in this plan are because the data source itself changed, not incidentally.
- Log messages must name the target service explicitly (e.g. `"Web UI: ..."`), per existing convention in `main.py`.
- `bin-led-scraper/` output (`data/recycling_schedule.json`) must never contain address, postcode, or UPRN — bin type and date only.
- All Python test commands below assume `cd bin-led-reminder/` first, using the repo's existing pytest setup (`pytest>=7.0` already in `requirements.txt`).

---

### Task 1: Update bin colour mapping to the new taxonomy

**Files:**
- Modify: `bin-led-reminder/constants.py`
- Modify: `bin-led-reminder/tests/test_colours.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `BIN_COLOURS` dict in `constants.py` keyed by `'RECYCLING BIN - 240L'`, `'GARDEN WASTE BIN'`, `'RUBBISH BIN - 180L'` — every later task that touches bin-type strings uses these exact keys.

- [ ] **Step 1: Update the failing tests to the new taxonomy**

Edit `bin-led-reminder/tests/test_colours.py`. Replace:

```python
def test_bin_colours_blue_bin_maps_to_blue():
    assert BIN_COLOURS['Blue Bin'] == COLOUR_BLUE


def test_bin_colours_green_bin_maps_to_green():
    assert BIN_COLOURS['Green or Brown Bin'] == COLOUR_GREEN


def test_black_bag_absent_from_bin_colours():
    # Black Bag is filtered before lookup and must never drive the LEDs
    assert 'Black Bag' not in BIN_COLOURS
```

with:

```python
def test_bin_colours_recycling_maps_to_blue():
    assert BIN_COLOURS['RECYCLING BIN - 240L'] == COLOUR_BLUE


def test_bin_colours_garden_waste_maps_to_green():
    assert BIN_COLOURS['GARDEN WASTE BIN'] == COLOUR_GREEN


def test_bin_colours_rubbish_maps_to_orange():
    assert BIN_COLOURS['RUBBISH BIN - 180L'] == COLOUR_ORANGE


def test_food_caddy_absent_from_bin_colours():
    # Outdoor Food Caddy is filtered before lookup and must never drive the LEDs
    assert 'OUTDOOR FOOD CADDY' not in BIN_COLOURS
```

Also replace the two LED-display tests further down that use the old strings:

```python
def test_blue_bin_sets_blue_leds():
    _run_display('Blue Bin')
    _blinkt.set_all.assert_called_once_with(*COLOUR_BLUE, 0.1)
    _blinkt.show.assert_called()


def test_green_or_brown_bin_sets_green_leds():
    _run_display('Green or Brown Bin')
    _blinkt.set_all.assert_called_once_with(*COLOUR_GREEN, 0.1)
    _blinkt.show.assert_called()
```

with:

```python
def test_recycling_bin_sets_blue_leds():
    _run_display('RECYCLING BIN - 240L')
    _blinkt.set_all.assert_called_once_with(*COLOUR_BLUE, 0.1)
    _blinkt.show.assert_called()


def test_garden_waste_bin_sets_green_leds():
    _run_display('GARDEN WASTE BIN')
    _blinkt.set_all.assert_called_once_with(*COLOUR_GREEN, 0.1)
    _blinkt.show.assert_called()


def test_rubbish_bin_sets_orange_leds():
    _run_display('RUBBISH BIN - 180L')
    _blinkt.set_all.assert_called_once_with(*COLOUR_ORANGE, 0.1)
    _blinkt.show.assert_called()
```

And update the one remaining old-string reference in `test_leds_off_outside_reminder_window`:

```python
    schedule = {'collection_date': past_date, 'bins_due': ['Blue Bin']}
```

becomes:

```python
    schedule = {'collection_date': past_date, 'bins_due': ['RECYCLING BIN - 240L']}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py -v`
Expected: FAIL — `KeyError: 'RECYCLING BIN - 240L'` (and similar) since `constants.py` hasn't changed yet.

- [ ] **Step 3: Update `constants.py`**

In `bin-led-reminder/constants.py`, replace:

```python
BIN_COLOURS = {
    'Blue Bin':           COLOUR_BLUE,
    'Green or Brown Bin': COLOUR_GREEN,
}
```

with:

```python
BIN_COLOURS = {
    'RECYCLING BIN - 240L': COLOUR_BLUE,
    'GARDEN WASTE BIN':     COLOUR_GREEN,
    'RUBBISH BIN - 180L':   COLOUR_ORANGE,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py -v`
Expected: PASS (all tests, including the pre-existing palette/error tests).

- [ ] **Step 5: Commit**

```bash
git add bin-led-reminder/constants.py bin-led-reminder/tests/test_colours.py
git commit -m "feat: update bin colour mapping to new council taxonomy"
```

---

### Task 2: Filter Outdoor Food Caddy instead of Black Bag in schedule detection

**Files:**
- Modify: `bin-led-reminder/bin_led_service.py:265-273` (`detect_collection_schedule`)
- Modify: `bin-led-reminder/tests/test_colours.py`

**Interfaces:**
- Consumes: `BinLEDService.detect_collection_schedule()` (existing method, unchanged signature — returns `{'collection_date': date, 'bins_due': [str, ...]}`).
- Produces: `detect_collection_schedule()` now excludes `'OUTDOOR FOOD CADDY'` instead of `'Black Bag'`. Task 3 builds on this.

- [ ] **Step 1: Write the failing test**

Add to `bin-led-reminder/tests/test_colours.py` (near the other service-logic tests, after `_run_display` helper definitions):

```python
def _make_service_with_data(collections):
    """Construct a BinLEDService whose load_data() returns fixed collections."""
    from bin_led_service import BinLEDService
    service = BinLEDService.__new__(BinLEDService)
    service.logger = logging.getLogger('test')
    service.load_data = lambda: {'collections': collections}
    return service


def test_food_caddy_excluded_from_bins_due():
    collections = [
        {
            'date': 'Thu - 30 Jul 2026',
            'date_parsed': '2026-07-30T00:00:00',
            'bin_type': 'OUTDOOR FOOD CADDY',
            'day_of_week': 'Thursday',
        },
        {
            'date': 'Thu - 30 Jul 2026',
            'date_parsed': '2026-07-30T00:00:00',
            'bin_type': 'GARDEN WASTE BIN',
            'day_of_week': 'Thursday',
        },
    ]
    service = _make_service_with_data(collections)
    with patch('bin_led_service.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 7, 25)
        mock_dt.fromisoformat = datetime.fromisoformat
        schedule = service.detect_collection_schedule()
    assert schedule['bins_due'] == ['GARDEN WASTE BIN']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py::test_food_caddy_excluded_from_bins_due -v`
Expected: FAIL — `bins_due` still contains `'OUTDOOR FOOD CADDY'` because the service still filters on `'Black Bag'`.

- [ ] **Step 3: Update `detect_collection_schedule()`**

In `bin-led-reminder/bin_led_service.py`, find:

```python
        # Get bin types for this week (excluding Black Bag)
        bins_due = []
        for collection in this_week:
            bin_type = collection['bin_type']
            if "Black Bag" not in bin_type:
                bins_due.append(bin_type)
```

Replace with:

```python
        # Get bin types for this week (excluding Outdoor Food Caddy, which
        # is collected every week and isn't worth a reminder)
        bins_due = []
        for collection in this_week:
            bin_type = collection['bin_type']
            if "OUTDOOR FOOD CADDY" not in bin_type:
                bins_due.append(bin_type)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add bin-led-reminder/bin_led_service.py bin-led-reminder/tests/test_colours.py
git commit -m "feat: ignore Outdoor Food Caddy instead of Black Bag"
```

---

### Task 3: Split-pixel LED display when two bins share a date

**Files:**
- Modify: `bin-led-reminder/bin_led_service.py:315-345` (`update_led_display`)
- Modify: `bin-led-reminder/tests/test_colours.py`

**Interfaces:**
- Consumes: `BIN_COLOURS` from Task 1, `bins_due` list from Task 2's `detect_collection_schedule()`.
- Produces: `update_led_display()` now calls `blinkt.set_pixel(i, r, g, b, brightness)` for the two-bin case instead of always calling `blinkt.set_all`. No other method signatures change.

- [ ] **Step 1: Write the failing tests**

Add to `bin-led-reminder/tests/test_colours.py`:

```python
def _run_display_multi(bin_types):
    """Run update_led_display() with multiple bins due on the same date."""
    _blinkt.reset_mock()
    service = _make_service()
    schedule = {'collection_date': _COLLECTION_DATE, 'bins_due': bin_types}
    with patch.object(service, 'detect_collection_schedule', return_value=schedule):
        with patch('bin_led_service.datetime') as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            service.update_led_display()
    return service


def test_two_bins_due_splits_leds_into_two_colour_blocks():
    _run_display_multi(['GARDEN WASTE BIN', 'RUBBISH BIN - 180L'])
    expected_calls = (
        [call(i, *COLOUR_GREEN, 0.1) for i in range(4)]
        + [call(i, *COLOUR_ORANGE, 0.1) for i in range(4, 8)]
    )
    _blinkt.set_pixel.assert_has_calls(expected_calls, any_order=False)
    _blinkt.set_all.assert_not_called()
    _blinkt.show.assert_called()


def test_three_bins_due_uses_first_two_by_priority(caplog):
    with caplog.at_level(logging.WARNING):
        _run_display_multi(['RECYCLING BIN - 240L', 'GARDEN WASTE BIN', 'RUBBISH BIN - 180L'])
    expected_calls = (
        [call(i, *COLOUR_GREEN, 0.1) for i in range(4)]
        + [call(i, *COLOUR_ORANGE, 0.1) for i in range(4, 8)]
    )
    _blinkt.set_pixel.assert_has_calls(expected_calls, any_order=False)
    assert 'dropped' in caplog.text.lower()
```

Add `call` to the existing `from unittest.mock import MagicMock, patch` import line, making it:

```python
from unittest.mock import MagicMock, call, patch
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py::test_two_bins_due_splits_leds_into_two_colour_blocks tests/test_colours.py::test_three_bins_due_uses_first_two_by_priority -v`
Expected: FAIL — `update_led_display()` currently only reads `bins_due[0]` and calls `set_all`, so `set_pixel` is never called.

- [ ] **Step 3: Rewrite `update_led_display()`**

In `bin-led-reminder/bin_led_service.py`, find the body of `update_led_display()` from `if bins_due:` down to the matching `else:` block that clears LEDs when no bins are due:

```python
            if bins_due:
                self.logger.info(f"Reminder active! Bins due: {bins_due}")
                
                primary_bin = bins_due[0]
                colour = BIN_COLOURS.get(primary_bin)
                if colour:
                    blinkt.set_all(*colour, self.config['led_brightness'])
                    blinkt.show()
                    self.logger.info(f"LEDs set for {primary_bin}")
                else:
                    self.logger.error(f"Unrecognised bin type '{primary_bin}' — treating as error")
                    blinkt.set_all(*COLOUR_ERROR, self.config['led_brightness'])
                    blinkt.show()
            else:
                blinkt.clear()
                blinkt.show()
                self.logger.info("No bins due - LEDs cleared")
```

Replace with:

```python
            if bins_due:
                self.logger.info(f"Reminder active! Bins due: {bins_due}")

                # Fixed priority order keeps the split stable across runs,
                # independent of scrape/list order.
                priority_order = ['GARDEN WASTE BIN', 'RUBBISH BIN - 180L', 'RECYCLING BIN - 240L']
                ordered_bins = [b for b in priority_order if b in bins_due]
                # Any bin type not in the known priority list (unrecognised)
                # still needs to be checked for the error path below.
                ordered_bins += [b for b in bins_due if b not in priority_order]

                unrecognised = [b for b in ordered_bins if BIN_COLOURS.get(b) is None]
                if unrecognised:
                    self.logger.error(f"Unrecognised bin type '{unrecognised[0]}' — treating as error")
                    blinkt.set_all(*COLOUR_ERROR, self.config['led_brightness'])
                    blinkt.show()
                elif len(ordered_bins) == 1:
                    colour = BIN_COLOURS[ordered_bins[0]]
                    blinkt.set_all(*colour, self.config['led_brightness'])
                    blinkt.show()
                    self.logger.info(f"LEDs set for {ordered_bins[0]}")
                else:
                    if len(ordered_bins) > 2:
                        dropped = ordered_bins[2:]
                        self.logger.warning(f"More than two bins due — dropped {dropped} from LED display")
                        ordered_bins = ordered_bins[:2]
                    first_colour = BIN_COLOURS[ordered_bins[0]]
                    second_colour = BIN_COLOURS[ordered_bins[1]]
                    brightness = self.config['led_brightness']
                    for i in range(4):
                        blinkt.set_pixel(i, *first_colour, brightness)
                    for i in range(4, 8):
                        blinkt.set_pixel(i, *second_colour, brightness)
                    blinkt.show()
                    self.logger.info(f"LEDs split: {ordered_bins[0]} (0-3), {ordered_bins[1]} (4-7)")
            else:
                blinkt.clear()
                blinkt.show()
                self.logger.info("No bins due - LEDs cleared")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py -v`
Expected: PASS (all tests, including the single-bin tests from Task 1 — `ordered_bins` has length 1 for those, so they still hit the `set_all` branch).

- [ ] **Step 5: Commit**

```bash
git add bin-led-reminder/bin_led_service.py bin-led-reminder/tests/test_colours.py
git commit -m "feat: split LEDs into two colour blocks when two bins share a date"
```

---

### Task 4: Replace HTML scraping with a JSON fetch from the external scraper's output

**Files:**
- Modify: `bin-led-reminder/bin_led_service.py`
- Modify: `bin-led-reminder/requirements.txt`
- Modify: `bin-led-reminder/config.example.json`
- Modify: `bin-led-reminder/tests/test_colours.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `BinLEDService.fetch_schedule_data()` (replaces `fetch_data()` + `scrape_collections()` + `parse_date()`, all three removed) — returns a `dict` matching the `{"metadata": {...}, "collections": [...]}` schema. `save_data(data: dict)` signature changes from `save_data(bins_data: list)` to `save_data(data: dict)` — it now writes the dict verbatim instead of building its own metadata. Task 5/6 (the external scraper) must produce data in exactly this schema.

- [ ] **Step 1: Write the failing tests**

Add to `bin-led-reminder/tests/test_colours.py`:

```python
def test_fetch_schedule_data_returns_parsed_json():
    from bin_led_service import BinLEDService
    service = BinLEDService.__new__(BinLEDService)
    service.config = {'base_url': 'https://example.invalid/recycling_schedule.json'}
    service.logger = logging.getLogger('test')

    mock_response = MagicMock()
    mock_response.json.return_value = {
        'metadata': {'last_updated': '2026-07-20T06:00:00', 'total_collections': 1},
        'collections': [{
            'date': 'Thu - 30 Jul 2026',
            'date_parsed': '2026-07-30T00:00:00',
            'bin_type': 'GARDEN WASTE BIN',
            'day_of_week': 'Thursday',
        }],
    }
    mock_response.raise_for_status.return_value = None

    with patch('bin_led_service.requests.get', return_value=mock_response) as mock_get:
        data = service.fetch_schedule_data()

    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == 'https://example.invalid/recycling_schedule.json'
    assert data['metadata']['last_updated'] == '2026-07-20T06:00:00'
    assert data['collections'][0]['bin_type'] == 'GARDEN WASTE BIN'


def test_save_data_preserves_fetched_metadata(tmp_path):
    from bin_led_service import BinLEDService
    service = BinLEDService.__new__(BinLEDService)
    service.data_file = tmp_path / 'recycling_schedule.json'
    service.logger = logging.getLogger('test')

    fetched = {
        'metadata': {'last_updated': '2026-07-20T06:00:00', 'total_collections': 1},
        'collections': [{
            'date': 'Thu - 30 Jul 2026',
            'date_parsed': '2026-07-30T00:00:00',
            'bin_type': 'GARDEN WASTE BIN',
            'day_of_week': 'Thursday',
        }],
    }
    service.save_data(fetched)

    saved = json.loads(service.data_file.read_text())
    assert saved['metadata']['last_updated'] == '2026-07-20T06:00:00'
    assert saved['collections'][0]['bin_type'] == 'GARDEN WASTE BIN'
```

Add `import json` to the top of `test_colours.py` if not already present (it isn't currently imported there — check the existing import block and add it alongside `logging`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py::test_fetch_schedule_data_returns_parsed_json tests/test_colours.py::test_save_data_preserves_fetched_metadata -v`
Expected: FAIL — `AttributeError: 'BinLEDService' object has no attribute 'fetch_schedule_data'`, and `save_data` still expects a list and builds its own metadata.

- [ ] **Step 3: Remove the old HTML-scraping code and add the new fetch/save methods**

In `bin-led-reminder/bin_led_service.py`:

1. Remove the import: `from bs4 import BeautifulSoup`

2. Remove the `get_url()` method entirely:

```python
    def get_url(self):
        """Build the scraping URL"""
        return f"{self.config['base_url']}?language=en&uprn={self.config['uprn']}"
```

3. Replace `fetch_data()` with `fetch_schedule_data()`:

```python
    def fetch_data(self, retry_attempts=3, delay=2):
        """Fetch webpage with retry logic"""
        url = self.get_url()

        for attempt in range(retry_attempts):
            try:
                headers = {
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    )
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                self.logger.warning(f"Fetch attempt {attempt + 1} failed: {e}")
                if attempt < retry_attempts - 1:
                    time.sleep(delay)
                else:
                    raise
```

becomes:

```python
    def fetch_schedule_data(self, retry_attempts=3, delay=2):
        """Fetch the pre-scraped schedule JSON from base_url, with retry logic"""
        url = self.config['base_url']

        for attempt in range(retry_attempts):
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                if not data.get('collections'):
                    raise ValueError("Fetched schedule has no collections")
                return data
            except (requests.RequestException, ValueError) as e:
                self.logger.warning(f"Fetch attempt {attempt + 1} failed: {e}")
                if attempt < retry_attempts - 1:
                    time.sleep(delay)
                else:
                    raise
```

4. Remove `parse_date()` entirely:

```python
    def parse_date(self, date_str):
        """Parse date string into datetime object"""
        try:
            # Handle format like "Wed - 23 Jul 2025"
            date_part = date_str.split(' - ')[1] if ' - ' in date_str else date_str
            return datetime.strptime(date_part, "%d %b %Y")
        except (ValueError, IndexError) as e:
            self.logger.warning(f"Could not parse date '{date_str}': {e}")
            return None
```

5. Remove `scrape_collections()` entirely (the whole method that builds `soup = BeautifulSoup(...)` and selects `.collectionsrow`).

6. Replace `save_data()`:

```python
    def save_data(self, bins_data):
        """Save collection data to JSON file"""
        metadata = {
            'last_updated': datetime.now().isoformat(),
            'uprn': self.config['uprn'],
            'source_url': self.get_url(),
            'total_collections': len(bins_data)
        }

        output_data = {
            'metadata': metadata,
            'collections': bins_data
        }

        with open(self.data_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)

        self.logger.info(f"Data saved to {self.data_file}")
```

becomes:

```python
    def save_data(self, data):
        """Persist fetched schedule data to disk, preserving its own metadata
        (in particular metadata.last_updated, which is set by the external
        scraper and drives the staleness indicator — see
        docs/superpowers/specs/2026-07-25-council-endpoint-migration-design.md)."""
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        self.logger.info(f"Data saved to {self.data_file}")
```

7. Update the call site in `run_service()`:

```python
                if self.should_update_data():
                    self.logger.info("Data update needed - scraping new data")
                    bins_data = self.scrape_collections()
                    self.save_data(bins_data)
                    self.clear_error_state()  # Clear any previous errors
```

becomes:

```python
                if self.should_update_data():
                    self.logger.info("Data update needed - fetching new schedule")
                    data = self.fetch_schedule_data()
                    self.save_data(data)
                    self.clear_error_state()  # Clear any previous errors
```

8. Update `load_config()`'s `default_config` dict:

```python
        default_config = {
            "uprn": "REDACTED",
            "base_url": "https://self.eastcambs.gov.uk/appshost/firmstep/self/apps/custompage/bincollections",
            "update_interval_weeks": 2,
            "check_interval_hours": 1,
            "led_brightness": 0.1,
            "log_level": "INFO",
            "reminder_start_hours_before": 24,
            "reminder_end_hours_after": 1,
        }
```

becomes (using the repo's actual GitHub path — replace `<owner>/<repo>` with `steven-rolph/bin-led-reminder`, matching `git remote -v`):

```python
        default_config = {
            "base_url": "https://raw.githubusercontent.com/steven-rolph/bin-led-reminder/main/bin-led-scraper/data/recycling_schedule.json",
            "update_interval_weeks": 1,
            "check_interval_hours": 1,
            "led_brightness": 0.1,
            "log_level": "INFO",
            "reminder_start_hours_before": 24,
            "reminder_end_hours_after": 1,
        }
```

- [ ] **Step 4: Update `config.example.json`**

Replace the contents of `bin-led-reminder/config.example.json`:

```json
{
  "uprn": "YOUR_UPRN_HERE",
  "base_url": "https://self.eastcambs.gov.uk/appshost/firmstep/self/apps/custompage/bincollections",
  "update_interval_weeks": 2,
  "check_interval_hours": 1,
  "led_brightness": 0.1,
  "log_level": "INFO",
  "reminder_start_hours_before": 24,
  "reminder_end_hours_after": 1
}
```

with:

```json
{
  "base_url": "https://raw.githubusercontent.com/steven-rolph/bin-led-reminder/main/bin-led-scraper/data/recycling_schedule.json",
  "update_interval_weeks": 1,
  "check_interval_hours": 1,
  "led_brightness": 0.1,
  "log_level": "INFO",
  "reminder_start_hours_before": 24,
  "reminder_end_hours_after": 1
}
```

- [ ] **Step 5: Remove `beautifulsoup4` from `requirements.txt`**

In `bin-led-reminder/requirements.txt`, remove the line `beautifulsoup4>=4.9.3`, leaving:

```
requests>=2.25.1
blinkt>=0.1.2
pytest>=7.0
```

- [ ] **Step 6: Run the full test suite to verify everything still passes**

Run: `cd bin-led-reminder && python -m pytest tests/test_colours.py -v`
Expected: PASS (all tests, including the two new ones from Step 1).

- [ ] **Step 7: Commit**

```bash
git add bin-led-reminder/bin_led_service.py bin-led-reminder/requirements.txt bin-led-reminder/config.example.json bin-led-reminder/tests/test_colours.py
git commit -m "feat: fetch pre-scraped schedule JSON instead of scraping HTML directly"
```

---

### Task 5: New external scraper (`bin-led-scraper/`)

**Files:**
- Create: `bin-led-scraper/scrape_bins.py`
- Create: `bin-led-scraper/requirements.txt`
- Create: `bin-led-scraper/data/.gitkeep`

**Interfaces:**
- Consumes: `COUNCIL_POSTCODE` and `COUNCIL_UPRN` environment variables.
- Produces: `bin-led-scraper/data/recycling_schedule.json` in the exact schema Task 4's `fetch_schedule_data()`/`save_data()` expect: `{"metadata": {"last_updated": <ISO datetime str>, "total_collections": <int>}, "collections": [{"date": "<%a - %d %b %Y>", "date_parsed": "<ISO datetime str>", "bin_type": "<str>", "day_of_week": "<%A>"}]}`.

This component drives a real browser against a live, third-party website with a session/captcha gate — it is explicitly out of scope for an offline mocked test suite (see spec's Testing section). Verification is: run it against the real site via `workflow_dispatch` (Task 6) and inspect the committed output.

- [ ] **Step 1: Create `bin-led-scraper/requirements.txt`**

```
playwright>=1.40.0
```

- [ ] **Step 2: Create `bin-led-scraper/data/.gitkeep`**

Empty file — ensures the `data/` directory exists in git before the first scrape run commits into it.

```bash
mkdir -p bin-led-scraper/data
touch bin-led-scraper/data/.gitkeep
```

- [ ] **Step 3: Write `bin-led-scraper/scrape_bins.py`**

```python
#!/usr/bin/env python3
"""
Scrapes East Cambridgeshire District Council's bin collection schedule from
their AchieveForms "Waste collections calendar" form.

The council's form is fully client-rendered (no server-rendered HTML to
scrape) and gates its data lookup behind a session + short-lived
invisible-reCAPTCHA token, so this drives a real headless browser through
the visible form fields rather than replaying the internal API payload
directly. See:
docs/superpowers/specs/2026-07-25-council-endpoint-migration-design.md

NOTE: the postcode-search trigger (Enter key vs. auto-search-as-you-type)
was inferred, not directly observed, during investigation. If this script
starts failing at the "waiting for address options" step, that's the first
thing to check with a real browser + DevTools open.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

FORM_URL = (
    "https://eastcambs-self.achieveservice.com/AchieveForms/"
    "?mode=fill&consentMessage=yes"
    "&form_uri=sandbox-publish://AF-Process-2c7575a6-0139-4555-9d8a-ab504a44d989"
    "/AF-Stage-94ee5097-94db-474d-bc7a-d1796e3ab83a/definition.json"
    "&process=1"
    "&process_uri=sandbox-processes://AF-Process-2c7575a6-0139-4555-9d8a-ab504a44d989"
    "&process_id=AF-Process-2c7575a6-0139-4555-9d8a-ab504a44d989"
)

OUTPUT_FILE = Path(__file__).parent / "data" / "recycling_schedule.json"
MAX_ATTEMPTS = 3


def scrape_once(postcode: str, uprn: str) -> list[dict]:
    """Run the form flow once. Returns the raw select_data list of
    {"label": "<BIN TYPE> - DD/MM/YYYY", "value": "<BIN TYPE>"} entries."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(FORM_URL, wait_until="networkidle")

        postcode_field = page.get_by_label("Please enter your postcode or street name")
        postcode_field.fill(postcode)
        postcode_field.press("Enter")

        address_field = page.get_by_label("Select your address")
        address_field.wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            "(el) => el.options && el.options.length > 1",
            arg=address_field.element_handle(),
            timeout=15000,
        )

        with page.expect_response(
            lambda r: "apibroker/runLookup" in r.url and "ScheduledStart" in r.text()
        ) as response_info:
            address_field.select_option(value=uprn)

        payload = response_info.value.json()
        browser.close()

    return payload["integration"]["transformed"]["select_data"]


def parse_entries(select_data: list[dict]) -> list[dict]:
    """Convert raw {label, value} entries into the internal schedule schema."""
    collections = []
    for entry in select_data:
        bin_type = entry["value"]
        match = re.search(r"(\d{2}/\d{2}/\d{4})", entry["label"])
        if not match:
            continue
        date_obj = datetime.strptime(match.group(1), "%d/%m/%Y")
        collections.append({
            "date": date_obj.strftime("%a - %d %b %Y"),
            "date_parsed": date_obj.isoformat(),
            "bin_type": bin_type,
            "day_of_week": date_obj.strftime("%A"),
        })
    collections.sort(key=lambda c: c["date_parsed"])
    return collections


def main():
    postcode = os.environ["COUNCIL_POSTCODE"]
    uprn = os.environ["COUNCIL_UPRN"]

    last_error = None
    collections = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            select_data = scrape_once(postcode, uprn)
            collections = parse_entries(select_data)
            if not collections:
                raise ValueError("No collection entries parsed from response")
            break
        except Exception as e:
            last_error = e
            print(f"Attempt {attempt} failed: {e}", file=sys.stderr)
    else:
        print(f"All {MAX_ATTEMPTS} attempts failed: {last_error}", file=sys.stderr)
        sys.exit(1)

    output_data = {
        "metadata": {
            "last_updated": datetime.now().isoformat(),
            "total_collections": len(collections),
        },
        "collections": collections,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"Wrote {len(collections)} collection entries to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Commit**

```bash
git add bin-led-scraper/scrape_bins.py bin-led-scraper/requirements.txt bin-led-scraper/data/.gitkeep
git commit -m "feat: add headless-browser scraper for the new council AchieveForms system"
```

---

### Task 6: GitHub Actions workflow to run the scraper weekly

**Files:**
- Create: `.github/workflows/scrape-bins.yml`

**Interfaces:**
- Consumes: `scrape_bins.py` from Task 5, repo secrets `COUNCIL_POSTCODE` and `COUNCIL_UPRN`.
- Produces: commits to `bin-led-scraper/data/recycling_schedule.json` on `main`, which Task 4's `fetch_schedule_data()` reads via the raw URL.

- [ ] **Step 1: Write the workflow file**

```yaml
name: Scrape bin collection schedule

on:
  schedule:
    - cron: '0 6 * * 1'  # 06:00 UTC every Monday
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r bin-led-scraper/requirements.txt

      - name: Install Playwright browsers
        run: playwright install --with-deps chromium

      - name: Run scraper
        env:
          COUNCIL_POSTCODE: ${{ secrets.COUNCIL_POSTCODE }}
          COUNCIL_UPRN: ${{ secrets.COUNCIL_UPRN }}
        run: python bin-led-scraper/scrape_bins.py

      - name: Commit updated schedule
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add bin-led-scraper/data/recycling_schedule.json
          git diff --staged --quiet || git commit -m "chore: update bin collection schedule"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/scrape-bins.yml
git commit -m "ci: run the bin schedule scraper weekly via GitHub Actions"
```

- [ ] **Step 3: Note for the user (not an automated step)**

Before this workflow can succeed, `COUNCIL_POSTCODE` and `COUNCIL_UPRN` must be added as repo secrets (Settings → Secrets and variables → Actions), and the workflow should be triggered once manually via `workflow_dispatch` (Actions tab → "Scrape bin collection schedule" → "Run workflow") to confirm the selector strategy in `scrape_bins.py` actually works against the live site before relying on the weekly cron.

---

### Task 7: Web UI backend — new bin filter, `next_collections` list, staleness

**Files:**
- Modify: `bin-led-webui/main.py`

**Interfaces:**
- Consumes: `bin-led-scraper`'s schema (Task 5) as read from `recycling_schedule.json` via `_read_json`.
- Produces: `GET /api/status` response shape changes from `{"next_collection": {...} | None, ...}` to `{"next_collections": [...], "last_scraped": <str> | None, ...}`. `GET /api/config` no longer includes `"uprn"`. Task 8 (frontend) consumes this new shape.

- [ ] **Step 1: Update the two `"Black Bag"` filters**

In `bin-led-webui/main.py`, in `_leds_active()`:

```python
    for col in collections:
        if col.get("bin_type") == "Black Bag":
            continue
```

becomes:

```python
    for col in collections:
        if col.get("bin_type") == "OUTDOOR FOOD CADDY":
            continue
```

- [ ] **Step 2: Rewrite `get_status()` to produce `next_collections` (plural) and `last_scraped`**

Replace:

```python
@app.get("/api/status")
def get_status():
    schedule_data = _read_json(SCHEDULE_FILE)
    collections = schedule_data.get("collections", []) if schedule_data else []

    has_error = ERROR_FILE.exists()
    error_details = None
    if has_error:
        error_details = _read_json(ERROR_FILE)

    next_collection = None
    for col in collections:
        if col.get("bin_type") == "Black Bag":
            continue
        days = _recalculate_days_until(col["date"])
        if days is not None and days >= 0:
            next_collection = {
                "date": col["date"],
                "bin_type": col["bin_type"],
                "days_until": days,
                "hours_until": _hours_until(col["date"]),
            }
            break

    return {
        "led_service_running": _service_is_active(),
        "has_error": has_error,
        "error_details": error_details,
        "next_collection": next_collection,
        "leds_active": _leds_active(collections),
    }
```

with:

```python
@app.get("/api/status")
def get_status():
    schedule_data = _read_json(SCHEDULE_FILE)
    collections = schedule_data.get("collections", []) if schedule_data else []

    has_error = ERROR_FILE.exists()
    error_details = None
    if has_error:
        error_details = _read_json(ERROR_FILE)

    # Collect every non-ignored collection sharing the earliest upcoming
    # date (collections is sorted by date, so matches are contiguous) —
    # keeps this in sync with what the split-LED display on the Pi shows.
    next_collections = []
    next_date = None
    for col in collections:
        if col.get("bin_type") == "OUTDOOR FOOD CADDY":
            continue
        days = _recalculate_days_until(col["date"])
        if days is None or days < 0:
            continue
        if next_date is None:
            next_date = col["date"]
        elif col["date"] != next_date:
            break
        next_collections.append({
            "date": col["date"],
            "bin_type": col["bin_type"],
            "days_until": days,
            "hours_until": _hours_until(col["date"]),
        })

    last_scraped = (schedule_data or {}).get("metadata", {}).get("last_updated")

    return {
        "led_service_running": _service_is_active(),
        "has_error": has_error,
        "error_details": error_details,
        "next_collections": next_collections,
        "leds_active": _leds_active(collections),
        "last_scraped": last_scraped,
    }
```

- [ ] **Step 3: Remove `uprn` from `get_config()`**

Replace:

```python
    # Return only the fields the UI cares about (omit base_url, uprn)
    return {
        "uprn": data.get("uprn"),
        "update_interval_weeks": data.get("update_interval_weeks"),
        "check_interval_hours": data.get("check_interval_hours"),
        "led_brightness": data.get("led_brightness"),
        "log_level": data.get("log_level"),
        "reminder_start_hours_before": data.get("reminder_start_hours_before", 24),
        "reminder_end_hours_after": data.get("reminder_end_hours_after", 1),
    }
```

with:

```python
    # Return only the fields the UI cares about (omit base_url)
    return {
        "update_interval_weeks": data.get("update_interval_weeks"),
        "check_interval_hours": data.get("check_interval_hours"),
        "led_brightness": data.get("led_brightness"),
        "log_level": data.get("log_level"),
        "reminder_start_hours_before": data.get("reminder_start_hours_before", 24),
        "reminder_end_hours_after": data.get("reminder_end_hours_after", 1),
    }
```

- [ ] **Step 4: Manually verify the endpoint shapes**

There is no existing automated test suite for `main.py` (consistent with the rest of this codebase — see Task 8, which is verified the same way). Verify by running the web UI in dev mode and hitting the endpoints directly:

```bash
cd bin-led-webui
LED_SERVICE_DIR=../bin-led-reminder python -m uvicorn main:app --reload
# in another terminal:
curl -s localhost:8000/api/status | python -m json.tool
curl -s localhost:8000/api/config | python -m json.tool
```

Expected: `/api/status` response has a `next_collections` list (not `next_collection`) and a `last_scraped` key; `/api/config` response has no `uprn` key. (If `bin-led-reminder/recycling_schedule.json` doesn't exist locally yet, `/api/status` will still return 200 with `next_collections: []` and `last_scraped: null` since `schedule_data` is `None`-safe.)

- [ ] **Step 5: Commit**

```bash
git add bin-led-webui/main.py
git commit -m "feat: web UI backend — next_collections list, last_scraped, drop uprn"
```

---

### Task 8: Web UI frontend — new colours, `next_collections`, staleness, split LED-strip visualiser

**Files:**
- Modify: `bin-led-webui/static/consts.js`
- Modify: `bin-led-webui/static/app.js`

**Interfaces:**
- Consumes: `GET /api/status`'s `next_collections` (list) and `last_scraped` from Task 7.
- Produces: no new exports consumed elsewhere — this is the last code task.

- [ ] **Step 1: Update `consts.js`'s bin-type colours**

Replace:

```js
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
```

with:

```js
// ─── Bin type colours ─────────────────────────────────────────────────────────
export const COLOUR_BIN_BLUE   = '#3b82f6';  // Recycling Bin - 240L
export const COLOUR_BIN_GREEN  = '#22c55e';  // Garden Waste Bin
export const COLOUR_BIN_ORANGE = '#ffa500';  // Rubbish Bin - 180L
export const COLOUR_MUTED_DOT  = '#6b7280';  // Ignored bin type (Outdoor Food Caddy); also used for muted UI dots/text

// ─── Service & LED state indicators ───────────────────────────────────────────
// Running dot → COLOUR_BIN_GREEN
// Stopped / error dot → COLOUR_ERROR
export const COLOUR_ERROR      = '#ef4444';  // error state, service stopped, flash red, log errors
export const COLOUR_LEDS_ACTIVE = '#facc15';  // yellow dot when LEDs are on
// LEDs-off dot → COLOUR_MUTED_DOT
```

- [ ] **Step 2: Update `BIN_COLOURS` in `consts.js`**

Replace:

```js
// Keys must match bin_type strings in recycling_schedule.json exactly.
// Keep in sync with BIN_COLOURS in bin-led-reminder/constants.py.
export const BIN_COLOURS = {
  'Blue Bin':           COLOUR_BIN_BLUE,
  'Green or Brown Bin': COLOUR_BIN_GREEN,
  'Black Bag':          COLOUR_BIN_BLACK_BAG,
};
```

with:

```js
// Keys must match bin_type strings in recycling_schedule.json exactly.
// Keep in sync with BIN_COLOURS in bin-led-reminder/constants.py.
// Outdoor Food Caddy is deliberately absent — it never drives the LEDs.
export const BIN_COLOURS = {
  'RECYCLING BIN - 240L': COLOUR_BIN_BLUE,
  'GARDEN WASTE BIN':     COLOUR_BIN_GREEN,
  'RUBBISH BIN - 180L':   COLOUR_BIN_ORANGE,
};
```

- [ ] **Step 3: Update the CSS custom property comment for the renamed constant**

The `_root.style.setProperty(...)` block references `COLOUR_ERROR`, `COLOUR_LED_OFF`, etc. directly — none of those reference `COLOUR_BIN_BLACK_BAG` by name, so no change needed there. Confirm this by checking there is no `--colour-bin-black-bag` property tied to `COLOUR_BIN_BLACK_BAG` left stale — search `consts.js` for any remaining `COLOUR_BIN_BLACK_BAG` reference and confirm none remain after Steps 1–2.

Run: `grep -n COLOUR_BIN_BLACK_BAG bin-led-webui/static/consts.js`
Expected: no output.

- [ ] **Step 4: Update `app.js`'s import line**

Replace:

```js
import {
  COLOUR_BIN_GREEN, COLOUR_BIN_BLACK_BAG,
  COLOUR_ERROR, COLOUR_LEDS_ACTIVE, COLOUR_LED_OFF, COLOUR_FLASH_WHITE,
  COLOUR_SUCCESS, COLOUR_FAILURE, COLOUR_MUTED,
  BIN_COLOURS, TEST_COLOUR_HEX,
} from '/static/consts.js';
```

with:

```js
import {
  COLOUR_BIN_GREEN, COLOUR_MUTED_DOT,
  COLOUR_ERROR, COLOUR_LEDS_ACTIVE, COLOUR_LED_OFF, COLOUR_FLASH_WHITE,
  COLOUR_SUCCESS, COLOUR_FAILURE, COLOUR_MUTED,
  BIN_COLOURS, TEST_COLOUR_HEX,
} from '/static/consts.js';
```

- [ ] **Step 5: Replace `ledVisualiserColour` (singular) with `ledVisualiserColours` (plural, returns an array)**

Replace:

```js
function ledVisualiserColour(status, testColour) {
  if (testColour) return TEST_COLOUR_HEX[testColour];
  if (status.has_error) return COLOUR_ERROR;
  if (status.leds_active) {
    const bt = status.next_collection?.bin_type;
    return BIN_COLOURS[bt] || COLOUR_FLASH_WHITE;
  }
  return null;
}
```

with:

```js
function ledVisualiserColours(status, testColour) {
  if (testColour) return [TEST_COLOUR_HEX[testColour]];
  if (status.has_error) return [COLOUR_ERROR];
  if (status.leds_active) {
    const types = (status.next_collections || []).map(c => c.bin_type);
    const colours = types.map(t => BIN_COLOURS[t]).filter(Boolean);
    return colours.length ? colours : [COLOUR_FLASH_WHITE];
  }
  return [];
}
```

- [ ] **Step 6: Update `StatusCard` to render `next_collections` (list) and `last_scraped`**

Replace:

```js
function StatusCard({ status }) {
  if (!status) return html`<article aria-busy="true">Loading status...</article>`;

  const { led_service_running, has_error, error_details, next_collection, leds_active } = status;

  return html`
    <article>
      <header><strong>Service Status</strong></header>

      ${has_error && html`
        <div class="error-banner">
          <strong>Error state active</strong> — LEDs showing red.
          ${error_details && html` <br /><small>${JSON.stringify(error_details)}</small>`}
        </div>
      `}

      <p>
        <span class="status-dot" style=${{ background: led_service_running ? COLOUR_BIN_GREEN : COLOUR_ERROR }}></span>
        LED service: <strong>${led_service_running ? 'Running' : 'Stopped'}</strong>
      </p>
      <p>
        <span class="status-dot" style=${{ background: leds_active ? COLOUR_LEDS_ACTIVE : COLOUR_BIN_BLACK_BAG }}></span>
        LEDs: <strong>${leds_active ? 'Active' : 'Off'}</strong>
      </p>

      ${next_collection && html`
        <p>
          <span class="bin-dot" style=${{ background: binColour(next_collection.bin_type) }}></span>
          Next: <strong>${next_collection.bin_type}</strong> — ${next_collection.date}
          <span class="days-badge">
            ${next_collection.days_until > 1
              ? `${next_collection.days_until} days`
              : next_collection.hours_until != null && next_collection.hours_until < 1
              ? (next_collection.days_until === 0 ? 'Due now' : 'Tomorrow')
              : next_collection.hours_until != null
              ? `${next_collection.days_until === 1 ? 'Tomorrow' : 'Today'} (in ${next_collection.hours_until}h)`
              : next_collection.days_until === 0 ? 'Today' : 'Tomorrow'}
          </span>
        </p>
      `}
    </article>
  `;
}
```

with:

```js
function nextCollectionBadge(col) {
  return col.days_until > 1
    ? `${col.days_until} days`
    : col.hours_until != null && col.hours_until < 1
    ? (col.days_until === 0 ? 'Due now' : 'Tomorrow')
    : col.hours_until != null
    ? `${col.days_until === 1 ? 'Tomorrow' : 'Today'} (in ${col.hours_until}h)`
    : col.days_until === 0 ? 'Today' : 'Tomorrow';
}

function StatusCard({ status }) {
  if (!status) return html`<article aria-busy="true">Loading status...</article>`;

  const { led_service_running, has_error, error_details, next_collections, leds_active, last_scraped } = status;

  return html`
    <article>
      <header><strong>Service Status</strong></header>

      ${has_error && html`
        <div class="error-banner">
          <strong>Error state active</strong> — LEDs showing red.
          ${error_details && html` <br /><small>${JSON.stringify(error_details)}</small>`}
        </div>
      `}

      <p>
        <span class="status-dot" style=${{ background: led_service_running ? COLOUR_BIN_GREEN : COLOUR_ERROR }}></span>
        LED service: <strong>${led_service_running ? 'Running' : 'Stopped'}</strong>
      </p>
      <p>
        <span class="status-dot" style=${{ background: leds_active ? COLOUR_LEDS_ACTIVE : COLOUR_MUTED_DOT }}></span>
        LEDs: <strong>${leds_active ? 'Active' : 'Off'}</strong>
      </p>

      ${next_collections && next_collections.map(col => html`
        <p key=${col.bin_type}>
          <span class="bin-dot" style=${{ background: binColour(col.bin_type) }}></span>
          Next: <strong>${col.bin_type}</strong> — ${col.date}
          <span class="days-badge">${nextCollectionBadge(col)}</span>
        </p>
      `)}

      ${last_scraped && html`
        <p>
          <small style=${{ color: COLOUR_MUTED_DOT }}>
            Last scraped: ${new Date(last_scraped).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}
          </small>
        </p>
      `}
    </article>
  `;
}
```

- [ ] **Step 7: Update `UpcomingCollections`'s filter**

Replace:

```js
  const upcoming = schedule.collections
    .filter(c => c.bin_type !== 'Black Bag')
    .slice(0, 6);
```

with:

```js
  const upcoming = schedule.collections
    .filter(c => c.bin_type !== 'OUTDOOR FOOD CADDY')
    .slice(0, 6);
```

- [ ] **Step 8: Update the "Stop the LED service..." muted text colour reference**

Replace:

```js
      ${serviceRunning !== false && html`
        <small style=${{ color: COLOUR_BIN_BLACK_BAG }}>Stop the LED service to enable test controls</small>
      `}
```

with:

```js
      ${serviceRunning !== false && html`
        <small style=${{ color: COLOUR_MUTED_DOT }}>Stop the LED service to enable test controls</small>
      `}
```

- [ ] **Step 9: Update `ConfigPanel` to render the split LED strip from a colour array**

Replace:

```js
function ConfigPanel({ ledColour, ledBrightness, serviceRunning }) {
```

with:

```js
function ConfigPanel({ ledColours, ledBrightness, serviceRunning }) {
```

Replace the `led-strip` block:

```js
      <div class="led-strip">
        ${[0,1,2,3,4,5,6,7].map(i => {
          const isLit = ledColour !== null;
          return html`<div
            key=${i}
            class="led-square"
            style=${{
              backgroundColor: isLit ? ledColour : COLOUR_LED_OFF,
              opacity: isLit ? ledBrightness : 1,
              boxShadow: isLit ? `0 0 10px 3px ${ledColour}` : 'none',
            }}
          ></div>`;
        })}
      </div>
```

with:

```js
      <div class="led-strip">
        ${[0,1,2,3,4,5,6,7].map(i => {
          const isLit = ledColours.length > 0;
          const colour = ledColours.length === 2
            ? (i < 4 ? ledColours[0] : ledColours[1])
            : ledColours[0];
          return html`<div
            key=${i}
            class="led-square"
            style=${{
              backgroundColor: isLit ? colour : COLOUR_LED_OFF,
              opacity: isLit ? ledBrightness : 1,
              boxShadow: isLit ? `0 0 10px 3px ${colour}` : 'none',
            }}
          ></div>`;
        })}
      </div>
```

- [ ] **Step 10: Update `App()`'s call sites**

Replace:

```js
  const ledColour = status ? ledVisualiserColour(status, testColour) : null;

  return html`
    <main>
      <h1>Bin LED Reminder</h1>
      <${StatusCard} status=${status} />
      <${UpcomingCollections} schedule=${schedule} />
      <${ServiceControls}
        onAction=${fetchStatus}
        serviceRunning=${status?.led_service_running}
        onTestFlash=${handleTestFlash}
        ledBrightness=${config?.led_brightness ?? 0.1}
      />
      <${ConfigPanel}
        ledColour=${ledColour}
        ledBrightness=${config?.led_brightness ?? 0.1}
        serviceRunning=${status?.led_service_running}
      />
      <${LogViewer} />
    </main>
  `;
```

with:

```js
  const ledColours = status ? ledVisualiserColours(status, testColour) : [];

  return html`
    <main>
      <h1>Bin LED Reminder</h1>
      <${StatusCard} status=${status} />
      <${UpcomingCollections} schedule=${schedule} />
      <${ServiceControls}
        onAction=${fetchStatus}
        serviceRunning=${status?.led_service_running}
        onTestFlash=${handleTestFlash}
        ledBrightness=${config?.led_brightness ?? 0.1}
      />
      <${ConfigPanel}
        ledColours=${ledColours}
        ledBrightness=${config?.led_brightness ?? 0.1}
        serviceRunning=${status?.led_service_running}
      />
      <${LogViewer} />
    </main>
  `;
```

- [ ] **Step 11: Manually verify in a browser**

There is no JS test framework in this repo (consistent with existing conventions — the frontend has never had automated tests). Verify by running the dev server and checking in a browser:

```bash
cd bin-led-webui
LED_SERVICE_DIR=../bin-led-reminder python -m uvicorn main:app --reload
```

Open `http://localhost:8000`. With no `recycling_schedule.json` present yet, the page should load without console errors, "Upcoming Collections" should show "No upcoming collections found," and the status card should show no "Next" lines and no "Last scraped" line (since `last_scraped` is `null`).

Then manually write a test `bin-led-reminder/recycling_schedule.json` with two collections sharing tomorrow's date (`GARDEN WASTE BIN` and `RUBBISH BIN - 180L`) and a `metadata.last_updated`, refresh the page, and confirm: two "Next:" lines appear, the LED-strip visualiser in the Configuration section shows 4 green + 4 orange squares (only visible when `leds_active` is true — set the collection date to today or use the reminder window defaults so `_leds_active()` returns true), and a "Last scraped: ..." line appears. Delete the test file afterward (it's gitignored, so this doesn't need a git operation, just `rm bin-led-reminder/recycling_schedule.json` if you don't want to keep it locally).

- [ ] **Step 12: Commit**

```bash
git add bin-led-webui/static/consts.js bin-led-webui/static/app.js
git commit -m "feat: web UI frontend — new bin colours, next_collections list, split LED visualiser"
```

---

### Task 9: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by other tasks — do this last.

- [ ] **Step 1: Update `README.md`'s repository layout diagram**

Replace:

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

with:

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

- [ ] **Step 2: Update `README.md`'s LED colours table and Black Bag note**

Replace:

```markdown
## LED colours

| Colour | Meaning |
|---|---|
| 🟢 Green | Green or Brown Bin due tomorrow |
| 🔵 Blue | Blue Bin (recycling) due tomorrow |
| 🔴 Red | Error state — scrape failed or service fault |
| Off | No collection imminent |

Black Bag collections happen every week and are intentionally ignored — the
reminder is only for the bins that alternate.
```

with:

```markdown
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
```

- [ ] **Step 3: Update `README.md`'s installation instructions**

Replace:

```
cp config.example.json config.json
# Edit config.json and set your UPRN
nano config.json
```

with:

```
cp config.example.json config.json
# Edit config.json if you need to override any defaults
nano config.json
```

- [ ] **Step 4: Update `README.md`'s Configuration section**

Replace:

```markdown
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
```

with:

```markdown
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
```

- [ ] **Step 5: Update `README.md`'s Web UI API table**

Replace:

```markdown
| `GET` | `/api/status` | LED service state, error state, next collection, LEDs active |
```

with:

```markdown
| `GET` | `/api/status` | LED service state, error state, next collections due, LEDs active, last scraped timestamp |
```

Replace:

```markdown
| `GET` | `/api/config` | Current config (UPRN and base\_url omitted) |
```

with:

```markdown
| `GET` | `/api/config` | Current config (base\_url omitted) |
```

- [ ] **Step 6: Update `README.md`'s Data source section**

Replace:

```markdown
## Data source

East Cambridgeshire District Council bin collection schedule, scraped directly
from their self-service portal. Schedule data is cached in
`recycling_schedule.json` (gitignored) and refreshed every two weeks.
```

with:

```markdown
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
```

- [ ] **Step 7: Update `CLAUDE.md`'s repository layout**

Replace:

```
bin-led-reminder/          ← repo root
├── .gitignore
├── README.md
├── CLAUDE.md              ← this file
│
├── bin-led-reminder/      ← core LED service
│   ├── bin_led_service.py
│   ├── constants.py       ← LED colour definitions (single source of truth)
│   ├── bin-led-reminder.service
│   ├── config.example.json
│   ├── config.json        ← gitignored (contains UPRN)
│   ├── requirements.txt
│   ├── install.sh
│   ├── manage.sh
│   └── tests/
│       ├── test_leds.py   ← Pi hardware test (requires blinkt)
│       └── test_colours.py ← unit tests (runs on any machine, mocks blinkt)
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

with:

```
bin-led-reminder/          ← repo root
├── .gitignore
├── README.md
├── CLAUDE.md              ← this file
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
└── bin-led-scraper/       ← weekly GitHub Actions scraper (headless browser)
    ├── scrape_bins.py
    ├── requirements.txt
    └── data/
        └── recycling_schedule.json   ← committed output, fetched by the Pi
```

(`config.json` no longer contains a UPRN — see the config table update in Step 11.)

- [ ] **Step 8: Update `CLAUDE.md`'s LED colour logic table**

Replace:

```markdown
## LED colour logic

| Colour | Trigger |
|---|---|
| Green | Green or Brown Bin due |
| Blue | Blue Bin (recycling) due |
| Red | Error state (scrape failed, service fault) |
| Off | No collection imminent |

Black Bag collections are intentionally ignored — they happen every week and
don't need a reminder. See `recycling_schedule.json` for bin type strings.
```

with:

```markdown
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
```

Also update the paragraph immediately below the table that currently reads:

```markdown
When both a Blue Bin and a Green/Brown Bin fall on the same week, `bins_due[0]`
determines the LED colour (Blue takes priority as it appears first in the
council's schedule output).
```

Remove this paragraph entirely — it's superseded by the "Same-date split display" note above (this was the exact tech-debt item this migration fixes).

- [ ] **Step 9: Update `CLAUDE.md`'s Colour constants section**

In the "When adding a new colour or bin type mapping, update **all three** of" list, no structural change is needed (still 3 files), but update the sample bin-type mapping guidance to reflect the current keys are the new taxonomy strings — this is just making sure no stale example strings remain. Search `CLAUDE.md` for `Blue Bin`, `Green or Brown Bin`, and `Black Bag` and replace every remaining occurrence with the new equivalents (`RECYCLING BIN - 240L`, `GARDEN WASTE BIN`/`RUBBISH BIN - 180L`, `OUTDOOR FOOD CADDY`) or remove the reference if it was describing old-system-specific behaviour that no longer applies.

Run: `grep -n "Blue Bin\|Green or Brown\|Black Bag" CLAUDE.md`
Expected after edits: no output.

- [ ] **Step 10: Update `CLAUDE.md`'s Data source section**

Replace:

```markdown
## Data source

The council website is scraped by UPRN (Unique Property Reference Number). The
scraper targets `.collectionsrow` elements, skipping any row containing an
iframe (the address selector). If the council redesigns their page,
`scrape_collections()` in `bin_led_service.py` will need updating.
```

with:

```markdown
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
```

- [ ] **Step 11: Update `CLAUDE.md`'s Service architecture diagram and config table**

Replace:

```markdown
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
```

with:

```markdown
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
```

Then find `CLAUDE.md`'s config table (in the "Config path resolution" / config
documentation area — search for `reminder_start_hours_before` to locate it if
it's not immediately adjacent to the Service architecture section) and remove
its `uprn` row, updating `base_url`'s description to "Where the pre-scraped
schedule JSON is fetched from" and `update_interval_weeks`'s default to `1`,
matching the README.md Configuration table update from Step 4.

- [ ] **Step 12: Move the resolved tech-debt item out of Known issues**

In `CLAUDE.md`'s "Known issues / tech debt" section, remove the bullet:

```markdown
- 🟢 **No mixed-colour indication** — when both Blue and Green bins are due on
  the same collection date only `bins_due[0]` drives the LED colour. In practice
  the council alternates them weekly so this hasn't occurred, but it's not
  handled. Could pulse/alternate LEDs instead.
```

This is resolved by Task 3's split-pixel display — no replacement bullet needed.

- [ ] **Step 13: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: update README and CLAUDE.md for the AchieveForms migration"
```

---

## Self-Review Notes

- **Spec coverage:** every section of the spec (background/architecture, `bin-led-scraper/`, Pi-side changes, colour mapping, web UI, config, tests, docs) maps to a task above (Tasks 1–3 = colours/split-display, Task 4 = Pi-side fetch, Tasks 5–6 = scraper + CI, Tasks 7–8 = web UI, Task 9 = docs).
- **Type/name consistency checked:** `fetch_schedule_data()` (Task 4) is the exact name used consistently; `save_data(data)` signature change is consistent between Task 4's implementation and its two call sites (`run_service()`, tests). `next_collections` (plural) is used consistently across Task 7 (backend) and Task 8 (frontend) — no leftover singular `next_collection` references. `COLOUR_MUTED_DOT` replaces every `COLOUR_BIN_BLACK_BAG` reference in both `consts.js` and `app.js` (Task 8, Steps 1–4 and 8 cover all three usage sites found via `grep`).
- **No placeholders:** every step includes complete, runnable code — no "add error handling" or "similar to Task N" shortcuts.
