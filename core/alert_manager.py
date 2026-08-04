"""
core/alert_manager.py — Telegram Alert & Trading Signal Manager
Kirim sinyal trading ke Telegram sehingga user bisa eksekusi di broker nyata
"""
import requests
import logging
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ─── Alert Config File ────────────────────────────────────────
ALERT_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "alert_config.json"
)

DEFAULT_ALERT_CONFIG = {
    "telegram_enabled":  False,
    "telegram_bot_token": "",
    "telegram_chat_id":   "",
    "whatsapp_enabled":  False,
    "alert_on_buy":      True,
    "alert_on_sell":     True,
    "alert_on_signal":   True,
    "alert_on_autotrade": True,
    "min_confidence":    70,
    "broker_name":       "Mirae Asset",
    "broker_app_name":   "Neo HOTS",
    "updated_at":        "",
}


def load_alert_config() -> Dict[str, Any]:
    try:
        if os.path.exists(ALERT_CONFIG_FILE):
            with open(ALERT_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg = DEFAULT_ALERT_CONFIG.copy()
                cfg.update(saved)
                return cfg
    except Exception as e:
        logger.warning(f"[alert] Load config error: {e}")
    return DEFAULT_ALERT_CONFIG.copy()


def save_alert_config(config: Dict) -> bool:
    try:
        os.makedirs(os.path.dirname(ALERT_CONFIG_FILE), exist_ok=True)
        config["updated_at"] = datetime.now().isoformat()
        with open(ALERT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[alert] Save config error: {e}")
        return False


def send_telegram(bot_token: str, chat_id: str, message: str) -> Dict[str, Any]:
    """Kirim pesan ke Telegram via Bot API."""
    if not bot_token or not chat_id:
        return {"success": False, "error": "Bot token atau chat ID belum diset"}
    try:
        url  = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return {"success": True, "message_id": data["result"]["message_id"]}
        return {"success": False, "error": data.get("description", "Unknown error")}
    except Exception as e:
        logger.error(f"[alert] Telegram error: {e}")
        return {"success": False, "error": str(e)}


def test_telegram_connection(bot_token: str, chat_id: str) -> Dict[str, Any]:
    """Test koneksi Telegram."""
    msg = (
        "🤖 <b>AI Trading Bot — Test Koneksi</b>\n\n"
        "✅ Koneksi Telegram berhasil!\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} WIB\n\n"
        "Kamu akan menerima sinyal trading di sini."
    )
    return send_telegram(bot_token, chat_id, msg)


def format_trade_signal(
    action: str,           # BUY / SELL
    ticker: str,
    price: float,
    lots: int,
    leverage: int = 1,
    note: str = "",
    ai_confidence: int = 0,
    stop_loss: float = 0,
    take_profit: float = 0,
    broker_name: str = "Broker",
    app_name: str = "App Broker",
) -> str:
    """Format pesan sinyal trading untuk Telegram."""
    emoji_action = "🟢 BUY" if action == "BUY" else "🔴 SELL"
    leverage_str = f" 【{leverage}x LEVERAGE】" if leverage > 1 else ""
    shares       = lots * 100
    gross_value  = price * shares
    fee          = gross_value * (0.0019 if action == "BUY" else 0.0029)
    total        = gross_value + fee if action == "BUY" else gross_value - fee

    sl_line = f"🛑 Stop Loss : <b>Rp {stop_loss:,.0f}</b>\n" if stop_loss else ""
    tp_line = f"🎯 Take Profit: <b>Rp {take_profit:,.0f}</b>\n" if take_profit else ""
    lev_line = (
        f"⚡ Leverage   : <b>{leverage}x</b> (simulasi margin)\n"
        if leverage > 1 else ""
    )
    conf_line = (
        f"🧠 AI Confidence: <b>{ai_confidence}%</b>\n"
        if ai_confidence else ""
    )
    note_line = f"📝 Catatan    : {note}\n" if note else ""

    msg = (
        f"{'━'*30}\n"
        f"⚡ <b>SINYAL TRADING{leverage_str}</b>\n"
        f"{'━'*30}\n\n"
        f"{emoji_action} <b>{ticker}</b>\n\n"
        f"💰 Harga      : <b>Rp {price:,.0f}</b>\n"
        f"📦 Lot        : <b>{lots} lot</b> ({shares:,} lembar)\n"
        f"💵 Nilai      : <b>Rp {gross_value:,.0f}</b>\n"
        f"🏦 Fee        : Rp {fee:,.0f}\n"
        f"{'Total Bayar' if action=='BUY' else 'Net Terima'}: <b>Rp {total:,.0f}</b>\n"
        f"{sl_line}"
        f"{tp_line}"
        f"{lev_line}"
        f"{conf_line}"
        f"{note_line}\n"
        f"{'━'*30}\n"
        f"📱 <b>Cara Eksekusi di {broker_name}:</b>\n"
        f"1. Buka app <b>{app_name}</b>\n"
        f"2. Cari saham <b>{ticker}</b>\n"
        f"3. Tekan tombol <b>{'BELI' if action=='BUY' else 'JUAL'}</b>\n"
        f"4. Input harga: <b>Rp {price:,.0f}</b>\n"
        f"5. Input lot: <b>{lots} lot</b>\n"
        f"6. Konfirmasi order ✅\n"
        f"{'━'*30}\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} WIB\n"
        f"🤖 AI Trading Bot IDX"
    )
    return msg


def send_trade_signal(
    action: str,
    ticker: str,
    price: float,
    lots: int,
    leverage: int = 1,
    note: str = "",
    ai_confidence: int = 0,
    stop_loss: float = 0,
    take_profit: float = 0,
) -> Dict[str, Any]:
    """Kirim sinyal trading ke semua channel yang aktif."""
    cfg = load_alert_config()

    # Cek apakah alert tipe ini aktif
    if action == "BUY" and not cfg.get("alert_on_buy"):
        return {"success": True, "skipped": True, "reason": "Buy alert dinonaktifkan"}
    if action == "SELL" and not cfg.get("alert_on_sell"):
        return {"success": True, "skipped": True, "reason": "Sell alert dinonaktifkan"}

    msg     = format_trade_signal(
        action, ticker, price, lots, leverage, note,
        ai_confidence, stop_loss, take_profit,
        cfg.get("broker_name", "Broker"),
        cfg.get("broker_app_name", "App Broker"),
    )
    results = {}

    # Kirim ke Telegram
    if cfg.get("telegram_enabled") and cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        results["telegram"] = send_telegram(
            cfg["telegram_bot_token"],
            cfg["telegram_chat_id"],
            msg,
        )
    else:
        results["telegram"] = {"success": False, "skipped": True, "reason": "Telegram belum diaktifkan"}

    overall_success = any(v.get("success") for v in results.values())
    return {
        "success":  overall_success,
        "channels": results,
        "message":  msg,
    }


def send_autotrade_alert(
    action: str, ticker: str, price: float, lots: int,
    reason: str, confidence: int, stop_loss: float, take_profit: float
) -> Dict[str, Any]:
    """Alert khusus dari Auto Trading Engine."""
    cfg = load_alert_config()
    if not cfg.get("alert_on_autotrade"):
        return {"success": True, "skipped": True}

    emoji = "🤖🟢" if action == "BUY" else "🤖🔴"
    shares = lots * 100
    msg = (
        f"{'━'*30}\n"
        f"{emoji} <b>AUTO TRADE SIGNAL</b>\n"
        f"{'━'*30}\n\n"
        f"{'BUY' if action=='BUY' else 'SELL'} <b>{ticker}</b>\n\n"
        f"💰 Harga : <b>Rp {price:,.0f}</b>\n"
        f"📦 Lot   : <b>{lots} lot</b> ({shares:,} lembar)\n"
        f"🧠 Alasan: {reason}\n"
        f"📊 Confidence: <b>{confidence}%</b>\n"
        f"🛑 Stop Loss  : Rp {stop_loss:,.0f}\n"
        f"🎯 Take Profit: Rp {take_profit:,.0f}\n\n"
        f"{'━'*30}\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} WIB"
    )

    if cfg.get("telegram_enabled") and cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        return send_telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
    return {"success": False, "skipped": True, "reason": "Telegram belum diaktifkan"}
