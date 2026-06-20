#!/bin/bash
# Setup script for Ubuntu VM deployment

set -e  # Exit on error

echo "=========================================="
echo "Meralco Outage Checker - Ubuntu Setup"
echo "=========================================="
echo ""

# Check if running on Ubuntu/Debian
if ! command -v apt-get &> /dev/null; then
    echo "❌ This script is for Ubuntu/Debian systems only"
    exit 1
fi

echo "📦 Updating system packages..."
sudo apt-get update

echo ""
echo "📦 Installing system dependencies for Playwright..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libatspi2.0-0t64 \
    libgtk-3-0t64 \
    libasound2t64

echo ""
echo "🐍 Creating Python virtual environment..."
python3 -m venv venv

echo ""
echo "📦 Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "🌐 Installing Chromium browser for Playwright..."
python3 -m playwright install chromium

echo ""
echo "✅ Setup complete!"
echo ""
echo "=========================================="
echo "Next Steps:"
echo "=========================================="
echo ""
echo "1. Configure your Telegram bot:"
echo "   cp config.env.example config.env"
echo "   nano config.env  # Edit with your credentials"
echo ""
echo "2. Test the script:"
echo "   source venv/bin/activate"
echo "   python3 check_maintenance.py \"Quezon City\" --telegram"
echo ""
echo "3. Setup cron jobs (see README.md)"
echo ""
