# Meralco Outage & Alert Checker

A serverless automated system utilizing **GitHub Actions** to scrape and monitor Meralco's outage pages and send notifications via Telegram. Supports scraping React/Next.js dynamic HTML using Playwright.

## 1. Maintenance Checker (`check_maintenance.py`)
Checks Meralco's **Planned Maintenance** schedule.
* Matches areas.
* Caches results using GitHub Actions Cache (`actions/cache`) across runs.
* Runs automatically **every 48 hours**.

## 2. Urgent Alert Checker (`check_alerts.py`)
Checks Meralco's **Alerts Page** for active Red/Yellow grid alerts and immediate Rotational Brownouts.
* Extracts time windows even with complex nested DOM trees.
* Caches results using GitHub Actions Cache (`actions/cache`) across runs.
* Runs automatically **every 12 hours**.

## Serverless Deployment via GitHub Actions
Since you've moved to GitHub workflows, no VM setup is required.

1. Go to your repository on GitHub.
2. Navigate to **Settings > Secrets and variables > Actions**.
3. Create three **New repository secrets**:
   * `TELEGRAM_BOT_TOKEN`: The bot token from @BotFather.
   * `TELEGRAM_CHAT_ID`: Your chat ID from @userinfobot.
   * `SEARCH_AREAS`: A comma-separated list of your areas (e.g., `"Taguig,QC"`). Note the quotes if they have spaces.
4. The isolated workflows in `.github/workflows/` automatically execute based on their own separate cron schedules.
5. Click **Actions** to view the divided workflows and test them manually via **Run workflow**.
