"""
server.py — Flask API Server untuk AI Trading Bot Saham Indonesia
Main orchestrator yang menghubungkan semua modul
"""
import os, sys, logging, json, time
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime
import threading

# Setup path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from config import FLASK_PORT, FLASK_DEBUG, DEFAULT_WATCHLIST, DATA_DIR
from core.data_fetcher import get_stock_info, get_price_history, get_ihsg_data
from core.fundamental import run_fundamental_analysis
from core.technical import run_technical_analysis
from core.news_analyzer import fetch_all_news
from core.flow_analyzer import run_flow_analysis
from core.gemini_brain import analyze_stock_with_ai, generate_market_outlook
from trading.portfolio import (
    get_portfolio_summary, buy_stock, sell_stock,
    load_trade_history, reset_portfolio
)
from trading.risk_manager import calculate_position_size, get_risk_metrics
from core.autotrade import (
    load_autotrade_config, save_autotrade_config,
    load_autotrade_logs, add_autotrade_log,
    clear_autotrade_logs, AutoTradingEngine
)
from core.alert_manager import (
    load_alert_config, save_alert_config,
    send_telegram, test_telegram_connection,
    send_trade_signal, send_autotrade_alert,
)
from trading.portfolio import calculate_leverage, LEVERAGE_CONFIG

# ─── Logging Setup ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Flask App ─────────────────────────────────────────────
app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)

os.makedirs(DATA_DIR, exist_ok=True)

# ─── In-memory cache ───────────────────────────────────────
_cache = {}
CACHE_TTL    = 300  # 5 menit untuk data normal
CACHE_TTL_RT = 15   # 15 detik untuk data realtime


def get_cached(key: str, ttl: int = None):
    if key in _cache:
        data, ts = _cache[key]
        effective_ttl = ttl if ttl is not None else CACHE_TTL
        if time.time() - ts < effective_ttl:
            return data
    return None


def set_cached(key: str, data):
    _cache[key] = (data, time.time())


# ─────────────────────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve frontend."""
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    """
    Serve static frontend assets (app.js, styles.css, dll).
    Hanya izinkan file yang ada di BASE_DIR, bukan direktori.
    Blok akses ke path API agar tidak bentrok.
    """
    # Jangan tangani path yang dimulai dengan 'api/'
    if filename.startswith("api/"):
        from flask import abort
        abort(404)
    safe_path = os.path.join(BASE_DIR, filename)
    if os.path.isfile(safe_path):
        return send_from_directory(BASE_DIR, filename)
    from flask import abort
    abort(404)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat(), "version": "1.0.0"})


# ─── Stock Info ──────────────────────────────────────────────
@app.route("/api/stock/<ticker>")
def stock_info(ticker):
    """Get basic stock info."""
    cached = get_cached(f"info_{ticker}")
    if cached:
        return jsonify(cached)

    result = get_stock_info(ticker)
    if result["success"]:
        set_cached(f"info_{ticker}", result)
    return jsonify(result)


@app.route("/api/stock/<ticker>/history")
def stock_history(ticker):
    """Get OHLCV history."""
    period   = request.args.get("period", "6mo")
    interval = request.args.get("interval", "1d")
    cache_key = f"hist_{ticker}_{period}_{interval}"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

    result = get_price_history(ticker, period=period, interval=interval)
    if result["success"]:
        set_cached(cache_key, result)
    return jsonify(result)


@app.route("/api/stock/<ticker>/realtime")
def stock_realtime(ticker):
    """
    Get latest 1-minute OHLCV candles for real-time chart updates.
    Uses yfinance with 1d period + 1m interval (most recent session).
    Cache is only 15 seconds to keep data fresh.
    """
    cache_key = f"rt_{ticker}"
    cached = get_cached(cache_key, ttl=CACHE_TTL_RT)
    if cached:
        return jsonify(cached)

    try:
        import yfinance as yf
        jk    = f"{ticker.upper()}.JK"
        stock = yf.Ticker(jk)

        # 1-minute bars for today
        df = stock.history(period="1d", interval="1m")

        if df is None or df.empty:
            # Fallback: last known price from info
            info_res = get_stock_info(ticker)
            if info_res["success"]:
                d = info_res["data"]
                result = {
                    "success": True,
                    "ticker": ticker.upper(),
                    "realtime": True,
                    "last_price": d.get("current_price", 0),
                    "change_pct": d.get("change_pct", 0),
                    "volume": d.get("volume", 0),
                    "bars": [],
                    "source": "info_fallback",
                }
                return jsonify(result)
            return jsonify({"success": False, "error": "No realtime data"})

        # Konversi ke WIB (Asia/Jakarta) lalu jadikan naive sebelum hitung unix timestamp
        # Ini penting: tz_localize(None) TANPA konversi dulu = jam salah
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Jakarta").tz_localize(None)
        else:
            # Tidak ada tz — cek apakah jam masih UTC (rata-rata jam < 7)
            sample_hours = df.index.hour.mean() if len(df) > 0 else 12
            if sample_hours < 7:
                df.index = df.index + pd.Timedelta(hours=7)

        bars = []
        for ts, row in df.iterrows():
            # ts sekarang naive WIB — hitung unix timestamp sebagai WIB
            import calendar
            unix_ts = int(calendar.timegm(ts.timetuple())) - 7 * 3600  # naive WIB → UTC unix
            bars.append({
                "time":   unix_ts,
                "open":   round(float(row["Open"]), 0),
                "high":   round(float(row["High"]), 0),
                "low":    round(float(row["Low"]), 0),
                "close":  round(float(row["Close"]), 0),
                "volume": int(row["Volume"]),
            })

        last_bar  = bars[-1] if bars else {}
        prev_bar  = bars[-2] if len(bars) >= 2 else last_bar
        last_price = last_bar.get("close", 0)
        prev_close = prev_bar.get("close", last_price)
        change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close else 0

        result = {
            "success":    True,
            "ticker":     ticker.upper(),
            "realtime":   True,
            "last_price": last_price,
            "change_pct": round(change_pct, 2),
            "volume":     last_bar.get("volume", 0),
            "bars":       bars[-60:],  # last 60 1-minute bars
            "bar_count":  len(bars),
            "source":     "yfinance_1m",
            "fetched_at": datetime.now().isoformat(),
        }
        # Short cache — 15 seconds
        _cache[cache_key] = (result, time.time())
        return jsonify(result)

    except Exception as e:
        logger.warning(f"[realtime] Error for {ticker}: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/stock/<ticker>/news")
def stock_news_only(ticker):
    """
    Get latest news and whale signals for a ticker.
    Uses 30 seconds cache to be reactive for fast trading.
    """
    cache_key = f"news_only_{ticker}"
    cached = get_cached(cache_key, ttl=30)
    if cached:
        return jsonify(cached)

    try:
        info_res = get_stock_info(ticker)
        company_name = info_res.get("data", {}).get("company_name", ticker) if info_res["success"] else ticker
        result = fetch_all_news(ticker, company_name, max_per_source=10)
        if result["success"]:
            _cache[cache_key] = (result, time.time())
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ─── Full Analysis ───────────────────────────────────────────
@app.route("/api/analyze/<ticker>", methods=["GET"])
def analyze_stock(ticker):
    """
    Full AI Analysis endpoint — mengintegrasikan semua modul.
    Ini adalah endpoint utama yang dipanggil saat user analisis saham.
    """
    ticker = ticker.upper()
    use_ai = request.args.get("ai", "true").lower() == "true"

    logger.info(f"[API] Full analysis requested for {ticker} (AI: {use_ai})")

    try:
        # 1. Data dasar saham
        info_result = get_stock_info(ticker)
        if not info_result["success"]:
            return jsonify({"success": False, "error": f"Saham {ticker} tidak ditemukan"}), 404

        stock_data = info_result

        # 2. Historical data (untuk teknikal & flow)
        hist_result = get_price_history(ticker, period="1y", interval="1d")
        history = hist_result.get("data", []) if hist_result["success"] else []

        # 3. Analisis fundamental
        fund_result = run_fundamental_analysis(stock_data.get("data", {}))

        # 4. Analisis teknikal
        tech_result = run_technical_analysis(history) if history else {"success": False, "error": "No history"}

        # 5. Berita & sentimen
        company_name = stock_data.get("data", {}).get("company_name", ticker)
        news_result  = fetch_all_news(ticker, company_name, max_per_source=8)

        # 6. Fund flow analysis
        flow_result = run_flow_analysis(ticker, history) if history else {"success": False}

        # 7. Portfolio context (apakah ada posisi?)
        try:
            from trading.portfolio import load_portfolio
            portfolio = load_portfolio()
            pos = portfolio.get("positions", {}).get(ticker)
            current_price = stock_data.get("data", {}).get("current_price", 0)
            portfolio_context = {
                "has_position": pos is not None,
                "position": {
                    "lots": pos.get("lots", 0) if pos else 0,
                    "avg_price": pos.get("avg_price", 0) if pos else 0,
                    "pnl_pct": ((current_price - pos.get("avg_price", 0)) / pos.get("avg_price", 1) * 100) if pos else 0,
                    "pnl_rp":  ((current_price - pos.get("avg_price", 0)) * pos.get("shares", 0)) if pos else 0,
                } if pos else {}
            } if pos else {"has_position": False}
        except Exception:
            portfolio_context = {"has_position": False}

        # 8. AI Analysis (Gemini)
        ai_result = None
        if use_ai:
            ai_result = analyze_stock_with_ai(
                ticker=ticker,
                stock_info=stock_data,
                fundamental=fund_result,
                technical=tech_result if tech_result.get("success") else {},
                news=news_result,
                flow=flow_result if flow_result.get("success") else {},
                portfolio_context=portfolio_context,
            )

        # ─── Composite overall score ───────────────────
        scores = {
            "fundamental": fund_result.get("composite_score", 50),
            "technical":   tech_result.get("composite_score", 50) if tech_result.get("success") else 50,
            "sentiment":   news_result.get("sentiment_summary", {}).get("score", 50),
            "flow":        flow_result.get("composite_score", 50) if flow_result.get("success") else 50,
        }
        overall_score = (
            scores["fundamental"] * 0.30 +
            scores["technical"]   * 0.30 +
            scores["sentiment"]   * 0.20 +
            scores["flow"]        * 0.20
        )

        response = {
            "success":    True,
            "ticker":     ticker,
            "stock_info": stock_data,
            "fundamental": fund_result,
            "technical":  tech_result,
            "news":       news_result,
            "flow":       flow_result,
            "portfolio_context": portfolio_context,
            "ai_analysis": ai_result,
            "scores":     scores,
            "overall_score": round(overall_score, 1),
            "analyzed_at": datetime.now().isoformat(),
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"[API] Analysis error for {ticker}: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ─── Watchlist ───────────────────────────────────────────────
@app.route("/api/watchlist")
def watchlist():
    """Get quick data untuk semua saham di watchlist."""
    cache_key = "watchlist_summary"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

    results = []
    for ticker in DEFAULT_WATCHLIST[:12]:  # limit 12 untuk performa
        try:
            info = get_stock_info(ticker)
            if info["success"]:
                d = info["data"]
                fund = run_fundamental_analysis(d)
                results.append({
                    "ticker": ticker,
                    "name": d.get("company_name", ticker),
                    "price": d.get("current_price", 0),
                    "change_pct": d.get("change_pct", 0),
                    "volume": d.get("volume", 0),
                    "market_cap": d.get("market_cap", 0),
                    "pe_ratio": d.get("pe_ratio", 0),
                    "fundamental_score": fund.get("composite_score", 50),
                    "fundamental_signal": fund.get("signal", "N/A"),
                    "sector": d.get("sector", "N/A"),
                })
        except Exception as e:
            logger.warning(f"[watchlist] Error for {ticker}: {e}")

    data = {"success": True, "data": results, "count": len(results)}
    set_cached(cache_key, data)
    return jsonify(data)


# ─── IHSG ────────────────────────────────────────────────────
@app.route("/api/ihsg")
def ihsg():
    cached = get_cached("ihsg")
    if cached:
        return jsonify(cached)
    result = get_ihsg_data(period="3mo")
    if result["success"]:
        set_cached("ihsg", result)
    return jsonify(result)


# ─── Portfolio API ───────────────────────────────────────────
@app.route("/api/portfolio")
def portfolio_summary():
    """Get portfolio summary dengan harga terkini."""
    try:
        from trading.portfolio import load_portfolio
        portfolio = load_portfolio()
        positions = portfolio.get("positions", {})

        current_prices = {}
        for ticker in positions:
            try:
                info = get_stock_info(ticker)
                if info["success"]:
                    current_prices[ticker] = info["data"].get("current_price", 0)
            except Exception:
                pass

        summary = get_portfolio_summary(current_prices)
        risk    = get_risk_metrics(summary)
        summary["risk_metrics"] = risk

        return jsonify({"success": True, "data": summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/portfolio/buy", methods=["POST"])
def portfolio_buy():
    """Execute paper buy order."""
    data   = request.json or {}
    ticker = data.get("ticker", "").upper()
    price  = float(data.get("price", 0))
    lots   = int(data.get("lots", 0))
    note   = data.get("note", "")

    if not ticker or price <= 0 or lots <= 0:
        return jsonify({"success": False, "error": "Parameter tidak valid"}), 400

    result = buy_stock(ticker, price, lots, note)
    return jsonify(result)


@app.route("/api/portfolio/sell", methods=["POST"])
def portfolio_sell():
    """Execute paper sell order."""
    data   = request.json or {}
    ticker = data.get("ticker", "").upper()
    price  = float(data.get("price", 0))
    lots   = int(data.get("lots", 0))
    note   = data.get("note", "")

    if not ticker or price <= 0 or lots <= 0:
        return jsonify({"success": False, "error": "Parameter tidak valid"}), 400

    result = sell_stock(ticker, price, lots, note)
    return jsonify(result)


@app.route("/api/portfolio/history")
def portfolio_history():
    """Get trade history."""
    history = load_trade_history()
    return jsonify({"success": True, "data": history, "count": len(history)})


@app.route("/api/portfolio/reset", methods=["POST"])
def portfolio_reset():
    """Reset portfolio."""
    data    = request.json or {}
    confirm = data.get("confirm", False)
    result  = reset_portfolio(confirm=confirm)
    return jsonify(result)


# ─── Position Sizing ─────────────────────────────────────────
@app.route("/api/risk/position-size")
def position_size():
    """Calculate optimal position size."""
    try:
        capital   = float(request.args.get("capital", 100_000_000))
        risk_pct  = float(request.args.get("risk_pct", 1.0))
        entry     = float(request.args.get("entry", 0))
        stop_loss = float(request.args.get("stop_loss", 0))

        if entry <= 0 or stop_loss <= 0:
            return jsonify({"success": False, "error": "Entry dan stop loss harus > 0"})

        result = calculate_position_size(capital, risk_pct, entry, stop_loss)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ─── Lightweight Price Endpoints ─────────────────────────────
@app.route("/api/stock/<ticker>/price")
def stock_price_only(ticker):
    """
    Ultra-lightweight price endpoint — hanya current price, change, volume.
    Cache 15 detik. Digunakan untuk auto-refresh harga di UI.
    """
    cache_key = f"price_{ticker.upper()}"
    cached = get_cached(cache_key, ttl=15)
    if cached:
        return jsonify(cached)
    try:
        import yfinance as yf
        jk = f"{ticker.upper()}.JK"
        stock = yf.Ticker(jk)
        fi = stock.fast_info
        current_price = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', 0)
        prev_close    = getattr(fi, 'previous_close', current_price) or current_price
        volume        = getattr(fi, 'last_volume', 0) or 0
        change        = current_price - prev_close
        change_pct    = (change / prev_close * 100) if prev_close else 0
        result = {
            "success":     True,
            "ticker":      ticker.upper(),
            "price":       round(float(current_price), 0),
            "prev_close":  round(float(prev_close), 0),
            "change":      round(float(change), 0),
            "change_pct":  round(float(change_pct), 2),
            "volume":      int(volume),
            "fetched_at":  datetime.now().isoformat(),
        }
        _cache[cache_key] = (result, time.time())
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/market/prices")
def market_prices_bulk():
    """
    Bulk price refresh untuk semua saham di watchlist.
    Digunakan oleh frontend untuk auto-update harga di tabel watchlist.
    Cache per-ticker 15 detik.
    """
    tickers = request.args.get("tickers", "")
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else DEFAULT_WATCHLIST[:12]

    results = {}
    for ticker in ticker_list:
        cache_key = f"price_{ticker}"
        cached = get_cached(cache_key, ttl=15)
        if cached:
            results[ticker] = cached
            continue
        try:
            import yfinance as yf
            jk = f"{ticker}.JK"
            stock = yf.Ticker(jk)
            fi = stock.fast_info
            current_price = getattr(fi, 'last_price', None) or getattr(fi, 'previous_close', 0)
            prev_close    = getattr(fi, 'previous_close', current_price) or current_price
            volume        = getattr(fi, 'last_volume', 0) or 0
            change        = current_price - prev_close
            change_pct    = (change / prev_close * 100) if prev_close else 0
            r = {
                "success":    True,
                "ticker":     ticker,
                "price":      round(float(current_price), 0),
                "change_pct": round(float(change_pct), 2),
                "volume":     int(volume),
            }
            _cache[cache_key] = (r, time.time())
            results[ticker] = r
        except Exception as e:
            results[ticker] = {"success": False, "error": str(e)}

    return jsonify({"success": True, "prices": results, "count": len(results), "fetched_at": datetime.now().isoformat()})



@app.route("/api/market/outlook")
def market_outlook():
    """Generate AI market outlook untuk watchlist."""
    cached = get_cached("market_outlook")
    if cached:
        return jsonify(cached)
    try:
        # Quick data watchlist
        watchlist_data = []
        for ticker in DEFAULT_WATCHLIST[:8]:
            try:
                info = get_stock_info(ticker)
                if info["success"]:
                    d = info["data"]
                    fund = run_fundamental_analysis(d)
                    watchlist_data.append({
                        "ticker": ticker,
                        "price": d.get("current_price", 0),
                        "change_pct": d.get("change_pct", 0),
                        "overall_score": fund.get("composite_score", 50),
                        "signal": fund.get("signal", "N/A"),
                    })
            except Exception:
                pass

        result = generate_market_outlook(watchlist_data)
        if result["success"]:
            set_cached("market_outlook", result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ─── Auto Trading API ────────────────────────────────────────
@app.route("/api/autotrade/status", methods=["GET"])
def autotrade_status():
    config = load_autotrade_config()
    engine = globals().get('autotrade_engine')
    return jsonify({
        "success": True,
        "config": config,
        "is_scanning": engine.is_scanning if engine else False,
        "last_scan_time": engine.last_scan_time if engine else None,
        "engine_alive": engine.is_alive() if engine else False,
    })

@app.route("/api/autotrade/toggle", methods=["POST"])
def autotrade_toggle():
    data = request.json or {}
    enabled = data.get("enabled", False)
    
    config = load_autotrade_config()
    config["enabled"] = enabled
    save_autotrade_config(config)
    
    status_str = "diaktifkan" if enabled else "dinonaktifkan"
    add_autotrade_log(f"Auto-trading toggle diubah menjadi {status_str.upper()}", "info")
    
    return jsonify({"success": True, "enabled": enabled})

@app.route("/api/autotrade/config", methods=["POST"])
def autotrade_update_config():
    data = request.json or {}
    config = load_autotrade_config()
    
    if "interval_minutes" in data:
        config["interval_minutes"] = max(1, int(data["interval_minutes"]))
    if "max_allocation_pct" in data:
        config["max_allocation_pct"] = min(40.0, max(5.0, float(data["max_allocation_pct"])))
    if "risk_per_trade_pct" in data:
        config["risk_per_trade_pct"] = min(5.0, max(0.5, float(data["risk_per_trade_pct"])))
    if "min_confidence_pct" in data:
        config["min_confidence_pct"] = min(95, max(60, int(data["min_confidence_pct"])))
    if "trailing_stop_pct" in data:
        config["trailing_stop_pct"] = min(15.0, max(2.0, float(data["trailing_stop_pct"])))
    if "enable_stop_loss_monitor" in data:
        config["enable_stop_loss_monitor"] = bool(data["enable_stop_loss_monitor"])
    if "watchlist" in data:
        config["watchlist"] = list(data["watchlist"])

    save_autotrade_config(config)
    add_autotrade_log("Konfigurasi auto-trading berhasil diperbarui", "info")
    return jsonify({"success": True, "config": config})

@app.route("/api/autotrade/logs", methods=["GET"])
def autotrade_logs():
    logs = load_autotrade_logs()
    return jsonify({"success": True, "data": logs})

@app.route("/api/autotrade/logs/clear", methods=["POST"])
def autotrade_clear_logs():
    clear_autotrade_logs()
    return jsonify({"success": True})

@app.route("/api/autotrade/trigger", methods=["POST"])
def autotrade_trigger_scan():
    """Manual trigger to start scanning immediately."""
    engine = globals().get('autotrade_engine')
    if engine and engine.is_scanning:
        return jsonify({"success": False, "error": "Scanning sedang berjalan, harap tunggu..."}), 400

    config = load_autotrade_config()

    if config.get("enabled", False):
        # Engine running — signal it to scan now via event
        if engine:
            engine.trigger_scan_now()
            add_autotrade_log("Manual scan dipicu oleh user (melalui signal event)", "info")
            return jsonify({"success": True, "message": "Scan segera dijalankan oleh engine yang aktif"})

    # Engine disabled or not running — run scan in a standalone background thread
    def force_scan():
        try:
            if engine:
                engine.is_scanning = True
                engine.run_scan(config)
        except Exception as e:
            add_autotrade_log(f"Manual scan error: {str(e)}", "error")
        finally:
            if engine:
                engine.is_scanning = False
                engine.last_scan_time = datetime.now().isoformat()

    threading.Thread(target=force_scan, daemon=True, name="ManualScanThread").start()
    add_autotrade_log("Manual scan watchlist dipicu oleh user (engine inactive)", "info")
    return jsonify({"success": True, "message": "Scan manual dimulai di background"})


# ─── Fast Trade & Leverage API ───────────────────────────────

@app.route("/api/trade/leverage-calc", methods=["POST"])
def leverage_calc():
    """Hitung detail posisi leverage untuk preview sebelum order."""
    data     = request.json or {}
    ticker   = data.get("ticker", "").upper()
    price    = float(data.get("price", 0))
    lots     = int(data.get("lots", 1))
    leverage = int(data.get("leverage", 1))

    if price <= 0 or lots <= 0:
        return jsonify({"success": False, "error": "Price dan lots harus > 0"})

    try:
        from trading.portfolio import load_portfolio
        portfolio = load_portfolio()
        capital   = portfolio.get("cash", 0)

        results = {}
        for lev in [1, 2, 3, 5]:
            results[str(lev)] = calculate_leverage(price, lots, lev, capital)

        selected = calculate_leverage(price, lots, leverage, capital)

        return jsonify({
            "success":   True,
            "ticker":    ticker,
            "price":     price,
            "lots":      lots,
            "selected":  selected,
            "all_options": results,
            "cash":      capital,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/trade/fast-buy", methods=["POST"])
def fast_buy():
    """Fast Buy — eksekusi beli 1 klik + kirim alert Telegram."""
    data      = request.json or {}
    ticker    = data.get("ticker", "").upper()
    price     = float(data.get("price", 0))
    lots      = int(data.get("lots", 1))
    leverage  = int(data.get("leverage", 1))
    stop_loss = float(data.get("stop_loss", 0))
    take_profit = float(data.get("take_profit", 0))
    note      = data.get("note", "Fast Trade")
    ai_conf   = int(data.get("ai_confidence", 0))

    if not ticker or price <= 0 or lots <= 0:
        return jsonify({"success": False, "error": "Parameter tidak valid"}), 400

    # Eksekusi order di portfolio (paper trading)
    lev_data = calculate_leverage(price, lots, leverage, 0)
    actual_lots = lots
    result = buy_stock(ticker, price, actual_lots, note=f"{note} [leverage={leverage}x]")

    if not result["success"]:
        return jsonify(result), 400

    # Tambah info leverage ke result
    result["leverage"]   = leverage
    result["lev_data"]   = lev_data

    # Kirim alert Telegram
    alert_result = send_trade_signal(
        action="BUY", ticker=ticker, price=price, lots=actual_lots,
        leverage=leverage, note=note, ai_confidence=ai_conf,
        stop_loss=stop_loss, take_profit=take_profit,
    )
    result["alert"] = alert_result

    # Invalidate cache portfolio
    _cache.pop("watchlist_summary", None)

    # Broadcast ke SSE clients
    _sse_broadcast("trade", {
        "action": "BUY", "ticker": ticker, "price": price,
        "lots": actual_lots, "leverage": leverage,
        "total_cost": result.get("total_cost", 0),
        "remaining_cash": result.get("remaining_cash", 0),
        "message": result.get("message", ""),
        "timestamp": datetime.now().isoformat(),
    })

    return jsonify(result)
def fast_sell():
    """Fast Sell — eksekusi jual 1 klik + kirim alert Telegram."""
    data      = request.json or {}
    ticker    = data.get("ticker", "").upper()
    price     = float(data.get("price", 0))
    lots      = int(data.get("lots", 1))
    note      = data.get("note", "Fast Trade")
    stop_loss = float(data.get("stop_loss", 0))
    take_profit = float(data.get("take_profit", 0))
    ai_conf   = int(data.get("ai_confidence", 0))

    if not ticker or price <= 0 or lots <= 0:
        return jsonify({"success": False, "error": "Parameter tidak valid"}), 400

    result = sell_stock(ticker, price, lots, note=f"{note} [fast-sell]")
    if not result["success"]:
        return jsonify(result), 400

    alert_result = send_trade_signal(
        action="SELL", ticker=ticker, price=price, lots=lots,
        leverage=1, note=note, ai_confidence=ai_conf,
        stop_loss=stop_loss, take_profit=take_profit,
    )
    result["alert"] = alert_result
    _cache.pop("watchlist_summary", None)

    # Broadcast ke SSE clients
    _sse_broadcast("trade", {
        "action": "SELL", "ticker": ticker, "price": price,
        "lots": lots,
        "pnl_rp": result.get("pnl_rp", 0),
        "pnl_pct": result.get("pnl_pct", 0),
        "net_proceed": result.get("net_proceed", 0),
        "remaining_cash": result.get("remaining_cash", 0),
        "message": result.get("message", ""),
        "timestamp": datetime.now().isoformat(),
    })

    return jsonify(result)


@app.route("/api/trade/signal", methods=["POST"])
def send_signal_only():
    """Kirim sinyal trading ke Telegram TANPA eksekusi order (untuk live trading manual)."""
    data        = request.json or {}
    action      = data.get("action", "BUY").upper()
    ticker      = data.get("ticker", "").upper()
    price       = float(data.get("price", 0))
    lots        = int(data.get("lots", 1))
    leverage    = int(data.get("leverage", 1))
    stop_loss   = float(data.get("stop_loss", 0))
    take_profit = float(data.get("take_profit", 0))
    note        = data.get("note", "")
    ai_conf     = int(data.get("ai_confidence", 0))

    if not ticker or price <= 0:
        return jsonify({"success": False, "error": "Ticker dan harga wajib diisi"}), 400

    result = send_trade_signal(
        action=action, ticker=ticker, price=price, lots=lots,
        leverage=leverage, note=note, ai_confidence=ai_conf,
        stop_loss=stop_loss, take_profit=take_profit,
    )
    return jsonify(result)


# ─── Alert Config API ─────────────────────────────────────────

@app.route("/api/alert/config", methods=["GET"])
def get_alert_config():
    """Get konfigurasi alert."""
    cfg = load_alert_config()
    # Sembunyikan token dari response (hanya tampilkan apakah sudah diset)
    safe = cfg.copy()
    if safe.get("telegram_bot_token"):
        safe["telegram_bot_token_set"] = True
        safe["telegram_bot_token"] = safe["telegram_bot_token"][:8] + "..." if len(safe.get("telegram_bot_token","")) > 8 else ""
    else:
        safe["telegram_bot_token_set"] = False
    return jsonify({"success": True, "config": safe})


@app.route("/api/alert/config", methods=["POST"])
def update_alert_config():
    """Update konfigurasi alert."""
    data = request.json or {}
    cfg  = load_alert_config()

    # Update fields yang dikirim
    bool_fields = ["telegram_enabled", "alert_on_buy", "alert_on_sell", "alert_on_signal", "alert_on_autotrade"]
    str_fields  = ["telegram_bot_token", "telegram_chat_id", "broker_name", "broker_app_name"]
    int_fields  = ["min_confidence"]

    for f in bool_fields:
        if f in data:
            cfg[f] = bool(data[f])
    for f in str_fields:
        if f in data and data[f]:
            cfg[f] = str(data[f]).strip()
    for f in int_fields:
        if f in data:
            cfg[f] = int(data[f])

    save_alert_config(cfg)
    return jsonify({"success": True, "message": "Konfigurasi alert berhasil disimpan"})


@app.route("/api/alert/test", methods=["POST"])
def test_alert():
    """Test kirim pesan Telegram."""
    data      = request.json or {}
    bot_token = data.get("telegram_bot_token", "")
    chat_id   = data.get("telegram_chat_id", "")

    # Kalau tidak dikasih, ambil dari config yang tersimpan
    if not bot_token or not chat_id:
        cfg       = load_alert_config()
        bot_token = bot_token or cfg.get("telegram_bot_token", "")
        chat_id   = chat_id   or cfg.get("telegram_chat_id", "")

    if not bot_token or not chat_id:
        return jsonify({"success": False, "error": "Bot token dan Chat ID belum diset"})

    result = test_telegram_connection(bot_token, chat_id)
    return jsonify(result)


@app.route("/api/trade/leverage-options", methods=["GET"])
def leverage_options():
    """Get semua opsi leverage yang tersedia."""
    return jsonify({
        "success": True,
        "options": [
            {"value": k, **v} for k, v in LEVERAGE_CONFIG.items()
        ]
    })


# ─── Server-Sent Events (SSE) — Realtime Stream ──────────────
import queue as _queue
from flask import Response, stream_with_context

# Global broadcast queues: { client_id: Queue }
_sse_clients: dict = {}
_sse_lock = threading.Lock()


def _sse_broadcast(event: str, data: dict):
    """Push event ke semua SSE client yang tersambung."""
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for cid, q in _sse_clients.items():
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(cid)
        for cid in dead:
            _sse_clients.pop(cid, None)


def _portfolio_snapshot():
    """Ambil snapshot portfolio ringan (harga dari cache)."""
    try:
        from trading.portfolio import load_portfolio, load_trade_history
        portfolio = load_portfolio()
        positions = portfolio.get("positions", {})
        cash = portfolio.get("cash", 0)
        init_cap = portfolio.get("initial_capital", 100_000_000)

        positions_out = []
        total_mkt = 0
        for ticker, pos in positions.items():
            cached = get_cached(f"price_{ticker}", ttl=20)
            price = cached.get("price", pos.get("avg_price", 0)) if cached else pos.get("avg_price", 0)
            shares = pos.get("shares", 0)
            avg = pos.get("avg_price", 0)
            mkt = price * shares
            cost = avg * shares
            pnl = mkt - cost
            pnl_pct = (pnl / cost * 100) if cost else 0
            total_mkt += mkt
            positions_out.append({
                "ticker":        ticker,
                "lots":          pos.get("lots", 0),
                "shares":        shares,
                "avg_price":     avg,
                "current_price": price,
                "market_value":  round(mkt, 0),
                "pnl_rp":        round(pnl, 0),
                "pnl_pct":       round(pnl_pct, 2),
            })

        total_val = total_mkt + cash
        total_pnl = total_val - init_cap
        total_pnl_pct = (total_pnl / init_cap * 100) if init_cap else 0

        history = load_trade_history()
        last5 = list(reversed(history[-5:])) if history else []

        return {
            "cash":                cash,
            "total_market_value":  round(total_mkt, 0),
            "total_portfolio_value": round(total_val, 0),
            "total_pnl_rp":        round(total_pnl, 0),
            "total_pnl_pct":       round(total_pnl_pct, 2),
            "positions":           positions_out,
            "last_trades":         last5,
            "timestamp":           datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


def _flow_snapshot(ticker: str):
    """Ambil snapshot flow dana ringan dari cache / hitung ulang cepat."""
    try:
        import yfinance as yf
        jk = f"{ticker.upper()}.JK"
        stock = yf.Ticker(jk)
        fi = stock.fast_info

        price     = float(getattr(fi, "last_price",      None) or getattr(fi, "previous_close", 0) or 0)
        prev      = float(getattr(fi, "previous_close",  price) or price)
        volume    = int(getattr(fi,   "last_volume",     0) or 0)
        avg_vol   = int(getattr(fi,   "three_month_average_volume", 1) or 1)
        change    = price - prev
        change_pct = (change / prev * 100) if prev else 0
        vol_ratio  = volume / avg_vol if avg_vol else 1.0

        # Dana masuk/keluar estimasi sederhana: positif = masuk, negatif = keluar
        money_flow_rp = change * volume   # Rp — proxy beli-jual hari ini
        flow_dir = "MASUK" if money_flow_rp >= 0 else "KELUAR"
        flow_strength = min(100, abs(vol_ratio * 50))

        return {
            "ticker":        ticker.upper(),
            "price":         round(price, 0),
            "change":        round(change, 0),
            "change_pct":    round(change_pct, 2),
            "volume":        volume,
            "vol_ratio":     round(vol_ratio, 2),
            "money_flow_rp": round(money_flow_rp, 0),
            "flow_direction": flow_dir,
            "flow_strength": round(flow_strength, 1),
            "timestamp":     datetime.now().isoformat(),
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "timestamp": datetime.now().isoformat()}


def _sse_portfolio_worker():
    """Background thread: push portfolio snapshot + watchlist flow setiap 3 detik."""
    import time as _time
    logger.info("[SSE] Portfolio stream worker started")
    while True:
        try:
            snap = _portfolio_snapshot()
            _sse_broadcast("portfolio", snap)

            # Harga tickers di posisi aktif
            from trading.portfolio import load_portfolio
            positions = load_portfolio().get("positions", {})
            if positions:
                prices = {}
                for ticker in list(positions.keys()):
                    cached = get_cached(f"price_{ticker}", ttl=20)
                    if cached:
                        prices[ticker] = cached
                if prices:
                    _sse_broadcast("prices", {"prices": prices, "timestamp": datetime.now().isoformat()})

        except Exception as e:
            logger.debug(f"[SSE worker] {e}")
        _time.sleep(3)


def _sse_flow_worker():
    """Background thread: push flow data watchlist setiap 5 detik."""
    import time as _time
    logger.info("[SSE] Flow stream worker started")
    idx = 0
    while True:
        try:
            # Rotasi watchlist agar tidak semua sekaligus (hemat API)
            tickers = DEFAULT_WATCHLIST[:8]
            ticker = tickers[idx % len(tickers)]
            idx += 1

            # Gunakan cache price dulu
            cached = get_cached(f"price_{ticker}", ttl=20)
            if cached:
                flow_data = {
                    "ticker":         ticker,
                    "price":          cached.get("price", 0),
                    "change_pct":     cached.get("change_pct", 0),
                    "volume":         cached.get("volume", 0),
                    "flow_direction": "MASUK" if cached.get("change_pct", 0) >= 0 else "KELUAR",
                    "timestamp":      datetime.now().isoformat(),
                }
                _sse_broadcast("flow", flow_data)
        except Exception as e:
            logger.debug(f"[SSE flow worker] {e}")
        _time.sleep(5)


# Start SSE background workers saat module di-import
_sse_portfolio_thread = threading.Thread(target=_sse_portfolio_worker, daemon=True, name="SSEPortfolioWorker")
_sse_flow_thread      = threading.Thread(target=_sse_flow_worker,      daemon=True, name="SSEFlowWorker")
_sse_portfolio_thread.start()
_sse_flow_thread.start()


@app.route("/api/stream")
def sse_stream():
    """
    SSE endpoint — client subscribe untuk dapat push realtime:
    - event: portfolio  → snapshot portfolio + P&L tiap 3 detik
    - event: prices     → harga posisi aktif tiap 3 detik
    - event: flow       → dana keluar/masuk tiap 5 detik
    - event: trade      → notifikasi order baru (instant)
    - event: ping       → keepalive tiap 10 detik
    """
    import queue as _queue_mod
    import time as _time

    client_id = f"{id(threading.current_thread())}_{_time.time()}"
    q = _queue_mod.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients[client_id] = q

    logger.info(f"[SSE] Client {client_id[:12]} connected. Total: {len(_sse_clients)}")

    def generate():
        # Kirim snapshot awal segera
        try:
            snap = _portfolio_snapshot()
            yield f"event: portfolio\ndata: {json.dumps(snap, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        last_ping = _time.time()
        try:
            while True:
                # Ping keepalive setiap 10 detik agar koneksi tidak putus
                if _time.time() - last_ping > 10:
                    yield f"event: ping\ndata: {json.dumps({'t': datetime.now().isoformat()})}\n\n"
                    last_ping = _time.time()

                try:
                    msg = q.get(timeout=1.0)
                    yield msg
                except _queue_mod.Empty:
                    pass
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                _sse_clients.pop(client_id, None)
            logger.info(f"[SSE] Client {client_id[:12]} disconnected. Total: {len(_sse_clients)}")

    resp = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )
    return resp


@app.route("/api/stream/broadcast-trade", methods=["POST"])
def broadcast_trade_event():
    """Internal endpoint: broadcast trade event ke semua SSE clients."""
    data = request.json or {}
    _sse_broadcast("trade", {**data, "timestamp": datetime.now().isoformat()})
    return jsonify({"success": True, "clients": len(_sse_clients)})


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Start auto trading engine thread
    autotrade_engine = AutoTradingEngine()
    autotrade_engine.start()

    print("=" * 60)
    print("AI TRADING BOT SAHAM INDONESIA")
    print("=" * 60)
    print(f"Server: http://localhost:{FLASK_PORT}")
    print(f"Model : {os.getenv('GEMINI_MODEL','gemini-2.0-flash')}")
    print(f"Modal : Rp {float(os.getenv('INITIAL_CAPITAL','100000000')):,.0f}")
    print("=" * 60)
    print("Warning: Pastikan GEMINI_API_KEY sudah diset di file .env !")
    print("=" * 60)
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=FLASK_DEBUG)
