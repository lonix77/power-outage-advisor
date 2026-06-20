#!/usr/bin/env python3
"""
Meralco Outage Checker with Telegram Notifications
Checks for maintenance advisories and sends notifications via Telegram
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import argparse
import sys
import os
from urllib.parse import urljoin
from datetime import datetime, timedelta
import urllib.request
import re
import urllib.parse
import json
from pathlib import Path


# Cache file to track previously found advisories
CACHE_FILE = Path.home() / '.meralco_advisories_cache.json'


def load_advisory_history():
    """Load previously found advisories from cache file"""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}


def save_advisory_history(data):
    """Save current advisories to cache file"""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Warning: Could not save advisory history: {e}")


def extract_event_date(title):
    """Extract the first event date from advisory title. Returns datetime object or None."""
    date_match = re.match(r'(\w+ \d+(?:\s*–\s*\d+)?,\s*\d{4})', title)
    if date_match:
        try:
            full_date = date_match.group(1)
            year_match = re.search(r'(\d{4})', full_date)
            year = year_match.group(1) if year_match else ''
            date_part = full_date.split('–')[0].strip()
            if ',' not in date_part:
                date_part = f"{date_part}, {year}"
            return datetime.strptime(date_part, '%B %d, %Y')
        except:
            pass
    return None


def categorize_advisories(current_matches, previous_data, area):
    """
    Categorize advisories as new, same-today, same-future, or same-past.
    
    Returns: {
        'new': [match_info, ...],
        'same_today': [match_info, ...],
        'same_future': [match_info, ...],
        'same_past': [match_info, ...]
    }
    """
    categories = {
        'new': [],
        'same_today': [],
        'same_future': [],
        'same_past': []
    }
    
    # Get previous advisories for this area (list of titles)
    previous_titles = set(previous_data.get('areas', {}).get(area, []))
    today = datetime.now().date()
    
    for match in current_matches:
        title = match['title']
        event_date = extract_event_date(title)
        
        if title not in previous_titles:
            # This is a NEW advisory
            categories['new'].append(match)
        else:
            # This is a SAME (previously seen) advisory
            if event_date:
                event_date_only = event_date.date()
                if event_date_only == today:
                    categories['same_today'].append(match)
                elif event_date_only > today:
                    categories['same_future'].append(match)
                else:
                    categories['same_past'].append(match)
            else:
                # Can't determine date, treat as same-future to be safe
                categories['same_future'].append(match)
    
    return categories


def send_telegram_message(bot_token, chat_id, message, parse_mode='HTML'):
    """Send a message via Telegram Bot API using only urllib (no external deps)"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({
            'chat_id': chat_id,
            'text': message,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('ok', False)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")
        return False


def check_maint(search_keywords, send_telegram=False, bot_token=None, chat_id=None, silent=False):
    """
    Check for maintenance advisories
    
    Args:
        search_keywords: List of areas to search for, or single area string
        send_telegram: Whether to send Telegram notifications
        bot_token: Telegram bot token
        chat_id: Telegram chat ID
        silent: If True, suppress console output except errors
    
    Returns:
        (found_count, matches_dict) tuple where matches_dict = {area: [matches]}
    """
    # Convert single string to list for consistent handling
    if isinstance(search_keywords, str):
        search_keywords = [search_keywords]
    
    base_url = "https://company.meralco.com.ph"
    list_url = f"{base_url}/news-and-advisories/maintenance-schedule"
    
    # Dictionary to store matches per area: {area: [matches]}
    matches_by_area = {area: [] for area in search_keywords}
    scraping_successful = False  # Track if scraping completed successfully
    
    if not silent:
        areas_str = ", ".join(f"'{kw}'" for kw in search_keywords)
        print(f"--- Checking Meralco Advisories for: {areas_str} ---")
        print("🔄 Loading page and executing JavaScript...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # Add timeout to prevent hanging
            page.goto(list_url, wait_until='networkidle', timeout=60000)
            
            if not silent:
                print("   ⏳ Looking for 'show more' buttons...")
            
            # Click "show more" buttons with smart stopping (date-based)
            clicks = 0
            max_safety_clicks = 100
            no_change_count = 0
            seen_titles = set()
            old_date_count = 0
            
            while clicks < max_safety_clicks:
                # Get all current advisory titles BEFORE clicking
                soup_before = BeautifulSoup(page.content(), 'html.parser')
                advisories_before = soup_before.find_all('div', class_='views-field-title')
                titles_before = set()
                
                for adv in advisories_before:
                    link = adv.find('a')
                    if link:
                        title = link.get_text().strip()
                        titles_before.add(title)
                
                count_before = len(titles_before)
                
                # Try to find and click button
                button_found = False
                selectors = ['.pager-next a', 'a:has-text("Show more")', 'button:has-text("Show more")']
                
                for selector in selectors:
                    try:
                        button = page.locator(selector).first
                        if button.is_visible(timeout=1000):
                            button.scroll_into_view_if_needed()
                            button.click()
                            clicks += 1
                            page.wait_for_timeout(2000)
                            button_found = True
                            
                            # Get titles AFTER clicking
                            soup_after = BeautifulSoup(page.content(), 'html.parser')
                            advisories_after = soup_after.find_all('div', class_='views-field-title')
                            titles_after = set()
                            
                            for adv in advisories_after:
                                link = adv.find('a')
                                if link:
                                    titles_after.add(link.get_text().strip())
                            
                            count_after = len(titles_after)
                            new_unique = titles_after - titles_before
                            
                            if not silent:
                                print(f"   ✓ Click {clicks}: {count_before} → {count_after} items (+{len(new_unique)} new unique)")
                            
                            # Check if we got truly new content
                            if len(new_unique) == 0:
                                no_change_count += 1
                                if not silent:
                                    print(f"      ⚠️ No new unique items (strike {no_change_count}/3)")
                                if no_change_count >= 3:
                                    if not silent:
                                        print(f"   🛑 STOPPING: No new content after 3 consecutive clicks")
                                    button_found = False
                                    break
                            else:
                                no_change_count = 0
                                seen_titles.update(new_unique)
                                
                                # Check: are new items past events?
                                old_items_in_batch = 0
                                for title in list(new_unique)[:5]:
                                    date_match = re.match(r'(\w+ \d+(?:\s*–\s*\d+)?,\s*\d{4})', title)
                                    if date_match:
                                        try:
                                            full_date = date_match.group(1)
                                            year_match = re.search(r'(\d{4})', full_date)
                                            year = year_match.group(1) if year_match else ''
                                            date_part = full_date.split('–')[0].strip()
                                            if ',' not in date_part:
                                                date_part = f"{date_part}, {year}"
                                            date_obj = datetime.strptime(date_part, '%B %d, %Y')
                                            days_old = (datetime.now() - date_obj).days
                                            if days_old >= 1:
                                                old_items_in_batch += 1
                                        except:
                                            pass
                                
                                if old_items_in_batch >= 3:
                                    if not silent:
                                        print(f"      ℹ️ Getting past events (1+ days old)")
                                    old_date_count += 1
                                    if old_date_count >= 1:
                                        if not silent:
                                            print(f"   🛑 STOPPING: Reached past events (only showing today/future)")
                                        button_found = False
                                        break
                            
                            break
                    except:
                        continue
                
                if not button_found:
                    break
            
            if not silent:
                if clicks == 0:
                    print("   ℹ️ No 'show more' buttons found")
                elif clicks >= max_safety_clicks:
                    print(f"   ⚠️ Reached safety limit of {max_safety_clicks} clicks")
            
            # Parse the fully rendered HTML
            html_content = page.content()
            soup = BeautifulSoup(html_content, 'html.parser')
            advisories = soup.find_all('div', class_='views-field-title')
            
            if not advisories:
                if not silent:
                    print("⚠️ Could not find any advisories. The website structure might have changed.")
                # Don't mark as successful - site structure may have changed
                return 0, []
            
            # Mark as successful - we successfully loaded and parsed the page
            scraping_successful = True
            
            # Search for matches (filter out past events)
            for adv in advisories:
                link_tag = adv.find('a')
                if not link_tag:
                    continue
                    
                text = link_tag.get_text().strip()
                
                # Check against all search keywords
                for search_keyword in search_keywords:
                    if search_keyword.lower() in text.lower():
                        # Filter out past events - only show today or future dates
                        date_match = re.match(r'(\w+ \d+(?:\s*–\s*\d+)?,\s*\d{4})', text)
                        if date_match:
                            try:
                                full_date = date_match.group(1)
                                year_match = re.search(r'(\d{4})', full_date)
                                year = year_match.group(1) if year_match else ''
                                date_part = full_date.split('–')[0].strip()
                                if ',' not in date_part:
                                    date_part = f"{date_part}, {year}"
                                date_obj = datetime.strptime(date_part, '%B %d, %Y')
                                days_old = (datetime.now() - date_obj).days
                                
                                # Skip past events (only show today or future)
                                if days_old >= 1:
                                    continue
                            except:
                                pass  # If date parsing fails, show the item anyway
                        
                        relative_link = link_tag.get('href')
                        full_link = urljoin(base_url, relative_link)
                        
                        match_info = {
                            'title': text,
                            'url': full_link
                        }
                        
                        # Add to this area's matches (avoid duplicates)
                        if match_info not in matches_by_area[search_keyword]:
                            matches_by_area[search_keyword].append(match_info)
                            
                            if not silent:
                                print(f"\n✅ MATCH FOUND for '{search_keyword}': {text}")
                                print(f"🔗 Link: {full_link}")
            
            # Calculate total matches across all areas
            total_matches = sum(len(matches) for matches in matches_by_area.values())
            
            if not silent:
                if total_matches == 0:
                    print(f"No active advisories found for any area.")
                else:
                    print(f"\n📊 Total matches: {total_matches}")
                    for area, matches in matches_by_area.items():
                        if matches:
                            print(f"  - {area}: {len(matches)} advisory(ies)")
            
            # Smart Telegram notification with advisory tracking
            if send_telegram and bot_token and chat_id:
                # Load previous advisories
                previous_data = load_advisory_history()
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if not silent:
                    if previous_data:
                        print(f"\n📁 Loaded advisory history from: {CACHE_FILE}")
                        print(f"   Last check: {previous_data.get('last_check', 'unknown')}")
                    else:
                        print(f"\n📁 No previous history found (first run)")
                
                # Categorize advisories for each area
                all_new = []
                all_same_today = []
                all_same_future = []
                all_same_past = []
                
                message_parts = []
                
                for area, matches in matches_by_area.items():
                    if matches:
                        categories = categorize_advisories(matches, previous_data, area)
                        
                        all_new.extend(categories['new'])
                        all_same_today.extend(categories['same_today'])
                        all_same_future.extend(categories['same_future'])
                        all_same_past.extend(categories['same_past'])
                        
                        if not silent:
                            print(f"\n🔍 {area}: {len(matches)} advisory(ies)")
                            print(f"   🆕 New: {len(categories['new'])}")
                            print(f"   🔴 Today: {len(categories['same_today'])}")
                            print(f"   📅 Future: {len(categories['same_future'])}")
                            print(f"   ✅ Past: {len(categories['same_past'])}")
                        
                        # Generate message for this area
                        if categories['new']:
                            # NEW ADVISORIES - Full details
                            message_parts.append(f"🆕 <b>{area}</b> - NEW ADVISORIES ({len(categories['new'])})")
                            for match in categories['new']:
                                message_parts.append(f"  • {match['title']}")
                                message_parts.append(f"    🔗 {match['url']}")
                        
                        if categories['same_today']:
                            # EVENT HAPPENING TODAY - Full details
                            message_parts.append(f"🔴 <b>{area}</b> - EVENT TODAY ({len(categories['same_today'])})")
                            for match in categories['same_today']:
                                message_parts.append(f"  • {match['title']}")
                                message_parts.append(f"    🔗 {match['url']}")
                        
                        if categories['same_future'] and not categories['new'] and not categories['same_today']:
                            # ONLY FUTURE EVENTS (no new, no today) - Brief mention
                            dates = []
                            for match in categories['same_future']:
                                event_date = extract_event_date(match['title'])
                                if event_date:
                                    dates.append(event_date.strftime('%b %d'))
                            dates_str = ', '.join(sorted(set(dates)))
                            message_parts.append(f"📅 <b>{area}</b> - No new advisories (scheduled: {dates_str})")
                        elif categories['same_future'] and (categories['new'] or categories['same_today']):
                            # FUTURE EVENTS with new or today events - Brief mention
                            dates = []
                            for match in categories['same_future']:
                                event_date = extract_event_date(match['title'])
                                if event_date:
                                    dates.append(event_date.strftime('%b %d'))
                            dates_str = ', '.join(sorted(set(dates)))
                            message_parts.append(f"📅 <b>{area}</b> - Also scheduled: {dates_str}")
                        
                        if categories['same_past'] and not any([categories['new'], categories['same_today'], categories['same_future']]):
                            # ONLY PAST EVENTS - Brief mention
                            message_parts.append(f"✅ <b>{area}</b> - No new advisories")
                
                # Build final message
                if all_new or all_same_today:
                    # Send notification for new or today events
                    message = f"⚡ <b>Meralco Outage Alert</b>\n\n"
                    message += f"🕐 <b>Checked:</b> {timestamp}\n\n"
                    message += '\n'.join(message_parts)
                    
                    success = send_telegram_message(bot_token, chat_id, message)
                    if not silent:
                        if success:
                            print("✅ Telegram notification sent successfully (new/today events)")
                        else:
                            print("⚠️ Failed to send Telegram notification")
                            
                elif all_same_future:
                    # Only future events, send brief notification
                    message = f"ℹ️ <b>Meralco Status Update</b>\n\n"
                    message += f"🕐 <b>Checked:</b> {timestamp}\n\n"
                    message += '\n'.join(message_parts)
                    
                    success = send_telegram_message(bot_token, chat_id, message)
                    if not silent:
                        if success:
                            print("✅ Telegram notification sent successfully (future events reminder)")
                        else:
                            print("⚠️ Failed to send Telegram notification")
                            
                elif all_same_past:
                    # Only past events, send brief notification
                    message = f"✅ <b>Meralco Status Update</b>\n\n"
                    message += f"🕐 <b>Checked:</b> {timestamp}\n\n"
                    message += '\n'.join(message_parts)
                    
                    success = send_telegram_message(bot_token, chat_id, message)
                    if not silent:
                        if success:
                            print("✅ Telegram notification sent successfully (no new advisories)")
                        else:
                            print("⚠️ Failed to send Telegram notification")
                elif total_matches == 0:
                    # No matches at all - handle in notify-always section below
                    pass
                
                # Update advisory history cache ONLY if scraping was successful
                # This prevents overwriting good data with empty data due to site errors
                if scraping_successful:
                    current_data = {
                        'last_check': timestamp,
                        'areas': {}
                    }
                    for area, matches in matches_by_area.items():
                        current_data['areas'][area] = [match['title'] for match in matches]
                    
                    # Additional safety: Don't overwrite existing data with empty data
                    # (could indicate site issues rather than legitimately no advisories)
                    total_new = sum(len(titles) for titles in current_data['areas'].values())
                    total_old = sum(len(titles) for titles in previous_data.get('areas', {}).values())
                    
                    if total_new == 0 and total_old > 0:
                        if not silent:
                            print(f"⚠️ Warning: Found 0 advisories but cache has {total_old}. Keeping old cache.")
                            print(f"   This could indicate site issues. Cache NOT updated.")
                    else:
                        save_advisory_history(current_data)
                        
                        if not silent:
                            total_cached = sum(len(titles) for titles in current_data['areas'].values())
                            print(f"💾 Saved {total_cached} advisory titles to cache: {CACHE_FILE}")
                else:
                    if not silent:
                        print(f"⚠️ Skipping cache update - scraping may have failed")
            
            return total_matches, matches_by_area
                
        except Exception as e:
            error_msg = f"❌ Error: {e}"
            print(error_msg)
            
            # Send error notification to Telegram
            if send_telegram and bot_token and chat_id:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                areas_str = ", ".join(search_keywords)
                error_message = f"⚠️ <b>Meralco Checker Error</b>\n\n"
                error_message += f"🔍 <b>Search:</b> {areas_str}\n"
                error_message += f"🕐 <b>Time:</b> {timestamp}\n"
                error_message += f"❌ <b>Error:</b> {str(e)[:500]}"
                send_telegram_message(bot_token, chat_id, error_message)
            
            # Do NOT update cache on error - preserve existing data
            if not silent:
                print(f"⚠️ Cache NOT updated due to error - preserving existing data")
            
            return 0, {area: [] for area in search_keywords}
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check Meralco maintenance advisories with optional Telegram notifications"
    )
    parser.add_argument("area", help="Area(s) to search for. Use comma-separated for multiple (e.g., 'Quezon City,Taguig')")
    parser.add_argument("--telegram", action="store_true", 
                       help="Send Telegram notification if matches found")
    parser.add_argument("--bot-token", 
                       help="Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)")
    parser.add_argument("--chat-id", 
                       help="Telegram chat ID (or set TELEGRAM_CHAT_ID env var)")
    parser.add_argument("--silent", action="store_true",
                       help="Suppress console output except errors")
    parser.add_argument("--notify-always", action="store_true",
                       help="Send Telegram notification even when no matches found")
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    
    args = parser.parse_args()
    
    # Parse comma-separated areas
    search_areas = [area.strip() for area in args.area.split(',')]
    
    # Get Telegram credentials from args or environment variables
    bot_token = args.bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = args.chat_id or os.getenv('TELEGRAM_CHAT_ID')
    
    # Validate Telegram credentials if notification requested
    if args.telegram and (not bot_token or not chat_id):
        print("❌ Error: Telegram notification requested but credentials not provided.")
        print("   Set --bot-token and --chat-id, or set environment variables:")
        print("   TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        sys.exit(1)
    
    found_count, matches_by_area = check_maint(
        search_areas,
        send_telegram=args.telegram,
        bot_token=bot_token,
        chat_id=chat_id,
        silent=args.silent
    )
    
    # Send "all clear" notification if requested
    if args.telegram and args.notify_always and found_count == 0:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        areas_str = ", ".join(search_areas)
        message = f"✅ <b>Meralco Check Complete</b>\n\n"
        message += f"🕐 <b>Checked:</b> {timestamp}\n"
        message += f"📊 <b>Result:</b> No advisories found\n\n"
        for area in search_areas:
            message += f"✅ <b>{area}</b>: All clear\n"
        send_telegram_message(bot_token, chat_id, message)
    
    # Exit with appropriate code
    sys.exit(0 if found_count >= 0 else 1)
