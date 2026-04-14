"""
NSE India Market Holidays configuration.
Automatically fetches, tracks, and caches official NSE holidays year over year.
"""
import os
import json
import logging
from datetime import datetime, date
import requests

logger = logging.getLogger("HolidaysTracker")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "nse_holidays.json")

# Fallback holidays for 2026 (Bootstrap)
FALLBACK_HOLIDAYS = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id (Eid ul-Adha)",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}

def fetch_nse_holidays(year: int) -> dict:
    """Fetch official holiday calendar from NSE India."""
    url = "https://www.nseindia.com/api/holiday-master?type=trading"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays"
    }
    try:
        # Establish session to get cookies first (NSE blocks direct API hits)
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        response = session.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            holidays = {}
            # Parse 'CMRS' (Capital Market) holidays
            for h in data.get("CMRS", []):
                # NSE returns parsing formats like '26-Jan-2026'
                try:
                    dt = datetime.strptime(h.get("tradingDate"), "%d-%b-%Y")
                    if dt.year == year:
                        holidays[dt.strftime("%Y-%m-%d")] = h.get("description")
                except Exception:
                    continue
            if holidays:
                return holidays
    except Exception as e:
        logger.debug(f"Failed to fetch NSE holidays from API: {e}")
        
    return {}

def _get_annual_holidays() -> dict:
    """Retrieve holidays, preferring a cached copy for the current year. Updates dynamically."""
    current_year = datetime.now().year
    
    # Ensure cache directory exists
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    
    # 1. Try to load from cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                if data.get("year") == current_year and data.get("holidays"):
                    return data["holidays"]
        except Exception:
            pass
            
    # 2. If no cache or year rolled over, fetch new ones automatically
    logger.info(f"Year rolled over -> Auto-fetching {current_year} NSE Holidays...")
    fresh_holidays = fetch_nse_holidays(current_year)
    
    if not fresh_holidays:
        logger.warning(f"Could not reach NSE. Falling back to internal bootstrap holidays.")
        fresh_holidays = FALLBACK_HOLIDAYS if current_year == 2026 else {}
        
    # 3. Save to cache
    if fresh_holidays:
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump({"year": current_year, "holidays": fresh_holidays}, f, indent=4)
        except Exception:
            pass
            
    return fresh_holidays

def get_holiday_status() -> dict:
    """Returns today's holiday status and the next upcoming holiday dynamically."""
    holidays = _get_annual_holidays()
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    is_holiday_today = today_str in holidays
    today_holiday_name = holidays.get(today_str, None)
    
    # Find next upcoming holiday
    upcoming_holiday = None
    days_until = None
    today_date = datetime.now().date()
    
    for date_str, name in sorted(holidays.items()):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            if dt > today_date:
                upcoming_holiday = {"date": date_str, "name": name}
                days_until = (dt - today_date).days
                break
        except Exception:
            continue
            
    return {
        "is_holiday_today": is_holiday_today,
        "today_holiday_name": today_holiday_name,
        "upcoming_holiday": upcoming_holiday,
        "days_until": days_until
    }
