#!/usr/bin/env python3
"""
Meralco Alert Checker with Telegram Notifications - SIMPLIFIED
Checks if search areas appear on Yellow/Red Alerts or Rotational Brownout pages
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import argparse
import sys
import os
from datetime import datetime
import urllib.request
import urllib.parse
import json
from pathlib import Path


# Cache file to track previously found alerts
CACHE_FILE = Path.home() / '.meralco_alerts_cache.json'

# Debug toggle (set in __main__ from --debug or env)
DEBUG_HEADER = False


def load_alert_history():
    """Load previously found alerts from cache file"""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Warning: Could not load alert history: {e}")
        return {}


def save_alert_history(data):
    """Save current alerts to cache file"""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Warning: Could not save alert history: {e}")


def categorize_alerts(current_alerts, previous_data, area):
    """
    Categorize alerts as new or same
    """
    previous_titles = set(previous_data.get('areas', {}).get(area, []))
    current_titles = set(alert['title'] for alert in current_alerts)
    
    new = []
    same = []
    
    for alert in current_alerts:
        if alert['title'] in previous_titles:
            same.append(alert)
        else:
            new.append(alert)
    
    return {'new': new, 'same': same}


def send_telegram_message(bot_token, chat_id, message):
    """Send message via Telegram Bot API"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(data).encode('utf-8'),
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            resp_body = response.read().decode('utf-8')
            try:
                resp_json = json.loads(resp_body)
                if resp_json.get('ok'):
                    return True
                else:
                    print(f"Telegram API error: {resp_json}")
                    return False
            except Exception:
                # Non-JSON response
                print(f"Telegram HTTP response: {response.status} {resp_body}")
                return response.status == 200
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8')
        except Exception:
            body = '<no body>'
        print(f"Telegram HTTPError {e.code}: {body}")
        return False
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False


def extract_effectivity_date(full_text, soup=None):
    """Try to extract an effectivity date from the page header text.

    Looks for patterns like "MAY 14, 2026" or "May 14, 2026" in the first
    30 lines of the page text and returns a `datetime.date` if found.
    Returns None when no parsable date is found.
    """
    if not full_text and soup is None:
        return None

    # Quick HTML-level search for obvious month-day-year patterns (covers uppercase "MAY 15, 2026")
    if soup is not None:
        try:
            html = str(soup)
            m = re.search(r'([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})', html, re.IGNORECASE)
            if m:
                month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
                try:
                    month_norm = month_str.title()
                    cand = f"{month_norm} {int(day_str)}, {int(year_str)}"
                    dt = datetime.strptime(cand, "%B %d, %Y")
                    return dt.date()
                except Exception:
                    pass
            # also try patterns like 'MAY 15 2026' without comma
            m2 = re.search(r'([A-Za-z]{3,9})\s+(\d{1,2})\s+(\d{4})', html, re.IGNORECASE)
            if m2:
                month_str, day_str, year_str = m2.group(1), m2.group(2), m2.group(3)
                try:
                    month_norm = month_str.title()
                    cand = f"{month_norm} {int(day_str)} {int(year_str)}"
                    dt = datetime.strptime(cand, "%B %d %Y")
                    return dt.date()
                except Exception:
                    pass
        except Exception:
            pass

    # Prepare candidate texts: header lines plus specific HTML elements when soup provided
    candidates = []
    if full_text:
        lines = full_text.splitlines()
        head_lines = lines[:60]
        candidates.append("\n".join(head_lines))
    else:
        head_lines = []

    if soup is not None:
        # time tags
        for t in soup.find_all('time'):
            txt = t.get('datetime') or t.get_text()
            if txt:
                candidates.append(txt.strip())

        # meta tags that may contain published time
        for meta_name in ('date', 'pubdate', 'publishdate', 'publish_date', 'article:published_time'):
            mt = soup.find('meta', attrs={'name': meta_name}) or soup.find('meta', attrs={'property': meta_name})
            if mt and mt.get('content'):
                candidates.append(mt.get('content').strip())

        # elements with class or id containing date-like keywords
        date_elems = soup.find_all(attrs={
            'class': re.compile(r'(date|effectivity|posted|publish|entry|time)', re.I)
        }) + soup.find_all(attrs={
            'id': re.compile(r'(date|effectivity|posted|publish|entry|time)', re.I)
        })
        for el in date_elems:
            txt = el.get_text(separator=' ', strip=True)
            if txt:
                candidates.append(txt)

    # Join candidates into texts to search
    texts_to_search = [c for c in candidates if c]
    if not texts_to_search:
        # fallback to original full_text first 60 lines
        texts_to_search = ["\n".join(head_lines)] if head_lines else []

    # Try several patterns (Month Day Year OR Day Month Year), allow optional comma and newlines
    patterns = [
        r'([A-Za-z]{3,9})\s+(\d{1,2})(?:,)?\s*(\d{4})',
        r'(\d{1,2})\s+([A-Za-z]{3,9})(?:,)?\s*(\d{4})'
    ]

    fmts = ["%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%Y/%m/%d"]

    for text_to_search in texts_to_search:
        for pat in patterns:
            m = re.search(pat, text_to_search, re.IGNORECASE | re.DOTALL)
            if not m:
                continue

            # Determine which groups correspond to month/day/year
            if pat == patterns[0]:
                month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
            else:
                day_str, month_str, year_str = m.group(1), m.group(2), m.group(3)

            month_norm = month_str.title()
            try:
                day = int(day_str)
                year = int(year_str)
            except Exception:
                continue

            # Build candidates with/without comma and try multiple formats
            cands = [f"{month_norm} {day}, {year}", f"{month_norm} {day} {year}", f"{day} {month_norm} {year}", f"{year}-{int(day):02d}-{1:02d}"]
            for cand in cands:
                for fmt in fmts:
                    try:
                        dt = datetime.strptime(cand, fmt)
                        return dt.date()
                    except Exception:
                        continue

    # If not found, try scanning adjacent line pairs (handles "MAY" on one line and "14, 2026" on next)
    stripped_lines = [ln.strip() for ln in head_lines if ln.strip()]
    for i in range(len(stripped_lines) - 1):
        combo = f"{stripped_lines[i]} {stripped_lines[i+1]}"
        for pat in patterns:
            m = re.search(pat, combo, re.IGNORECASE)
            if not m:
                continue
            # assign groups according to which pattern matched
            if pat == patterns[0]:
                month_str, day_str, year_str = m.group(1), m.group(2), m.group(3)
            else:
                day_str, month_str, year_str = m.group(1), m.group(2), m.group(3)

            month_norm = month_str.title()
            day = int(day_str)
            year = int(year_str)

            candidates = [f"{month_norm} {day}, {year}", f"{month_norm} {day} {year}", f"{day} {month_norm} {year}"]
            for cand in candidates:
                for fmt in fmts:
                    try:
                        dt = datetime.strptime(cand, fmt)
                        return dt.date()
                    except Exception:
                        continue


        # fallback: try searching raw HTML for common labels like 'Effectivity' or 'Effective'
        # (this code is reached only if above attempts didn't return)
        try:
            html_text = ''
            if soup is not None:
                html_text = str(soup)
            elif full_text:
                html_text = full_text

            # look for EFFECTIVITY: May 14, 2026 or Effective as of May 14 2026
            lbl_patterns = [r'(?:EFFECTIVI?TY|EFFECTIVE|EFFECTIVE AS OF)[:\s\-]*([A-Za-z]{3,9}\s+\d{1,2}(?:,?\s*\d{4})?)',
                            r'(?:EFFECTIVI?TY|EFFECTIVE)[:\s\-]*([\d]{1,2}\s+[A-Za-z]{3,9}(?:,?\s*\d{4})?)']
            for lp in lbl_patterns:
                m = re.search(lp, html_text, re.IGNORECASE)
                if m:
                    date_str = m.group(1)
                    # try parse with/without year
                    for fmt in ["%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%B %d", "%b %d"]:
                        try:
                            # if year missing, assume current year
                            if re.search(r'\d{4}', date_str) is None and '%Y' not in fmt:
                                dt = datetime.strptime(f"{date_str} {datetime.now().year}", fmt + ' %Y')
                            else:
                                dt = datetime.strptime(date_str, fmt)
                            return dt.date()
                        except Exception:
                            continue
        except Exception:
            pass

        return None


def header_date_status(full_text, soup=None):
    """Return simple status of header date: 'today', 'past', 'future', or None.

    This first looks for an exact textual match of today's date in common
    formats within the first 60 lines. If not found, it attempts to extract
    any date and compare it to today.
    """
    if not full_text:
        return None

    today = datetime.now().date()
    day = today.day
    year = today.year
    month_full = today.strftime('%B')
    month_abbr = today.strftime('%b')
    month_upper = today.strftime('%B').upper()

    lines = full_text.splitlines()
    head = "\n".join(lines[:60])

    # Exact textual patterns for today
    today_patterns = [
        f"{month_full} {day}, {year}",
        f"{month_abbr} {day}, {year}",
        f"{month_upper} {day}, {year}",
        f"{day} {month_full} {year}",
        f"{day} {month_abbr} {year}",
        f"{day} {month_upper} {year}",
        f"{month_full} {day} {year}",
        f"{month_abbr} {day} {year}",
    ]

    for pat in today_patterns:
        if pat in head:
            return 'today'

    # No exact today match — try to extract any date and compare
    eff = extract_effectivity_date(full_text, soup)
    if eff:
        if eff < today:
            return 'past'
        elif eff == today:
            return 'today'
        else:
            return 'future'

    return None


def check_yellow_red_alerts(page, search_keywords, silent=False):
    """Check Yellow/Red alert page for presence of search areas"""
    alerts_by_area = {area: [] for area in search_keywords}
    base_url = "https://company.meralco.com.ph"
    alert_url = f"{base_url}/news-and-advisories/yellow-and-red-alert-locations"
    
    if not silent:
        print(f"\n🚨 Checking Yellow/Red Alerts...")
    
    try:
        page.goto(alert_url, wait_until='networkidle', timeout=60000)
        
        # Expand all province toggles
        if not silent:
            print("   🔽 Expanding all province sections...")
        
        toggle_selectors = ['button.toggle', 'button[aria-expanded="false"]', '.accordion-toggle', 'a[data-toggle="collapse"]']
        for selector in toggle_selectors:
            try:
                toggles = page.locator(selector).all()
                for toggle in toggles:
                    try:
                        if toggle.is_visible(timeout=1000):
                            toggle.click()
                            page.wait_for_timeout(500)
                    except Exception:
                        continue
            except Exception:
                continue
        
        # Get full page text
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        full_page_text = soup.get_text()

        if DEBUG_HEADER:
            try:
                dump_path = '/tmp/meralco_rotational_debug.html'
                with open(dump_path, 'w', encoding='utf-8') as fh:
                    fh.write(html_content)
                print(f"DEBUG: dumped rendered HTML to: {dump_path}")
            except Exception as e:
                print(f"DEBUG: failed to write HTML dump: {e}")

        if DEBUG_HEADER:
            head_lines = full_page_text.splitlines()[:30]
            print("--- Header snippet (Rotational Brownout) ---")
            for ln in head_lines:
                print(ln)
            print("--- End snippet ---")
            print(f"Header date status: {header_date_status(full_page_text, soup)}")
            # Extra debug: title, headings, date-like elements, regex search
            try:
                if soup:
                    title = soup.title.string.strip() if soup.title and soup.title.string else ''
                    print(f"Page title: {title}")
                    for tag in ('h1','h2','h3'):
                        for el in soup.find_all(tag)[:5]:
                            print(f"{tag}: {el.get_text(strip=True)}")
                    date_elems = soup.find_all(attrs={'class': re.compile(r'(date|effectivity|posted|publish|entry|time)', re.I)}) + soup.find_all(attrs={'id': re.compile(r'(date|effectivity|posted|publish|entry|time)', re.I)})
                    print("Date-like elements (first 5):")
                    for el in date_elems[:5]:
                        print(" -", el.name, el.get('class'), el.get('id'), "->", el.get_text(' ', strip=True))
                    html = str(soup)
                    m = re.search(r'([A-Za-z]{3,9}\s+\d{1,2},?\s*\d{4})', html)
                    if m:
                        print(f"Regex date match in HTML: {m.group(1)}")
                    else:
                        print("No regex date match in HTML")
            except Exception as e:
                print(f"DEBUG parse error: {e}")

        if DEBUG_HEADER:
            head_lines = full_page_text.splitlines()[:30]
            print("--- Header snippet (Yellow/Red Alerts) ---")
            for ln in head_lines:
                print(ln)
            print("--- End snippet ---")
            print(f"Header date status: {header_date_status(full_page_text, soup)}")
            # Extra debug: title, headings, date-like elements, regex search
            try:
                if soup:
                    title = soup.title.string.strip() if soup.title and soup.title.string else ''
                    print(f"Page title: {title}")
                    for tag in ('h1','h2','h3'):
                        for el in soup.find_all(tag)[:5]:
                            print(f"{tag}: {el.get_text(strip=True)}")
                    date_elems = soup.find_all(attrs={'class': re.compile(r'(date|effectivity|posted|publish|entry|time)', re.I)}) + soup.find_all(attrs={'id': re.compile(r'(date|effectivity|posted|publish|entry|time)', re.I)})
                    print("Date-like elements (first 5):")
                    for el in date_elems[:5]:
                        print(" -", el.name, el.get('class'), el.get('id'), "->", el.get_text(' ', strip=True))
                    html = str(soup)
                    m = re.search(r'([A-Za-z]{3,9}\s+\d{1,2},?\s*\d{4})', html)
                    if m:
                        print(f"Regex date match in HTML: {m.group(1)}")
                    else:
                        print("No regex date match in HTML")
            except Exception as e:
                print(f"DEBUG parse error: {e}")

        # Verify effectivity date in header (if present)
        status = header_date_status(full_page_text, soup)
        eff = extract_effectivity_date(full_page_text, soup)
        eff_iso = eff.isoformat() if eff else None
        if DEBUG_HEADER:
            print(f"Extracted effectivity date: {eff_iso}")
        if status == 'past':
            if not silent:
                print("   ℹ️ Header date is before today; no new Yellow/Red alerts for today.")
            return alerts_by_area
        
        # Use HTML source position for accurate ordering
        html_str = str(soup)
        time_pattern = r'Between\s+\d{1,2}:\d{2}(?:AM|PM)\s+and\s+\d{1,2}:\d{2}(?:AM|PM)'
        
        # Find all time ranges with their positions in HTML source
        time_headers = []
        for match in re.finditer(time_pattern, html_str, re.I):
            time_headers.append({
                'pos': match.start(),
                'time': match.group(0)
            })
        
        # Simple search: check if area name appears anywhere on page
        for area in search_keywords:
            if area.lower() in full_page_text.lower():
                # Find ALL positions of area in HTML source
                area_regex = re.compile(rf"\b{re.escape(area)}\b", re.I)
                area_matches = list(area_regex.finditer(html_str))
                if not area_matches:
                    # Fallback to loose match
                    area_matches = list(re.finditer(re.escape(area), html_str, re.I))
                
                # Collect all unique time windows for this area
                time_ranges = []
                if area_matches:
                    for area_match in area_matches:
                        area_pos = area_match.start()
                        
                        # Find the closest preceding time header for this occurrence
                        closest_time = None
                        closest_distance = float('inf')
                        
                        for time_info in time_headers:
                            if time_info['pos'] < area_pos:
                                distance = area_pos - time_info['pos']
                                if distance < closest_distance:
                                    closest_distance = distance
                                    closest_time = time_info['time']
                        
                        if closest_time and closest_time not in time_ranges:
                            time_ranges.append(closest_time)
                
                # Create the alert with all time ranges
                title_ext = f" - {', '.join(time_ranges)}" if time_ranges else ""
                alert_info = {
                    'title': f"Yellow/Red Alert - {area}{title_ext}",
                    'url': alert_url,
                    'effectivity_date': eff_iso,
                    'header_status': status
                }
                alerts_by_area[area].append(alert_info)
                
                if not silent:
                    print(f"   🚨 FOUND: {area} appears on Yellow/Red Alerts page")
            elif not silent:
                print(f"   ✓ {area} not found on Yellow/Red Alerts page")
    
    except Exception as e:
        if not silent:
            print(f"   ⚠️ Error checking alerts: {e}")
    
    return alerts_by_area


def check_rotational_brownout(page, search_keywords, silent=False):
    """Check rotational brownout page for presence of search areas"""
    brownouts_by_area = {area: [] for area in search_keywords}
    base_url = "https://company.meralco.com.ph"
    brownout_url = f"{base_url}/news-and-advisories/rotational-brownout"
    
    if not silent:
        print(f"\n⚡ Checking Rotational Brownouts...")
    
    try:
        page.goto(brownout_url, wait_until='networkidle', timeout=60000)
        
        # Click "Show More" buttons if any
        if not silent:
            print("   📄 Looking for 'Show More' button...")
        
        show_more_selectors = ['button:has-text("Show More")', 'a:has-text("Show More")', '.show-more', '.load-more']
        for selector in show_more_selectors:
            try:
                buttons = page.locator(selector).all()
                for btn in buttons:
                    try:
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            page.wait_for_timeout(2000)
                    except Exception:
                        continue
            except Exception:
                continue
        
        # Get full page text
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        full_page_text = soup.get_text()

        # Verify effectivity date in header (if present)
        status = header_date_status(full_page_text, soup)
        eff = extract_effectivity_date(full_page_text, soup)
        eff_iso = eff.isoformat() if eff else None
        if DEBUG_HEADER:
            print(f"Extracted effectivity date: {eff_iso}")
        if status == 'past':
            if not silent:
                print("   ℹ️ Header date is before today; no new Rotational Brownout alerts for today.")
            return brownouts_by_area
        
        # Use HTML source position for accurate ordering
        html_str = str(soup)
        time_pattern = r'Between\s+\d{1,2}:\d{2}(?:AM|PM)\s+and\s+\d{1,2}:\d{2}(?:AM|PM)'
        
        # Find all time ranges with their positions in HTML source
        time_headers = []
        for match in re.finditer(time_pattern, html_str, re.I):
            time_headers.append({
                'pos': match.start(),
                'time': match.group(0)
            })
        
        # Simple search: check if area name appears anywhere on page
        for area in search_keywords:
            # Try to find elements that contain the area name and extract a nearby date
            area_pattern = re.compile(rf"\b{re.escape(area)}\b", re.I)
            localized_found = False
            
            # Find ALL positions of area in HTML source
            area_matches = list(area_pattern.finditer(html_str))
            if not area_matches:
                area_matches = list(re.finditer(re.escape(area), html_str, re.I))
            
            # Collect all unique time windows for this area
            time_ranges = []
            if area_matches:
                for area_match in area_matches:
                    area_pos = area_match.start()
                    
                    # Find the closest preceding time header for this occurrence
                    closest_time = None
                    closest_distance = float('inf')
                    
                    for time_info in time_headers:
                        if time_info['pos'] < area_pos:
                            distance = area_pos - time_info['pos']
                            if distance < closest_distance:
                                closest_distance = distance
                                closest_time = time_info['time']
                    
                    if closest_time and closest_time not in time_ranges:
                        time_ranges.append(closest_time)
                
                time_range = ', '.join(time_ranges) if time_ranges else None
                
                # Now find the actual soup elements for date extraction
                matches = soup.find_all(string=area_pattern)
                if not matches:
                    matches = soup.find_all(string=re.compile(re.escape(area), re.I))
                
                if matches:
                    # Use the last match to correspond with our HTML position logic
                    m = matches[-1] if len(matches) > 1 else matches[0]

                    # 2. Walk up a few levels to find date in the same block
                    curr = m.parent
                    for _ in range(4):
                        if curr is None:
                            break
                        block_text = curr.get_text(separator=' ', strip=True)
                        eff_local = extract_effectivity_date(block_text, curr)
                        status_local = header_date_status(block_text, curr)
                        
                        if DEBUG_HEADER:
                            snippet = block_text[:200].replace('\n', ' ')
                            print(f"DEBUG: matched element snippet: {snippet}")
                            print(f"DEBUG: local extracted date: {eff_local}, status: {status_local}")
                        
                        if eff_local or status_local:
                            title_ext = f" - {time_range}" if time_range else ""
                            brownout_info = {
                                'title': f"Rotational Brownout - {area}{title_ext}",
                                'url': brownout_url,
                                'effectivity_date': eff_local.isoformat() if eff_local else None,
                                'header_status': status_local
                            }
                            brownouts_by_area[area].append(brownout_info)
                            localized_found = True
                            break
                        curr = curr.parent
                    if localized_found:
                        break

            # If nothing found in ancestors, search nearby siblings and previous content
            if not localized_found and matches:
                for m in matches:
                    anc = m.parent
                    # search this ancestor and its nearby siblings for date-like text
                    nearby_checked = []
                    for ancestor in [anc] + ([anc.parent] if anc and anc.parent else []):
                        if ancestor is None:
                            continue
                        # check text nodes in ancestor
                        for text_node in ancestor.find_all(string=True):
                            if re.search(r'[A-Za-z]{3,9}\s+\d{1,2},?\s*\d{4}', text_node, re.I):
                                txt = text_node.strip()
                                if DEBUG_HEADER:
                                    print(f"DEBUG: nearby text_node match: {txt[:120]}")
                                eff_local = extract_effectivity_date(txt, None)
                                status_local = header_date_status(txt, None)
                                if eff_local or status_local:
                                    title_ext = f" - {time_range}" if time_range else ""
                                    brownout_info = {
                                        'title': f"Rotational Brownout - {area}{title_ext}",
                                        'url': brownout_url,
                                        'effectivity_date': eff_local.isoformat() if eff_local else None,
                                        'header_status': status_local
                                    }
                                    brownouts_by_area[area].append(brownout_info)
                                    localized_found = True
                                    break
                        if localized_found:
                            break
                        # check previous siblings
                        sib_count = 0
                        for sib in ancestor.previous_siblings:
                            if sib_count > 6:
                                break
                            try:
                                stext = sib.get_text(separator=' ', strip=True)
                            except Exception:
                                stext = str(sib)
                            if re.search(r'[A-Za-z]{3,9}\s+\d{1,2},?\s*\d{4}', stext, re.I):
                                if DEBUG_HEADER:
                                    print(f"DEBUG: previous_sibling match: {stext[:120]}")
                                eff_local = extract_effectivity_date(stext, None)
                                status_local = header_date_status(stext, None)
                                if eff_local or status_local:
                                    title_ext = f" - {time_range}" if time_range else ""
                                    brownout_info = {
                                        'title': f"Rotational Brownout - {area}{title_ext}",
                                        'url': brownout_url,
                                        'effectivity_date': eff_local.isoformat() if eff_local else None,
                                        'header_status': status_local
                                    }
                                    brownouts_by_area[area].append(brownout_info)
                                    localized_found = True
                                    break
                            sib_count += 1
                        if localized_found:
                            break
                    if localized_found:
                        break

            # Fallback: simple page-level search
            if not localized_found:
                if area.lower() in full_page_text.lower():
                    title_ext = f" - {time_range}" if time_range else ""
                    brownout_info = {
                        'title': f"Rotational Brownout - {area}{title_ext}",
                        'url': brownout_url,
                        'effectivity_date': eff_iso,
                        'header_status': status
                    }
                    brownouts_by_area[area].append(brownout_info)
                    if not silent:
                        print(f"   ⚡ FOUND: {area} appears on Rotational Brownout page")
                elif not silent:
                    print(f"   ✓ {area} not found on Rotational Brownout page")
    
    except Exception as e:
        if not silent:
            print(f"   ⚠️ Error checking brownouts: {e}")
    
    return brownouts_by_area


def check_alerts(search_keywords, send_telegram=False, bot_token=None, chat_id=None, silent=False):
    """Main function to check alerts"""
    if isinstance(search_keywords, str):
        search_keywords = [kw.strip() for kw in search_keywords.split(',')]
    
    if not silent:
        print(f"--- Checking Meralco Alerts for: '{', '.join(search_keywords)}' ---")
        print("🔄 Loading pages and executing JavaScript...")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Check both types of alerts
            alerts_by_area = check_yellow_red_alerts(page, search_keywords, silent)
            brownouts_by_area = check_rotational_brownout(page, search_keywords, silent)
            
            browser.close()
            
            # Combine all alerts
            all_alerts_by_area = {}
            for area in search_keywords:
                combined = alerts_by_area.get(area, []) + brownouts_by_area.get(area, [])
                if combined:
                    all_alerts_by_area[area] = combined
            
            total_alerts = sum(len(alerts) for alerts in all_alerts_by_area.values())
            
            if not silent:
                print(f"\n📊 Total alerts: {total_alerts}")
                for area, alerts in all_alerts_by_area.items():
                    print(f"  - {area}: {len(alerts)} alert(s)")
            
            # Smart Telegram notification with alert tracking
            if send_telegram and bot_token and chat_id:
                # Load previous alerts
                previous_data = load_alert_history()
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if not silent:
                    if previous_data:
                        print(f"\n📁 Loaded alert history from: {CACHE_FILE}")
                        print(f"   Last check: {previous_data.get('last_check', 'unknown')}")
                    else:
                        print(f"\n📁 No previous history found (first run)")
                
                # Categorize alerts
                all_new = []
                all_same = []
                message_parts = []
                
                for area in search_keywords:
                    area_alerts_yellow = alerts_by_area.get(area, [])
                    area_alerts_brownout = brownouts_by_area.get(area, [])
                    combined_alerts = area_alerts_yellow + area_alerts_brownout
                    
                    categories = categorize_alerts(combined_alerts, previous_data, area)
                    all_new.extend(categories['new'])
                    all_same.extend(categories['same'])

                    if not silent:
                        print(f"\n🔍 {area}: {len(combined_alerts)} alert(s)")
                        print(f"   🆕 New: {len(categories['new'])}")
                        print(f"   ♻️ Same: {len(categories['same'])}")

                    # Generate message for this area exactly as requested
                    message_parts.append(f"<b>{area}</b>")
                    
                    # 1. Yellow/Red Alerts Source
                    if area_alerts_yellow:
                        for alert in area_alerts_yellow:
                            status_label = "🚨 NEW" if alert in categories['new'] else "⚠️ Ongoing"
                            message_parts.append(f"  • {status_label}: {alert['title']}")
                            if alert.get('effectivity_date') or alert.get('header_status'):
                                message_parts.append(f"    🗓️ {alert.get('effectivity_date') or 'unknown'} ({alert.get('header_status') or 'no-date'})")
                            message_parts.append(f"    🔗 <a href='{alert['url']}'>View Source</a>")
                    else:
                        message_parts.append(f"  ✅ No Yellow/Red Alert for the searched areas")

                    # 2. Rotational Brownout Source
                    if area_alerts_brownout:
                        for alert in area_alerts_brownout:
                            status_label = "🚨 NEW" if alert in categories['new'] else "⚠️ Ongoing"
                            message_parts.append(f"  • {status_label}: {alert['title']}")
                            if alert.get('effectivity_date') or alert.get('header_status'):
                                message_parts.append(f"    🗓️ {alert.get('effectivity_date') or 'unknown'} ({alert.get('header_status') or 'no-date'})")
                            message_parts.append(f"    🔗 <a href='{alert['url']}'>View Source</a>")
                    else:
                        message_parts.append(f"  ✅ No Rotational Brownout for the searched areas")
                    
                    message_parts.append("") # Spacer between areas
                
                # Build and send message
                if message_parts:
                    if all_new:
                        header = f"🚨 <b>URGENT: Meralco Power Alert</b>\n\n"
                    elif all_same:
                        header = f"⚠️ <b>Meralco Alert Update</b>\n\n"
                    else:
                        header = f"⚡ <b>Meralco Alert Status</b>\n\n"
                    
                    message = header
                    message += f"🕐 <b>Checked:</b> {timestamp}\n\n"
                    message += '\n'.join(message_parts)
                    
                    success = send_telegram_message(bot_token, chat_id, message)
                    if not silent:
                        if success:
                            alert_type = "new" if all_new else "ongoing"
                            print(f"✅ Telegram notification sent successfully ({alert_type} alerts)")
                        else:
                            print("⚠️ Failed to send Telegram notification")
                
                # Update cache
                current_data = {
                    'last_check': timestamp,
                    'areas': {}
                }
                for area, alerts in all_alerts_by_area.items():
                    current_data['areas'][area] = [alert['title'] for alert in alerts]
                
                save_alert_history(current_data)
                
                if not silent:
                    total_cached = sum(len(titles) for titles in current_data['areas'].values())
                    print(f"💾 Saved {total_cached} alert titles to cache: {CACHE_FILE}")
            
            return total_alerts, all_alerts_by_area
                
        except Exception as e:
            error_msg = f"❌ Error: {e}"
            print(error_msg)
            return 0, {}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Check Meralco alerts for specific areas')
    parser.add_argument('search_areas', help='Comma-separated areas to search for (e.g., "Cavite,Manila")')
    parser.add_argument('--telegram', action='store_true', help='Send Telegram notification if alerts found')
    parser.add_argument('--bot-token', help='Telegram bot token')
    parser.add_argument('--chat-id', help='Telegram chat ID')
    parser.add_argument('--silent', action='store_true', help='Minimal output (no debug info)')
    parser.add_argument('--debug', action='store_true', help='Print header snippet and date-detection diagnostics')
    
    args = parser.parse_args()
    # Global debug flag for header inspection
    DEBUG_HEADER = args.debug or bool(os.environ.get('DEBUG_HEADER'))
    
    # Resolve Telegram credentials from CLI args or environment variables
    bot_token = args.bot_token or os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
    chat_id = args.chat_id or os.environ.get('TELEGRAM_CHAT_ID') or os.environ.get('CHAT_ID')

    # Report credential sources for diagnostics (don't print raw token)
    if bot_token:
        bot_source = 'cli' if args.bot_token else 'env'
        print(f"🔐 Telegram bot token provided (source: {bot_source})")
    else:
        print("⚠️ [WARN] No Telegram bot token found in CLI args or TELEGRAM_BOT_TOKEN env")

    if chat_id:
        chat_source = 'cli' if args.chat_id else 'env'
        print(f"🔔 Telegram chat id provided (source: {chat_source})")
    else:
        print("⚠️ [WARN] No Telegram chat id found in CLI args or TELEGRAM_CHAT_ID env")

    if args.telegram and not (bot_token and chat_id):
        print("⚠️ [WARN] --telegram requested but credentials missing; sending will be skipped.")

    total, alerts = check_alerts(
        args.search_areas,
        send_telegram=args.telegram,
        bot_token=bot_token,
        chat_id=chat_id,
        silent=args.silent
    )
    
    sys.exit(0 if total >= 0 else 1)
