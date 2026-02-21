# Amtrak Auto Train Delay Tracker

Tracks daily delay data for Amtrak's Auto Train service and displays it on a live dashboard.

- **Train 53** — Southbound: Lorton, VA (LOR) to Sanford, FL (SFA)
- **Train 52** — Northbound: Sanford, FL (SFA) to Lorton, VA (LOR)

## Live Dashboard

View the dashboard at: **[wonky4556.github.io/amtrak-auto-train-status/dashboard.html](https://wonky4556.github.io/amtrak-auto-train-status/dashboard.html)**

The dashboard shows arrival/departure delay charts, average delays, worst delays, and on-time percentages for both train directions.

## How It Works

1. A Python script (`amtrak_status.py`) fetches real-time train data from the [Amtraker v3 API](https://github.com/piemadd/amtrak)
2. Scheduled and actual arrival/departure times are compared to calculate delay in minutes
3. Results are appended to `auto_train_status.csv`
4. A GitHub Actions workflow runs every 2 hours (9 AM–2 PM ET) to collect data automatically
5. The dashboard (`dashboard.html`) reads the CSV and renders interactive charts via Chart.js

## Running Locally

```bash
pip install -r requirements.txt
python amtrak_status.py
```

To fetch data for a specific date:
```bash
python amtrak_status.py --date 2026-02-10
```

To view the dashboard locally:
```bash
python -m http.server
# Open http://localhost:8000/dashboard.html
```

## Project Structure

```
amtrak_status.py          # Data collection script
auto_train_status.csv     # Historical delay data (auto-updated)
dashboard.html            # GitHub Pages dashboard
favicon.svg               # Site favicon
requirements.txt          # Python dependencies
.github/workflows/        # GitHub Actions automation
```
