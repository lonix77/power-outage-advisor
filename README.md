# Meralco Power Outage & Alert Advisor

An automated, serverless system that scrapes Meralco's outage advisories and grid alerts, sending notifications directly to your Telegram. Built with Python and Playwright, it is designed to run entirely in the cloud using GitHub Actions.

## Features

The system is split into two independent monitoring tools:

1. **Maintenance Checker** (`check_maintenance.py`)
   Scrapes Meralco's **Planned Maintenance** schedule.
   * Matches detected maintenance schedules against your specified areas or barangays.
   * Utilizes GitHub Actions Cache (`actions/cache`) to suppress duplicate notifications.
   * Pre-configured to run automatically every **48 hours**.

2. **Urgent Alert Checker** (`check_alerts.py`)
   Scrapes Meralco's **Alerts Page** for active Red/Yellow grid alerts and immediate Rotational Brownouts.
   * Parses specific time-window blocks dynamically rendered in the page's React layer.
   * Leverages caching to ensure you are only alerted to new or changing alert states.
   * Pre-configured to run automatically every **12 hours**.

## Prerequisites

To use this script, you will need to provision Telegram API credentials:
1. **Telegram Bot Token**: Message `@BotFather` on Telegram to create a bot and get its API token.
2. **Telegram Chat ID**: Message `@userinfobot` on Telegram from your personal account to get your ID. This tells the script where to send the alerts.
3. **Search Areas**: You need to define a comma-separated list of target cities, municipalities, or barangays you wish to monitor.

## How to Deploy (Fork & Run)

This project requires zero infrastructure and is tailored to run perfectly on GitHub's free tier. 

1. **Fork this repository** to your own GitHub account.
2. In your forked repository, navigate to **Settings** > **Secrets and variables** > **Actions**.
3. Create the following three **New repository secrets**:
   * `TELEGRAM_BOT_TOKEN` (e.g., `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)
   * `TELEGRAM_CHAT_ID` (e.g., `123456789`)
   * `SEARCH_AREAS` (e.g., `"Makati,Taguig"`. *Note: Wrap the entire string in quotes if some names contain spaces.*)
4. Go to the **Actions** tab in your repository. GitHub disables workflows on forked repositories by default. Click **"I understand my workflows, go ahead and enable them"**.
5. To test the integration immediately, select either workflow on the left sidebar and click **Run workflow**.

## Modifying Schedules
Schedules are defined via standard cron syntax. You can edit the intervals at any point by modifying `.github/workflows/alert-checker.yml` and `.github/workflows/maintenance-checker.yml` directly in your repository.
