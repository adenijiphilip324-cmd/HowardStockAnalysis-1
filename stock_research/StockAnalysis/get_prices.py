import yfinance as yf
import tkinter as tk
from tkinter import scrolledtext
import pandas as pd

# ==================== CONFIG ====================
stocks = [
    "RY.TO", "TD.TO", "SHOP.TO", "ENB.TO", "CNQ.TO",
    "BNS.TO", "SU.TO", "CP.TO", "TRI.TO", "ABX.TO"
]

LOOKBACK_PERIOD = "6mo"   # enough data for SMA/RSI
MIN_BARS = 60             # need enough rows for SMA50 + RSI


# ==================== INDICATORS ====================
def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    # Standard RSI calculation using average gains/losses
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ==================== SCORING ====================
def score_stock(df: pd.DataFrame) -> tuple[float, list[str], list[str], dict]:
    """
    Returns:
        (score_0_to_10, drivers_positive, drivers_negative, debug_values)
    """
    close = df["Close"]
    volume = df["Volume"]

    df = df.copy()
    df["SMA20"] = sma(close, 20)
    df["SMA50"] = sma(close, 50)
    df["RSI14"] = rsi(close, 14)
    df["VOL_AVG20"] = sma(volume, 20)

    last = df.iloc[-1]
    score = 0
    pos = []
    neg = []

    # Guard against NaNs in last rows
    if pd.isna(last["SMA20"]) or pd.isna(last["SMA50"]) or pd.isna(last["RSI14"]) or pd.isna(last["VOL_AVG20"]):
        return 0.0, [], ["Not enough data to compute indicators reliably"], {
            "close": float(last["Close"]),
            "volume": int(last["Volume"]),
        }

    price = float(last["Close"])
    sma20 = float(last["SMA20"])
    sma50 = float(last["SMA50"])
    rsi14 = float(last["RSI14"])
    vol = float(last["Volume"])
    vol_avg20 = float(last["VOL_AVG20"])

    # --- Scoring rules (simple & transparent) ---
    # +2 if price above SMA20
    if price > sma20:
        score += 2
        pos.append("Price > SMA20 (short-term strength)")
    else:
        neg.append("Price <= SMA20 (short-term weakness)")

    # +2 if SMA20 above SMA50 (bullish short-to-mid trend)
    if sma20 > sma50:
        score += 2
        pos.append("SMA20 > SMA50 (trend positive)")
    else:
        neg.append("SMA20 <= SMA50 (trend not confirmed)")

    # +2 if RSI is in a healthy “bullish but not overbought” band (45–65)
    if 45 <= rsi14 <= 65:
        score += 2
        pos.append("RSI(14) in 45–65 (healthy momentum)")
    elif rsi14 > 70:
        neg.append("RSI(14) > 70 (possibly overbought)")
    elif rsi14 < 40:
        neg.append("RSI(14) < 40 (weak momentum)")
    else:
        # neutral zone (40–45 or 65–70)
        score += 1
        pos.append("RSI(14) near healthy range (neutral+)")

    # +2 if today volume > 1.3x 20-day avg volume
    if vol_avg20 > 0 and vol >= 1.3 * vol_avg20:
        score += 2
        pos.append("Volume spike vs 20D avg")
    else:
        neg.append("No strong volume confirmation")

    # +2 if close is within 5% of 60-day high (breakout pressure)
    high_60 = float(df["High"].tail(60).max())
    if high_60 > 0 and price >= 0.95 * high_60:
        score += 2
        pos.append("Near 60D high (breakout potential)")
    else:
        neg.append("Not near recent highs")

    # Clamp to 0–10 and keep as float
    score = float(max(0, min(10, score)))

    debug = {
        "close": price,
        "volume": int(vol),
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "sma20": sma20,
        "sma50": sma50,
        "rsi14": rsi14,
        "vol_avg20": int(vol_avg20),
        "high_60": high_60,
    }
    return score, pos, neg, debug


# ==================== DATA FETCH + UI ====================
def fetch_and_score():
    result_text.delete(1.0, tk.END)
    result_text.insert(tk.END, "Running technical scan...\n\n")

    results = []

    for stock in stocks:
        try:
            ticker = yf.Ticker(stock)
            df = ticker.history(period=LOOKBACK_PERIOD)

            if df.empty or len(df) < MIN_BARS:
                result_text.insert(tk.END, f"{stock}: Not enough data (need ~{MIN_BARS} bars)\n\n")
                continue

            score, pos, neg, dbg = score_stock(df)

            results.append((stock, score, pos, neg, dbg))

        except Exception as e:
            result_text.insert(tk.END, f"{stock}: Error - {str(e)[:120]}\n\n")

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)

    # Render nicely
    for stock, score, pos, neg, dbg in results:
        result_text.insert(tk.END, f"{stock} — Score: {score:.1f}/10\n")
        result_text.insert(tk.END, f"  Date: {dbg.get('date','')}\n")
        result_text.insert(tk.END, f"  Close: {dbg.get('close',0):.2f}\n")
        result_text.insert(tk.END, f"  Volume: {dbg.get('volume',0):,} (20D avg: {dbg.get('vol_avg20',0):,})\n")
        result_text.insert(tk.END, f"  SMA20: {dbg.get('sma20',0):.2f} | SMA50: {dbg.get('sma50',0):.2f}\n")
        result_text.insert(tk.END, f"  RSI14: {dbg.get('rsi14',0):.1f} | 60D High: {dbg.get('high_60',0):.2f}\n")

        if pos:
            result_text.insert(tk.END, "  + Drivers:\n")
            for p in pos[:4]:
                result_text.insert(tk.END, f"    - {p}\n")
        if neg:
            result_text.insert(tk.END, "  - Risks/Notes:\n")
            for n in neg[:4]:
                result_text.insert(tk.END, f"    - {n}\n")

        result_text.insert(tk.END, "\n")


# ==================== GUI ====================
root = tk.Tk()
root.title("Canadian Stock Technical Scanner (MVP)")
root.geometry("720x750")

tk.Label(
    root,
    text="Daily Technical Scan (0–10 Score) — Canada (MVP)",
    font=("Arial", 14, "bold")
).pack(pady=12)

tk.Button(
    root,
    text="Run Scan",
    command=fetch_and_score,
    font=("Arial", 12),
    bg="#28a745",
    fg="white",
    height=2,
    width=18
).pack(pady=8)

result_text = scrolledtext.ScrolledText(root, width=90, height=35, font=("Arial", 10))
result_text.pack(pady=10, padx=12)

root.mainloop()