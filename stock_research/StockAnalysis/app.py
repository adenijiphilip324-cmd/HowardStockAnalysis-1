import streamlit as st
import pandas as pd
import yfinance as yf

STOCKS = [
    "RY.TO", "TD.TO", "SHOP.TO", "ENB.TO", "CNQ.TO",
    "BNS.TO", "SU.TO", "CP.TO", "TRI.TO", "ABX.TO"
]

LOOKBACK_PERIOD = "6mo"
MIN_BARS = 60


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def score_stock(df: pd.DataFrame):
    close = df["Close"]
    volume = df["Volume"]

    df = df.copy()
    df["SMA20"] = sma(close, 20)
    df["SMA50"] = sma(close, 50)
    df["RSI14"] = rsi(close, 14)
    df["VOL_AVG20"] = sma(volume, 20)

    last = df.iloc[-1]

    # not enough data for indicators
    if pd.isna(last["SMA20"]) or pd.isna(last["SMA50"]) or pd.isna(last["RSI14"]) or pd.isna(last["VOL_AVG20"]):
        return None

    price = float(last["Close"])
    sma20 = float(last["SMA20"])
    sma50 = float(last["SMA50"])
    rsi14 = float(last["RSI14"])
    vol = float(last["Volume"])
    vol_avg20 = float(last["VOL_AVG20"])
    high_60 = float(df["High"].tail(60).max())

    score = 0
    drivers = []

    if price > sma20:
        score += 2
        drivers.append("Price > SMA20")
    if sma20 > sma50:
        score += 2
        drivers.append("SMA20 > SMA50")
    if 45 <= rsi14 <= 65:
        score += 2
        drivers.append("RSI 45–65")
    elif 40 <= rsi14 < 45 or 65 < rsi14 <= 70:
        score += 1
        drivers.append("RSI neutral+")
    if vol_avg20 > 0 and vol >= 1.3 * vol_avg20:
        score += 2
        drivers.append("Volume spike")
    if high_60 > 0 and price >= 0.95 * high_60:
        score += 2
        drivers.append("Near 60D high")

    return {
        "Ticker": df.attrs.get("ticker", ""),
        "Date": df.index[-1].strftime("%Y-%m-%d"),
        "Close": round(price, 2),
        "Volume": int(vol),
        "VolAvg20": int(vol_avg20),
        "SMA20": round(sma20, 2),
        "SMA50": round(sma50, 2),
        "RSI14": round(rsi14, 1),
        "Score": float(min(10, max(0, score))),
        "Drivers": ", ".join(drivers),
    }


@st.cache_data(ttl=300)
def run_scan(tickers):
    rows = []
    for t in tickers:
        df = yf.Ticker(t).history(period=LOOKBACK_PERIOD)
        if df.empty or len(df) < MIN_BARS:
            continue
        df.attrs["ticker"] = t
        row = score_stock(df)
        if row:
            rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("Score", ascending=False)
    return out


st.set_page_config(page_title="Canadian Technical Scanner", layout="wide")

st.title("Canadian Technical Scanner (MVP)")
st.caption("Daily technical scan with 0–10 score. MVP UI in Streamlit.")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    tickers_text = st.text_area("Tickers (one per line)", "\n".join(STOCKS), height=180)
with col2:
    min_score = st.slider("Min score filter", 0, 10, 6)
with col3:
    run = st.button("Run Scan", use_container_width=True)

if run:
    tickers = [x.strip() for x in tickers_text.splitlines() if x.strip()]
    with st.spinner("Running scan..."):
        df = run_scan(tickers)

    if df.empty:
        st.warning("No results (check tickers or data availability).")
    else:
        df_filtered = df[df["Score"] >= float(min_score)].copy()
        st.subheader("Results")
        st.dataframe(df_filtered, use_container_width=True)

        st.subheader("Top Picks")
        st.table(df.head(5)[["Ticker", "Score", "Drivers", "Close", "Volume", "Date"]])