#!/usr/bin/env python3
"""
Amtrak Auto Train Status Tracker
Pulls scheduled vs actual times for Train 53 (LOR → SFA) and Train 52 (SFA → LOR) daily.

Usage:
    python amtrak_status.py                   # Fetch current train status from real-time API
    python amtrak_status.py --date 2026-02-10 # Only record if matching the given date

Data is appended to auto_train_status.csv in the script directory.
Run via cron or scheduled task to accumulate historical data over time.
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(SCRIPT_DIR, "auto_train_status.csv")

TRAIN_CONFIG = {
    53: {"route": "LOR → SFA", "stations": ["LOR", "SFA"]},
    52: {"route": "SFA → LOR", "stations": ["SFA", "LOR"]},
}

CSV_HEADERS = [
    "date",
    "train_num",
    "station",
    "scheduled_arrival",
    "actual_arrival",
    "arrival_delay_mins",
    "scheduled_departure",
    "actual_departure",
    "departure_delay_mins",
    "status",
    "source",
]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def init_csv():
    """Create CSV with headers if it doesn't exist."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()


def date_already_recorded(date_str, station, train_num):
    """Check if a date+station+train combo is already in the CSV."""
    if not os.path.exists(CSV_FILE):
        return False
    with open(CSV_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["date"] == date_str and row["station"] == station and str(row["train_num"]) == str(train_num):
                return True
    return False


def append_rows(rows):
    """Append rows to the CSV file."""
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        for row in rows:
            writer.writerow(row)


def parse_delay_minutes(scheduled, actual):
    """Calculate delay in minutes between two ISO datetime strings."""
    if not scheduled or not actual:
        return None
    try:
        sch = datetime.fromisoformat(scheduled)
        act = datetime.fromisoformat(actual)
        # Strip timezone info if only one has it
        if sch.tzinfo and not act.tzinfo:
            sch = sch.replace(tzinfo=None)
        elif act.tzinfo and not sch.tzinfo:
            act = act.replace(tzinfo=None)
        delta = (act - sch).total_seconds() / 60
        return round(delta)
    except Exception:
        return None


def fetch_realtime(train_num, stations):
    """Fetch current train status from Amtraker v3 API.

    Returns a list of row dicts, or an empty list if the train isn't active.
    """
    url = f"https://api-v3.amtraker.com/v3/trains/{train_num}"
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Real-time API error for Train {train_num}: {e}")
        return []

    # The API returns a dict keyed by train number, value is a list of train instances
    trains = data if isinstance(data, list) else data.get(str(train_num), [])
    if not trains:
        print(f"  Train {train_num} is not currently active.")
        return []

    # Determine the origin station (first station in the route) for deriving service date
    origin_station = stations[0]

    rows = []
    for train in trains:
        train_stations = train.get("stations", [])
        train_date = None

        for stn in train_stations:
            code = stn.get("code", "")
            if code not in stations:
                continue

            sch_arr = stn.get("schArr", "")
            sch_dep = stn.get("schDep", "")
            act_arr = stn.get("arr", "")
            act_dep = stn.get("dep", "")

            # Derive service date from scheduled departure at origin station
            if code == origin_station and sch_dep:
                try:
                    train_date = datetime.fromisoformat(sch_dep).strftime("%Y-%m-%d")
                except Exception:
                    train_date = datetime.now().strftime("%Y-%m-%d")

            if not train_date:
                train_date = datetime.now().strftime("%Y-%m-%d")

            rows.append({
                "date": train_date,
                "train_num": train_num,
                "station": code,
                "scheduled_arrival": sch_arr or "",
                "actual_arrival": act_arr or "",
                "arrival_delay_mins": parse_delay_minutes(sch_arr, act_arr) if sch_arr and act_arr else "",
                "scheduled_departure": sch_dep or "",
                "actual_departure": act_dep or "",
                "departure_delay_mins": parse_delay_minutes(sch_dep, act_dep) if sch_dep and act_dep else "",
                "status": stn.get("status", ""),
                "source": "amtraker_v3",
            })

    return rows


def run(target_date=None):
    """Fetch current train status for all trains from the real-time API.

    If target_date is specified, only records matching that date are saved.
    """
    for train_num, config in TRAIN_CONFIG.items():
        stations = config["stations"]
        route = config["route"]
        print(f"\nFetching status for Train {train_num} ({route})")

        rows = fetch_realtime(train_num, stations)
        if not rows:
            print("  No active train data available.")
            continue

        # Filter to target date if specified
        if target_date:
            rows = [r for r in rows if r["date"] == target_date]
            if not rows:
                print(f"  No data matching date {target_date}.")
                continue

        # Deduplicate against existing CSV
        new_rows = [r for r in rows if not date_already_recorded(r["date"], r["station"], train_num)]
        if not new_rows:
            print("  Data already recorded.")
            continue

        append_rows(new_rows)
        dates = sorted(set(r["date"] for r in new_rows))
        print(f"  Added {len(new_rows)} records for date(s): {', '.join(dates)}")


def main():
    parser = argparse.ArgumentParser(
        description="Track Amtrak Auto Train status (Train 52 & 53)"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Only save data matching this date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    init_csv()
    run(args.date)


if __name__ == "__main__":
    main()
