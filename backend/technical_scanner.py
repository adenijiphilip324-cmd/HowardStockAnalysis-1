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
    Returns a dict with scores and metadata.
    
    REVISED v2: More discriminating scoring with:
    - Tighter RSI bands (less catch-all)
    - Gradient scoring (not just binary)
    - Conflicting signal penalties
    - Higher volume thresholds
    """
    ticker = row['ticker'].split(':')[-1]
    raw_exchange = row['ticker'].split(':')[0]
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
    sma200 = row.get('SMA200', ema50)  # fallback if missing
    rsi = row['RSI']
    macd = row['MACD.macd']
    macd_signal = row['MACD.signal']
    atr = row['ATR']
    rel_vol = row['relative_volume_10d_calc']
    volume = row['volume']
    
    total_score = 0
    
    # ── 1. Trend Score (35 pts) ──────────────────────────────────────────
    # Require BOTH EMA alignment AND MACD for full score
    trend_score = 0
    ema_aligned = close > ema20 > ema50 > sma200  # Stricter: full alignment
    macd_bullish = macd > macd_signal
    
    if ema_aligned and macd_bullish:
        trend_score = 35  # Full points: strong multi-timeframe confirmation
    elif ema_aligned:
        trend_score = 22  # Partial: EMA aligned but MACD not confirming
    elif macd_bullish:
        trend_score = 18  # Partial: MACD bullish but EMA not aligned
    elif close > ema20 and ema20 > ema50:  # At least recent trend is up
        trend_score = 10
    elif close < ema20 and ema20 > ema50:  # Downtrend but oversold
        trend_score = -5  # Small penalty for downtrend
    else:
        trend_score = 0
        
    total_score += max(0, trend_score)  # Don't go negative
    
    # ── 2. Momentum Score (35 pts) ───────────────────────────────────────
    # Stricter RSI bands: 50-70 optimal, penalize extremes
    momentum_score = 0
    if 50 <= rsi <= 65:
        momentum_score = 35  # Optimal: healthy momentum, not overbought
    elif 65 < rsi <= 75:
        momentum_score = 25  # Good but warming up
    elif 40 <= rsi < 50:
        momentum_score = 15  # Weak momentum, just above oversold
    elif rsi > 75:
        momentum_score = 10  # Overbought: exhaustion risk
    elif rsi < 40:
        momentum_score = -10  # Penalize: weakness
    else:
        momentum_score = 0
        
    total_score += max(0, momentum_score)
    
    # ── 3. Volatility Score (15 pts) ─────────────────────────────────────
    # ATR% sweet spot: 5-12% for penny stocks (not too tame, not too wild)
    volatility_score = 0
    atr_pct = (atr / close * 100) if close > 0 else 0
    if 5 <= atr_pct <= 12:
        volatility_score = 15  # Ideal: tradeable but not too erratic
    elif 3 <= atr_pct < 5:
        volatility_score = 8   # Low: too tame, low profit potential
    elif 12 < atr_pct <= 20:
        volatility_score = 8   # Elevated but manageable
    elif atr_pct > 20:
        volatility_score = 0   # Too wild for reliable entry/exit
    else:
        volatility_score = 0
        
    total_score += volatility_score
    
    # ── 4. Volume Score (15 pts) ─────────────────────────────────────────
    # Stricter thresholds: relative_vol > 1.5x (50% above avg) + $1M+ dollar volume
    volume_score = 0
    dollar_volume = volume * close
    
    if rel_vol > 2.0 and dollar_volume > 1000000:
        volume_score = 15  # Excellent: strong conviction
    elif rel_vol > 1.5 and dollar_volume > 750000:
        volume_score = 12  # Good: above-average activity
    elif rel_vol > 1.2 and dollar_volume > 500000:
        volume_score = 8   # Moderate: acceptable but not compelling
    elif rel_vol > 1.0 or dollar_volume > 300000:
        volume_score = 4   # Weak: just barely above threshold
    else:
        volume_score = 0
        
    total_score += volume_score
    
    # ── Conflict Penalties ───────────────────────────────────────────────
    # Penalize conflicting signals
    if macd_bullish and rsi < 40:
        total_score -= 10  # MACD bullish but RSI oversold = divergence risk
    if close > ema20 and rsi > 80:
        total_score -= 8   # Price up but extremely overbought = pullback risk
        
    # Cap between 0-100
    total_score = max(0, min(100, total_score))
    
    # Dynamic Entry/SL/TP
    entry_price = close
    stop_loss = round(entry_price - (1.5 * atr), 2) if atr else round(entry_price * 0.9, 2)
    risk = entry_price - stop_loss
    take_profit = round(entry_price + (2.5 * risk), 2) if risk > 0 else round(entry_price * 1.2, 2)
    
    # Rationale - broken down by component
    rationale_parts = []
    if trend_score >= 35:
        rationale_parts.append("✓ Strong multi-timeframe uptrend (EMA + MACD aligned)")
    elif trend_score >= 22:
        rationale_parts.append("◐ EMA uptrend forming but MACD diverging")
    elif trend_score >= 10:
        rationale_parts.append("◐ Recent uptrend but multi-timeframe weak")
    else:
        rationale_parts.append("✗ Downtrend or unclear direction")
    
    if momentum_score >= 35:
        rationale_parts.append(f"✓ Optimal momentum (RSI {rsi:.1f}, no overbought)")
    elif momentum_score >= 25:
        rationale_parts.append(f"◐ Rising momentum (RSI {rsi:.1f}, warming)")
    elif momentum_score >= 15:
        rationale_parts.append(f"◐ Weak momentum (RSI {rsi:.1f})")
    else:
        rationale_parts.append(f"✗ Weakness (RSI {rsi:.1f})")
    
    if volatility_score >= 15:
        rationale_parts.append(f"✓ Ideal volatility (ATR {atr_pct:.1f}%, tradeable)")
    elif volatility_score >= 8:
        rationale_parts.append(f"◐ ATR {atr_pct:.1f}% - acceptable")
    else:
        rationale_parts.append(f"✗ ATR {atr_pct:.1f}% - too low or wild")
    
    if volume_score >= 15:
        rationale_parts.append(f"✓ Strong conviction (Vol {rel_vol:.1f}x, ${dollar_volume/1000:.0f}k)")
    elif volume_score >= 12:
        rationale_parts.append(f"◐ Good volume (Vol {rel_vol:.1f}x)")
    elif volume_score >= 8:
        rationale_parts.append(f"◐ Acceptable volume (Vol {rel_vol:.1f}x)")
    else:
        rationale_parts.append(f"✗ Low volume (Vol {rel_vol:.1f}x)")
    
    return {
        "ticker": ticker,
        "exchange": exchange,
        "company": row['description'],
        "total_score": round(total_score, 1),
        "momentum_score": round(momentum_score, 1),
        "trend_score": round(trend_score, 1),
        "volatility_score": round(volatility_score, 1),
        "volume_score": round(volume_score, 1),
        "current_price": close,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rsi": round(rsi, 1),
        "macd_signal": "Bullish Cross" if macd > macd_signal else "Neutral",
        "atr_pct": round(atr_pct, 2),
        "relative_volume": round(rel_vol, 2),
        "dollar_volume": round(dollar_volume, 0),
        "high_52w": row.get('high_52w', 0), # placeholder if not in row
        "low_52w": row.get('low_52w', 0),   # placeholder if not in row
        "rationale": " | ".join(rationale_parts),
        "scan_date": str(date.today())
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = get_technical_signals(price_threshold=5.0)
    for r in results[:5]:
        print(f"Ticker: {r['ticker']} | Score: {r['total_score']} | Price: {r['current_price']}")
