"""
Colour constants and LED display logic tests.
Run with: python -m pytest tests/test_colours.py -v

Mocks blinkt so the suite runs on any machine, not just the Pi.
"""

import logging
import pathlib
import sys
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, call, patch

# Mock blinkt before any service import — it is Pi-only hardware
_blinkt = MagicMock()
sys.modules['blinkt'] = _blinkt

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from constants import (
    BIN_COLOURS,
    COLOUR_BLUE,
    COLOUR_CYAN,
    COLOUR_ERROR,
    COLOUR_GREEN,
    COLOUR_ORANGE,
    COLOUR_PINK,
    COLOUR_PURPLE,
    COLOUR_RED,
    COLOUR_WHITE,
    COLOUR_YELLOW,
)

# ── Palette validation ─────────────────────────────────────────────────────────

FULL_PALETTE = {
    'COLOUR_RED':    COLOUR_RED,
    'COLOUR_GREEN':  COLOUR_GREEN,
    'COLOUR_BLUE':   COLOUR_BLUE,
    'COLOUR_WHITE':  COLOUR_WHITE,
    'COLOUR_ORANGE': COLOUR_ORANGE,
    'COLOUR_PURPLE': COLOUR_PURPLE,
    'COLOUR_PINK':   COLOUR_PINK,
    'COLOUR_CYAN':   COLOUR_CYAN,
    'COLOUR_YELLOW': COLOUR_YELLOW,
}


def test_all_palette_colours_are_valid_rgb_tuples():
    for name, colour in FULL_PALETTE.items():
        assert isinstance(colour, tuple), f"{name} is not a tuple"
        assert len(colour) == 3, f"{name} does not have 3 components"
        for i, v in enumerate(colour):
            assert isinstance(v, int), f"{name}[{i}] is not an int"
            assert 0 <= v <= 255, f"{name}[{i}]={v} is out of 0–255 range"


def test_colour_error_is_red():
    assert COLOUR_ERROR == COLOUR_RED


# ── BIN_COLOURS mapping ────────────────────────────────────────────────────────

def test_bin_colours_recycling_maps_to_blue():
    assert BIN_COLOURS['RECYCLING BIN - 240L'] == COLOUR_BLUE


def test_bin_colours_garden_waste_maps_to_green():
    assert BIN_COLOURS['GARDEN WASTE BIN'] == COLOUR_GREEN


def test_bin_colours_rubbish_maps_to_orange():
    assert BIN_COLOURS['RUBBISH BIN - 180L'] == COLOUR_ORANGE


def test_food_caddy_absent_from_bin_colours():
    # Outdoor Food Caddy is filtered before lookup and must never drive the LEDs
    assert 'OUTDOOR FOOD CADDY' not in BIN_COLOURS


def test_unknown_bin_type_returns_none():
    assert BIN_COLOURS.get('Mystery Bin') is None


# ── LED display logic ──────────────────────────────────────────────────────────
# These tests exercise the dict-lookup path in update_led_display().
# datetime.now() is patched to a fixed time so the reminder window is
# always active regardless of when the tests run.

_FIXED_NOW = datetime(2026, 4, 18, 14, 0, 0)  # 2pm — well inside the window
_COLLECTION_DATE = _FIXED_NOW.date() + timedelta(days=1)  # tomorrow


def _make_service():
    """Construct a BinLEDService bypassing file I/O."""
    from bin_led_service import BinLEDService
    service = BinLEDService.__new__(BinLEDService)
    service.config = {
        'led_brightness': 0.1,
        'reminder_start_hours_before': 24,
        'reminder_end_hours_after': 1,
    }
    service.error_file = pathlib.Path('/tmp/_test_error_state.json')
    service.error_file.unlink(missing_ok=True)
    service.logger = logging.getLogger('test')
    return service


def _run_display(bin_type):
    """Run update_led_display() with a fixed schedule and patched time."""
    _blinkt.reset_mock()
    service = _make_service()
    schedule = {'collection_date': _COLLECTION_DATE, 'bins_due': [bin_type]}
    with patch.object(service, 'detect_collection_schedule', return_value=schedule):
        with patch('bin_led_service.datetime') as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            service.update_led_display()
    return service


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


def test_unknown_bin_sets_error_leds(caplog):
    with caplog.at_level(logging.ERROR):
        _run_display('Mystery Bin')
    _blinkt.set_all.assert_called_once_with(*COLOUR_ERROR, 0.1)
    _blinkt.show.assert_called()
    assert 'Mystery Bin' in caplog.text


def test_detect_schedule_skips_food_caddy_when_finding_next_date():
    """Food Caddy on day N must not anchor the reminder window away from day N+1."""
    service = _make_service()
    today = _FIXED_NOW.date()
    real_bin_date = today + timedelta(days=1)
    mock_data = {
        'collections': [
            {'date_parsed': today.isoformat(), 'bin_type': 'OUTDOOR FOOD CADDY'},
            {'date_parsed': real_bin_date.isoformat(), 'bin_type': 'GARDEN WASTE BIN'},
        ]
    }
    with patch.object(service, 'load_data', return_value=mock_data):
        with patch('bin_led_service.datetime') as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            result = service.detect_collection_schedule()
    assert result is not None
    assert result['collection_date'] == real_bin_date
    assert result['bins_due'] == ['GARDEN WASTE BIN']


def test_detect_schedule_food_caddy_only_returns_none():
    """If only Outdoor Food Caddy collections remain, no reminder should fire."""
    service = _make_service()
    today = _FIXED_NOW.date()
    mock_data = {
        'collections': [
            {'date_parsed': today.isoformat(), 'bin_type': 'OUTDOOR FOOD CADDY'},
        ]
    }
    with patch.object(service, 'load_data', return_value=mock_data):
        with patch('bin_led_service.datetime') as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW
            mock_dt.fromisoformat = datetime.fromisoformat
            result = service.detect_collection_schedule()
    assert result is None


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


def test_leds_off_outside_reminder_window():
    """When now is outside the reminder window, LEDs should be cleared."""
    _blinkt.reset_mock()
    service = _make_service()
    # Collection was two days ago — outside any window
    past_date = _FIXED_NOW.date() - timedelta(days=2)
    schedule = {'collection_date': past_date, 'bins_due': ['RECYCLING BIN - 240L']}
    with patch.object(service, 'detect_collection_schedule', return_value=schedule):
        with patch('bin_led_service.datetime') as mock_dt:
            mock_dt.now.return_value = _FIXED_NOW
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            service.update_led_display()
    _blinkt.clear.assert_called()
    _blinkt.show.assert_called()
