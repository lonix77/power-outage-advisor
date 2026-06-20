# Meralco Outage & Alert Checker

A unified automated system holding two utilities to scrape and monitor Meralco's outage pages and send notifications via Telegram. It supports scraping React/Next.js dynamic HTML using Playwright.

## 1. Maintenance Checker (`check_maintenance.py`)
Checks Meralco's **Planned Maintenance** schedule (twice daily is recommended).
* Caches results in `.meralco_advisories_cache.json`
* Emits a message showing planned maintenance timeframes for your matched areas.

## 2. Urgent Alert Checker (`check_alerts.py`)
Checks Meralco's **Alerts Page** for active Red/Yellow grid alerts and immediate Rotational Brownouts (checking every 1-2 hours is recommended).
* Extracts time windows even with complex nested DOM trees.
* Caches results in `.meralco_alerts_cache.json`

## Requirements
* Python 3
* Playwright
* BeautifulSoup4

## Setup
1. Run `./setup_ubuntu.sh` to install system packages, create virtual environment, and install dependencies.
2. Run `source venv/bin/activate` followed by `playwright install chromium`
3. Copy `config.env.example` to `config.env` and populate `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and `SEARCH_AREAS`.

## Usage
* You can test them directly:
  `python3 check_maintenance.py "Taguig,Makati" --telegram --bot-token "..." --chat-id "..."`
  `python3 check_alerts.py "Taguig,Makati" --telegram --bot-token "..." --chat-id "..."`

* Or use the wrappers loaded with `config.env` values:
  `./run_maintenance.sh`
  `./run_alerts.sh`

## Cron Examples (Add via `crontab -e`)
```bash
# Check planned maintenance at 8:00 AM and 6:00 PM
0 8,18 * * * /path/to/mer-outage/run_maintenance.sh >> /path/to/mer-outage/run_maintenance.log 2>&1

# Check urgent alerts every 2 hours from 9 AM to 11 PM
0 9-23/2 * * * /path/to/mer-outage/run_alerts.sh >> /path/to/mer-outage/run_alerts.log 2>&1
```
