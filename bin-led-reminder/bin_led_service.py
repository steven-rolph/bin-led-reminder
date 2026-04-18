#!/usr/bin/env python3
"""
Bin Collection LED Reminder Service
Smart visual reminder for bin collection days using Blinkt! LEDs
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
import logging
import blinkt

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
            "uprn": "10095400001",
            "base_url": "https://self.eastcambs.gov.uk/appshost/firmstep/self/apps/custompage/bincollections",
            "update_interval_weeks": 2,
            "check_interval_hours": 1,
            "led_brightness": 0.1,
            "log_level": "INFO"
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

    def get_url(self):
        """Build the scraping URL"""
        return f"{self.config['base_url']}?language=en&uprn={self.config['uprn']}"

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

    def parse_date(self, date_str):
        """Parse date string into datetime object"""
        try:
            # Handle format like "Wed - 23 Jul 2025"
            date_part = date_str.split(' - ')[1] if ' - ' in date_str else date_str
            return datetime.strptime(date_part, "%d %b %Y")
        except (ValueError, IndexError) as e:
            self.logger.warning(f"Could not parse date '{date_str}': {e}")
            return None

    def scrape_collections(self):
        """Scrape bin collection data from the website"""
        self.logger.info("Fetching collection data...")

        try:
            response = self.fetch_data()
            soup = BeautifulSoup(response.content, 'html.parser')

            bins_data = []
            collection_rows = soup.select('.collectionsrow')

            # Skip the first row if it's the address selector (has iframe)
            collection_rows = [row for row in collection_rows if not row.find('iframe')]

            for row in collection_rows:
                bin_type_elem = row.select_one('.col-sm-4, .col-xs-4')
                date_elem = row.select_one('.col-sm-6, .col-xs-6')

                if bin_type_elem and date_elem:
                    bin_type = bin_type_elem.text.strip()
                    date_str = date_elem.text.strip()
                    date_obj = self.parse_date(date_str)

                    if date_obj:
                        bins_data.append({
                            'date': date_str,
                            'date_parsed': date_obj.isoformat(),
                            'bin_type': bin_type,
                            'day_of_week': date_obj.strftime('%A'),
                        })

            if not bins_data:
                raise Exception("No collection data found")

            # Sort by date
            bins_data.sort(key=lambda x: x['date_parsed'])

            self.logger.info(f"Successfully scraped {len(bins_data)} collection entries")
            return bins_data

        except Exception as e:
            self.logger.error(f"Error scraping data: {e}")
            raise

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

        last_updated = datetime.fromisoformat(data['metadata']['last_updated'])
        weeks_since_update = (datetime.now() - last_updated).days / 7

        return weeks_since_update >= self.config['update_interval_weeks']

    def get_next_collection(self):
        """Get the next collection from saved data"""
        data = self.load_data()
        if not data:
            return None

        today = datetime.now().date()

        for collection in data['collections']:
            collection_date = datetime.fromisoformat(collection['date_parsed']).date()
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
            collection_date = datetime.fromisoformat(collection['date_parsed']).date()
            if collection_date >= today:
                next_date = collection_date
                break

        if not next_date:
            return []

        # Return all collections on that exact date
        return [
            c for c in data['collections']
            if datetime.fromisoformat(c['date_parsed']).date() == next_date
        ]

    def detect_collection_schedule(self):
        """
        Detect the next collection date and which bins are due.
        Returns dict with collection_date (datetime.date) and bins_due.
        """
        next_collection = self.get_next_collection()
        if not next_collection:
            return None

        this_week = self.get_this_weeks_collections()

        collection_date = datetime.fromisoformat(next_collection['date_parsed']).date()

        # Get bin types for this week (excluding Black Bag)
        bins_due = []
        for collection in this_week:
            bin_type = collection['bin_type']
            if "Black Bag" not in bin_type:
                bins_due.append(bin_type)

        return {
            'collection_date': collection_date,
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

        # Set all LEDs to red
        blinkt.set_all(255, 0, 0, self.config['led_brightness'])
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

        # Reminder window: midnight the day before collection → 01:00 on collection day
        collection_dt = datetime.combine(schedule['collection_date'], datetime.min.time())
        reminder_start = collection_dt - timedelta(days=1)
        reminder_end = collection_dt + timedelta(hours=1)
        should_display = reminder_start <= now < reminder_end
        
        if should_display:
            bins_due = schedule['bins_due']
            
            if bins_due:
                self.logger.info(f"Reminder active! Bins due: {bins_due}")
                
                # Determine LED color based on bin type
                primary_bin = bins_due[0]
                
                if "Blue" in primary_bin:
                    blinkt.set_all(0, 0, 255, self.config['led_brightness'])
                elif "Green" in primary_bin or "Brown" in primary_bin:
                    blinkt.set_all(0, 255, 0, self.config['led_brightness'])
                else:
                    self.logger.warning(f"Unrecognised bin type '{primary_bin}' — clearing LEDs")
                    blinkt.clear()

                blinkt.show()
                self.logger.info(f"LEDs set for {primary_bin}")
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
                    self.logger.info("Data update needed - scraping new data")
                    bins_data = self.scrape_collections()
                    self.save_data(bins_data)
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
