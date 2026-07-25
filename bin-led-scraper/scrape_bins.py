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

The form itself is rendered inside an iframe (`<iframe class="achieveforms-iframe">`,
populated client-side after the outer page loads) rather than directly on the
page — field lookups must be scoped to that frame, not the top-level page.

NOTE: selecting an address does not itself trigger the schedule lookup — a
"Find collection dates" button appears once an address is selected and must
be clicked to fire the runLookup request. If this script starts timing out
waiting for that response, check with a real browser + DevTools open whether
the button's accessible name/role has changed.
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

        # The form fields live inside an iframe (id="fillform-frame-1",
        # class="achieveforms-iframe") populated by JS after the outer page
        # loads — get_by_label on `page` directly never finds them.
        form = page.frame_locator("iframe.achieveforms-iframe")

        postcode_field = form.get_by_label("Please enter your postcode or street name")
        postcode_field.fill(postcode)
        postcode_field.press("Enter")

        address_field = form.get_by_label("Select your address")
        address_field.wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            "(el) => el.options && el.options.length > 1",
            arg=address_field.element_handle(),
            timeout=15000,
        )
        address_field.select_option(value=uprn)

        # Selecting the address does not itself trigger the schedule lookup —
        # a "Find collection dates" button appears once an address is picked
        # and must be clicked to fire the runLookup request.
        with page.expect_response(
            lambda r: "apibroker/runLookup" in r.url and "ScheduledStart" in r.text()
        ) as response_info:
            form.get_by_role("button", name="Find collection dates").click()

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
