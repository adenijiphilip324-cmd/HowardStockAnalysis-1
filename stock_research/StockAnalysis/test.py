"""
test_run.py
-----------
Run this to test the scanner without needing Airtable or Zapier.
Works fully offline using sample data if internet is unavailable.

Usage:
    python test_run.py
"""

import logging
from datetime import date
from scorer import score_trade, detect_repeat_buys, count_same_day_insiders

logging.basicConfig(level=logging.WARNING)  # suppress yfinance noise


# ── Sample market data (used when yfinance is unavailable) ───────────────────
SAMPLE_MARKET_DATA = {
    "ACB.TO":  {"ticker": "ACB.TO",  "last_close": 1.85, "atr_pct": 9.2,  "dollar_volume_m": 42.0,  "high_52w": 3.20},
    "SU.TO":   {"ticker": "SU.TO",   "last_close": 4.50, "atr_pct": 7.8,  "dollar_volume_m": 68.0,  "high_52w": 6.50},
    "SHOP.TO": {"ticker": "SHOP.TO", "last_close": 8.90, "atr_pct": 4.5,  "dollar_volume_m": 55.0,  "high_52w": 12.40},
    "CNQ.TO":  {"ticker": "CNQ.TO",  "last_close": 3.20, "atr_pct": 12.1, "dollar_volume_m": 90.0,  "high_52w": 5.10},
}

SAMPLE_TRADES = [
    {"ticker": "ACB.TO",  "company": "Aurora Cannabis Inc",    "insider_name": "Miguel Martin",       "title": "CEO",              "trade_date": date.today(), "shares": 50000, "price": 1.85, "value": 92500},
    {"ticker": "SU.TO",   "company": "Suncor Energy Inc",      "insider_name": "Rich Kruger",         "title": "President & CEO",  "trade_date": date.today(), "shares": 20000, "price": 4.50, "value": 90000},
    {"ticker": "SU.TO",   "company": "Suncor Energy Inc",      "insider_name": "Kris Smith",          "title": "CFO",              "trade_date": date.today(), "shares": 10000, "price": 4.50, "value": 45000},
    {"ticker": "SHOP.TO", "company": "Shopify Inc",            "insider_name": "Harley Finkelstein",  "title": "President",        "trade_date": date.today(), "shares": 5000,  "price": 8.90, "value": 44500},
    {"ticker": "CNQ.TO",  "company": "Canadian Natural Res",   "insider_name": "Steve Laut",          "title": "Executive Vice Chairman", "trade_date": date.today(), "shares": 30000, "price": 3.20, "value": 96000},
    {"ticker": "CNQ.TO",  "company": "Canadian Natural Res",   "insider_name": "Tim McKay",           "title": "CEO",              "trade_date": date.today(), "shares": 25000, "price": 3.20, "value": 80000},
    {"ticker": "CNQ.TO",  "company": "Canadian Natural Res",   "insider_name": "Mark Stainthorpe",    "title": "CFO",              "trade_date": date.today(), "shares": 15000, "price": 3.20, "value": 48000},
]


def run_test(use_live=True):
    print("\n" + "=" * 65)
    print("  INSIDER SCANNER — TEST RUN (no Airtable, no Zapier)")
    print("=" * 65 + "\n")

    # ── Step 1: Get trades ───────────────────────────────────────
    trades = []
    if use_live:
        print("Step 1: Trying to scrape OpenInsider for today's buys...")
        try:
            from scraper import fetch_insider_buys
            trades = fetch_insider_buys()
            print(f"  ✅ Scraped {len(trades)} live trades")
        except Exception as e:
            print(f"  ⚠️  Live scrape failed ({type(e).__name__}) — using sample data")

    if not trades:
        print("Step 1: Using sample trades (realistic test data)...")
        trades = SAMPLE_TRADES
        print(f"  ✅ Loaded {len(trades)} sample trades")

    print()

    # ── Step 2: Get market data ──────────────────────────────────
    print("Step 2: Getting ATR and volume data...")
    market_cache = {}
    for trade in trades:
        ticker = trade["ticker"]
        if ticker in market_cache:
            continue
        # Try live first
        if use_live:
            try:
                from market_data import get_market_data
                result = get_market_data(ticker)
                if result:
                    market_cache[ticker] = result
                    print(f"  ✅ {ticker} — live data (ATR {result['atr_pct']}%, Vol ${result['dollar_volume_m']}M)")
                    continue
            except Exception:
                pass
        # Fall back to sample
        if ticker in SAMPLE_MARKET_DATA:
            market_cache[ticker] = SAMPLE_MARKET_DATA[ticker]
            m = SAMPLE_MARKET_DATA[ticker]
            print(f"  📋 {ticker} — sample data (ATR {m['atr_pct']}%, Vol ${m['dollar_volume_m']}M)")
        else:
            print(f"  ❌ {ticker} — no data available, skipping")

    print()

    # ── Step 3: Score ────────────────────────────────────────────
    print("Step 3: Filtering and scoring...\n")
    repeat_keys = detect_repeat_buys(trades)
    same_day_counts = count_same_day_insiders(trades)

    signals = []
    skipped = 0

    for trade in trades:
        ticker = trade["ticker"]
        market = market_cache.get(ticker)
        if not market:
            skipped += 1
            continue

        is_repeat = (ticker, trade["insider_name"]) in repeat_keys
        same_day  = same_day_counts.get(ticker, 1)

        result = score_trade(
            trade=trade,
            market=market,
            is_repeat=is_repeat,
            same_day_count=same_day,
            spy_gap_pct=0.0,
        )

        if result:
            signals.append(result)
        else:
            skipped += 1

    # ── Step 4: Print results ────────────────────────────────────
    print(f"  {len(signals)} signals passed filters  |  {skipped} skipped (didn't meet V1/V2 criteria)\n")

    if not signals:
        print("  No qualifying signals today.")
        return

    signals.sort(key=lambda s: s["total_score"], reverse=True)

    print("=" * 65)
    print(f"  TOP {len(signals)} SIGNALS  (sorted by score)")
    print("=" * 65)

    for i, s in enumerate(signals, 1):
        tp = f"${s['take_profit']}" if s["take_profit"] else "Hold to Close"
        score_bar = "█" * int(s["total_score"] / 5) + "░" * (20 - int(s["total_score"] / 5))
        print(f"""
  #{i}  {s['ticker']}  —  {s['company']}
       Insider : {s['insider_name']} ({s['title']})
       Trade   : {s['shares']:,} shares @ ${s['price_paid']}  (${s['total_value']:,.0f} total)
       Market  : Close ${s['last_close']}  |  ATR {s['atr_pct']}%  |  Vol ${s['dollar_volume_m']}M/day
       Strategy: Variant {s['variant']}  |  Entry ~${s['entry_price']}  |  SL ${s['stop_loss']}  |  TP {tp}
       Score   : {s['total_score']:5.1f}/100  {score_bar}  {s['rating'].upper()}
                 Insider Strength {s['insider_strength']:4.1f}  +  Volatility {s['volatility_score']:4.1f}
                 Liquidity {s['liquidity_score']:4.1f}        +  Timing {s['timing_score']:4.1f}
       Why     : {s['rationale']}""")
        if s["spy_gap_note"]:
            print(f"       ⚠️   {s['spy_gap_note']}")
        print("  " + "-" * 61)

    print(f"\n  ⚠️  {signals[0]['disclaimer']}\n")
    print(f"  Next step: add your .env keys and run  python main.py\n")


if __name__ == "__main__":
    run_test(use_live=True)