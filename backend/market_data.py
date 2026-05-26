"""
market_data.py
--------------
Fetches ATR%, daily dollar volume, and 52-week high for a ticker.
Uses Polygon.io as primary source (better TSX coverage than yfinance).
Falls back to yfinance if Polygon key is not set or call fails.
"""

import logging
import os
import time
import requests
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
POLYGON_BASE    = "https://api.polygon.io"

# Polygon free plan: 5 requests/minute → 12s between calls
_POLYGON_MIN_INTERVAL = 12.0
_last_polygon_call: float = 0.0


def get_market_data(ticker: str) -> dict | None:
    """
    Fetch market data for a ticker and return:
      - last_close       : most recent closing price
      - atr_pct          : 14-day ATR as % of close
      - dollar_volume_m  : last day's dollar volume in $M
      - high_52w         : 52-week high
    """
    # Generate symbol variants based on possible TradingView exchange prefixes
    # and common Yahoo/Polygon suffixes. We return variants ordered by
    # best-guess for the exchange first (so the first successful hit is used).
    def _generate_variants(raw: str) -> list[str]:
        raw = raw.strip()
        # If caller already provided a dotted suffix (e.g. ORE.TO) or a full
        # TradingView format (TSX:ORE), normalize but keep as-is first.
        if ':' in raw:
            exch, base = raw.split(':', 1)
            exch = exch.upper()
            base = base.upper()
        else:
            exch = None
            base = raw.upper()

        # Suffix candidates in rough preference order
        common_suffixes = ["", ".TO", ".V", ".CN", ".NS", ".L", ".AX", ".DE"]

        # Exchange-specific ordering
        if exch in ("TSX", "TSE"):
            prefs = ["", ".TO", ".CN", ".V"]
        elif exch in ("TSXV", "TSV", "V"):
            prefs = ["", ".V", ".TO", ".CN"]
        elif exch in ("CSE", "CVE"):
            prefs = ["", ".V", ".TO"]
        elif exch in ("NYSE", "NASDAQ", "AMEX") or exch is None and len(base) <= 5:
            # US tickers typically work without suffix
            prefs = ["", ".TO", ".V"]
        elif exch in ("LON", "XLON"):
            prefs = ["", ".L"]
        elif exch in ("FRA", "XETR"):
            prefs = ["", ".DE"]
        elif exch in ("ASX",):
            prefs = ["", ".AX"]
        else:
            prefs = common_suffixes

        variants = []
        # If raw already contains a dot-suffix, prefer that exact string first
        if '.' in raw and raw.upper() not in variants:
            variants.append(raw.upper())

        for sfx in prefs:
            cand = f"{base}{sfx}"
            if cand not in variants:
                variants.append(cand)

        # Deduplicate and return
        return variants

    variants = _generate_variants(ticker)
    logger.debug(f"Generated market-data variants for {ticker}: {variants}")

    # 1) Try Polygon for each variant (if available)
    if POLYGON_API_KEY:
        for v in variants:
            try:
                logger.debug(f"Trying Polygon for variant: {v}")
                res = _get_from_polygon(v)
                if res:
                    res["ticker"] = v
                    logger.info(f"Polygon hit for {ticker} -> {v}")
                    return res
            except Exception as e:
                logger.debug(f"Polygon variant {v} failed: {e}")
        logger.warning(f"Polygon failed for variants of {ticker}, trying yfinance fallback...")

    # 2) Try yfinance for each variant with a small retry loop
    for v in variants:
        attempts = 0
        while attempts < 3:
            try:
                logger.debug(f"Trying yfinance for variant: {v} (attempt {attempts+1})")
                res = _get_from_yfinance(v)
                if res:
                    res["ticker"] = v
                    logger.info(f"yfinance hit for {ticker} -> {v}")
                    return res
                # if None, break retry loop for this variant (likely no data)
                break
            except Exception as e:
                attempts += 1
                wait = 1 * (2 ** attempts)
                logger.warning(f"yfinance attempt {attempts} failed for {v}: {e} — retrying in {wait}s")
                time.sleep(wait)

    # Nothing found
    return None


def _get_from_polygon(ticker: str) -> dict | None:
    global _last_polygon_call
    elapsed = time.time() - _last_polygon_call
    if elapsed < _POLYGON_MIN_INTERVAL:
        wait = _POLYGON_MIN_INTERVAL - elapsed
        time.sleep(wait)
    _last_polygon_call = time.time()

    try:
        polygon_ticker = ticker.replace(".TO", "").replace(".V", "")
        to_date   = date.today()
        from_date = to_date - timedelta(days=90)
        url = (
            f"{POLYGON_BASE}/v2/aggs/ticker/{polygon_ticker}/range/1/day"
            f"/{from_date}/{to_date}"
            f"?adjusted=true&sort=asc&limit=120&apiKey={POLYGON_API_KEY}"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if len(results) < 15: return None

        closes  = [r["c"] for r in results]
        highs   = [r["h"] for r in results]
        volumes = [r["v"] for r in results]

        recent = results[-15:]
        tr_list = []
        for i in range(1, len(recent)):
            h, l, pc = recent[i]["h"], recent[i]["l"], recent[i-1]["c"]
            tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))

        atr        = sum(tr_list) / len(tr_list)
        last_close = closes[-1]
        atr_pct    = (atr / last_close) * 100
        dollar_volume_m = (last_close * volumes[-1]) / 1_000_000
        high_52w        = max(highs)

        return {
            "ticker":          ticker,
            "last_close":      round(last_close, 2),
            "atr_pct":         round(atr_pct, 2),
            "dollar_volume_m": round(dollar_volume_m, 1),
            "high_52w":        round(high_52w, 2),
        }
    except Exception as e:
        logger.warning(f"Polygon failed: {e}")
        return None


def _get_from_yfinance(ticker: str) -> dict | None:
    try:
        import yfinance as yf
        data = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        if data.empty or len(data) < 15: return None

        if hasattr(data.columns, "levels"): data.columns = data.columns.droplevel(1)
        
        last_close = float(data["Close"].iloc[-1])
        recent = data.tail(15)
        tr_list = []
        for i in range(1, len(recent)):
            h, l, pc = float(recent["High"].iloc[i]), float(recent["Low"].iloc[i]), float(recent["Close"].iloc[i-1])
            tr_list.append(max(h-l, abs(h-pc), abs(l-pc)))
        
        atr = sum(tr_list) / len(tr_list)
        atr_pct = (atr / last_close) * 100
        dollar_volume_m = (last_close * float(data["Volume"].iloc[-1])) / 1_000_000
        high_52w = float(data["High"].max())

        return {
            "ticker": ticker,
            "last_close": round(last_close, 2),
            "atr_pct": round(atr_pct, 2),
            "dollar_volume_m": round(dollar_volume_m, 1),
            "high_52w": round(high_52w, 2),
        }
    except Exception as e:
        logger.warning(f"yfinance failed: {e}")
        return None


def get_spy_gap(on_date: date | None = None) -> float:
    """
    Returns the SPY gap percentage: ((Open - Prev Close) / Prev Close) * 100.
    """
    import yfinance as yf
    try:
        ticker = "SPY"
        if on_date:
            start = on_date - timedelta(days=7)
            end   = on_date + timedelta(days=2)
            df = yf.download(ticker, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), progress=False)
            if df.empty: return 0.0
            
            on_date_str = on_date.strftime("%Y-%m-%d")
            found_idx = -1
            for i, dt in enumerate(df.index):
                if dt.strftime("%Y-%m-%d") == on_date_str:
                    found_idx = i
                    break
            
            if found_idx <= 0: return 0.0
            prev_close_val = df.iloc[found_idx - 1]["Close"]
            open_price_val = df.iloc[found_idx]["Open"]
            prev_close = float(prev_close_val.iloc[0]) if hasattr(prev_close_val, 'iloc') else float(prev_close_val)
            open_price = float(open_price_val.iloc[0]) if hasattr(open_price_val, 'iloc') else float(open_price_val)
        else:
            df = yf.download(ticker, period="5d", progress=False)
            if df.empty or len(df) < 2: return 0.0
            prev_close_val = df.iloc[-2]["Close"]
            open_price_val = df.iloc[-1]["Open"]
            prev_close = float(prev_close_val.iloc[0]) if hasattr(prev_close_val, 'iloc') else float(prev_close_val)
            open_price = float(open_price_val.iloc[0]) if hasattr(open_price_val, 'iloc') else float(open_price_val)

        gap = ((open_price - prev_close) / prev_close) * 100
        logger.info(f"SPY Gap OK: {gap:.2f}%")
        return gap
    except Exception as e:
        logger.error(f"SPY Gap Error: {e}")
        return 0.0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(get_spy_gap())
