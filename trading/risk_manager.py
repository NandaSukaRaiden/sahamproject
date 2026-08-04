"""
trading/risk_manager.py — Manajemen Risiko Trading
Hitung position sizing, max risk, dan validasi order
"""
from typing import Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import RISK_CONFIG, INITIAL_CAPITAL


def calculate_position_size(
    capital: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_loss_price: float,
    max_position_pct: float = None,
) -> Dict[str, Any]:
    """
    Hitung ukuran posisi optimal berdasarkan risk management.
    
    Formula: Position Size = (Capital × Risk%) / (Entry - Stop Loss)
    Minimum 1 lot (100 lembar)
    """
    if max_position_pct is None:
        max_position_pct = RISK_CONFIG["max_position_pct"]

    risk_amount   = capital * (risk_per_trade_pct / 100)
    price_diff    = abs(entry_price - stop_loss_price)

    if price_diff <= 0:
        return {"success": False, "error": "Entry price dan stop loss tidak valid"}

    # Jumlah lembar berdasarkan risiko
    shares_by_risk = risk_amount / price_diff

    # Konversi ke lot (1 lot = 100 lembar, bulat ke bawah)
    lots_by_risk = max(1, int(shares_by_risk / 100))

    # Batas maksimal posisi
    max_position_value = capital * max_position_pct
    max_lots_by_capital = max(1, int(max_position_value / (entry_price * 100)))

    # Pilih yang lebih kecil
    recommended_lots   = min(lots_by_risk, max_lots_by_capital)
    position_value     = recommended_lots * 100 * entry_price
    position_pct       = position_value / capital * 100
    actual_risk_amount = recommended_lots * 100 * price_diff
    actual_risk_pct    = actual_risk_amount / capital * 100

    return {
        "success": True,
        "recommended_lots": recommended_lots,
        "recommended_shares": recommended_lots * 100,
        "position_value": round(position_value, 0),
        "position_pct": round(position_pct, 1),
        "actual_risk_amount": round(actual_risk_amount, 0),
        "actual_risk_pct": round(actual_risk_pct, 2),
        "max_lots_by_capital": max_lots_by_capital,
        "lots_by_risk": lots_by_risk,
    }


def validate_order(
    action: str,
    ticker: str,
    price: float,
    lots: int,
    portfolio_cash: float,
    portfolio_value: float,
    existing_position_value: float = 0,
) -> Dict[str, Any]:
    """
    Validasi order sebelum eksekusi.
    """
    warnings = []
    errors   = []

    if lots < 1:
        errors.append("Minimum 1 lot per order")

    if price <= 0:
        errors.append("Harga tidak valid")

    if action.upper() == "BUY":
        order_value = price * lots * 100 * 1.002  # termasuk fee estimasi
        if order_value > portfolio_cash:
            errors.append(f"Saldo tidak cukup (butuh Rp {order_value:,.0f}, ada Rp {portfolio_cash:,.0f})")

        new_pos_value = existing_position_value + order_value
        pos_pct = new_pos_value / portfolio_value * 100 if portfolio_value else 100
        if pos_pct > 25:
            warnings.append(f"Posisi {ticker} akan menjadi {pos_pct:.1f}% dari portfolio (disarankan max 20%)")
        if pos_pct > 40:
            errors.append(f"Posisi terlalu besar ({pos_pct:.1f}%), risiko konsentrasi sangat tinggi")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}

    return {"valid": True, "errors": [], "warnings": warnings}


def calculate_kelly_criterion(win_rate: float, avg_gain: float, avg_loss: float) -> Dict[str, Any]:
    """
    Hitung Kelly Criterion untuk optimal position sizing.
    f* = (b*p - q) / b
    b = avg_gain / avg_loss
    p = win_rate
    q = 1 - win_rate
    """
    if avg_loss == 0:
        return {"kelly_pct": 0, "half_kelly_pct": 0, "note": "Data tidak cukup"}

    p = win_rate / 100
    q = 1 - p
    b = abs(avg_gain / avg_loss) if avg_loss else 1

    kelly = (b * p - q) / b
    kelly_pct = max(0, kelly * 100)

    return {
        "kelly_pct": round(kelly_pct, 1),
        "half_kelly_pct": round(kelly_pct / 2, 1),
        "win_odds": round(b, 2),
        "note": f"Kelly {kelly_pct:.1f}% → Disarankan Half-Kelly {kelly_pct/2:.1f}% per trade"
    }


def get_risk_metrics(portfolio_summary: Dict) -> Dict[str, Any]:
    """Hitung metrik risiko keseluruhan portfolio."""
    total_value  = portfolio_summary.get("total_portfolio_value", 0)
    cash         = portfolio_summary.get("cash", 0)
    positions    = portfolio_summary.get("positions", [])
    init_cap     = portfolio_summary.get("initial_capital", INITIAL_CAPITAL)
    total_pnl_pct = portfolio_summary.get("total_pnl_pct", 0)

    if not total_value:
        return {}

    # Konsentrasi risiko
    max_pos_pct  = max((p["weight_pct"] for p in positions), default=0)
    cash_ratio   = cash / total_value * 100

    # Drawdown dari initial capital
    if total_pnl_pct < 0:
        current_drawdown = abs(total_pnl_pct)
    else:
        current_drawdown = 0

    # Risk score (semakin rendah semakin aman)
    risk_score = 0
    risk_score += min(40, max_pos_pct)     # konsentrasi saham terbesar
    risk_score += max(0, 30 - cash_ratio)  # kurangnya cash buffer
    risk_score += current_drawdown         # drawdown aktual

    risk_level = (
        "VERY LOW" if risk_score < 20 else
        "LOW" if risk_score < 35 else
        "MEDIUM" if risk_score < 50 else
        "HIGH" if risk_score < 70 else
        "VERY HIGH"
    )

    trade_stats = portfolio_summary.get("trade_stats", {})
    kelly = calculate_kelly_criterion(
        trade_stats.get("win_rate_pct", 50),
        trade_stats.get("avg_gain_pct", 5),
        trade_stats.get("avg_loss_pct", -3),
    )

    return {
        "risk_score":       round(risk_score, 1),
        "risk_level":       risk_level,
        "max_position_pct": round(max_pos_pct, 1),
        "cash_buffer_pct":  round(cash_ratio, 1),
        "current_drawdown_pct": round(current_drawdown, 2),
        "max_drawdown_threshold": RISK_CONFIG["max_drawdown"] * 100,
        "kelly":            kelly,
        "alert": current_drawdown > RISK_CONFIG["max_drawdown"] * 100,
    }
