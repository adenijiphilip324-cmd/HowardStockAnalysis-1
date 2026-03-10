import requests
from datetime import date

ZAPIER_URL = "https://hooks.zapier.com/hooks/catch/26457810/uc3jklq/"
SLACK_URL  = "https://hooks.slack.com/services/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"

# Realistic dummy signal
signal = {
    "ticker": "AAPL",
    "company": "Apple Inc.",
    "insider_name": "Tim Cook",
    "title": "CEO",
    "trade_date": "2026-03-07",
    "scan_date": str(date.today()),
    "shares": 50000,
    "price_paid": 212.45,
    "total_value": 10622500,
    "last_close": 214.10,
    "atr_pct": 4.2,
    "dollar_volume_m": 85.3,
    "52w_high": 237.23,
    "variant": "V1 – Earnings Season",
    "entry_price": 214.10,
    "stop_loss": 205.50,
    "take_profit": "235.51 / 257.92",
    "insider_strength": 30,
    "volatility_score": 25,
    "liquidity_score": 25,
    "timing_score": 15,
    "total_score": 95,
    "rating": "⭐ STRONG BUY",
    "rationale": "CEO cluster buy during earnings window. ATR 4.2% meets V1 threshold. High liquidity. Repeat buy detected.",
    "same_day_insiders": 3,
    "repeat_buy": True,
    "spy_gap_note": "SPY gap-up confirmed — favorable entry",
    "disclaimer": "This is not financial advice. For informational purposes only."
}

# --- Build email HTML ---
email_html = f"""
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#1a1a2e">📈 Insider Scanner — Daily Signal Report</h2>
<p style="color:#555">Scan Date: {signal['scan_date']}</p>

<div style="background:#f0f7ff;border-left:4px solid #0066cc;padding:15px;border-radius:4px;margin:20px 0">
  <h3 style="margin:0 0 5px 0">{signal['ticker']} — {signal['company']}</h3>
  <span style="font-size:20px;font-weight:bold;color:#cc0000">{signal['rating']}</span>
  <span style="margin-left:15px;font-size:24px;font-weight:bold;color:#0066cc">{signal['total_score']}/100</span>
</div>

<table style="width:100%;border-collapse:collapse">
  <tr style="background:#f5f5f5"><th style="text-align:left;padding:8px">Field</th><th style="text-align:left;padding:8px">Value</th></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">Insider</td><td style="padding:8px;border-bottom:1px solid #eee">{signal['insider_name']} ({signal['title']})</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">Trade Date</td><td style="padding:8px;border-bottom:1px solid #eee">{signal['trade_date']}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">Shares / Value</td><td style="padding:8px;border-bottom:1px solid #eee">{signal['shares']:,} shares @ ${signal['price_paid']} = ${signal['total_value']:,.0f}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">ATR %</td><td style="padding:8px;border-bottom:1px solid #eee">{signal['atr_pct']}%</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">Variant</td><td style="padding:8px;border-bottom:1px solid #eee">{signal['variant']}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">Entry / SL / TP</td><td style="padding:8px;border-bottom:1px solid #eee">${signal['entry_price']} / ${signal['stop_loss']} / {signal['take_profit']}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">Same-Day Insiders</td><td style="padding:8px;border-bottom:1px solid #eee">{signal['same_day_insiders']}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">Repeat Buy</td><td style="padding:8px;border-bottom:1px solid #eee">{'Yes ✅' if signal['repeat_buy'] else 'No'}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee">SPY Gap</td><td style="padding:8px;border-bottom:1px solid #eee">{signal['spy_gap_note']}</td></tr>
</table>

<div style="background:#fff8e1;border-left:4px solid #ffa000;padding:12px;margin:20px 0;border-radius:4px">
  <strong>Rationale:</strong> {signal['rationale']}
</div>

<h4>Score Breakdown</h4>
<table style="width:100%;border-collapse:collapse">
  <tr><td style="padding:6px">Insider Strength</td><td style="padding:6px">{signal['insider_strength']}/30</td></tr>
  <tr><td style="padding:6px">Volatility</td><td style="padding:6px">{signal['volatility_score']}/25</td></tr>
  <tr><td style="padding:6px">Liquidity</td><td style="padding:6px">{signal['liquidity_score']}/25</td></tr>
  <tr><td style="padding:6px">Timing</td><td style="padding:6px">{signal['timing_score']}/20</td></tr>
  <tr style="font-weight:bold;border-top:2px solid #333"><td style="padding:6px">TOTAL</td><td style="padding:6px">{signal['total_score']}/100</td></tr>
</table>

<p style="color:#999;font-size:11px;margin-top:30px">{signal['disclaimer']}</p>
</body></html>
"""

# --- Build Slack message ---
slack_text = (
    f"📈 *Insider Scanner — {signal['scan_date']}*\n\n"
    f"*{signal['ticker']}* — {signal['company']}\n"
    f"{signal['rating']}  |  Score: *{signal['total_score']}/100*\n\n"
    f"👤 {signal['insider_name']} ({signal['title']}) bought *{signal['shares']:,} shares* @ ${signal['price_paid']}\n"
    f"💰 Total Value: ${signal['total_value']:,.0f}\n"
    f"📊 ATR: {signal['atr_pct']}%  |  Variant: {signal['variant']}\n"
    f"🎯 Entry: ${signal['entry_price']}  |  SL: ${signal['stop_loss']}  |  TP: {signal['take_profit']}\n"
    f"👥 Same-day insiders: {signal['same_day_insiders']}  |  Repeat buy: {'Yes ✅' if signal['repeat_buy'] else 'No'}\n"
    f"📉 {signal['spy_gap_note']}\n\n"
    f"_{signal['rationale']}_"
)

# --- Send to Zapier ---
print("Sending to Zapier (→ Email)...")
r = requests.post(ZAPIER_URL, json={
    "email_subject": f"📈 Insider Scanner — {signal['ticker']} {signal['rating']} ({signal['total_score']}/100)",
    "email_html": email_html,
    **signal
})
print(f"  Zapier → {r.status_code} {r.text}")

# --- Send to Slack ---
print("\nSending to Slack...")
r = requests.post(SLACK_URL, json={"text": slack_text})
print(f"  Slack  → {r.status_code} {r.text}")

print("\n✅ Done — check Howard's Slack channel and email inbox.")