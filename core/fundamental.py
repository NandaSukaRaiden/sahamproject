"""
core/fundamental.py — Analisis Fundamental Saham IDX
Mengolah data raw menjadi skor dan insight fundamental yang rinci.
"""
import logging
from typing import Dict, Any, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logger = logging.getLogger(__name__)


def safe(val, default=0.0):
    """Safe value extraction"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def score_pe(pe: float, sector: str = "") -> Dict:
    """Skor PER — semakin rendah semakin baik (relatif)"""
    if pe <= 0:
        return {"value": pe, "score": 0, "signal": "N/A", "note": "Data tidak tersedia atau rugi"}
    if pe < 8:
        return {"value": pe, "score": 95, "signal": "SANGAT MURAH", "note": "PER sangat rendah, potensi undervalued"}
    elif pe < 12:
        return {"value": pe, "score": 80, "signal": "MURAH", "note": "PER di bawah rata-rata, valuasi menarik"}
    elif pe < 18:
        return {"value": pe, "score": 65, "signal": "WAJAR", "note": "PER dalam kisaran wajar"}
    elif pe < 25:
        return {"value": pe, "score": 45, "signal": "MAHAL", "note": "PER di atas rata-rata, perlu pertimbangan"}
    elif pe < 40:
        return {"value": pe, "score": 25, "signal": "SANGAT MAHAL", "note": "PER sangat tinggi, risiko overvalued"}
    else:
        return {"value": pe, "score": 10, "signal": "EKSTREM", "note": "PER ekstrem tinggi, sangat spekulatif"}


def score_pbv(pbv: float) -> Dict:
    """Skor PBV"""
    if pbv <= 0:
        return {"value": pbv, "score": 0, "signal": "N/A", "note": "Data tidak tersedia"}
    if pbv < 0.5:
        return {"value": pbv, "score": 95, "signal": "DEEP VALUE", "note": "Harga di bawah nilai buku, sangat murah"}
    elif pbv < 1.0:
        return {"value": pbv, "score": 85, "signal": "UNDERVALUED", "note": "Trading di bawah book value"}
    elif pbv < 2.0:
        return {"value": pbv, "score": 70, "signal": "WAJAR", "note": "PBV dalam kisaran normal"}
    elif pbv < 3.5:
        return {"value": pbv, "score": 50, "signal": "PREMIUM", "note": "Premium valuation, perlu ROE tinggi"}
    elif pbv < 6.0:
        return {"value": pbv, "score": 30, "signal": "MAHAL", "note": "Premium tinggi, perlu growth kuat"}
    else:
        return {"value": pbv, "score": 15, "signal": "VERY EXPENSIVE", "note": "Valuasi sangat premium"}


def score_roe(roe: float) -> Dict:
    """Skor ROE — semakin tinggi semakin baik"""
    pct = roe * 100 if abs(roe) <= 1 else roe
    if pct < 0:
        return {"value": pct, "score": 5, "signal": "NEGATIF", "note": "Perusahaan dalam kerugian"}
    elif pct < 5:
        return {"value": pct, "score": 20, "signal": "BURUK", "note": "ROE sangat rendah"}
    elif pct < 10:
        return {"value": pct, "score": 40, "signal": "CUKUP", "note": "ROE di bawah rata-rata"}
    elif pct < 15:
        return {"value": pct, "score": 60, "signal": "BAIK", "note": "ROE di atas rata-rata"}
    elif pct < 20:
        return {"value": pct, "score": 75, "signal": "SANGAT BAIK", "note": "ROE tinggi, manajemen efisien"}
    elif pct < 30:
        return {"value": pct, "score": 88, "signal": "EXCELLENT", "note": "ROE sangat tinggi, bisnis kuat"}
    else:
        return {"value": pct, "score": 95, "signal": "OUTSTANDING", "note": "ROE luar biasa, moat bisnis kuat"}


def score_roe_vs_pbv(roe_pct: float, pbv: float) -> Dict:
    """Analisis ROE vs PBV — kualitas vs harga"""
    if pbv <= 0 or roe_pct <= 0:
        return {"score": 50, "note": "Data tidak lengkap untuk analisis ROE/PBV"}
    ratio = roe_pct / pbv  # idealnya > 10
    if ratio > 20:
        return {"score": 90, "note": f"ROE/PBV={ratio:.1f} — sangat atraktif, kualitas tinggi harga wajar"}
    elif ratio > 12:
        return {"score": 75, "note": f"ROE/PBV={ratio:.1f} — menarik, value yang baik"}
    elif ratio > 8:
        return {"score": 60, "note": f"ROE/PBV={ratio:.1f} — cukup menarik"}
    elif ratio > 5:
        return {"score": 45, "note": f"ROE/PBV={ratio:.1f} — kurang atraktif"}
    else:
        return {"score": 25, "note": f"ROE/PBV={ratio:.1f} — tidak menarik, terlalu mahal relatif kualitas"}


def score_growth(rev_growth: float, earn_growth: float) -> Dict:
    """Skor pertumbuhan revenue dan laba"""
    rev_pct = rev_growth * 100 if abs(rev_growth) <= 1 else rev_growth
    earn_pct = earn_growth * 100 if abs(earn_growth) <= 1 else earn_growth
    avg = (rev_pct + earn_pct) / 2

    if avg > 30:
        s, sig = 90, "HYPERGROWTH"
    elif avg > 20:
        s, sig = 80, "FAST GROWTH"
    elif avg > 10:
        s, sig = 65, "GROWTH"
    elif avg > 0:
        s, sig = 50, "STAGNANT"
    elif avg > -10:
        s, sig = 30, "DECLINING"
    else:
        s, sig = 10, "SHARP DECLINE"

    return {
        "revenue_growth_pct": round(rev_pct, 1),
        "earnings_growth_pct": round(earn_pct, 1),
        "score": s,
        "signal": sig,
        "note": f"Revenue: {rev_pct:+.1f}%, Laba: {earn_pct:+.1f}% YoY"
    }


def score_liquidity(current_ratio: float, quick_ratio: float) -> Dict:
    """Skor likuiditas"""
    cr = current_ratio
    qr = quick_ratio
    if cr >= 2.0 and qr >= 1.0:
        s, sig = 85, "SANGAT LIKUID"
    elif cr >= 1.5 and qr >= 0.8:
        s, sig = 70, "LIKUID"
    elif cr >= 1.0:
        s, sig = 50, "CUKUP"
    elif cr >= 0.8:
        s, sig = 30, "KURANG LIKUID"
    else:
        s, sig = 10, "TIDAK LIKUID"

    return {
        "current_ratio": cr,
        "quick_ratio": qr,
        "score": s,
        "signal": sig,
        "note": f"Current Ratio: {cr:.2f}x | Quick Ratio: {qr:.2f}x"
    }


def score_leverage(debt_to_equity: float, sector: str = "") -> Dict:
    """Skor leverage / hutang"""
    der = debt_to_equity / 100 if debt_to_equity > 10 else debt_to_equity

    # Bank & keuangan punya leverage tinggi secara normal
    is_financial = any(k in sector.lower() for k in ["bank", "financial", "insurance"])
    threshold = 8.0 if is_financial else 1.5

    ratio_normalized = der / threshold
    if ratio_normalized < 0.3:
        s, sig = 90, "DEBT-FREE"
    elif ratio_normalized < 0.6:
        s, sig = 75, "KONSERVATIF"
    elif ratio_normalized < 1.0:
        s, sig = 55, "MODERAT"
    elif ratio_normalized < 1.5:
        s, sig = 35, "AGRESIF"
    else:
        s, sig = 15, "HIGHLY LEVERAGED"

    return {
        "der": der,
        "score": s,
        "signal": sig,
        "note": f"DER: {der:.2f}x ({'normal untuk sektor keuangan' if is_financial else 'vs threshold ' + str(threshold) + 'x'})"
    }


def score_dividend(yield_pct: float, payout_ratio: float) -> Dict:
    """Skor dividen"""
    y = yield_pct * 100 if yield_pct and yield_pct <= 1 else (yield_pct or 0)
    pr = payout_ratio * 100 if payout_ratio and payout_ratio <= 1 else (payout_ratio or 0)

    if y == 0:
        return {"yield_pct": 0, "payout_ratio": pr, "score": 40, "signal": "NO DIVIDEND",
                "note": "Tidak membagikan dividen — bisa growth reinvestment atau kondisi keuangan"}
    elif y < 1:
        s, sig = 45, "NOMINAL"
    elif y < 2:
        s, sig = 55, "RENDAH"
    elif y < 4:
        s, sig = 70, "WAJAR"
    elif y < 6:
        s, sig = 85, "TINGGI"
    else:
        s, sig = 90, "SANGAT TINGGI"

    # Penalti jika payout terlalu tinggi (tidak sustainable)
    if pr > 100:
        s = max(s - 30, 10)
        sig += " (TIDAK SUSTAINABLE)"

    return {
        "yield_pct": round(y, 2),
        "payout_ratio": round(pr, 1),
        "score": s,
        "signal": sig,
        "note": f"Yield: {y:.1f}% | Payout Ratio: {pr:.0f}%"
    }


def run_fundamental_analysis(info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Jalankan analisis fundamental lengkap dari data info saham.
    Returns dict dengan semua skor dan summary.
    """
    sector = info.get("sector", "")

    pe    = safe(info.get("pe_ratio"))
    pbv   = safe(info.get("pb_ratio"))
    roe   = safe(info.get("roe"))
    roa   = safe(info.get("roa"))
    pm    = safe(info.get("profit_margin"))
    rev_g = safe(info.get("revenue_growth"))
    ear_g = safe(info.get("earnings_growth"))
    cr    = safe(info.get("current_ratio"))
    qr    = safe(info.get("quick_ratio"))
    der   = safe(info.get("debt_to_equity"))
    dy    = safe(info.get("dividend_yield"))
    pr    = safe(info.get("payout_ratio"))
    beta  = safe(info.get("beta"), 1.0)
    mktcap = safe(info.get("market_cap"))
    eps   = safe(info.get("eps_ttm"))

    # Scoring
    pe_score   = score_pe(pe, sector)
    pbv_score  = score_pbv(pbv)
    roe_score  = score_roe(roe)
    roe_pbv    = score_roe_vs_pbv(roe_score["value"], pbv)
    growth     = score_growth(rev_g, ear_g)
    liquidity  = score_liquidity(cr, qr)
    leverage   = score_leverage(der, sector)
    dividend   = score_dividend(dy, pr)

    # Weighted composite score
    weights = {
        "pe":       0.15,
        "pbv":      0.12,
        "roe":      0.18,
        "roe_pbv":  0.10,
        "growth":   0.20,
        "liquidity":0.10,
        "leverage": 0.10,
        "dividend": 0.05,
    }

    composite = (
        pe_score["score"]    * weights["pe"] +
        pbv_score["score"]   * weights["pbv"] +
        roe_score["score"]   * weights["roe"] +
        roe_pbv["score"]     * weights["roe_pbv"] +
        growth["score"]      * weights["growth"] +
        liquidity["score"]   * weights["liquidity"] +
        leverage["score"]    * weights["leverage"] +
        dividend["score"]    * weights["dividend"]
    )

    # Risk-adjusted (beta penalty)
    if beta > 1.5:
        composite -= 5
    elif beta < 0.7:
        composite += 3

    composite = max(0, min(100, composite))

    # Sinyal fundamental
    if composite >= 80:
        signal = "STRONG BUY"
        color  = "#0ECB81"
    elif composite >= 65:
        signal = "BUY"
        color  = "#0ECB81"
    elif composite >= 45:
        signal = "HOLD"
        color  = "#F0B90B"
    elif composite >= 30:
        signal = "SELL"
        color  = "#e58e26"
    else:
        signal = "STRONG SELL"
        color  = "#F6465D"

    # Market cap kategori
    if mktcap >= 100_000_000_000_000:
        cap_cat = "Big Cap (>100T)"
    elif mktcap >= 10_000_000_000_000:
        cap_cat = "Mid-Big Cap (10-100T)"
    elif mktcap >= 1_000_000_000_000:
        cap_cat = "Mid Cap (1-10T)"
    elif mktcap >= 100_000_000_000:
        cap_cat = "Small Cap (100B-1T)"
    else:
        cap_cat = "Micro Cap (<100B)"

    return {
        "composite_score": round(composite, 1),
        "signal": signal,
        "signal_color": color,
        "category": cap_cat,
        "metrics": {
            "pe":        pe_score,
            "pbv":       pbv_score,
            "roe":       roe_score,
            "roe_vs_pbv": roe_pbv,
            "growth":    growth,
            "liquidity": liquidity,
            "leverage":  leverage,
            "dividend":  dividend,
        },
        "key_metrics": {
            "eps":            round(eps, 2),
            "roa_pct":        round(roa * 100 if abs(roa) <= 1 else roa, 1),
            "profit_margin_pct": round(pm * 100 if abs(pm) <= 1 else pm, 1),
            "beta":           round(beta, 2),
            "market_cap_rp":  mktcap,
        },
        "analyst": {
            "target_mean":   info.get("analyst_target_mean", 0),
            "target_high":   info.get("analyst_target_high", 0),
            "target_low":    info.get("analyst_target_low", 0),
            "recommendation": info.get("analyst_recommendation", "N/A"),
            "analyst_count": info.get("analyst_count", 0),
        }
    }


if __name__ == "__main__":
    # Test
    from core.data_fetcher import get_stock_info
    info = get_stock_info("BBCA")
    if info["success"]:
        result = run_fundamental_analysis(info["data"])
        print(f"📊 Fundamental Score: {result['composite_score']}/100 — {result['signal']}")
        for k, v in result["metrics"].items():
            print(f"  {k:12s}: {v.get('score',0):3.0f} | {v.get('signal','')}")
