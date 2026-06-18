"""
test_technical_scanner.py
-------------------------
Simple regression test for MGPR numeric ratings and output structure.
Run: python backend/test_technical_scanner.py
"""

from technical_scanner import calculate_mgpr


def run_test():
    sample_row = {
        "ticker": "TSX:TEST",
        "description": "Test Company Inc.",
        "close": 10.0,
        "EMA20": 9.0,
        "EMA50": 8.0,
        "RSI": 65.0,
        "MACD.macd": 1.0,
        "MACD.signal": 0.5,
        "ATR": 0.7,
        "relative_volume_10d_calc": 1.5,
        "volume": 60000,
        "high_52w": 15.2,
        "low_52w": 5.0,
    }

    result = calculate_mgpr(sample_row)

    assert isinstance(result["rating"], (int, float)), "rating must be numeric"
    assert result["rating"] == float(result["total_score"]), "rating should equal total_score"
    assert "rating_label" not in result, "technical scanner output should not include a rating label"
    assert result["macd_signal"] == "Bullish Cross", "expected bullish MACD label"
    assert result["total_score"] == 94.4, "expected total score ~94.4 on continuous 100-point scale"
    assert result["entry_price"] == 10.0, "expected entry price to equal close"
    assert result["stop_loss"] < result["entry_price"], "stop loss must be below entry"
    assert result["take_profit"] > result["entry_price"], "take profit must be above entry"

    print("✅ test_technical_scanner passed")


if __name__ == "__main__":
    run_test()
