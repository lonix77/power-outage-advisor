#!/bin/bash
# Wrapper script for cron jobs - Alert Checker
# This script loads environment variables and runs the alert checker

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from config.env
if [ -f "$SCRIPT_DIR/config.env" ]; then
    # Use set -a to automatically export all variables
    # This properly handles values with spaces
    set -a
    source "$SCRIPT_DIR/config.env"
    set +a
else
    echo "❌ config.env not found in $SCRIPT_DIR"
    exit 1
fi

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Check all areas in a single run (comma-separated from SEARCH_AREAS)
echo "Checking areas for alerts: $SEARCH_AREAS"
python3 "$SCRIPT_DIR/check_alerts.py" "$SEARCH_AREAS" \
    --telegram \
    --bot-token "$TELEGRAM_BOT_TOKEN" \
    --chat-id "$TELEGRAM_CHAT_ID"

echo "✅ Alert check complete: $(date)"
