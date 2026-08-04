"""
config.py — Konfigurasi global AI Trading Bot Saham Indonesia
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Gemini AI ─────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ─── Paper Trading ─────────────────────────────────────────
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", 100_000_000))
BROKER_NAME     = os.getenv("BROKER_NAME", "mirae")

# Biaya transaksi (sesuai rata-rata broker Indonesia)
BROKER_FEE_BUY  = 0.0019   # 0.19% buy
BROKER_FEE_SELL = 0.0029   # 0.29% sell (termasuk pajak 0.1%)

# ─── Server ────────────────────────────────────────────────
FLASK_PORT  = int(os.getenv("FLASK_PORT", 5000))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

# ─── Data Paths ────────────────────────────────────────────
BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
DATA_DIR          = os.path.join(BASE_DIR, "data")
PORTFOLIO_FILE    = os.path.join(DATA_DIR, "portfolio.json")
TRADE_HISTORY_FILE = os.path.join(DATA_DIR, "trade_history.json")

# ─── Saham IDX — Daftar Watchlist Default ──────────────────
DEFAULT_WATCHLIST = [
    "BBCA", "BBRI", "BMRI", "TLKM", "ASII",
    "GOTO", "BYAN", "ADRO", "ICBP", "UNVR",
    "SIDO", "MNCN", "PGAS", "INDF", "KLBF",
]

# ─── Sumber Berita ─────────────────────────────────────────
NEWS_SOURCES = [
    {
        "name": "Kontan",
        "rss": "https://rss.kontan.co.id/category/investasi",
    },
    {
        "name": "Bisnis.com",
        "rss": "https://market.bisnis.com/rss",
    },
    {
        "name": "CNBC Indonesia",
        "rss": "https://www.cnbcindonesia.com/rss",
    },
    {
        "name": "IDX",
        "url": "https://www.idx.co.id/id/berita/",
    },
]

# ─── Indikator Teknikal ────────────────────────────────────
TECH_PERIODS = {
    "rsi": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_window": 20,
    "bb_std": 2,
    "ma_short": 20,
    "ma_medium": 50,
    "ma_long": 200,
    "stoch_k": 14,
    "stoch_d": 3,
    "atr": 14,
    "obv": 20,
}

# ─── Telegram Alert ────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Risk Management ───────────────────────────────────────
RISK_CONFIG = {
    "max_position_pct": 0.20,   # max 20% modal per saham
    "default_stop_loss": 0.05,  # 5% stop loss default
    "default_take_profit": 0.10, # 10% take profit default
    "max_drawdown": 0.15,        # max drawdown 15%
}

# ─── Timezone ──────────────────────────────────────────────
TIMEZONE = "Asia/Jakarta"

print(f"[Config] Loaded. Gemini model: {GEMINI_MODEL} | Capital: Rp {INITIAL_CAPITAL:,.0f}")
