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

# HTML fallback: same parameters
OPENINSIDER_SCREENER_URL = "http://openinsider.com/screener"

OPENINSIDER_HTML_URL = (
    "http://openinsider.com/screener?"
    "s=&o=&pl=&ph=&ll=&lh=&fd=3&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&"
    "xp=1&vl=10&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&"
    "grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&"
    "sortcol=0&cnt=100&action=1"
)


def _build_openinsider_payload() -> dict[str, str]:
    """Create a default OpenInsider screener payload from the live form."""
    resp = requests.get(OPENINSIDER_HTML_URL, headers=HEADERS_HTTP, timeout=60)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form", action="/screener")
    if not form:
        raise ValueError("OpenInsider form not found")

    payload: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        typ = inp.get("type", "text")
        if typ == "checkbox":
            if inp.has_attr("checked") or inp.get("value"):
                payload[name] = inp.get("value", "1")
            continue
        payload[name] = inp.get("value", "")

    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        option = sel.find("option", selected=True) or sel.find("option")
        payload[name] = option.get("value", "") if option else ""

    payload.update({"action": "1", "page": "1", "cnt": "100", "xp": "1"})
    return payload


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
    payload = _build_openinsider_payload()
    payload["type"] = "csv"
    resp = requests.post(OPENINSIDER_SCREENER_URL, headers=HEADERS_HTTP, data=payload, timeout=60)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "text/csv" not in content_type and not resp.text.strip().startswith("X"):  # maybe HTML
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
    payload = _build_openinsider_payload()
    resp = requests.post(OPENINSIDER_SCREENER_URL, headers=HEADERS_HTTP, data=payload, timeout=60)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    trades = []
    target_table = soup.find("table", class_="tinytable")
    header_map = None

    if target_table is not None:
        header = target_table.find("tr")
        cols = [th.get_text(strip=True).replace("\xa0", " ").lower() for th in header.find_all(["th", "td"])]
        header_map = {name: idx for idx, name in enumerate(cols)}
    else:
        # Fallback: scan all tables when class-based selection fails
        for table in soup.find_all("table"):
            header = table.find("tr")
            if not header:
                continue
            cols = [th.get_text(strip=True).replace("\xa0", " ").lower() for th in header.find_all(["th", "td"])]
            if all(h in " ".join(cols) for h in ("trade date", "ticker", "insider name")):
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
