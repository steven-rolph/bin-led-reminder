#!/usr/bin/env python3
"""
Bin Collection LED Reminder Service
Smart visual reminder for bin collection days using Blinkt! LEDs
"""

import requests
import json
import time
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
import logging
import blinkt
from constants import BIN_COLOURS, COLOUR_ERROR

class BinLEDService:
    def __init__(self, config_file="config.json"):
        self.config = self.load_config(config_file)
        self.data_file = Path("recycling_schedule.json")
        self.error_file = Path("error_state.json")
        self.setup_logging()
        self.running = False

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

    def load_config(self, config_file):
        """Load configuration from JSON file"""
        default_config = {
            "base_url": "https://raw.githubusercontent.com/steven-rolph/bin-led-reminder/main/bin-led-scraper/data/recycling_schedule.json",
            "update_interval_weeks": 1,
            "check_interval_hours": 1,
            "led_brightness": 0.1,
            "log_level": "INFO",
            "reminder_start_hours_before": 24,
            "reminder_end_hours_after": 1,
        }
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            return default_config
        except json.JSONDecodeError as e:
            print(f"config.json is malformed ({e}) — falling back to defaults", file=sys.stderr)
            return default_config

    def setup_logging(self):
        """Set up logging configuration"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        level_name = self.config.get("log_level", "INFO").upper()
        log_level = getattr(logging, level_name, None)
        if log_level is None:
            log_level = logging.INFO
            print(f"Unrecognised log_level '{level_name}' in config — defaulting to INFO", file=sys.stderr)

        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "bin_led_service.log"),
                logging.StreamHandler()
            ]
        )

        self.logger = logging.getLogger(__name__)

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

    def save_data(self, data):
        """Persist fetched schedule data to disk, preserving its own metadata
        (in particular metadata.last_updated, which is set by the external
        scraper and drives the staleness indicator — see
        docs/superpowers/specs/2026-07-25-council-endpoint-migration-design.md)."""
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        self.logger.info(f"Data saved to {self.data_file}")

    def load_data(self):
        """Load existing collection data"""
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.warning("No existing data file found")
            return None
        except json.JSONDecodeError:
            self.logger.error("recycling_schedule.json is corrupt — will re-scrape")
            return None

    def should_update_data(self):
        """Check if data needs updating (every 2 weeks)"""
        data = self.load_data()
        if not data:
            return True

        try:
            last_updated = datetime.fromisoformat(data['metadata']['last_updated'])
        except ValueError:
            return True
        weeks_since_update = (datetime.now() - last_updated).days / 7

        return weeks_since_update >= self.config['update_interval_weeks']

    def get_next_collection(self):
        """Get the next collection from saved data"""
        data = self.load_data()
        if not data:
            return None

        today = datetime.now().date()

        for collection in data['collections']:
            try:
                collection_date = datetime.fromisoformat(collection['date_parsed']).date()
            except ValueError:
                continue
            if collection_date >= today:
                return collection

        return None

    def get_this_weeks_collections(self):
        """Get all collections for the next upcoming collection date"""
        data = self.load_data()
        if not data:
            return []

        today = datetime.now().date()

        # Find the next collection date
        next_date = None
        for collection in data['collections']:
            try:
                collection_date = datetime.fromisoformat(collection['date_parsed']).date()
            except ValueError:
                continue
            if collection_date >= today:
                next_date = collection_date
                break

        if not next_date:
            return []

        # Return all collections on that exact date
        result = []
        for c in data['collections']:
            try:
                if datetime.fromisoformat(c['date_parsed']).date() == next_date:
                    result.append(c)
            except ValueError:
                continue
        return result

    def detect_collection_schedule(self):
        """
        Detect the next collection date and which bins are due.
        Returns dict with collection_date (datetime.date) and bins_due.
        """
        data = self.load_data()
        if not data:
            return None

        today = datetime.now().date()

        # Find the next date that has at least one non-Food-Caddy collection.
        # Iterating the sorted schedule and skipping Food Caddy entries means
        # a Food-Caddy-only day (it's collected every week) never incorrectly
        # anchors the reminder window.
        next_date = None
        for collection in data['collections']:
            try:
                collection_date = datetime.fromisoformat(collection['date_parsed']).date()
            except ValueError:
                continue
            if collection_date >= today and "OUTDOOR FOOD CADDY" not in collection['bin_type']:
                next_date = collection_date
                break

        if not next_date:
            return None

        bins_due = []
        for collection in data['collections']:
            try:
                if datetime.fromisoformat(collection['date_parsed']).date() == next_date:
                    bin_type = collection['bin_type']
                    if "OUTDOOR FOOD CADDY" not in bin_type:
                        bins_due.append(bin_type)
            except ValueError:
                continue

        return {
            'collection_date': next_date,
            'bins_due': list(dict.fromkeys(bins_due)),  # Deduplicate, preserving order
        }

    def set_error_state(self, error_type, error_message):
        """Set error state and display red LEDs"""
        error_data = {
            'has_error': True,
            'error_type': error_type,
            'error_message': error_message,
            'error_timestamp': datetime.now().isoformat()
        }

        with open(self.error_file, 'w') as f:
            json.dump(error_data, f, indent=2)

        self.logger.error(f"Error state set: {error_type} - {error_message}")

        # Set all LEDs to error colour
        blinkt.set_all(*COLOUR_ERROR, self.config['led_brightness'])
        blinkt.show()

    def clear_error_state(self):
        """Clear error state"""
        if self.error_file.exists():
            self.error_file.unlink()
        self.logger.info("Error state cleared")

    def has_error(self):
        """Check if system is in error state"""
        return self.error_file.exists()

    def update_led_display(self):
        """Update LED display based on current schedule"""
        if self.has_error():
            return  # Keep error LEDs on

        schedule = self.detect_collection_schedule()
        if not schedule:
            self.logger.warning("No collection schedule found")
            blinkt.clear()
            blinkt.show()
            return

        now = datetime.now()

        # Reminder window: configurable hours before midnight of collection day → configurable hours after
        collection_dt = datetime.combine(schedule['collection_date'], datetime.min.time())
        reminder_start = collection_dt - timedelta(hours=self.config.get('reminder_start_hours_before', 24))
        reminder_end = collection_dt + timedelta(hours=self.config.get('reminder_end_hours_after', 1))
        should_display = reminder_start <= now < reminder_end
        
        if should_display:
            bins_due = schedule['bins_due']
            
            if bins_due:
                self.logger.info(f"Reminder active! Bins due: {bins_due}")

                # Fixed priority order keeps the split stable across runs,
                # independent of scrape/list order.
                priority_order = ['GARDEN WASTE BIN', 'RUBBISH BIN - 180L', 'RECYCLING BIN - 240L']
                ordered_bins = [b for b in priority_order if b in bins_due]
                # Any bin type not in the known priority list (unrecognised)
                # still needs to be checked for the error path below.
                ordered_bins += [b for b in bins_due if b not in priority_order]

                if len(ordered_bins) > 2:
                    dropped = ordered_bins[2:]
                    self.logger.warning(f"More than two bins due — dropped {dropped} from LED display")
                    ordered_bins = ordered_bins[:2]

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
        else:
            blinkt.clear()
            blinkt.show()

    def run_service(self):
        """Main service loop"""
        self.running = True
        self.logger.info("Bin LED Service starting...")

        # Clear LEDs on startup
        blinkt.clear()
        blinkt.show()

        while self.running:
            try:
                # Check if data update is needed
                if self.should_update_data():
                    self.logger.info("Data update needed - fetching new schedule")
                    data = self.fetch_schedule_data()
                    self.save_data(data)
                    self.clear_error_state()  # Clear any previous errors

                # Update LED display
                self.update_led_display()

                # Sleep for configured interval
                sleep_seconds = self.config['check_interval_hours'] * 3600
                self.logger.debug(f"Sleeping for {sleep_seconds} seconds")
                time.sleep(sleep_seconds)

            except Exception as e:
                self.logger.error(f"Service error: {e}")
                self.set_error_state("service_error", str(e))

                # Sleep shorter interval in error state
                time.sleep(300)  # 5 minutes

    def shutdown(self, signum, frame):
        """Graceful shutdown handler"""
        self.logger.info("Shutdown signal received")
        self.running = False

        # Clear LEDs on shutdown
        blinkt.clear()
        blinkt.show()
        sys.exit(0)

def main():
    """Main entry point"""
    service = BinLEDService()

    try:
        service.run_service()
    except KeyboardInterrupt:
        service.logger.info("Service interrupted by user")
    finally:
        # Clean up LEDs
        blinkt.clear()
        blinkt.show()

if __name__ == "__main__":
    main()
