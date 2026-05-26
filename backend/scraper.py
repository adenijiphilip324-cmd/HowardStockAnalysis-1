"""
scraper.py
----------
Fetches recent insider BUY transactions from OpenInsider.com.

Strategy:
  1. Try the CSV export endpoint first (faster, less likely to timeout)
  2. Fall back to HTML table scraping if CSV fails
Returns a list of dicts — one per trade.
"""

import logging
import io
import csv
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# CSV export: last 3 days, purchases only, dollar volume >= $10M
OPENINSIDER_CSV_URL = (
    "http://openinsider.com/screener?"
    "s=&o=&pl=&ph=&ll=&lh=&fd=3&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&"
    "xp=1&vl=10&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&"
    "grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&"
    "sortcol=0&cnt=100&action=1&"
    "type=csv"  # request CSV
)

# HTML fallback: same parameters
OPENINSIDER_HTML_URL = (
    "http://openinsider.com/screener?"
    "s=&o=&pl=&ph=&ll=&lh=&fd=3&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&"
    "xp=1&vl=10&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&"
    "grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&"
    "sortcol=0&cnt=100&action=1"
)


def _parse_value(s: str) -> float:
    """Parse a dollar/number string like '$1,234,567' or '12,345' to float."""
    return float(s.replace("$", "").replace(",", "").replace("+", "").strip() or "0")


def _parse_date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return date.today()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=60))
def _try_csv() -> list[dict] | None:
    """Try fetching OpenInsider as CSV. Returns list or None on failure."""
    logger.info("Attempting OpenInsider CSV export...")
    resp = requests.get(OPENINSIDER_CSV_URL, headers=HEADERS_HTTP, timeout=60)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    # OpenInsider may return HTML even for type=csv if it ignores the param
    if "text/csv" not in content_type and not resp.text.strip().startswith("X"):
        # Looks like HTML, not CSV
        logger.warning("CSV endpoint returned HTML — will try HTML scraper")
        return None

    trades = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        try:
            trade_type = row.get("Trade Type", "").strip()
            if "P" not in trade_type:
                continue  # only purchase types
            trades.append({
                "ticker":       row.get("Ticker", "").strip(),
                "company":      row.get("Company Name", "").strip(),
                "insider_name": row.get("Insider Name", "").strip(),
                "title":        row.get("Title", "").strip(),
                "trade_date":   _parse_date(row.get("Trade Date", "")),
                "shares":       _parse_value(row.get("Qty", "0")),
                "price":        _parse_value(row.get("Price", "0")),
                "value":        _parse_value(row.get("Value", "0")),
            })
        except (KeyError, ValueError) as e:
            logger.debug(f"Skipped CSV row: {e}")
    return trades


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=60))
def _try_html() -> list[dict]:
    """Scrape OpenInsider HTML table. Returns list (may be empty)."""
    logger.info("Fetching insider buys from OpenInsider (HTML)...")
    resp = requests.get(OPENINSIDER_HTML_URL, headers=HEADERS_HTTP, timeout=60)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    # Find a table that looks like the OpenInsider screener table by matching header names
    tables = soup.find_all("table")
    trades = []
    target_table = None
    header_map = None

    for table in tables:
        header = table.find("tr")
        if not header:
            continue
        cols = [th.get_text(strip=True).lower() for th in header.find_all(["th", "td"])]
        # Look for key headers present in OpenInsider tables
        if any(h in " ".join(cols) for h in ("trade date", "ticker", "insider name")):
            target_table = table
            header_map = {name: idx for idx, name in enumerate(cols)}
            break

    if not target_table or not header_map:
        logger.warning("Could not find insider trades table on OpenInsider")
        return []

    rows = target_table.find_all("tr")[1:]
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) < 5:
            continue
        try:
            # Determine trade type column (try several common names)
            trade_type = None
            for key in ("trade type", "type"):
                if key in header_map:
                    trade_type = cells[header_map[key]]
                    break
            # If not found, try to infer from nearby columns
            if not trade_type and len(cells) > 7:
                trade_type = cells[7]

            if not trade_type or "purchase" not in trade_type.lower() and "p -" not in trade_type.lower():
                continue

            def get_cell(name_candidates, default=""):
                for n in name_candidates:
                    if n in header_map:
                        idx = header_map[n]
                        if idx < len(cells):
                            return cells[idx]
                return default

            trade_date = _parse_date(get_cell(["trade date", "date"]))
            ticker = get_cell(["ticker", "symbol"]).upper()
            company = get_cell(["company name", "company"]) or ""
            insider_name = get_cell(["insider name", "owner"]) or ""
            title = get_cell(["title"]) or ""
            price = _parse_value(get_cell(["price"]))
            qty = _parse_value(get_cell(["qty", "shares"]))
            value = _parse_value(get_cell(["value"]))

            trades.append({
                "ticker":       ticker,
                "company":      company,
                "insider_name": insider_name,
                "title":        title,
                "trade_date":   trade_date,
                "shares":       qty,
                "price":        price,
                "value":        value if value else (price * qty),
            })
        except Exception as e:
            logger.debug(f"Skipped malformed row: {e}")

    logger.info(f"Found {len(trades)} insider purchases (HTML)")
    return trades


def fetch_insider_buys() -> list[dict]:
    """
    Main entry: scrape OpenInsider for recent insider purchases.
    Tries CSV export first for speed, falls back to HTML table scraping.
    Returns list of trade dicts.
    """
    # --- Try CSV first ---
    try:
        csv_result = _try_csv()
        if csv_result is not None:
            logger.info(f"Found {len(csv_result)} insider purchases (CSV)")
            return csv_result
    except Exception as e:
        logger.warning(f"CSV export failed: {e}; falling back to HTML")

    # --- Fallback: HTML ---
    return _try_html()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    buys = fetch_insider_buys()
    for b in buys[:5]:
        print(b)
