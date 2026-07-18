# Meralco Power Outage & Alert Advisor

An automated, serverless system that scrapes Meralco's outage advisories and grid alerts, sending notifications directly to your Telegram. Built with Python and Playwright, it is designed to run entirely in the cloud using GitHub Actions — **no server, no cost** (GitHub Actions is free for public repositories).

## Features

The system is split into two independent monitoring tools:

1. **Maintenance Checker** (`check_maintenance.py`)
   Scrapes Meralco's **Planned Maintenance** schedule.
   * Matches detected maintenance schedules against your specified areas or barangays.
   * Filters out advisories whose event has already fully passed, so you only get today's and upcoming schedules.
   * Utilizes GitHub Actions Cache (`actions/cache`) to suppress duplicate notifications.
   * Pre-configured to run automatically every **48 hours**.

2. **Urgent Alert Checker** (`check_alerts.py`)
   Scrapes Meralco's **Alerts Page** for active Red/Yellow grid alerts and immediate Rotational Brownouts.
   * Parses specific time-window blocks dynamically rendered in the page's React layer.
   * Leverages caching to ensure you are only alerted to new or changing alert states.
   * Pre-configured to run automatically every **12 hours**.

## Prerequisites

To use this project, you will need to provision Telegram API credentials:

1. **Telegram Bot Token**: Message `@BotFather` on Telegram to create a bot and get its API token.
2. **Telegram Chat ID**: Message `@userinfobot` on Telegram from your personal account to get your ID. This tells the script where to send the alerts.
3. **Search Areas**: A comma-separated list of target cities, municipalities, or barangays you wish to monitor (e.g. `Makati,Taguig`).

## Quick Start — Fork & Deploy (Recommended)

The easiest way to run your own copy is to fork this repository and let GitHub Actions do the work.

1. **Fork the repo**
   Click **Fork** at the top-right of this page to create your own copy under your GitHub account.

2. **Enable GitHub Actions**
   In your fork, go to the **Actions** tab. GitHub disables workflows on new forks by default — click **"I understand my workflows, go ahead and enable them"**.

3. **Add your secrets**
   Go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, and create the following three secrets:

   | Secret name | Example value | Notes |
   |-------------|---------------|-------|
   | `TELEGRAM_BOT_TOKEN` | `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz` | From `@BotFather` |
   | `TELEGRAM_CHAT_ID`   | `123456789` | From `@userinfobot` |
   | `SEARCH_AREAS`       | `Makati,Taguig` | Comma-separated. Names with spaces are fine; the value is quoted for you. |

   > **Never commit these values into the code.** Repository secrets are encrypted and are the only safe place to store them, especially on a public repo.

4. **Test it immediately**
   In the **Actions** tab, select either workflow in the left sidebar (*Meralco Planned Maintenance Checker* or *Meralco Urgent Alert Checker*) and click **Run workflow**. You should receive a Telegram message within a minute or two.

That's it — the checkers will now run automatically on their schedules (maintenance every 48 h, alerts every 12 h).

## Running Locally (Optional)

You can also run the scripts on your own machine to test or use them ad-hoc.

```bash
# 1. Clone your fork
git clone https://github.com/<your-username>/power-outage-advisor.git
cd power-outage-advisor

# 2. Create a virtual environment (Python 3.10+)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies + the Chromium browser Playwright drives
pip install -r requirements.txt
python -m playwright install chromium
```

### Usage

Both scripts take a comma-separated list of areas as the first argument. Telegram flags are optional — omit them to just print results to the console.

```bash
# Print upcoming maintenance for your areas (no Telegram)
python check_maintenance.py "Makati,Taguig"

# Same, but also send a Telegram notification (even when there is nothing to report)
python check_maintenance.py "Makati,Taguig" \
  --telegram --notify-always \
  --bot-token "<YOUR_BOT_TOKEN>" --chat-id "<YOUR_CHAT_ID>"

# Check for urgent grid alerts / rotational brownouts
python check_alerts.py "Cavite,Manila" \
  --telegram \
  --bot-token "<YOUR_BOT_TOKEN>" --chat-id "<YOUR_CHAT_ID>"
```

You can also export `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as environment variables instead of passing `--bot-token` / `--chat-id`.

**Common flags**

| Flag | Applies to | Description |
|------|------------|-------------|
| `--telegram` | both | Send a Telegram notification. |
| `--silent` | both | Minimal console output (used by the workflows). |
| `--notify-always` | maintenance | Send an "all clear" message even when no advisories match. |
| `--debug` | alerts | Print header snippet and date-detection diagnostics. |

## Modifying Schedules

Schedules are defined via standard cron syntax. Edit the intervals at any time by modifying the `cron:` lines in:

* `.github/workflows/maintenance-checker.yml`
* `.github/workflows/alert-checker.yml`

## How It Works

Each workflow checks out the repo, installs Python + Playwright, restores a small JSON cache (so you are only alerted to *new* or *changed* states), runs the relevant scraper, and saves the cache back. All scraping runs headless in GitHub's Ubuntu runners — nothing runs on your own hardware.

## Disclaimer

This is an unofficial, community project and is not affiliated with or endorsed by Meralco. It relies on scraping Meralco's public website; if their page structure changes, the scrapers may need updates. Always verify critical information against Meralco's official channels.
