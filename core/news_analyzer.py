"""
core/news_analyzer.py — Fetch dan Analisis Berita Saham IDX
+ Deteksi sinyal WHALE (big player / institusi masuk atau keluar)
"""
import feedparser
import requests
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logger = logging.getLogger(__name__)

# ─── Sumber RSS & URL Berita Indonesia ───────────────────
RSS_FEEDS = [
    {"name": "Kontan Investasi",    "url": "https://investasi.kontan.co.id/rss/berita/terbaru",  "source_type": "rss"},
    {"name": "Kontan Bursa",        "url": "https://market.kontan.co.id/rss/news",               "source_type": "rss"},
    {"name": "CNBC Indonesia",      "url": "https://www.cnbcindonesia.com/rss",                  "source_type": "rss"},
    {"name": "Bisnis.com Market",   "url": "https://market.bisnis.com/rss",                      "source_type": "rss"},
    {"name": "IDXChannel",          "url": "https://www.idxchannel.com/feed",                    "source_type": "rss"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

# ─── WHALE / Big Player Keywords ──────────────────────────
WHALE_KEYWORDS_MASUK = [
    # Asing
    "net foreign buy", "beli asing", "investor asing masuk", "akumulasi asing",
    "dana asing masuk", "foreign inflow", "foreign net buy",
    # Institusi/Bandar
    "beli institusi", "akumulasi bandar", "akumulasi institusional",
    "pembelian besar", "big lot", "block trade", "block deal",
    "transaksi jumbo",
    # Insider/Pengendali
    "insider buy", "orang dalam beli", "direksi beli",
    "komisaris beli", "pengendali tambah kepemilikan",
    "keterbukaan informasi beli", "perubahan kepemilikan signifikan",
    # Korporasi
    "buyback", "pembelian kembali saham", "right issue beli",
    "program buyback", "akuisisi saham",
    # Volume/Signal
    "lonjakan volume", "volume anomali", "volume tidak wajar",
    "akumulasi volume tinggi", "pembelian masif",
]

WHALE_KEYWORDS_KELUAR = [
    # Asing
    "net foreign sell", "jual asing", "investor asing keluar", "distribusi asing",
    "dana asing keluar", "foreign outflow", "foreign net sell",
    # Institusi/Bandar
    "jual institusi", "distribusi bandar", "distribusi institusional",
    "penjualan besar", "block sell",
    # Insider/Pengendali
    "insider sell", "orang dalam jual", "direksi jual",
    "komisaris jual", "pengendali kurangi kepemilikan",
    "keterbukaan informasi jual",
    # Forced/Emergency
    "margin call", "forced sell", "forced selling",
    "penjualan teknikal",
]

WHALE_KEYWORDS_NETRAL = [
    "akumulasi", "distribusi", "bandarmologi",
    "transaksi jumbo", "volume besar", "block trade",
    "transaksi aneh", "keterbukaan informasi",
]


def fetch_rss_news(feed_url: str, source_name: str, max_items: int = 10) -> List[Dict]:
    """Fetch berita dari RSS feed."""
    try:
        feed = feedparser.parse(feed_url)
        articles = []
        for entry in feed.entries[:max_items]:
            pub_date = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")

            summary = ""
            if hasattr(entry, "summary"):
                soup = BeautifulSoup(entry.summary, "html.parser")
                summary = soup.get_text()[:500]

            articles.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": summary,
                "published": pub_date,
                "source": source_name,
            })
        return articles
    except Exception as e:
        logger.warning(f"[news] RSS error {source_name}: {e}")
        return []


def is_relevant_to_ticker(text: str, ticker: str, company_name: str = "") -> bool:
    """Cek apakah berita relevan dengan ticker/perusahaan."""
    text_lower  = text.lower()
    ticker_low  = ticker.lower()
    company_low = company_name.lower()

    if ticker_low in text_lower:
        return True
    if company_low:
        words = [w for w in company_low.split() if len(w) > 3]
        if any(w in text_lower for w in words[:3]):
            return True
    market_keywords = [
        "ihsg", "bursa", "saham", "idx", "bei",
        "emiten", "investor", "pasar modal", "asing",
        "bi rate", "rupiah", "inflasi", "devisa",
    ]
    if any(kw in text_lower for kw in market_keywords):
        return True
    return False


def simple_sentiment_score(text: str) -> Dict[str, Any]:
    """Scoring sentimen sederhana berbasis kata kunci."""
    text_lower = text.lower()
    positive_words = [
        "naik", "meningkat", "pertumbuhan", "laba", "untung", "profit",
        "rekor", "tertinggi", "bullish", "beli", "akumulasi", "ekspansi",
        "dividen", "positif", "kinerja baik", "inovasi", "kontrak baru",
        "upgrade", "overweight", "buy", "outperform", "rally", "rebound",
        "melesat", "melambung", "tumbuh", "solid", "kuat", "efisiensi",
    ]
    negative_words = [
        "turun", "merosot", "rugi", "kerugian", "penurunan", "koreksi",
        "bearish", "jual", "distribusi", "kontraksi", "negatif", "gagal",
        "downgrade", "underweight", "sell", "underperform", "crash",
        "anjlok", "ambruk", "terpuruk", "melemah", "hutang",
        "bangkrut", "default", "suspensi", "delisting", "fraud", "manipulasi",
    ]
    pos_count = sum(1 for w in positive_words if w in text_lower)
    neg_count = sum(1 for w in negative_words if w in text_lower)
    total = pos_count + neg_count

    if total == 0:
        score, label = 0.0, "NETRAL"
    else:
        score = (pos_count - neg_count) / total
        if score > 0.3:    label = "POSITIF"
        elif score > 0:    label = "CUKUP POSITIF"
        elif score < -0.3: label = "NEGATIF"
        elif score < 0:    label = "CUKUP NEGATIF"
        else:              label = "NETRAL"

    return {"score": round(score, 2), "label": label,
            "positive_hits": pos_count, "negative_hits": neg_count}


def detect_whale_in_article(article: Dict, ticker: str) -> Dict[str, Any]:
    """
    Deteksi sinyal whale/big player dalam satu artikel berita.
    Returns dict dengan informasi deteksi whale.
    """
    full_text = f"{article.get('title', '')} {article.get('summary', '')}".lower()

    buy_hits  = [kw for kw in WHALE_KEYWORDS_MASUK if kw in full_text]
    sell_hits = [kw for kw in WHALE_KEYWORDS_KELUAR if kw in full_text]
    neutral_hits = [kw for kw in WHALE_KEYWORDS_NETRAL if kw in full_text]

    is_ticker_specific = ticker.lower() in full_text

    if not (buy_hits or sell_hits or neutral_hits):
        return {"is_whale": False}

    # Tentukan arah
    if buy_hits and not sell_hits:
        direction = "MASUK"
        icon      = "🐋🟢"
        severity  = "HIGH" if (len(buy_hits) >= 2 or is_ticker_specific) else "MEDIUM"
        alert_msg = f"WHALE MASUK: {', '.join(buy_hits[:3])}"
    elif sell_hits and not buy_hits:
        direction = "KELUAR"
        icon      = "🐳🔴"
        severity  = "HIGH" if (len(sell_hits) >= 2 or is_ticker_specific) else "MEDIUM"
        alert_msg = f"WHALE KELUAR: {', '.join(sell_hits[:3])}"
    elif buy_hits or sell_hits:
        direction = "MIXED"
        icon      = "🐋🟡"
        severity  = "MEDIUM"
        alert_msg = f"Aktivitas Whale Campuran: {', '.join((buy_hits + sell_hits)[:3])}"
    else:
        direction = "NETRAL"
        icon      = "🐬🔵"
        severity  = "LOW"
        alert_msg = f"Aktivitas Big Player: {', '.join(neutral_hits[:3])}"

    return {
        "is_whale":         True,
        "direction":        direction,
        "severity":         severity,
        "icon":             icon,
        "alert_message":    alert_msg,
        "buy_keywords":     buy_hits,
        "sell_keywords":    sell_hits,
        "is_ticker_specific": is_ticker_specific,
        "title":            article.get("title", ""),
        "source":           article.get("source", ""),
        "published":        article.get("published", ""),
        "link":             article.get("link", ""),
    }


def compute_whale_news_summary(whale_alerts: List[Dict]) -> Dict[str, Any]:
    """Ringkasan sinyal whale dari semua berita."""
    if not whale_alerts:
        return {
            "detected": False,
            "alert_level": "NORMAL",
            "buy_count": 0, "sell_count": 0,
            "overall_direction": "NETRAL",
            "alerts": [],
        }

    buy_alerts  = [a for a in whale_alerts if a["direction"] == "MASUK"]
    sell_alerts = [a for a in whale_alerts if a["direction"] == "KELUAR"]
    high_sev    = [a for a in whale_alerts if a["severity"] == "HIGH"]

    if len(buy_alerts) > len(sell_alerts):
        overall_direction = "MASUK"
        alert_level = "HIGH" if high_sev else "MEDIUM"
    elif len(sell_alerts) > len(buy_alerts):
        overall_direction = "KELUAR"
        alert_level = "HIGH" if high_sev else "MEDIUM"
    else:
        overall_direction = "NETRAL"
        alert_level = "LOW"

    # Sort by severity HIGH first, then ticker-specific first
    sorted_alerts = sorted(
        whale_alerts,
        key=lambda x: (x["severity"] != "HIGH", not x["is_ticker_specific"])
    )

    return {
        "detected":          len(whale_alerts) > 0,
        "alert_level":       alert_level,
        "buy_count":         len(buy_alerts),
        "sell_count":        len(sell_alerts),
        "total_signals":     len(whale_alerts),
        "overall_direction": overall_direction,
        "high_severity":     len(high_sev),
        "alerts":            sorted_alerts[:8],  # top 8
    }


def fetch_yfinance_news(ticker: str) -> List[Dict]:
    """Fetch news tagged specifically for the stock ticker using yfinance."""
    try:
        import yfinance as yf
        jk = ticker.upper() if ticker.upper().endswith(".JK") else f"{ticker.upper()}.JK"
        stock = yf.Ticker(jk)
        yf_news = stock.news
        
        articles = []
        if not yf_news:
            return []
            
        for item in yf_news:
            pub_time = item.get("providerPublishTime", 0)
            if pub_time:
                pub_date = datetime.fromtimestamp(pub_time).strftime("%Y-%m-%d %H:%M")
            else:
                pub_date = datetime.now().strftime("%Y-%m-%d %H:%M")
                
            title = item.get("title", "")
            summary = item.get("summary", "") or f"Berita penting mengenai {ticker.upper()} diterbitkan oleh {item.get('publisher', 'Yahoo Finance')}."
            
            articles.append({
                "title": title,
                "link": item.get("link", ""),
                "summary": summary,
                "published": pub_date,
                "source": item.get("publisher", "Yahoo Finance"),
            })
        return articles
    except Exception as e:
        logger.warning(f"[news] yfinance news error for {ticker}: {e}")
        return []


def fetch_all_news(
    ticker: str,
    company_name: str = "",
    max_per_source: int = 10
) -> Dict[str, Any]:
    """
    Fetch berita dari semua sumber, filter yang relevan, dan deteksi sinyal whale.
    """
    all_articles = []

    # 1. Ambil berita khusus saham ini dari yfinance (sangat spesifik dan pasti masuk)
    yf_articles = fetch_yfinance_news(ticker)
    all_articles.extend(yf_articles)

    # 2. Ambil berita pasar umum dari RSS feeds
    for source in RSS_FEEDS:
        try:
            articles = fetch_rss_news(source["url"], source["name"], max_per_source)
            all_articles.extend(articles)
            time.sleep(0.1)
        except Exception as e:
            logger.warning(f"[news] Source error {source['name']}: {e}")

    # Filter relevan + sentimen + whale detection
    relevant      = []
    general_market = []
    whale_alerts  = []

    for art in all_articles:
        full_text = f"{art.get('title','')} {art.get('summary','')}"
        sentiment = simple_sentiment_score(full_text)
        art["sentiment"] = sentiment

        # Whale Detection
        whale_info = detect_whale_in_article(art, ticker)
        if whale_info["is_whale"]:
            art["whale"] = whale_info
            whale_alerts.append(whale_info)
        else:
            art["whale"] = {"is_whale": False}

        is_ticker = (ticker.lower() in full_text.lower()) or (
            company_name and any(
                w in full_text.lower()
                for w in company_name.lower().split() if len(w) > 3
            )
        )

        if is_ticker:
            art["relevance"] = "SAHAM INI"
            relevant.append(art)
        elif is_relevant_to_ticker(full_text, ticker, company_name):
            art["relevance"] = "PASAR UMUM"
            general_market.append(art)

    # Sort: whale articles first, then by relevance
    relevant_sorted = sorted(
        relevant,
        key=lambda x: (not x["whale"]["is_whale"], x["whale"].get("severity", "LOW") != "HIGH")
    )
    combined = relevant_sorted[:10] + general_market[:5]

    # Aggregate sentiment
    if combined:
        avg_sentiment = sum(a["sentiment"]["score"] for a in combined) / len(combined)
        pos_count = sum(1 for a in combined if a["sentiment"]["score"] > 0.1)
        neg_count = sum(1 for a in combined if a["sentiment"]["score"] < -0.1)
    else:
        avg_sentiment = 0.0
        pos_count = neg_count = 0

    sentiment_score_100 = round((avg_sentiment + 1) / 2 * 100, 1)

    if avg_sentiment > 0.3:    sentiment_signal = "SANGAT POSITIF"
    elif avg_sentiment > 0.1:  sentiment_signal = "POSITIF"
    elif avg_sentiment < -0.3: sentiment_signal = "SANGAT NEGATIF"
    elif avg_sentiment < -0.1: sentiment_signal = "NEGATIF"
    else:                      sentiment_signal = "NETRAL"

    whale_summary = compute_whale_news_summary(whale_alerts)

    return {
        "success":         True,
        "ticker":          ticker,
        "total_articles":  len(combined),
        "relevant_stock":  len(relevant),
        "general_market":  len(general_market),
        "articles":        combined[:15],
        "sentiment_summary": {
            "score":              sentiment_score_100,
            "raw_score":          round(avg_sentiment, 3),
            "signal":             sentiment_signal,
            "positive_articles":  pos_count,
            "negative_articles":  neg_count,
            "neutral_articles":   len(combined) - pos_count - neg_count,
        },
        "whale_summary":   whale_summary,
        "fetched_at":      datetime.now().isoformat(),
    }


if __name__ == "__main__":
    result = fetch_all_news("BBCA", "Bank Central Asia")
    print(f"📰 News: {result['total_articles']} artikel")
    print(f"   Sentimen: {result['sentiment_summary']['signal']} ({result['sentiment_summary']['score']:.0f}/100)")
    ws = result["whale_summary"]
    if ws["detected"]:
        print(f"🐋 WHALE ALERT: {ws['overall_direction']} | Level: {ws['alert_level']} | Signals: {ws['total_signals']}")
        for a in ws["alerts"][:3]:
            print(f"   {a['icon']} [{a['severity']}] {a['title'][:80]}")
