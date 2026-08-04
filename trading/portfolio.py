"""
trading/portfolio.py — Paper Trading Portfolio Manager
Simulasi portofolio saham Indonesia dengan fee broker realistis
+ Leverage/Margin Simulator + Fast Trade
"""
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    INITIAL_CAPITAL, PORTFOLIO_FILE, TRADE_HISTORY_FILE,
    BROKER_FEE_BUY, BROKER_FEE_SELL, DATA_DIR
)

logger = logging.getLogger(__name__)
os.makedirs(DATA_DIR, exist_ok=True)

# ─── Leverage Config (simulasi margin BEI) ───────────────────
LEVERAGE_CONFIG = {
    1: {"label": "1x — Reguler",     "modal_ratio": 1.0,  "interest_daily": 0.0,   "color": "#8899bb", "risk": "LOW"},
    2: {"label": "2x — Margin",      "modal_ratio": 0.5,  "interest_daily": 0.045, "color": "#fbbf24", "risk": "MEDIUM"},
    3: {"label": "3x — Margin Plus", "modal_ratio": 0.333,"interest_daily": 0.065, "color": "#f97316", "risk": "HIGH"},
    5: {"label": "5x — Full Margin", "modal_ratio": 0.2,  "interest_daily": 0.10,  "color": "#ef4444", "risk": "VERY HIGH"},
}


def calculate_leverage(
    price: float, lots: int, leverage: int, capital: float
) -> Dict[str, Any]:
    """Hitung detail posisi dengan leverage."""
    cfg            = LEVERAGE_CONFIG.get(leverage, LEVERAGE_CONFIG[1])
    shares         = lots * 100
    full_value     = price * shares
    modal_needed   = full_value * cfg["modal_ratio"]
    pinjaman       = full_value - modal_needed
    fee_buy        = full_value * BROKER_FEE_BUY
    total_modal    = modal_needed + fee_buy
    interest_daily = pinjaman * (cfg["interest_daily"] / 100)
    liquidation    = price * (1 - 0.20 / leverage) if leverage > 1 else 0

    return {
        "leverage":            leverage,
        "label":               cfg["label"],
        "color":               cfg["color"],
        "risk_level":          cfg["risk"],
        "lots":                lots,
        "shares":              shares,
        "full_value":          round(full_value, 0),
        "modal_needed":        round(modal_needed, 0),
        "pinjaman":            round(pinjaman, 0),
        "fee_buy":             round(fee_buy, 0),
        "total_modal":         round(total_modal, 0),
        "can_afford":          total_modal <= capital,
        "interest_daily_rp":   round(interest_daily, 0),
        "interest_monthly_rp": round(interest_daily * 30, 0),
        "liquidation_price":   round(liquidation, 0),
        "potential_gain_10pct": round(full_value * 0.10 * leverage, 0),
        "potential_loss_10pct": round(full_value * 0.10 * leverage, 0),
    }



def load_portfolio() -> Dict[str, Any]:
    """Load portfolio dari file JSON."""
    try:
        if os.path.exists(PORTFOLIO_FILE):
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[portfolio] Load error: {e}")

    # Default portfolio baru
    return {
        "cash": INITIAL_CAPITAL,
        "initial_capital": INITIAL_CAPITAL,
        "positions": {},
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
    }


def save_portfolio(portfolio: Dict) -> bool:
    """Simpan portfolio ke file JSON."""
    try:
        portfolio["last_updated"] = datetime.now().isoformat()
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[portfolio] Save error: {e}")
        return False


def load_trade_history() -> List[Dict]:
    """Load riwayat transaksi."""
    try:
        if os.path.exists(TRADE_HISTORY_FILE):
            with open(TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[portfolio] History load error: {e}")
    return []


def save_trade_history(history: List[Dict]) -> bool:
    """Simpan riwayat transaksi."""
    try:
        with open(TRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[portfolio] History save error: {e}")
        return False


def calculate_buy_cost(price: float, lots: int) -> Dict[str, float]:
    """Hitung total biaya beli termasuk fee broker."""
    shares     = lots * 100
    gross_val  = price * shares
    fee        = gross_val * BROKER_FEE_BUY
    total_cost = gross_val + fee
    return {
        "shares":     shares,
        "lots":       lots,
        "gross_value": gross_val,
        "fee":        round(fee, 0),
        "total_cost": round(total_cost, 0),
        "price_per_share": price,
    }


def calculate_sell_proceeds(price: float, lots: int) -> Dict[str, float]:
    """Hitung hasil jual bersih setelah fee & pajak."""
    shares      = lots * 100
    gross_val   = price * shares
    fee         = gross_val * BROKER_FEE_SELL  # termasuk PPh final 0.1%
    net_proceed = gross_val - fee
    return {
        "shares":      shares,
        "lots":        lots,
        "gross_value": gross_val,
        "fee":         round(fee, 0),
        "net_proceed": round(net_proceed, 0),
        "price_per_share": price,
    }


def buy_stock(ticker: str, price: float, lots: int, note: str = "") -> Dict[str, Any]:
    """
    Eksekusi order beli di paper trading.
    """
    portfolio = load_portfolio()
    costs     = calculate_buy_cost(price, lots)

    if costs["total_cost"] > portfolio["cash"]:
        return {
            "success": False,
            "error": f"Saldo tidak cukup. Butuh Rp {costs['total_cost']:,.0f}, tersedia Rp {portfolio['cash']:,.0f}",
        }

    ticker = ticker.upper()

    # Update posisi
    if ticker in portfolio["positions"]:
        pos = portfolio["positions"][ticker]
        old_shares  = pos["shares"]
        old_avg     = pos["avg_price"]
        new_shares  = old_shares + costs["shares"]
        new_avg     = (old_shares * old_avg + costs["gross_value"]) / new_shares
        pos["shares"]    = new_shares
        pos["lots"]      = new_shares // 100
        pos["avg_price"] = round(new_avg, 0)
        pos["total_cost"] = pos["total_cost"] + costs["total_cost"]
        pos["last_buy_price"] = price
        pos["last_buy_date"]  = datetime.now().isoformat()
    else:
        portfolio["positions"][ticker] = {
            "ticker":         ticker,
            "shares":         costs["shares"],
            "lots":           lots,
            "avg_price":      price,
            "total_cost":     costs["total_cost"],
            "last_buy_price": price,
            "last_buy_date":  datetime.now().isoformat(),
            "first_buy_date": datetime.now().isoformat(),
        }

    # Kurangi cash
    portfolio["cash"] = round(portfolio["cash"] - costs["total_cost"], 0)
    save_portfolio(portfolio)

    # Catat transaksi
    history = load_trade_history()
    history.append({
        "id":         len(history) + 1,
        "type":       "BUY",
        "ticker":     ticker,
        "price":      price,
        "lots":       lots,
        "shares":     costs["shares"],
        "gross_value": costs["gross_value"],
        "fee":        costs["fee"],
        "total_cost": costs["total_cost"],
        "note":       note,
        "timestamp":  datetime.now().isoformat(),
    })
    save_trade_history(history)

    return {
        "success": True,
        "action":  "BUY",
        "ticker":  ticker,
        "price":   price,
        "lots":    lots,
        "shares":  costs["shares"],
        "total_cost": costs["total_cost"],
        "fee":     costs["fee"],
        "remaining_cash": portfolio["cash"],
        "message": f"✅ Beli {lots} lot {ticker} @ Rp {price:,.0f}. Total: Rp {costs['total_cost']:,.0f} (fee: Rp {costs['fee']:,.0f})",
    }


def sell_stock(ticker: str, price: float, lots: int, note: str = "") -> Dict[str, Any]:
    """
    Eksekusi order jual di paper trading.
    """
    portfolio = load_portfolio()
    ticker    = ticker.upper()

    if ticker not in portfolio["positions"]:
        return {"success": False, "error": f"Tidak ada posisi {ticker} di portfolio"}

    pos = portfolio["positions"][ticker]
    if lots * 100 > pos["shares"]:
        return {
            "success": False,
            "error": f"Lot melebihi kepemilikan. Punya {pos['lots']} lot, mau jual {lots} lot",
        }

    proceeds = calculate_sell_proceeds(price, lots)
    avg_price = pos["avg_price"]

    # Hitung P&L
    buy_cost  = avg_price * proceeds["shares"]
    pnl_rp    = proceeds["net_proceed"] - buy_cost
    pnl_pct   = (pnl_rp / buy_cost * 100) if buy_cost else 0

    # Update posisi
    new_shares = pos["shares"] - proceeds["shares"]
    if new_shares <= 0:
        del portfolio["positions"][ticker]
    else:
        pos["shares"] = new_shares
        pos["lots"]   = new_shares // 100
        pos["total_cost"] = max(0, pos["total_cost"] - buy_cost)

    # Tambah cash
    portfolio["cash"] = round(portfolio["cash"] + proceeds["net_proceed"], 0)
    save_portfolio(portfolio)

    # Catat transaksi
    history = load_trade_history()
    history.append({
        "id":          len(history) + 1,
        "type":        "SELL",
        "ticker":      ticker,
        "price":       price,
        "lots":        lots,
        "shares":      proceeds["shares"],
        "gross_value": proceeds["gross_value"],
        "fee":         proceeds["fee"],
        "net_proceed": proceeds["net_proceed"],
        "avg_buy_price": avg_price,
        "pnl_rp":      round(pnl_rp, 0),
        "pnl_pct":     round(pnl_pct, 2),
        "note":        note,
        "timestamp":   datetime.now().isoformat(),
    })
    save_trade_history(history)

    return {
        "success": True,
        "action":  "SELL",
        "ticker":  ticker,
        "price":   price,
        "lots":    lots,
        "shares":  proceeds["shares"],
        "net_proceed": proceeds["net_proceed"],
        "fee":     proceeds["fee"],
        "pnl_rp":  round(pnl_rp, 0),
        "pnl_pct": round(pnl_pct, 2),
        "remaining_cash": portfolio["cash"],
        "message": (
            f"✅ Jual {lots} lot {ticker} @ Rp {price:,.0f}. "
            f"Net: Rp {proceeds['net_proceed']:,.0f} | "
            f"P&L: {'🟢' if pnl_rp >= 0 else '🔴'} Rp {pnl_rp:+,.0f} ({pnl_pct:+.2f}%)"
        ),
    }


def get_portfolio_summary(current_prices: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Hitung ringkasan portfolio lengkap dengan P&L.
    current_prices: dict {ticker: current_price}
    """
    portfolio  = load_portfolio()
    positions  = portfolio.get("positions", {})
    cash       = portfolio.get("cash", 0)
    init_cap   = portfolio.get("initial_capital", INITIAL_CAPITAL)
    history    = load_trade_history()

    if current_prices is None:
        current_prices = {}

    total_market_value = 0
    positions_detail   = []

    for ticker, pos in positions.items():
        current_price = current_prices.get(ticker, pos.get("avg_price", 0))
        shares        = pos.get("shares", 0)
        avg_price     = pos.get("avg_price", 0)
        market_value  = current_price * shares
        cost_basis    = avg_price * shares
        pnl_rp        = market_value - cost_basis
        pnl_pct       = (pnl_rp / cost_basis * 100) if cost_basis else 0

        total_market_value += market_value

        positions_detail.append({
            "ticker":        ticker,
            "lots":          pos.get("lots", 0),
            "shares":        shares,
            "avg_price":     avg_price,
            "current_price": current_price,
            "market_value":  round(market_value, 0),
            "cost_basis":    round(cost_basis, 0),
            "pnl_rp":        round(pnl_rp, 0),
            "pnl_pct":       round(pnl_pct, 2),
            "weight_pct":    0,  # akan dihitung setelah
        })

    total_value = total_market_value + cash
    total_pnl   = total_value - init_cap
    total_pnl_pct = (total_pnl / init_cap * 100) if init_cap else 0

    # Hitung weight per posisi
    for p in positions_detail:
        p["weight_pct"] = round(p["market_value"] / total_value * 100, 1) if total_value else 0

    # Statistik transaksi
    sells = [t for t in history if t["type"] == "SELL"]
    win_trades  = [t for t in sells if t.get("pnl_rp", 0) > 0]
    loss_trades = [t for t in sells if t.get("pnl_rp", 0) < 0]
    win_rate    = len(win_trades) / len(sells) * 100 if sells else 0
    total_realized = sum(t.get("pnl_rp", 0) for t in sells)

    # Realisasi avg gain/loss
    avg_gain = (sum(t.get("pnl_pct", 0) for t in win_trades) / len(win_trades)) if win_trades else 0
    avg_loss = (sum(t.get("pnl_pct", 0) for t in loss_trades) / len(loss_trades)) if loss_trades else 0

    return {
        "cash":               round(cash, 0),
        "total_market_value": round(total_market_value, 0),
        "total_portfolio_value": round(total_value, 0),
        "initial_capital":    round(init_cap, 0),
        "total_pnl_rp":       round(total_pnl, 0),
        "total_pnl_pct":      round(total_pnl_pct, 2),
        "realized_pnl":       round(total_realized, 0),
        "unrealized_pnl":     round(total_market_value - sum(p["cost_basis"] for p in positions_detail), 0),
        "cash_ratio_pct":     round(cash / total_value * 100, 1) if total_value else 100,
        "positions":          sorted(positions_detail, key=lambda x: x["market_value"], reverse=True),
        "trade_stats": {
            "total_trades": len(history),
            "buy_trades":   len(history) - len(sells),
            "sell_trades":  len(sells),
            "win_trades":   len(win_trades),
            "loss_trades":  len(loss_trades),
            "win_rate_pct": round(win_rate, 1),
            "avg_gain_pct": round(avg_gain, 2),
            "avg_loss_pct": round(avg_loss, 2),
        },
        "last_updated": datetime.now().isoformat(),
    }


def reset_portfolio(confirm: bool = False) -> Dict[str, Any]:
    """Reset portfolio ke kondisi awal (hapus semua posisi)."""
    if not confirm:
        return {"success": False, "error": "Konfirmasi reset diperlukan (confirm=True)"}
    new_portfolio = {
        "cash": INITIAL_CAPITAL,
        "initial_capital": INITIAL_CAPITAL,
        "positions": {},
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
    }
    save_portfolio(new_portfolio)
    save_trade_history([])
    return {"success": True, "message": f"Portfolio direset. Modal awal: Rp {INITIAL_CAPITAL:,.0f}"}


if __name__ == "__main__":
    summary = get_portfolio_summary()
    print(f"💼 Portfolio: Rp {summary['total_portfolio_value']:,.0f}")
    print(f"   Cash: Rp {summary['cash']:,.0f} ({summary['cash_ratio_pct']:.1f}%)")
    print(f"   P&L: Rp {summary['total_pnl_rp']:+,.0f} ({summary['total_pnl_pct']:+.2f}%)")
