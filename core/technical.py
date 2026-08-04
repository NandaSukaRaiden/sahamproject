"""
core/technical.py — Analisis Teknikal Saham IDX
RSI, MACD, Bollinger Bands, MA, Stochastic, ATR, Volume Analysis, Support/Resistance
"""
import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, List
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TECH_PERIODS

logger = logging.getLogger(__name__)


def calc_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))


def calc_macd(closes: pd.Series, fast=12, slow=26, signal=9) -> Dict[str, pd.Series]:
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def calc_bb(closes: pd.Series, window=20, std=2) -> Dict[str, pd.Series]:
    ma = closes.rolling(window).mean()
    std_dev = closes.rolling(window).std()
    return {
        "upper": ma + std * std_dev,
        "middle": ma,
        "lower": ma - std * std_dev,
    }


def calc_stochastic(df: pd.DataFrame, k=14, d=3) -> Dict[str, pd.Series]:
    low_min  = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    stoch_k  = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-10)
    stoch_d  = stoch_k.rolling(d).mean()
    return {"k": stoch_k, "d": stoch_d}


def calc_atr(df: pd.DataFrame, period=14) -> pd.Series:
    high   = df["high"]
    low    = df["low"]
    close  = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_obv(df: pd.DataFrame) -> pd.Series:
    obv = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
    return obv


def find_support_resistance(closes: pd.Series, n=10) -> Dict[str, List[float]]:
    """Temukan level support dan resistance menggunakan local extrema."""
    highs = closes.rolling(n * 2 + 1, center=True).max()
    lows  = closes.rolling(n * 2 + 1, center=True).min()
    resistance_levels = sorted(closes[closes == highs].dropna().unique(), reverse=True)[:5]
    support_levels    = sorted(closes[closes == lows].dropna().unique(), reverse=True)[:5]
    return {
        "resistance": [round(r, 0) for r in resistance_levels],
        "support":    [round(s, 0) for s in support_levels],
    }


def interpret_rsi(rsi: float) -> Dict:
    if rsi >= 80:
        return {"signal": "OVERBOUGHT EKSTREM", "score": 10, "color": "#ef4444",
                "note": f"RSI {rsi:.1f} — sangat overbought, waspada reversal"}
    elif rsi >= 70:
        return {"signal": "OVERBOUGHT", "score": 30, "color": "#f97316",
                "note": f"RSI {rsi:.1f} — zona overbought, potensi koreksi"}
    elif rsi >= 60:
        return {"signal": "BULLISH", "score": 65, "color": "#86efac",
                "note": f"RSI {rsi:.1f} — momentum bullish kuat"}
    elif rsi >= 40:
        return {"signal": "NETRAL", "score": 55, "color": "#fbbf24",
                "note": f"RSI {rsi:.1f} — netral, tunggu konfirmasi"}
    elif rsi >= 30:
        return {"signal": "BEARISH", "score": 45, "color": "#f97316",
                "note": f"RSI {rsi:.1f} — momentum bearish"}
    elif rsi >= 20:
        return {"signal": "OVERSOLD", "score": 75, "color": "#4ade80",
                "note": f"RSI {rsi:.1f} — zona oversold, potensi bounce"}
    else:
        return {"signal": "OVERSOLD EKSTREM", "score": 85, "color": "#00ff88",
                "note": f"RSI {rsi:.1f} — sangat oversold, peluang buy tinggi"}


def interpret_macd(macd: float, signal: float, hist: float, prev_hist: float) -> Dict:
    """Interpretasi MACD dengan deteksi crossover."""
    crossover_up   = hist > 0 and prev_hist <= 0
    crossover_down = hist < 0 and prev_hist >= 0
    divergence     = abs(macd - signal)

    if crossover_up:
        s, sig = 80, "GOLDEN CROSS"
        note = "MACD golden cross — sinyal bullish kuat!"
    elif crossover_down:
        s, sig = 20, "DEATH CROSS"
        note = "MACD death cross — sinyal bearish kuat!"
    elif macd > signal and hist > 0 and hist > prev_hist:
        s, sig = 70, "BULLISH KUAT"
        note = f"MACD di atas signal, histogram menguat"
    elif macd > signal and hist > 0:
        s, sig = 60, "BULLISH"
        note = "MACD di atas signal line"
    elif macd < signal and hist < 0 and hist < prev_hist:
        s, sig = 25, "BEARISH KUAT"
        note = f"MACD di bawah signal, histogram melemah"
    else:
        s, sig = 40, "BEARISH"
        note = "MACD di bawah signal line"

    return {"score": s, "signal": sig, "note": note,
            "macd_val": round(macd, 2), "signal_val": round(signal, 2),
            "histogram": round(hist, 2), "crossover": crossover_up or crossover_down}


def interpret_bb(close: float, upper: float, middle: float, lower: float) -> Dict:
    """Interpretasi Bollinger Bands."""
    bandwidth = (upper - lower) / middle * 100 if middle else 0

    if close > upper:
        s, sig = 25, "DI ATAS UPPER BAND"
        note = f"Harga {close:,.0f} menembus upper BB {upper:,.0f} — overbought"
    elif close >= middle and close <= upper:
        pct = (close - middle) / (upper - middle) * 100 if upper != middle else 0
        s = 60 + pct * 0.1
        sig = "ATAS MIDDLE BAND"
        note = f"Harga di zona upper ({pct:.0f}% dari middle ke upper)"
    elif close < lower:
        s, sig = 80, "DI BAWAH LOWER BAND"
        note = f"Harga {close:,.0f} di bawah lower BB {lower:,.0f} — oversold, potensi bounce"
    else:
        pct = (middle - close) / (middle - lower) * 100 if middle != lower else 0
        s = 50 - pct * 0.1
        sig = "BAWAH MIDDLE BAND"
        note = f"Harga di zona lower ({pct:.0f}% dari middle ke lower)"

    return {
        "score": round(max(10, min(90, s)), 1),
        "signal": sig,
        "note": note,
        "upper": round(upper, 0),
        "middle": round(middle, 0),
        "lower": round(lower, 0),
        "bandwidth_pct": round(bandwidth, 1),
    }


def interpret_ma(close: float, ma20: float, ma50: float, ma200: float) -> Dict:
    """Interpretasi posisi harga vs Moving Average."""
    above_20  = close > ma20
    above_50  = close > ma50
    above_200 = close > ma200
    golden    = ma50 > ma200
    count_above = sum([above_20, above_50, above_200])

    if count_above == 3 and golden:
        s, sig = 85, "BULLISH KUAT"
        note = "Harga di atas MA20, MA50, MA200 dengan golden cross"
    elif count_above == 3:
        s, sig = 72, "UPTREND"
        note = "Harga di atas semua MA — uptrend solid"
    elif count_above == 2:
        s, sig = 58, "MODERAT BULLISH"
        note = f"Harga di atas 2 dari 3 MA"
    elif count_above == 1:
        s, sig = 38, "MODERAT BEARISH"
        note = "Harga di bawah sebagian besar MA"
    elif not golden:
        s, sig = 18, "BEARISH KUAT"
        note = "Harga di bawah semua MA, death cross aktif"
    else:
        s, sig = 25, "DOWNTREND"
        note = "Harga di bawah semua MA"

    trend_pct = ((close - ma200) / ma200 * 100) if ma200 else 0

    return {
        "score": s, "signal": sig, "note": note,
        "ma20": round(ma20, 0), "ma50": round(ma50, 0), "ma200": round(ma200, 0),
        "above_ma20": above_20, "above_ma50": above_50, "above_ma200": above_200,
        "golden_cross": golden,
        "trend_from_ma200_pct": round(trend_pct, 1),
    }


def interpret_volume(vol: float, avg_vol: float) -> Dict:
    """Analisis volume relatif terhadap rata-rata."""
    if avg_vol <= 0:
        return {"score": 50, "signal": "N/A", "ratio": 0, "note": "Data volume tidak tersedia"}
    ratio = vol / avg_vol
    if ratio > 3.0:
        s, sig = 80, "VOLUME EKSTREM"
        note = f"Volume {ratio:.1f}x rata-rata — aktivitas sangat tinggi!"
    elif ratio > 2.0:
        s, sig = 70, "VOLUME TINGGI"
        note = f"Volume {ratio:.1f}x rata-rata — aksi institusional"
    elif ratio > 1.5:
        s, sig = 60, "VOLUME NAIK"
        note = f"Volume {ratio:.1f}x di atas rata-rata"
    elif ratio > 0.8:
        s, sig = 50, "NORMAL"
        note = f"Volume normal ({ratio:.1f}x rata-rata)"
    elif ratio > 0.5:
        s, sig = 40, "VOLUME RENDAH"
        note = f"Volume rendah ({ratio:.1f}x rata-rata)"
    else:
        s, sig = 25, "VOLUME SANGAT RENDAH"
        note = f"Volume sangat rendah ({ratio:.1f}x rata-rata) — kurang likuid"

    return {"score": s, "signal": sig, "ratio": round(ratio, 2), "note": note}


def detect_candlestick_patterns(df: pd.DataFrame) -> List[str]:
    """Deteksi pola candlestick sederhana dari 3 candle terakhir."""
    if len(df) < 3:
        return []
    patterns = []
    row  = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    body      = abs(row["close"] - row["open"])
    range_tot = row["high"] - row["low"]
    upper_wick = row["high"] - max(row["open"], row["close"])
    lower_wick = min(row["open"], row["close"]) - row["low"]

    # Doji
    if range_tot > 0 and body / range_tot < 0.1:
        patterns.append("Doji — ketidakpastian pasar")

    # Hammer (bullish)
    if lower_wick >= 2 * body and upper_wick < body * 0.5 and row["close"] > row["open"]:
        patterns.append("Hammer — sinyal reversal bullish")

    # Shooting Star (bearish)
    if upper_wick >= 2 * body and lower_wick < body * 0.5 and row["close"] < row["open"]:
        patterns.append("Shooting Star — sinyal reversal bearish")

    # Bullish Engulfing
    if (prev["close"] < prev["open"] and
        row["close"] > row["open"] and
        row["open"] < prev["close"] and
        row["close"] > prev["open"]):
        patterns.append("Bullish Engulfing — sinyal pembalikan naik kuat")

    # Bearish Engulfing
    if (prev["close"] > prev["open"] and
        row["close"] < row["open"] and
        row["open"] > prev["close"] and
        row["close"] < prev["open"]):
        patterns.append("Bearish Engulfing — sinyal pembalikan turun kuat")

    # Marubozu Bullish
    if (row["close"] > row["open"] and
        upper_wick < body * 0.05 and
        lower_wick < body * 0.05):
        patterns.append("Bullish Marubozu — tekanan beli sangat kuat")

    # Three White Soldiers
    if (all(df.iloc[-i]["close"] > df.iloc[-i]["open"] for i in [1, 2, 3]) and
        df.iloc[-2]["close"] > df.iloc[-3]["close"] and
        df.iloc[-1]["close"] > df.iloc[-2]["close"]):
        patterns.append("Three White Soldiers — uptrend kuat berlanjut")

    # Three Black Crows
    if (all(df.iloc[-i]["close"] < df.iloc[-i]["open"] for i in [1, 2, 3]) and
        df.iloc[-2]["close"] < df.iloc[-3]["close"] and
        df.iloc[-1]["close"] < df.iloc[-2]["close"]):
        patterns.append("Three Black Crows — downtrend kuat berlanjut")

    return patterns


def run_technical_analysis(history: List[Dict]) -> Dict[str, Any]:
    """
    Jalankan analisis teknikal lengkap dari data OHLCV.
    """
    if not history or len(history) < 30:
        return {"success": False, "error": "Data tidak cukup untuk analisis teknikal (min 30 hari)"}

    df = pd.DataFrame(history)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_values("timestamp").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])

    close = df["close"]
    p     = TECH_PERIODS

    # ─── Kalkulasi indikator ─────────────────────────────
    rsi_series  = calc_rsi(close, p["rsi"])
    macd_data   = calc_macd(close, p["macd_fast"], p["macd_slow"], p["macd_signal"])
    bb_data     = calc_bb(close, p["bb_window"], p["bb_std"])
    stoch_data  = calc_stochastic(df, p["stoch_k"], p["stoch_d"])
    atr_series  = calc_atr(df, p["atr"])
    obv_series  = calc_obv(df)
    ma20_series = close.rolling(20).mean()
    ma50_series = close.rolling(50).mean()
    ma200_series= close.rolling(200).mean()

    # Nilai terkini
    current_close = float(close.iloc[-1])
    current_vol   = float(df["volume"].iloc[-1])
    avg_vol       = float(df["volume"].rolling(20).mean().iloc[-1])
    rsi_val   = float(rsi_series.iloc[-1])
    macd_val  = float(macd_data["macd"].iloc[-1])
    sig_val   = float(macd_data["signal"].iloc[-1])
    hist_val  = float(macd_data["histogram"].iloc[-1])
    prev_hist = float(macd_data["histogram"].iloc[-2]) if len(macd_data["histogram"]) > 1 else 0
    bb_upper  = float(bb_data["upper"].iloc[-1])
    bb_mid    = float(bb_data["middle"].iloc[-1])
    bb_lower  = float(bb_data["lower"].iloc[-1])
    ma20_val  = float(ma20_series.iloc[-1]) if not pd.isna(ma20_series.iloc[-1]) else current_close
    ma50_val  = float(ma50_series.iloc[-1]) if not pd.isna(ma50_series.iloc[-1]) else current_close
    ma200_val = float(ma200_series.iloc[-1]) if not pd.isna(ma200_series.iloc[-1]) else current_close
    atr_val   = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0
    stoch_k   = float(stoch_data["k"].iloc[-1]) if not pd.isna(stoch_data["k"].iloc[-1]) else 50
    stoch_d   = float(stoch_data["d"].iloc[-1]) if not pd.isna(stoch_data["d"].iloc[-1]) else 50

    # ─── Interpretasi ───────────────────────────────────
    rsi_interp  = interpret_rsi(rsi_val)
    macd_interp = interpret_macd(macd_val, sig_val, hist_val, prev_hist)
    bb_interp   = interpret_bb(current_close, bb_upper, bb_mid, bb_lower)
    ma_interp   = interpret_ma(current_close, ma20_val, ma50_val, ma200_val)
    vol_interp  = interpret_volume(current_vol, avg_vol)
    patterns    = detect_candlestick_patterns(df)
    sr          = find_support_resistance(close)

    # ─── Composite technical score ───────────────────────
    scores = [
        rsi_interp["score"] * 0.20,
        macd_interp["score"] * 0.25,
        bb_interp["score"] * 0.15,
        ma_interp["score"] * 0.25,
        vol_interp["score"] * 0.15,
    ]
    composite = sum(scores)

    # Candlestick bonus/penalty
    bullish_patterns = sum(1 for p in patterns if "bullish" in p.lower() or "white" in p.lower() or "hammer" in p.lower())
    bearish_patterns = sum(1 for p in patterns if "bearish" in p.lower() or "crow" in p.lower() or "shooting" in p.lower())
    composite += bullish_patterns * 3 - bearish_patterns * 3
    composite  = max(0, min(100, composite))

    # ─── Technical signal ───────────────────────────────
    if composite >= 75:
        tech_signal = "STRONG BUY"
    elif composite >= 60:
        tech_signal = "BUY"
    elif composite >= 45:
        tech_signal = "HOLD"
    elif composite >= 30:
        tech_signal = "SELL"
    else:
        tech_signal = "STRONG SELL"

    # ─── Fibonacci retracement dari 52-wk range ─────────
    period_high = float(close.rolling(min(252, len(close))).max().iloc[-1])
    period_low  = float(close.rolling(min(252, len(close))).min().iloc[-1])
    fib_range   = period_high - period_low
    fibonacci   = {
        "0.0":   round(period_low, 0),
        "23.6":  round(period_low + 0.236 * fib_range, 0),
        "38.2":  round(period_low + 0.382 * fib_range, 0),
        "50.0":  round(period_low + 0.500 * fib_range, 0),
        "61.8":  round(period_low + 0.618 * fib_range, 0),
        "78.6":  round(period_low + 0.786 * fib_range, 0),
        "100.0": round(period_high, 0),
    }

    # ─── Suggested entry/SL/TP ──────────────────────────
    suggested_sl = round(current_close - 2 * atr_val, 0)
    suggested_tp = round(current_close + 3 * atr_val, 0)
    risk_reward  = round((suggested_tp - current_close) / (current_close - suggested_sl + 1e-10), 2)

    # ─── Build OHLCV chart data ──────────────────────────
    chart_data = []
    for i, row in df.tail(120).iterrows():
        entry = {
            "timestamp": str(row["timestamp"]),
            "open":   round(float(row["open"]), 0),
            "high":   round(float(row["high"]), 0),
            "low":    round(float(row["low"]), 0),
            "close":  round(float(row["close"]), 0),
            "volume": int(row["volume"]),
        }
        # Tambahkan indikator ke chart data
        idx = df.index.get_loc(i)
        if idx < len(ma20_series) and not pd.isna(ma20_series.iloc[idx]):
            entry["ma20"]  = round(float(ma20_series.iloc[idx]), 0)
        if idx < len(ma50_series) and not pd.isna(ma50_series.iloc[idx]):
            entry["ma50"]  = round(float(ma50_series.iloc[idx]), 0)
        chart_data.append(entry)

    return {
        "success": True,
        "composite_score": round(composite, 1),
        "signal": tech_signal,
        "current_price": round(current_close, 0),
        "atr": round(atr_val, 0),
        "indicators": {
            "rsi":        rsi_interp,
            "macd":       macd_interp,
            "bollinger":  bb_interp,
            "ma":         ma_interp,
            "volume":     vol_interp,
            "stochastic": {
                "k": round(stoch_k, 1), "d": round(stoch_d, 1),
                "signal": "OVERSOLD" if stoch_k < 20 else ("OVERBOUGHT" if stoch_k > 80 else "NETRAL"),
                "score": 70 if stoch_k < 20 else (30 if stoch_k > 80 else 50),
            }
        },
        "candlestick_patterns": patterns,
        "support_resistance": sr,
        "fibonacci": fibonacci,
        "suggested_trade": {
            "entry":       round(current_close, 0),
            "stop_loss":   suggested_sl,
            "take_profit": suggested_tp,
            "risk_reward": risk_reward,
            "atr_based":   True,
        },
        "chart_data": chart_data,
    }


if __name__ == "__main__":
    from core.data_fetcher import get_price_history
    hist = get_price_history("BBCA", period="1y")
    if hist["success"]:
        res = run_technical_analysis(hist["data"])
        print(f"📈 Technical Score: {res['composite_score']}/100 — {res['signal']}")
        for k, v in res["indicators"].items():
            print(f"  {k:12s}: {v.get('score',0):3.0f} | {v.get('signal','')}")
