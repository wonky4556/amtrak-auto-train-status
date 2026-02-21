#!/usr/bin/env python3
"""
Amtrak Auto Train Status Tracker
Pulls scheduled vs actual times for Train 53 (LOR → SFA) and Train 52 (SFA → LOR) daily.

Usage:
    python amtrak_status.py --backfill       # Fetch past 7 days from ASMAD (both trains)
    python amtrak_status.py                  # Fetch today's status (real-time API + ASMAD fallback)
    python amtrak_status.py --date 2026-02-10  # Fetch a specific date

Data is appended to auto_train_status.csv in the script directory.
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

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

ASMAD_URL = "https://juckins.net/amtrak_status/archive/html/history.php"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
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
        fmt_options = ["%Y-%m-%dT%H:%M:%S%z", "%m/%d/%Y %H:%M"]
        sch = act = None
        for fmt in fmt_options:
            try:
                sch = datetime.strptime(scheduled, fmt)
                break
            except ValueError:
                continue
        for fmt in fmt_options:
            try:
                act = datetime.strptime(actual, fmt)
                break
            except ValueError:
                continue
        if sch and act:
            # Strip timezone info if only one has it
            if sch.tzinfo and not act.tzinfo:
                sch = sch.replace(tzinfo=None)
            elif act.tzinfo and not sch.tzinfo:
                act = act.replace(tzinfo=None)
            delta = (act - sch).total_seconds() / 60
            return round(delta)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Real-time source: Amtraker v3 API
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Historical source: ASMAD (juckins.net)
# ---------------------------------------------------------------------------

def fetch_asmad(start_date, end_date, train_num, stations):
    """Scrape ASMAD for train status between start_date and end_date.

    Dates should be datetime.date objects.
    Returns a list of row dicts.
    """
    params = {
        "train_num": train_num,
        "station": "",  # all stations, we filter client-side
        "date_start": start_date.strftime("%m/%d/%Y"),
        "date_end": end_date.strftime("%m/%d/%Y"),
        "df1": 1, "df2": 1, "df3": 1, "df4": 1,
        "df5": 1, "df6": 1, "df7": 1,
        "sort": "schDp",
        "sort_dir": "ASC",
        "co": "gt",
        "limit_mins": "",
        "dfon": 1,
    }

    try:
        resp = requests.get(ASMAD_URL, params=params, headers=HTTP_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ASMAD request error for Train {train_num}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the data table — it's the main table with train status rows
    tables = soup.find_all("table")
    if not tables:
        print(f"  No tables found in ASMAD response for Train {train_num}.")
        return []

    # The data table typically has headers like: Train, Origin Date, Station, ...
    data_table = None
    for table in tables:
        header_row = table.find("tr")
        if header_row:
            headers_text = header_row.get_text().lower()
            if "station" in headers_text and ("origin" in headers_text or "train" in headers_text):
                data_table = table
                break

    if not data_table:
        print(f"  Could not find data table in ASMAD response for Train {train_num}.")
        return []

    # Parse header positions
    header_row = data_table.find("tr")
    headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

    def col_index(keywords):
        for i, h in enumerate(headers):
            if all(k in h for k in keywords):
                return i
        return None

    idx_station = col_index(["station"])
    idx_origin_date = col_index(["origin"]) or col_index(["date"])
    idx_sch_arr = col_index(["sch", "ar"])
    idx_act_arr = col_index(["act", "ar"])
    idx_sch_dep = col_index(["sch", "dp"]) or col_index(["sch", "dep"])
    idx_act_dep = col_index(["act", "dp"]) or col_index(["act", "dep"])
    idx_comments = col_index(["comment"]) or col_index(["status"])

    rows = []
    data_rows = data_table.find_all("tr")[1:]  # skip header
    for tr in data_rows:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue

        station = cells[idx_station] if idx_station is not None and idx_station < len(cells) else ""
        if station not in stations:
            continue

        origin_date_raw = cells[idx_origin_date] if idx_origin_date is not None and idx_origin_date < len(cells) else ""
        sch_arr = cells[idx_sch_arr] if idx_sch_arr is not None and idx_sch_arr < len(cells) else ""
        act_arr = cells[idx_act_arr] if idx_act_arr is not None and idx_act_arr < len(cells) else ""
        sch_dep = cells[idx_sch_dep] if idx_sch_dep is not None and idx_sch_dep < len(cells) else ""
        act_dep = cells[idx_act_dep] if idx_act_dep is not None and idx_act_dep < len(cells) else ""
        comments = cells[idx_comments] if idx_comments is not None and idx_comments < len(cells) else ""

        # Normalize the origin date to YYYY-MM-DD
        service_date = ""
        for fmt in ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"]:
            try:
                service_date = datetime.strptime(origin_date_raw, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

        if not service_date:
            service_date = origin_date_raw

        rows.append({
            "date": service_date,
            "train_num": train_num,
            "station": station,
            "scheduled_arrival": sch_arr,
            "actual_arrival": act_arr,
            "arrival_delay_mins": parse_delay_minutes(sch_arr, act_arr) if sch_arr and act_arr else "",
            "scheduled_departure": sch_dep,
            "actual_departure": act_dep,
            "departure_delay_mins": parse_delay_minutes(sch_dep, act_dep) if sch_dep and act_dep else "",
            "status": comments,
            "source": "asmad",
        })

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_backfill(days=7):
    """Fetch the past N days of data from ASMAD for all trains."""
    today = datetime.now().date()
    start = today - timedelta(days=days)
    end = today

    for train_num, config in TRAIN_CONFIG.items():
        stations = config["stations"]
        route = config["route"]
        print(f"\nBackfilling {days} days for Train {train_num} ({route}): {start} to {end}")
        rows = fetch_asmad(start, end, train_num, stations)

        if not rows:
            print(f"  No data returned from ASMAD for Train {train_num}.")
            continue

        # Deduplicate against existing CSV
        new_rows = [r for r in rows if not date_already_recorded(r["date"], r["station"], train_num)]
        if not new_rows:
            print(f"  All dates already recorded for Train {train_num}.")
            continue

        append_rows(new_rows)
        dates = sorted(set(r["date"] for r in new_rows))
        print(f"  Added {len(new_rows)} records for {len(dates)} date(s): {', '.join(dates)}")


def run_daily(target_date=None):
    """Fetch today's (or a specific date's) train status for all trains.

    Strategy: try real-time API first, fall back to ASMAD.
    """
    if target_date:
        dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        dt = datetime.now().date()

    date_str = dt.strftime("%Y-%m-%d")

    for train_num, config in TRAIN_CONFIG.items():
        stations = config["stations"]
        route = config["route"]
        print(f"\nFetching status for {date_str} — Train {train_num} ({route})")

        # Check if already have this data
        all_recorded = all(date_already_recorded(date_str, s, train_num) for s in stations)
        if all_recorded:
            print(f"  Data for {date_str} already recorded.")
            continue

        # Try real-time API first (only useful if today and train is active)
        rows = []
        if dt == datetime.now().date():
            print("  Trying real-time API...")
            rows = fetch_realtime(train_num, stations)
            if rows:
                new_rows = [r for r in rows if not date_already_recorded(r["date"], r["station"], train_num)]
                if new_rows:
                    append_rows(new_rows)
                    print(f"  Added {len(new_rows)} records from real-time API.")
                    continue
                else:
                    print("  Real-time data already recorded.")
                    continue

        # Fall back to ASMAD
        print("  Trying ASMAD historical archive...")
        rows = fetch_asmad(dt, dt, train_num, stations)
        if rows:
            new_rows = [r for r in rows if not date_already_recorded(r["date"], r["station"], train_num)]
            if new_rows:
                append_rows(new_rows)
                print(f"  Added {len(new_rows)} records from ASMAD.")
            else:
                print("  ASMAD data already recorded.")
        else:
            print(f"  No data available yet for {date_str}.")


def main():
    parser = argparse.ArgumentParser(
        description="Track Amtrak Auto Train status (Train 52 & 53)"
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Fetch the past 7 days of status history from ASMAD",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=7,
        help="Number of days to backfill (default: 7)",
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Fetch status for a specific date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    init_csv()

    if args.backfill:
        run_backfill(args.backfill_days)
    else:
        run_daily(args.date)


if __name__ == "__main__":
    main()
