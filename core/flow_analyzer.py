"""
core/flow_analyzer.py — Analisis Dana Asing (Net Foreign Buy/Sell) & Fund Flow
Data dari Yahoo Finance + estimasi berdasarkan volume dan pergerakan institusional
"""
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def get_institutional_data(ticker: str) -> Dict[str, Any]:
    """Ambil data kepemilikan institusional dari Yahoo Finance."""
    try:
        jk = f"{ticker.upper()}.JK"
        stock = yf.Ticker(jk)

        # Institutional holders
        inst_holders = stock.institutional_holders
        major_holders = stock.major_holders

        inst_data = []
        if inst_holders is not None and not inst_holders.empty:
            for _, row in inst_holders.iterrows():
                inst_data.append({
                    "holder":  str(row.get("Holder", "")),
                    "shares":  int(row.get("Shares", 0) or 0),
                    "pct_out": float(row.get("% Out", 0) or 0),
                    "value":   float(row.get("Value", 0) or 0),
                })

        major_data = {}
        if major_holders is not None and not major_holders.empty:
            for _, row in major_holders.iterrows():
                if len(row) >= 2:
                    major_data[str(row.iloc[1])] = str(row.iloc[0])

        return {
            "success": True,
            "institutional_holders": inst_data[:10],
            "major_holders": major_data,
        }
    except Exception as e:
        logger.warning(f"[flow] Institutional data error for {ticker}: {e}")
        return {"success": False, "institutional_holders": [], "major_holders": {}}


def estimate_foreign_flow(df_price: pd.DataFrame, df_ihsg: pd.DataFrame = None) -> pd.DataFrame:
    """
    Estimasi aliran dana asing berdasarkan:
    - Volume spike relatif
    - Korelasi dengan IHSG movement
    - Price action vs volume (accumulation/distribution)
    Ini adalah estimasi heuristik karena data real net foreign hanya tersedia via Bloomberg/broker.
    """
    df = df_price.copy()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["close"]  = pd.to_numeric(df["close"], errors="coerce")
    df["open"]   = pd.to_numeric(df.get("open", df["close"]), errors="coerce")

    # Money Flow Index (MFI) — proxy untuk tekanan beli/jual
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["money_flow"]    = df["typical_price"] * df["volume"]
    df["direction"]     = np.sign(df["typical_price"].diff())
    df["pos_flow"]      = df["money_flow"].where(df["direction"] > 0, 0)
    df["neg_flow"]      = df["money_flow"].where(df["direction"] < 0, 0)

    window = 14
    pos_sum = df["pos_flow"].rolling(window).sum()
    neg_sum = df["neg_flow"].rolling(window).sum()
    mfr     = pos_sum / (neg_sum + 1e-10)
    df["mfi"] = 100 - (100 / (1 + mfr))

    # On-Balance Volume (OBV)
    df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()

    # Accumulation/Distribution Line
    clv = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"] + 1e-10)
    df["adl"] = (clv * df["volume"]).cumsum()

    # Volume ratio (aktual vs MA20)
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma20"] + 1e-10)

    # Estimasi "foreign flow signal" dari kombinasi indikator
    df["flow_signal"] = (df["mfi"] - 50) * df["vol_ratio"]

    return df


def compute_flow_summary(df: pd.DataFrame, ticker: str) -> Dict[str, Any]:
    """Hitung ringkasan aliran dana dari DataFrame yang sudah diproses."""
    if df.empty:
        return {}

    recent  = df.tail(5)    # 5 hari terakhir
    week    = df.tail(20)   # 20 hari (1 bulan)
    quarter = df.tail(60)   # 3 bulan

    def flow_score(signal_series: pd.Series) -> float:
        if signal_series.empty:
            return 50.0
        avg = signal_series.mean()
        # Normalize ke 0-100
        return max(0, min(100, 50 + avg * 2))

    recent_score  = flow_score(recent["flow_signal"])
    weekly_score  = flow_score(week["flow_signal"])
    quarterly_score = flow_score(quarter["flow_signal"])

    # MFI terkini
    current_mfi = float(df["mfi"].iloc[-1]) if not df["mfi"].isna().all() else 50.0

    # OBV trend
    obv_recent = df["obv"].iloc[-5:] if len(df) >= 5 else df["obv"]
    obv_slope  = (obv_recent.iloc[-1] - obv_recent.iloc[0]) / (obv_recent.std() + 1e-10)

    # Volume trend
    vol_ratio_now = float(df["vol_ratio"].iloc[-1]) if not df["vol_ratio"].isna().all() else 1.0

    # Composite flow score
    composite = (recent_score * 0.40 + weekly_score * 0.35 + quarterly_score * 0.25)
    composite = max(0, min(100, composite))

    if composite >= 70:
        flow_signal = "AKUMULASI KUAT"
        flow_desc   = "Tekanan beli dominan, kemungkinan akumulasi institusional"
    elif composite >= 57:
        flow_signal = "AKUMULASI"
        flow_desc   = "Dana lebih banyak masuk dari keluar"
    elif composite >= 43:
        flow_signal = "NETRAL"
        flow_desc   = "Aliran dana seimbang, pasar dalam konsolidasi"
    elif composite >= 30:
        flow_signal = "DISTRIBUSI"
        flow_desc   = "Dana lebih banyak keluar, waspada penjualan institusi"
    else:
        flow_signal = "DISTRIBUSI KUAT"
        flow_desc   = "Tekanan jual dominan, kemungkinan distribusi besar"

    # OBV interpretation
    if obv_slope > 1:
        obv_signal = "OBV NAIK (bullish)"
    elif obv_slope < -1:
        obv_signal = "OBV TURUN (bearish)"
    else:
        obv_signal = "OBV FLAT (konsolidasi)"

    # MFI interpretation
    if current_mfi > 80:
        mfi_signal = "OVERBOUGHT"
    elif current_mfi > 60:
        mfi_signal = "TEKANAN BELI"
    elif current_mfi < 20:
        mfi_signal = "OVERSOLD"
    elif current_mfi < 40:
        mfi_signal = "TEKANAN JUAL"
    else:
        mfi_signal = "NETRAL"

    # 20-hari flow history untuk chart
    flow_history = []
    for i, (idx, row) in enumerate(week.iterrows()):
        flow_history.append({
            "timestamp":   str(row["timestamp"]) if "timestamp" in row else str(idx),
            "mfi":         round(float(row["mfi"]) if not pd.isna(row["mfi"]) else 50, 1),
            "flow_signal": round(float(row["flow_signal"]) if not pd.isna(row["flow_signal"]) else 0, 2),
            "vol_ratio":   round(float(row["vol_ratio"]) if not pd.isna(row["vol_ratio"]) else 1, 2),
            "obv_norm":    round(float(row["obv"]) / 1e6, 2),
        })

    return {
        "composite_score":    round(composite, 1),
        "signal":             flow_signal,
        "description":        flow_desc,
        "recent_5d_score":    round(recent_score, 1),
        "weekly_score":       round(weekly_score, 1),
        "quarterly_score":    round(quarterly_score, 1),
        "indicators": {
            "mfi": {
                "value":  round(current_mfi, 1),
                "signal": mfi_signal,
                "note":   f"MFI {current_mfi:.1f} — {mfi_signal.lower()}"
            },
            "obv": {
                "slope":  round(obv_slope, 2),
                "signal": obv_signal,
                "note":   obv_signal,
            },
            "volume_ratio": {
                "value":  round(vol_ratio_now, 2),
                "signal": "TINGGI" if vol_ratio_now > 1.5 else ("NORMAL" if vol_ratio_now > 0.7 else "RENDAH"),
                "note":   f"Volume {vol_ratio_now:.1f}x dari rata-rata 20 hari"
            }
        },
        "flow_history": flow_history,
    }



def detect_whale_signals(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Deteksi sinyal aksi whale/institusi dari data harga dan volume.
    Menganalisis: volume spike, OBV divergence, price-volume divergence.
    """
    if df.empty or len(df) < 10:
        return {"detected": False, "signals": [], "alert_level": "NORMAL", "score": 50}

    signals    = []
    alert_level = "NORMAL"
    whale_score = 50

    # ── 1. Volume Spike Detection ──────────────────────────────
    if "vol_ratio" in df.columns and not df["vol_ratio"].isna().all():
        # Check last 3 days for spikes
        recent_vr = df["vol_ratio"].tail(3)
        max_vr    = float(recent_vr.max())

        if max_vr >= 5.0:
            signals.append({
                "type": "VOL_EXTREME",
                "icon": "🔴",
                "label": "VOLUME EKSTREM",
                "message": f"Volume {max_vr:.1f}x dari rata-rata 20 hari! Kemungkinan aksi institusional atau bandar besar sedang bergerak.",
                "severity": "CRITICAL",
            })
            alert_level  = "HIGH"
            whale_score += 30
        elif max_vr >= 3.0:
            signals.append({
                "type": "VOL_HIGH",
                "icon": "🟠",
                "label": "VOLUME TINGGI",
                "message": f"Volume {max_vr:.1f}x dari rata-rata. Potensi akumulasi/distribusi besar oleh institusi.",
                "severity": "HIGH",
            })
            if alert_level == "NORMAL":
                alert_level = "MEDIUM"
            whale_score += 15
        elif max_vr >= 2.0:
            signals.append({
                "type": "VOL_MODERATE",
                "icon": "🟡",
                "label": "VOLUME DI ATAS NORMAL",
                "message": f"Volume {max_vr:.1f}x rata-rata. Aktivitas lebih aktif dari biasa.",
                "severity": "MEDIUM",
            })
            whale_score += 5

    # ── 2. OBV Divergence ─────────────────────────────────────
    if "obv" in df.columns and "close" in df.columns and len(df) >= 10:
        price_5d = df["close"].tail(5)
        obv_5d   = df["obv"].tail(5)

        if len(price_5d) >= 5:
            price_chg = (float(price_5d.iloc[-1]) - float(price_5d.iloc[0])) / (float(price_5d.iloc[0]) + 1e-10) * 100
            obv_base  = abs(float(obv_5d.iloc[0])) + 1e-10
            obv_chg   = (float(obv_5d.iloc[-1]) - float(obv_5d.iloc[0])) / obv_base * 100

            # Bullish Divergence: price down but OBV up = hidden accumulation
            if price_chg < -1.5 and obv_chg > 8.0:
                signals.append({
                    "type": "OBV_DIV_BULL",
                    "icon": "🟢",
                    "label": "AKUMULASI DIAM-DIAM",
                    "message": f"Harga turun {price_chg:.1f}% tapi OBV naik {obv_chg:.1f}% — Bandar/institusi akumulasi secara tersembunyi!",
                    "severity": "HIGH",
                })
                if alert_level == "NORMAL":
                    alert_level = "MEDIUM"
                whale_score += 20

            # Bearish Divergence: price up but OBV down = hidden distribution
            elif price_chg > 1.5 and obv_chg < -8.0:
                signals.append({
                    "type": "OBV_DIV_BEAR",
                    "icon": "🔴",
                    "label": "DISTRIBUSI DIAM-DIAM",
                    "message": f"Harga naik {price_chg:.1f}% tapi OBV turun {obv_chg:.1f}% — Bandar sedang distribusi/jual diam-diam!",
                    "severity": "CRITICAL",
                })
                alert_level  = "HIGH"
                whale_score -= 25

    # ── 3. MFI Extreme Zones ──────────────────────────────────
    if "mfi" in df.columns and not df["mfi"].isna().all():
        current_mfi = float(df["mfi"].iloc[-1])
        if current_mfi >= 85:
            signals.append({
                "type": "MFI_EXTREME_OB",
                "icon": "🔴",
                "label": "MFI OVERBOUGHT EKSTREM",
                "message": f"MFI {current_mfi:.0f} — Uang mengalir keluar sangat kuat. Waspada distribusi besar.",
                "severity": "HIGH",
            })
            if alert_level == "NORMAL":
                alert_level = "MEDIUM"
            whale_score -= 20
        elif current_mfi <= 15:
            signals.append({
                "type": "MFI_EXTREME_OS",
                "icon": "🟢",
                "label": "MFI OVERSOLD EKSTREM",
                "message": f"MFI {current_mfi:.0f} — Uang mengalir masuk sangat kuat. Potensi akumulasi bawah oleh institusi.",
                "severity": "HIGH",
            })
            if alert_level == "NORMAL":
                alert_level = "MEDIUM"
            whale_score += 20

    # ── 4. ADL (Accumulation/Distribution) Trend ─────────────
    if "adl" in df.columns and len(df) >= 10:
        adl_10  = df["adl"].tail(10)
        adl_chg = float(adl_10.iloc[-1]) - float(adl_10.iloc[0])
        price_chg_10 = (float(df["close"].iloc[-1]) - float(df["close"].iloc[-10])) / (float(df["close"].iloc[-10]) + 1e-10) * 100

        if adl_chg > 0 and price_chg_10 < 0:
            signals.append({
                "type": "ADL_BULL_DIVERGENCE",
                "icon": "🔵",
                "label": "A/D LINE BULLISH",
                "message": "Accumulation/Distribution Line naik meski harga turun — sinyal akumulasi institusi tersembunyi.",
                "severity": "MEDIUM",
            })
            whale_score += 10

    whale_score = max(0, min(100, whale_score))

    return {
        "detected":    len(signals) > 0,
        "alert_level": alert_level,
        "signals":     signals,
        "signal_count": len(signals),
        "score":       round(whale_score, 1),
        "latest_vol_ratio": float(df["vol_ratio"].iloc[-1]) if "vol_ratio" in df.columns and not df["vol_ratio"].isna().all() else 1.0,
        "mfi_current": round(float(df["mfi"].iloc[-1]) if "mfi" in df.columns and not df["mfi"].isna().all() else 50, 1),
    }


def run_flow_analysis(ticker: str, history_data: List[Dict]) -> Dict[str, Any]:
    """Jalankan analisis fund flow lengkap termasuk whale detection."""
    try:
        if not history_data or len(history_data) < 20:
            return {"success": False, "error": "Data tidak cukup"}

        df = pd.DataFrame(history_data)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "high" not in df.columns:  df["high"] = df["close"]
        if "low"  not in df.columns:  df["low"]  = df["close"]
        if "open" not in df.columns:  df["open"] = df["close"]

        df_processed = estimate_foreign_flow(df)
        summary      = compute_flow_summary(df_processed, ticker)

        # Whale signals
        whale_signals = detect_whale_signals(df_processed)

        # Institutional data (best effort, don't let it fail everything)
        try:
            inst_data = get_institutional_data(ticker)
        except Exception:
            inst_data = {"success": False, "institutional_holders": [], "major_holders": {}}

        return {
            "success":      True,
            "ticker":       ticker,
            **summary,
            "whale":        whale_signals,
            "institutional": inst_data,
            "analyzed_at":  datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"[flow] run_flow_analysis error for {ticker}: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    from core.data_fetcher import get_price_history
    hist = get_price_history("BBCA", period="6mo")
    if hist["success"]:
        result = run_flow_analysis("BBCA", hist["data"])
        print(f"💰 Flow Score: {result.get('composite_score',0)}/100 — {result.get('signal','N/A')}")
        print(f"   {result.get('description','')}")
        print(f"   MFI: {result['indicators']['mfi']['value']:.1f} | OBV: {result['indicators']['obv']['signal']}")
