"""
core/autotrade.py — Engine Auto-Trading Otomatis (AI Mode) — FIXED v2
Fixes:
  - No more busy-loop when disabled (uses threading.Event.wait instead of for-ticks loop)
  - Only logs "disabled" message once per state change, not on every loop tick
  - Robust error handling per ticker
  - Smart stop-loss monitoring (cut loss when SL is hit even without Gemini scan)
  - Better capital management (tracks total invested value)
"""
import os
import sys
import json
import time
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATA_DIR, DEFAULT_WATCHLIST
from core.data_fetcher import get_stock_info, get_price_history
from core.fundamental import run_fundamental_analysis
from core.technical import run_technical_analysis
from core.news_analyzer import fetch_all_news
from core.flow_analyzer import run_flow_analysis
from core.gemini_brain import analyze_stock_with_ai
from trading.portfolio import load_portfolio, buy_stock, sell_stock, get_portfolio_summary
from trading.risk_manager import calculate_position_size

logger = logging.getLogger(__name__)

AUTOTRADE_CONFIG_FILE = os.path.join(DATA_DIR, "autotrade_config.json")
AUTOTRADE_LOGS_FILE   = os.path.join(DATA_DIR, "autotrade_logs.json")
_log_lock = threading.Lock()

# Default Config
DEFAULT_CONFIG = {
    "enabled": False,
    "interval_minutes": 10,
    "max_allocation_pct": 20.0,
    "risk_per_trade_pct": 1.0,
    "min_confidence_pct": 80,
    "enable_stop_loss_monitor": True,  # Pantau stop loss secara real-time
    "trailing_stop_pct": 5.0,          # Trailing stop 5% dari harga tertinggi
    "watchlist": DEFAULT_WATCHLIST[:8],
}


def load_autotrade_config() -> Dict[str, Any]:
    """Load konfigurasi auto-trade."""
    try:
        if os.path.exists(AUTOTRADE_CONFIG_FILE):
            with open(AUTOTRADE_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    if k not in config:
                        config[k] = v
                return config
    except Exception as e:
        logger.warning(f"[autotrade] Load config error: {e}")
    return DEFAULT_CONFIG.copy()


def save_autotrade_config(config: Dict) -> bool:
    """Simpan konfigurasi auto-trade."""
    try:
        with open(AUTOTRADE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[autotrade] Save config error: {e}")
        return False


def load_autotrade_logs() -> List[Dict]:
    """Load log auto-trade."""
    try:
        if os.path.exists(AUTOTRADE_LOGS_FILE):
            with open(AUTOTRADE_LOGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[autotrade] Load logs error: {e}")
    return []


def add_autotrade_log(message: str, log_type: str = "info") -> None:
    """Tambahkan log aktivitas auto-trade (maksimal 300 entries), thread-safe."""
    with _log_lock:
        try:
            logs = load_autotrade_logs()
            new_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": log_type.upper(),
                "message": message,
            }
            logs.append(new_entry)
            logs = logs[-300:]
            with open(AUTOTRADE_LOGS_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2, ensure_ascii=False)
            logger.info(f"[AutoTrade] [{log_type.upper()}] {message}")
        except Exception as e:
            logger.error(f"[autotrade] Log writing error: {e}")


def clear_autotrade_logs() -> None:
    """Hapus log auto-trade."""
    with _log_lock:
        try:
            with open(AUTOTRADE_LOGS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception as e:
            logger.error(f"[autotrade] Clear logs error: {e}")


def check_stop_loss_for_positions() -> None:
    """
    Monitor posisi aktif dan eksekusi stop loss / trailing stop secara otomatis.
    Dipanggil lebih sering (setiap interval pendek) untuk perlindungan modal.
    """
    try:
        portfolio = load_portfolio()
        positions = portfolio.get("positions", {})
        if not positions:
            return

        config = load_autotrade_config()
        trailing_stop_pct = config.get("trailing_stop_pct", 5.0)

        for ticker, pos in list(positions.items()):
            try:
                info_res = get_stock_info(ticker)
                if not info_res["success"]:
                    continue

                current_price = info_res["data"].get("current_price", 0)
                avg_price     = pos.get("avg_price", 0)
                lots          = pos.get("lots", 0)

                if current_price <= 0 or avg_price <= 0 or lots <= 0:
                    continue

                pnl_pct = (current_price - avg_price) / avg_price * 100

                # ─── Hard Stop Loss (7% dari rata-rata beli) ─────────────
                hard_sl_pct = -7.0
                if pnl_pct <= hard_sl_pct:
                    note = f"[AUTO STOP LOSS] Cut loss {ticker} @ Rp {current_price:,.0f}. P&L: {pnl_pct:.2f}% (batas {hard_sl_pct}%)"
                    add_autotrade_log(note, "warning")
                    sell_res = sell_stock(ticker, current_price, lots, note)
                    if sell_res["success"]:
                        add_autotrade_log(
                            f"Stop loss EKSEKUSI: {lots} lot {ticker} terjual @ Rp {current_price:,.0f}. "
                            f"P&L: Rp {sell_res.get('pnl_rp', 0):,.0f}",
                            "success"
                        )
                    continue

                # ─── Take Profit Partial (jual 50% di +10%) ──────────────
                if pnl_pct >= 10.0 and pos.get("partial_tp_done") != True:
                    partial_lots = max(1, lots // 2)
                    note = f"[AUTO TAKE PROFIT] Ambil profit partial {ticker} @ Rp {current_price:,.0f}. Gain: {pnl_pct:.2f}%"
                    add_autotrade_log(note, "success")
                    sell_res = sell_stock(ticker, current_price, partial_lots, note)
                    if sell_res["success"]:
                        add_autotrade_log(
                            f"TP partial EKSEKUSI: {partial_lots} lot {ticker} terjual. "
                            f"P&L: Rp {sell_res.get('pnl_rp', 0):,.0f}",
                            "success"
                        )
                        # Mark partial TP done to prevent double trigger
                        portfolio = load_portfolio()
                        if ticker in portfolio.get("positions", {}):
                            portfolio["positions"][ticker]["partial_tp_done"] = True
                            from trading.portfolio import save_portfolio
                            save_portfolio(portfolio)
                    continue

                # ─── Trailing Stop (harga drop lebih dari X% dari puncak) ─
                # We store the peak price in position data
                peak_price = pos.get("peak_price", avg_price)
                if current_price > peak_price:
                    # Update peak
                    portfolio = load_portfolio()
                    if ticker in portfolio.get("positions", {}):
                        portfolio["positions"][ticker]["peak_price"] = current_price
                        from trading.portfolio import save_portfolio
                        save_portfolio(portfolio)
                    peak_price = current_price

                trailing_sl = peak_price * (1 - trailing_stop_pct / 100)
                if current_price <= trailing_sl and pnl_pct > 0:
                    note = f"[TRAILING STOP] {ticker} hit trailing stop @ Rp {current_price:,.0f} (peak: Rp {peak_price:,.0f}, -{ trailing_stop_pct}%)"
                    add_autotrade_log(note, "warning")
                    sell_res = sell_stock(ticker, current_price, lots, note)
                    if sell_res["success"]:
                        add_autotrade_log(
                            f"Trailing stop EKSEKUSI: {lots} lot {ticker}. "
                            f"P&L: Rp {sell_res.get('pnl_rp', 0):,.0f}",
                            "success"
                        )

            except Exception as e:
                logger.debug(f"[autotrade] SL monitor error for {ticker}: {e}")

    except Exception as e:
        logger.error(f"[autotrade] check_stop_loss error: {e}")


class AutoTradingEngine(threading.Thread):
    """
    Background Thread Engine untuk scan watchlist + monitoring posisi aktif.
    Menggunakan Event.wait() agar tidak spin CPU saat idle.
    """
    def __init__(self):
        super().__init__(name="AutoTradingEngine")
        self.daemon = True
        self.stop_event   = threading.Event()
        self.scan_event   = threading.Event()  # Manual trigger
        self.is_scanning  = False
        self.last_scan_time = None
        self._was_enabled = False  # Track state changes for clean logging

    def run(self):
        add_autotrade_log("Engine Auto Trading v2 diinisialisasi di background thread", "info")

        while not self.stop_event.is_set():
            config = load_autotrade_config()
            enabled = config.get("enabled", False)

            # ─── Stop Loss Monitor (berjalan selama ada posisi, independen dari enabled) ─
            if config.get("enable_stop_loss_monitor", True):
                try:
                    check_stop_loss_for_positions()
                except Exception as e:
                    logger.debug(f"[autotrade] SL monitor thread error: {e}")

            if enabled:
                if not self._was_enabled:
                    add_autotrade_log("Auto Trading ENGINE aktif. Memulai siklus scan...", "info")
                    self._was_enabled = True

                # ─── Run scan ──────────────────────────────────────────────
                try:
                    self.is_scanning = True
                    self.run_scan(config)
                except Exception as e:
                    add_autotrade_log(f"Error dalam loop scanning: {str(e)}", "error")
                finally:
                    self.is_scanning = False
                    self.last_scan_time = datetime.now().isoformat()
                    self.scan_event.clear()

                # ─── Wait for interval or manual trigger ──────────────────
                interval_secs = config.get("interval_minutes", 10) * 60
                add_autotrade_log(
                    f"Scan selesai. Scan berikutnya dalam {config.get('interval_minutes', 10)} menit, "
                    f"atau klik 'Jalankan Scan Sekarang'.", "info"
                )
                triggered = self.scan_event.wait(timeout=interval_secs)
                if triggered:
                    add_autotrade_log("Scan dipicu secara manual oleh user.", "info")

            else:
                if self._was_enabled:
                    add_autotrade_log("Auto Trading dinonaktifkan oleh user.", "info")
                    self._was_enabled = False
                # Tidur sebentar dan cek ulang config (hemat CPU)
                self.stop_event.wait(timeout=5)

    def trigger_scan_now(self):
        """Signal engine agar langsung mulai scan saat ini."""
        self.scan_event.set()

    def run_scan(self, config: Dict[str, Any]):
        """Jalankan proses scanning untuk watchlist dengan logika profit maksimal."""
        watchlist = config.get("watchlist", [])
        if not watchlist:
            add_autotrade_log("Watchlist kosong, tidak ada emiten untuk dianalisis.", "warning")
            return

        add_autotrade_log(f"Memulai auto-scan {len(watchlist)} emiten: {', '.join(watchlist)}", "info")

        # Ambil snapshot portfolio sekali saja
        port_summary = get_portfolio_summary()
        port_value   = port_summary.get("total_portfolio_value", 100_000_000)
        cash         = port_summary.get("cash", 0)
        positions    = load_portfolio().get("positions", {})

        bought_count = 0
        sold_count   = 0

        for ticker in watchlist:
            if self.stop_event.is_set():
                break

            # Cek ulang enabled (user bisa matikan di tengah scan)
            if not load_autotrade_config().get("enabled", False):
                add_autotrade_log("Auto Trading dinonaktifkan di tengah scan. Scan dihentikan.", "warning")
                break

            ticker = ticker.upper()
            add_autotrade_log(f"[{ticker}] Menganalisis...", "info")

            try:
                # 1. Fetch price info
                info_res = get_stock_info(ticker)
                if not info_res["success"]:
                    add_autotrade_log(f"[{ticker}] Gagal fetch data: {info_res.get('error','?')}", "warning")
                    continue

                stock_info    = info_res["data"]
                current_price = stock_info.get("current_price", 0)

                if current_price <= 0:
                    add_autotrade_log(f"[{ticker}] Harga tidak valid ({current_price}), skip.", "warning")
                    continue

                # 2. Fetch historical data
                hist_res = get_price_history(ticker, period="1y", interval="1d")
                history  = hist_res.get("data", []) if hist_res.get("success") else []

                if len(history) < 30:
                    add_autotrade_log(f"[{ticker}] Data historis tidak cukup ({len(history)} hari), skip.", "warning")
                    continue

                # 3. Run analysis pipelines
                fund = run_fundamental_analysis(stock_info)
                tech = run_technical_analysis(history)
                news = fetch_all_news(ticker, stock_info.get("company_name", ticker))
                flow = run_flow_analysis(ticker, history)

                # 4. Build portfolio context for AI
                has_position = ticker in positions
                pos_details  = positions.get(ticker, {})
                portfolio_context = {
                    "has_position": has_position,
                    "position": {
                        "lots":      pos_details.get("lots", 0),
                        "avg_price": pos_details.get("avg_price", 0),
                        "pnl_pct":   round((current_price - pos_details.get("avg_price", 1)) / pos_details.get("avg_price", 1) * 100, 2) if has_position else 0,
                        "pnl_rp":    round((current_price - pos_details.get("avg_price", 0)) * pos_details.get("shares", 0), 0) if has_position else 0,
                        "peak_price": pos_details.get("peak_price", pos_details.get("avg_price", 0)),
                    } if has_position else {}
                }

                # 5. Gemini AI decision
                ai_res = analyze_stock_with_ai(
                    ticker=ticker,
                    stock_info=info_res,
                    fundamental=fund,
                    technical=tech,
                    news=news,
                    flow=flow,
                    portfolio_context=portfolio_context,
                )

                if not ai_res["success"]:
                    add_autotrade_log(f"[{ticker}] Gemini AI gagal: {ai_res.get('error','?')}", "warning")
                    time.sleep(3)
                    continue

                ai_data        = ai_res["data"]
                recommendation = ai_data.get("recommendation", "HOLD").upper()
                confidence     = float(ai_data.get("confidence", 0))
                min_conf       = float(config.get("min_confidence_pct", 80))
                risk_level     = ai_data.get("risk_level", "HIGH")
                time_horizon   = ai_data.get("time_horizon", "")
                es             = ai_data.get("entry_strategy", {})

                add_autotrade_log(
                    f"[{ticker}] AI: {recommendation} | Confidence: {confidence:.0f}% | "
                    f"Risk: {risk_level} | Horizon: {time_horizon}", "info"
                )

                # ─── FILTER KUALITAS TINGGI ──────────────────────────────
                # Lewati jika risiko sangat tinggi, confidence rendah, atau time horizon terlalu pendek
                if risk_level == "VERY HIGH":
                    add_autotrade_log(f"[{ticker}] Lewati — Risk level VERY HIGH, terlalu spekulatif.", "warning")
                    time.sleep(3)
                    continue

                # ─── BUY LOGIC ───────────────────────────────────────────
                if recommendation in ["BUY", "STRONG BUY"] and confidence >= min_conf:

                    # Batasi jumlah posisi aktif (max 5 saham sekaligus)
                    active_positions = len(load_portfolio().get("positions", {}))
                    if active_positions >= 5:
                        add_autotrade_log(f"[{ticker}] Lewati — Max 5 posisi aktif tercapai ({active_positions}).", "warning")
                        time.sleep(3)
                        continue

                    # Hitung alokasi posisi saat ini
                    current_val   = pos_details.get("shares", 0) * current_price
                    max_alloc_val = port_value * (config.get("max_allocation_pct", 20.0) / 100)

                    if current_val >= max_alloc_val:
                        add_autotrade_log(
                            f"[{ticker}] Lewati — alokasi sudah penuh "
                            f"(Rp {current_val:,.0f} / max Rp {max_alloc_val:,.0f})", "warning"
                        )
                        time.sleep(3)
                        continue

                    # Gunakan stop loss dari AI, fallback ke 7%
                    sl_price = float(es.get("stop_loss") or current_price * 0.93)
                    # Validasi SL — SL harus di bawah harga saat ini untuk BUY
                    if sl_price >= current_price:
                        sl_price = current_price * 0.93

                    sizing = calculate_position_size(
                        capital=port_value,
                        risk_per_trade_pct=float(config.get("risk_per_trade_pct", 1.0)),
                        entry_price=current_price,
                        stop_loss_price=sl_price,
                        max_position_pct=config.get("max_allocation_pct", 20.0) / 100,
                    )

                    if not sizing.get("success"):
                        add_autotrade_log(f"[{ticker}] Sizing error: {sizing.get('error','?')}", "warning")
                        time.sleep(3)
                        continue

                    recommended_lots = max(1, sizing["recommended_lots"])
                    cost_estimate    = recommended_lots * 100 * current_price * 1.002

                    if cost_estimate > cash:
                        add_autotrade_log(
                            f"[{ticker}] Saldo tidak cukup (butuh Rp {cost_estimate:,.0f}, ada Rp {cash:,.0f})", "warning"
                        )
                        time.sleep(3)
                        continue

                    # Eksekusi BUY
                    note     = f"[AUTO-BUY] AI={recommendation} Conf={confidence:.0f}% SL=Rp{sl_price:,.0f} TP1=Rp{es.get('take_profit_1',0):,.0f}"
                    buy_res  = buy_stock(ticker, current_price, recommended_lots, note)
                    if buy_res["success"]:
                        add_autotrade_log(
                            f"[{ticker}] AUTO-BUY: {recommended_lots} lot @ Rp {current_price:,.0f}. "
                            f"Total: Rp {buy_res.get('total_cost', 0):,.0f} | "
                            f"Sisa kas: Rp {buy_res.get('remaining_cash', 0):,.0f}", "success"
                        )
                        bought_count += 1
                        cash -= cost_estimate  # Update local cash for next iterations
                    else:
                        add_autotrade_log(f"[{ticker}] BUY gagal: {buy_res.get('error','?')}", "error")

                # ─── SELL LOGIC ──────────────────────────────────────────
                elif recommendation in ["SELL", "STRONG SELL"] and has_position:
                    lots_to_sell = pos_details.get("lots", 0)
                    if lots_to_sell > 0:
                        note     = f"[AUTO-SELL] AI={recommendation} Conf={confidence:.0f}% — Reversal/Exit"
                        sell_res = sell_stock(ticker, current_price, lots_to_sell, note)
                        if sell_res["success"]:
                            pnl    = sell_res.get("pnl_rp", 0)
                            pnl_p  = sell_res.get("pnl_pct", 0)
                            icon   = "+" if pnl >= 0 else ""
                            add_autotrade_log(
                                f"[{ticker}] AUTO-SELL: {lots_to_sell} lot @ Rp {current_price:,.0f}. "
                                f"P&L: {icon}Rp {pnl:,.0f} ({icon}{pnl_p:.2f}%)", "success"
                            )
                            sold_count += 1
                            cash += sell_res.get("net_proceed", 0)
                        else:
                            add_autotrade_log(f"[{ticker}] SELL gagal: {sell_res.get('error','?')}", "error")
                else:
                    add_autotrade_log(
                        f"[{ticker}] HOLD — tidak ada aksi (rec={recommendation}, conf={confidence:.0f}%)", "info"
                    )

                # Delay per emiten (respect Gemini API rate limit)
                time.sleep(5)

            except Exception as e:
                add_autotrade_log(f"[{ticker}] Exception: {str(e)}", "error")
                logger.exception(f"[autotrade] Unexpected error on {ticker}")

        add_autotrade_log(
            f"Auto-scan selesai. BUY: {bought_count} | SELL: {sold_count} | "
            f"Sisa kas: Rp {cash:,.0f}", "success"
        )

    def stop(self):
        self.stop_event.set()
        self.scan_event.set()  # Unblock wait
