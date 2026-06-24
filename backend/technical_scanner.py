"""
technical_scanner.py
--------------------
Scans TSX/TSXV stocks under $5, $10, and $20 for short-term upside.
Uses TradingView Screener API for technical indicators and MGPR scoring.
"""

import os
import logging
from datetime import date
from tradingview_screener import Query, Column

logger = logging.getLogger(__name__)

# MGPR Scoring Thresholds
MIN_SCAN_SCORE = float(os.getenv("MIN_SCAN_SCORE") or "80")   # Minimum score to be considered for Airtable (technical scans) — stricter threshold for quality signals
MIN_VOLUME_SHARES = int(os.getenv("MIN_VOLUME_SHARES") or "50000")

def get_technical_signals(price_threshold: float = 20.0) -> list[dict]:
    """
    Query TradingView for Canada (TSX/TSXV) stocks under a price threshold.
    Calculates MGPR (Market Growth Potential Rating) for each.
    """
    logger.info(f"Scanning TSX/TSXV for stocks under ${price_threshold}...")
    
    try:
        q = (Query()
             .set_markets('canada')
             .select(
                 'name', 'description', 'close', 'high', 'low', 'open', 'volume',
                 'relative_volume_10d_calc', 'RSI', 'MACD.macd', 'MACD.signal',
                 'ATR', 'EMA20', 'EMA50', 'SMA200', 'market_cap_basic'
             )
             .where(
                 Column('close') > 0.1,
                 Column('close') <= price_threshold,
                 Column('volume') >= MIN_VOLUME_SHARES,
                 Column('type') == 'stock'
             )
             .limit(100))  # Top 100 results
        
        count, df = q.get_scanner_data()
        logger.info(f"Scan result type: {type(df)} | Count: {count}")
        
        if df is None or len(df) == 0:
            logger.info(f"No stocks found under ${price_threshold}")
            return []
            
        signals = []
        for _, row in df.iterrows():
            score_data = calculate_mgpr(row)
            if score_data['total_score'] >= MIN_SCAN_SCORE:
                signals.append(score_data)
                
        logger.info(f"Found {len(signals)} qualifying technical signals under ${price_threshold}")
        return sorted(signals, key=lambda x: x['total_score'], reverse=True)

    except Exception as e:
        logger.error(f"Technical scan failed: {e}")
        return []

def calculate_mgpr(row: dict) -> dict:
    """
    Calculate MGPR score (0-100) based on technical indicators.
    Returns a dict with numeric `rating` and a `rating_label` classification.
    """
    ticker_value = str(row.get('ticker', ''))
    ticker = ticker_value.split(':')[-1] if ticker_value else ''
    raw_exchange = ticker_value.split(':')[0] if ':' in ticker_value else ''
    # Map to Airtable singleSelect: [TSX|TSXV|NYSE|NASDAQ|AMEX]
    if 'XTSX' in raw_exchange or 'NEO' in raw_exchange or 'AEO' in raw_exchange:
        exchange = 'TSX'
    elif 'XTSV' in raw_exchange:
        exchange = 'TSXV'
    elif 'NYSE' in raw_exchange:
        exchange = 'NYSE'
    elif 'NASDAQ' in raw_exchange:
        exchange = 'NASDAQ'
    else:
        exchange = 'TSX' # Default fallback for Canada
    
    close = row['close']
    ema20 = row['EMA20']
    ema50 = row['EMA50']
    rsi = row['RSI']
    macd = row['MACD.macd']
    macd_signal = row['MACD.signal']
    atr = row['ATR']
    rel_vol = row['relative_volume_10d_calc']
    volume = row['volume']
    
    # ── 1. Trend Score (25 pts) ──────────────────────────────────────────
    trend_score = 0.0
    if close > ema20 > ema50:
        trend_score += 12.5
    if macd > macd_signal:
        trend_score += 12.5
        
    # ── 2. Momentum Score (25 pts max) ───────────────────────────────────────
    # RSI sweet-spot: 55 to 70. Trapezoidal function:
    #   - Below 45: 0.0 pts
    #   - 45 to 55: scales linearly from 0.0 to 15.0 pts
    #   - 55 to 70: full 15.0 pts
    #   - 70 to 85: scales down linearly from 15.0 to 5.0 pts
    #   - Above 85: 5.0 pts
    rsi_pts = 0.0
    if rsi >= 55 and rsi <= 70:
        rsi_pts = 15.0
    elif rsi >= 45 and rsi < 55:
        rsi_pts = (rsi - 45.0) / 10.0 * 15.0
    elif rsi > 70 and rsi <= 85:
        rsi_pts = 15.0 - ((rsi - 70.0) / 15.0 * 10.0)
    elif rsi > 85:
        rsi_pts = 5.0

    # EMA 20 > EMA 50 distance (10 pts):
    #   - Scales linearly based on diff_pct = (ema20 - ema50) / ema50 * 100
    #   - 0.0% to 1.0% scales from 0.0 to 10.0 pts.
    #   - >= 1.0% gets full 10.0 pts.
    ema_diff_pts = 0.0
    if ema50 > 0:
        diff_pct = (ema20 - ema50) / ema50 * 100.0
        if diff_pct >= 5.0:
            ema_diff_pts = 10.0
        elif diff_pct > 0.0:
            ema_diff_pts = (diff_pct / 5.0) * 10.0
    
    momentum_score = round(rsi_pts + ema_diff_pts, 1)
        
    # ── 3. Volatility Score (25 pts) ─────────────────────────────────────
    # ATR% optimal sweet spot: 5% to 12%.
    #   - Below 3.0%: 0.0 pts
    #   - 3.0% to 5.0%: scales linearly from 0.0 to 25.0 pts
    #   - 5.0% to 12.0%: full 25.0 pts
    #   - 12.0% to 20.0%: scales down linearly from 25.0 to 12.5 pts
    #   - Above 20.0%: 12.5 pts
    volatility_score = 0.0
    atr_pct = (atr / close * 100) if close > 0 else 0
    if atr_pct >= 5.0 and atr_pct <= 12.0:
        volatility_score = 25.0
    elif atr_pct >= 3.0 and atr_pct < 5.0:
        volatility_score = (atr_pct - 3.0) / 2.0 * 25.0
    elif atr_pct > 12.0 and atr_pct <= 20.0:
        volatility_score = 25.0 - ((atr_pct - 12.0) / 8.0 * 12.5)
    elif atr_pct > 20.0:
        volatility_score = 12.5
        
    volatility_score = round(volatility_score, 1)
        
    # ── 4. Volume Score (25 pts) ─────────────────────────────────────────
    # Relative volume (12.5 pts):
    #   - Scales from 0.5 to 1.5 relative volume.
    #   - <= 0.5: 0.0 pts
    #   - 0.5 to 1.5: scales from 0.0 to 12.5 pts
    #   - >= 1.5: 12.5 pts
    rel_vol_pts = 0.0
    if rel_vol >= 1.5:
        rel_vol_pts = 12.5
    elif rel_vol > 0.5:
        rel_vol_pts = (rel_vol - 0.5) / 1.0 * 12.5

    # Dollar Volume (12.5 pts):
    #   - Scales from $100K to $5M.
    #   - <= $100K: 0.0 pts
    #   - $100K to $5M: scales from 0.0 to 12.5 pts
    #   - >= $5M: 12.5 pts
    dollar_vol = volume * close
    dollar_vol_pts = 0.0
    if dollar_vol >= 5000000.0:
        dollar_vol_pts = 12.5
    elif dollar_vol > 100000.0:
        dollar_vol_pts = (dollar_vol - 100000.0) / 4900000.0 * 12.5

    volume_score = round(rel_vol_pts + dollar_vol_pts, 1)

    total_score = round(trend_score + momentum_score + volatility_score + volume_score, 1)

    rating = float(total_score)
    
    # Dynamic Entry/SL/TP
    entry_price = close
    stop_loss = round(entry_price - (1.5 * atr), 2) if atr else round(entry_price * 0.9, 2)
    risk = entry_price - stop_loss
    take_profit = round(entry_price + (2.5 * risk), 2) if risk > 0 else round(entry_price * 1.2, 2)
    
    # Rationale
    rationale_parts = []
    if trend_score >= 25.0: rationale_parts.append("Strong multi-EMA trend with MACD confirmation.")
    if momentum_score >= 20.0: rationale_parts.append(f"Optimal momentum (RSI {rsi:.1f}).")
    if volume_score >= 12.5: rationale_parts.append(f"Increased relative volume ({rel_vol:.1f}x).")
    
    macd_signal_label = "Neutral"
    if macd > macd_signal:
        macd_signal_label = "Bullish Cross"
    elif macd < macd_signal:
        macd_signal_label = "Bearish Cross"

    return {
        "ticker": ticker,
        "exchange": exchange,
        "company": row.get('description', row.get('company', '')),
        "total_score": total_score,
        "rating": rating,
        "momentum_score": momentum_score,
        "trend_score": trend_score,
        "volatility_score": volatility_score,
        "volume_score": volume_score,
        "current_price": close,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rsi": rsi,
        "macd_signal": macd_signal_label,
        "atr_pct": round(atr_pct, 2),
        "high_52w": row.get('high_52w', 0), # placeholder if not in row
        "low_52w": row.get('low_52w', 0),   # placeholder if not in row
        "rationale": " ".join(rationale_parts) or "Neutral technical profile.",
        "scan_date": str(date.today())
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = get_technical_signals(price_threshold=5.0)
    for r in results[:5]:
        print(f"Ticker: {r['ticker']} | Score: {r['total_score']} | Price: {r['current_price']}")
