"""
scraper.py
----------
Fetches today's insider BUY transactions from OpenInsider.com.
Returns a list of dicts — one per trade.
"""

import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

OPENINSIDER_URL = (
    "http://openinsider.com/screener?"
    "s=&o=&pl=&ph=&ll=&lh=&fd=1&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&"
    "xp=1&vl=30&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&"
    "grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&"
    "sortcol=0&cnt=100&action=1"
)
# This URL filters for:
# - Only PURCHASES (xp=1)
# - Dollar volume >= $30M (vl=30)
# - Last 1 day (fd=1)
# - 100 results

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def fetch_insider_buys() -> list[dict]:
    """
    Scrape OpenInsider for recent insider purchases.
    Returns list of trade dicts with keys:
      ticker, company, insider_name, title, trade_date,
      shares, price, value
    """
    logger.info("Fetching insider buys from OpenInsider...")

    resp = requests.get(OPENINSIDER_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # The results table has class "tinytable"
    table = soup.find("table", {"class": "tinytable"})
    if not table:
        logger.warning("Could not find insider trades table on OpenInsider")
        return []

    trades = []
    rows = table.find_all("tr")[1:]  # skip header row

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 16:
            continue

        try:
            # OpenInsider column order (0-indexed):
            # 0=X, 1=Filing Date, 2=Trade Date, 3=Ticker, 4=Company Name,
            # 5=Insider Name, 6=Title, 7=Trade Type, 8=Price, 9=Qty,
            # 10=Owned, 11=ΔOwn, 12=Value, ...

            trade_type = cells[7].get_text(strip=True)
            if trade_type != "P - Purchase":
                continue  # only buys

            ticker = cells[3].get_text(strip=True)
            company = cells[4].get_text(strip=True)
            insider_name = cells[5].get_text(strip=True)
            title = cells[6].get_text(strip=True)
            trade_date_str = cells[2].get_text(strip=True)
            price_str = cells[8].get_text(strip=True).replace("$", "").replace(",", "")
            qty_str = cells[9].get_text(strip=True).replace(",", "").replace("+", "")
            value_str = cells[12].get_text(strip=True).replace("$", "").replace(",", "")

            # Parse numbers safely
            price = float(price_str) if price_str else 0.0
            qty = float(qty_str) if qty_str else 0.0
            value = float(value_str) if value_str else (price * qty)

            # Parse date
            try:
                trade_date = datetime.strptime(trade_date_str, "%Y-%m-%d").date()
            except ValueError:
                trade_date = date.today()

            trades.append({
                "ticker": ticker,
                "company": company,
                "insider_name": insider_name,
                "title": title,
                "trade_date": trade_date,
                "shares": qty,
                "price": price,
                "value": value,  # total $ value of trade
            })

        except (ValueError, IndexError) as e:
            logger.debug(f"Skipped malformed row: {e}")
            continue

    logger.info(f"Found {len(trades)} insider purchases")
    return trades


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    buys = fetch_insider_buys()
    for b in buys[:5]:
        print(b)