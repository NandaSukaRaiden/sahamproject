"""
core/gemini_brain.py — Google Gemini AI Trading Analyst
Mengintegrasikan semua data untuk menghasilkan analisis komprehensif dan keputusan trading
"""
import logging
import json
import re
from typing import Dict, Any, Optional
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import GEMINI_API_KEY, GEMINI_MODEL

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger_tmp = logging.getLogger(__name__)
    logger_tmp.warning("[gemini] google-genai not installed. Run: pip install google-genai")

logger = logging.getLogger(__name__)


def get_gemini_client():
    """Inisialisasi Gemini client."""
    if not GENAI_AVAILABLE:
        raise ImportError("google-genai belum terinstall. Jalankan: pip install google-genai")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        raise ValueError("GEMINI_API_KEY belum diset di file .env !")
    return genai.Client(api_key=GEMINI_API_KEY)


def build_master_prompt(
    ticker: str,
    stock_info: Dict,
    fundamental: Dict,
    technical: Dict,
    news: Dict,
    flow: Dict,
    portfolio_context: Dict = None,
) -> str:
    """
    Bangun prompt master yang sangat komprehensif untuk Gemini AI.
    """
    info = stock_info.get("data", {})
    fund_metrics = fundamental.get("metrics", {})
    tech_indicators = technical.get("indicators", {})
    news_summary = news.get("sentiment_summary", {})
    articles = news.get("articles", [])[:5]

    # Format articles
    news_text = ""
    for i, a in enumerate(articles, 1):
        news_text += f"\n  {i}. [{a.get('source','')}] {a.get('title','')}"
        if a.get('summary'):
            news_text += f"\n     Summary: {a.get('summary','')[:200]}"
        news_text += f"\n     Sentimen: {a.get('sentiment',{}).get('label','Netral')}"

    # Format fundamental
    fund_text = f"""
    - PER: {info.get('pe_ratio', 'N/A')} → {fund_metrics.get('pe',{}).get('signal','N/A')}
    - PBV: {info.get('pb_ratio', 'N/A')} → {fund_metrics.get('pbv',{}).get('signal','N/A')}
    - ROE: {round((info.get('roe',0) or 0)*100,1)}% → {fund_metrics.get('roe',{}).get('signal','N/A')}
    - ROA: {round((info.get('roa',0) or 0)*100,1)}%
    - Net Profit Margin: {round((info.get('profit_margin',0) or 0)*100,1)}%
    - Revenue Growth YoY: {round((info.get('revenue_growth',0) or 0)*100,1)}%
    - Earnings Growth YoY: {round((info.get('earnings_growth',0) or 0)*100,1)}%
    - Dividend Yield: {round((info.get('dividend_yield',0) or 0)*100,2)}%
    - DER: {info.get('debt_to_equity', 'N/A')}
    - Current Ratio: {info.get('current_ratio', 'N/A')}
    - EPS (TTM): {info.get('eps_ttm', 'N/A')}
    - Beta: {info.get('beta', 'N/A')}
    - Market Cap: Rp {info.get('market_cap', 0):,.0f}
    - Fundamental Score: {fundamental.get('composite_score', 'N/A')}/100 ({fundamental.get('signal','N/A')})
    - Analyst Target: Rp {info.get('analyst_target_mean', 0):,.0f} ({info.get('analyst_recommendation','N/A')})"""

    # Format technical
    tech_text = f"""
    - RSI (14): {tech_indicators.get('rsi',{}).get('note','N/A')}
    - MACD: {tech_indicators.get('macd',{}).get('note','N/A')}
    - Bollinger Bands: {tech_indicators.get('bollinger',{}).get('note','N/A')}
    - Moving Average: {tech_indicators.get('ma',{}).get('note','N/A')}
    - Volume: {tech_indicators.get('volume',{}).get('note','N/A')}
    - Stochastic: K={tech_indicators.get('stochastic',{}).get('k','N/A')}, Signal={tech_indicators.get('stochastic',{}).get('signal','N/A')}
    - Candlestick Patterns: {', '.join(technical.get('candlestick_patterns',[])) or 'Tidak ada pola signifikan'}
    - Support Levels: {technical.get('support_resistance',{}).get('support',[])}
    - Resistance Levels: {technical.get('support_resistance',{}).get('resistance',[])}
    - Technical Score: {technical.get('composite_score','N/A')}/100 ({technical.get('signal','N/A')})
    - ATR: Rp {technical.get('atr', 0):,.0f}"""

    # Format flow
    flow_text = f"""
    - Fund Flow Score: {flow.get('composite_score','N/A')}/100
    - Signal: {flow.get('signal','N/A')}
    - Keterangan: {flow.get('description','N/A')}
    - MFI: {flow.get('indicators',{}).get('mfi',{}).get('note','N/A')}
    - OBV Trend: {flow.get('indicators',{}).get('obv',{}).get('note','N/A')}
    - Volume Ratio: {flow.get('indicators',{}).get('volume_ratio',{}).get('note','N/A')}"""

    # Portfolio context
    port_text = ""
    if portfolio_context and portfolio_context.get("has_position"):
        pos = portfolio_context.get("position", {})
        port_text = f"""
    
    === POSISI SAAT INI ===
    - Jumlah Lot: {pos.get('lots', 0)} lot ({pos.get('lots', 0) * 100} lembar)
    - Harga Beli: Rp {pos.get('avg_price', 0):,.0f}
    - Harga Sekarang: Rp {info.get('current_price', 0):,.0f}
    - P&L: {pos.get('pnl_pct', 0):+.1f}% (Rp {pos.get('pnl_rp', 0):+,.0f})
    - Pertimbangkan apakah perlu CUT LOSS, HOLD, atau AVERAGE DOWN/UP"""

    suggested = technical.get("suggested_trade", {})

    prompt = f"""Kamu adalah AI Trading Analyst & Quantitative Portfolio Manager saham Indonesia yang sangat berpengalaman dan profesional, setara dengan analis top dari sekuritas ternama. Berikan analisis SANGAT RINCI, DISIPLIN, dan MENDALAM dalam Bahasa Indonesia yang profesional.

Tujuan utama Anda: Memberikan keputusan trading untuk memaksimalkan profit konsisten dengan manajemen risiko yang super ketat.

=== DATA SAHAM ===
Emiten    : {info.get('company_name', ticker)} ({ticker}.JK)
Sektor    : {info.get('sector','N/A')} | {info.get('industry','N/A')}
Harga     : Rp {info.get('current_price', 0):,.0f} ({info.get('change_pct', 0):+.2f}%)
52W Range : Rp {info.get('week52_low',0):,.0f} — Rp {info.get('week52_high',0):,.0f}
Volume    : {info.get('volume', 0):,.0f} (Avg: {info.get('avg_volume', 0):,.0f})
Tanggal   : {datetime.now().strftime('%d %B %Y, %H:%M WIB')}

=== ANALISIS FUNDAMENTAL ==={fund_text}

=== ANALISIS TEKNIKAL ==={tech_text}

=== ANALISIS BERITA & SENTIMEN ===
Total Berita  : {news.get('total_articles', 0)} artikel
Relevan Saham : {news.get('relevant_stock', 0)} artikel
Sentimen      : {news_summary.get('signal','N/A')} ({news_summary.get('score',50):.0f}/100)
Positif/Negatif: {news_summary.get('positive_articles',0)}/{news_summary.get('negative_articles',0)}

Berita Terkini:{news_text}

=== ANALISIS DANA KELUAR/MASUK ==={flow_text}
{port_text}

=== INSTRUKSI OUTPUT ===
Berikan analisis komprehensif dengan format JSON PERSIS seperti berikut (tidak ada teks di luar JSON):

{{
  "recommendation": "STRONG BUY | BUY | HOLD | SELL | STRONG SELL",
  "confidence": <angka 0-100, berikan angka tinggi >= 80 HANYA jika fundamental kuat, teknikal mendukung golden cross/uptrend, sentimen positif, dan dana masuk (flow) konsisten>,
  "time_horizon": "SHORT (< 1 minggu) | MEDIUM (1-4 minggu) | LONG (> 1 bulan)",
  "risk_level": "VERY LOW | LOW | MEDIUM | HIGH | VERY HIGH",
  
  "entry_strategy": {{
    "recommended_entry": <harga entry ideal dalam rupiah, dekat area support>,
    "entry_zone_low": <batas bawah zona beli>,
    "entry_zone_high": <batas atas zona beli>,
    "stop_loss": <harga stop loss wajib (sekitar 5-7% di bawah harga entry, di bawah support level terdekat)>,
    "take_profit_1": <target profit pertama, konservatif (min 5% dari entry)>,
    "take_profit_2": <target profit kedua, moderat (min 10% dari entry)>,
    "take_profit_3": <target profit ketiga, agresif (min 15% dari entry)>,
    "risk_reward_ratio": <angka desimal, contoh: 2.5, pastikan RRR minimal 1.5>,
    "lot_suggestion": "<saran lot berdasarkan manajemen risiko>",
    "max_loss_pct": <persentase kerugian jika stop loss kena>
  }},
  
  "price_targets": {{
    "bull_case": <target harga skenario bullish, 3 bulan>,
    "base_case": <target harga skenario normal, 3 bulan>,
    "bear_case": <target harga skenario bearish, 3 bulan>,
    "upside_from_current": <persentase kenaikan dari harga sekarang ke base case>,
    "downside_from_current": <persentase penurunan dari harga sekarang ke bear case>
  }},
  
  "analysis_summary": {{
    "fundamental_verdict": "<ringkasan 2-3 kalimat analisis fundamental>",
    "technical_verdict": "<ringkasan 2-3 kalimat analisis teknikal>",
    "news_verdict": "<ringkasan 2-3 kalimat sentimen berita>",
    "flow_verdict": "<ringkasan 2-3 kalimat analisis aliran dana>",
    "key_catalysts": ["<katalis bullish 1>", "<katalis bullish 2>", "<katalis bullish 3>"],
    "key_risks": ["<risiko 1>", "<risiko 2>", "<risiko 3>"],
    "overall_narrative": "<narasi lengkap analisis 3-5 paragraf, mengapa AI merekomendasikan ini, sangat rinci dan profesional>"
  }},
  
  "scores": {{
    "fundamental": {fundamental.get('composite_score', 50)},
    "technical": {technical.get('composite_score', 50)},
    "sentiment": {news_summary.get('score', 50)},
    "flow": {flow.get('composite_score', 50)},
    "overall": <rata-rata tertimbang dari 4 skor, fundamental 30% + technical 30% + sentiment 20% + flow 20%>
  }},
  
  "order_instructions": {{
    "action": "BUY | SELL | HOLD",
    "order_type": "LIMIT | MARKET",
    "broker_instruction": "<instruksi lengkap untuk eksekusi order di platform broker, seperti yang disampaikan trader profesional>",
    "timing": "<kapan waktu terbaik untuk eksekusi order>"
  }},
  
  "monitoring": {{
    "key_levels_to_watch": ["<level harga penting 1>", "<level harga penting 2>"],
    "next_catalyst_date": "<tanggal atau periode penting berikutnya, misal: laporan keuangan Q2 2025 atau RUPS>",
    "exit_conditions": "<kondisi yang harus dipenuhi untuk exit posisi>",
    "review_schedule": "<kapan analisis perlu di-review ulang>"
  }}
}}

PENTING: Response HANYA berisi JSON valid. Tidak ada teks, markdown, atau komentar di luar JSON. Gunakan angka tanpa tanda koma ribuan di dalam JSON."""

    return prompt


def analyze_stock_with_ai(
    ticker: str,
    stock_info: Dict,
    fundamental: Dict,
    technical: Dict,
    news: Dict,
    flow: Dict,
    portfolio_context: Dict = None,
) -> Dict[str, Any]:
    """
    Jalankan analisis AI lengkap menggunakan Google Gemini.
    """
    try:
        client = get_gemini_client()
        prompt = build_master_prompt(
            ticker, stock_info, fundamental, technical, news, flow, portfolio_context
        )

        logger.info(f"[gemini] Sending analysis request for {ticker}...")

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,       # rendah untuk analisis yang konsisten
                top_p=0.95,
                max_output_tokens=4096,
            ),
        )

        raw_text = response.text.strip()

        # Bersihkan markdown jika ada
        raw_text = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
        raw_text = re.sub(r"^```\s*", "", raw_text, flags=re.MULTILINE)
        raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE)

        # Parse JSON
        result = json.loads(raw_text)
        result["raw_prompt_length"] = len(prompt)
        result["model_used"]        = GEMINI_MODEL
        result["analyzed_at"]       = datetime.now().isoformat()
        result["ticker"]            = ticker.upper()

        logger.info(f"[gemini] ✅ Analysis complete for {ticker}: {result.get('recommendation','?')} ({result.get('confidence','?')}%)")
        return {"success": True, "data": result}

    except json.JSONDecodeError as e:
        logger.error(f"[gemini] JSON parse error for {ticker}: {e}")
        logger.error(f"[gemini] Raw response: {raw_text[:500] if 'raw_text' in dir() else 'N/A'}")
        return {
            "success": False,
            "error": f"JSON parse error: {e}",
            "raw_response": raw_text[:1000] if 'raw_text' in dir() else "",
        }
    except Exception as e:
        logger.error(f"[gemini] Error for {ticker}: {e}")
        return {"success": False, "error": str(e)}


def quick_sentiment_check(text: str) -> Dict[str, Any]:
    """Quick sentiment check pada teks berita menggunakan Gemini."""
    try:
        client = get_gemini_client()
        prompt = f"""Analisis sentimen teks berita saham Indonesia berikut. 
Berikan response JSON: {{"sentiment": "POSITIF|NEGATIF|NETRAL", "score": <-100 sampai 100>, "reason": "<alasan singkat>"}}

Teks: {text[:500]}

Response hanya JSON, tidak ada teks lain."""

        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=200),
        )
        raw = resp.text.strip().replace("```json", "").replace("```", "").strip()
        return {"success": True, "data": json.loads(raw)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_market_outlook(watchlist_data: list) -> Dict[str, Any]:
    """Generate market outlook untuk beberapa saham sekaligus."""
    try:
        client = get_gemini_client()

        stocks_summary = "\n".join([
            f"- {d.get('ticker')}: Rp {d.get('price',0):,.0f} ({d.get('change_pct',0):+.1f}%) | "
            f"Score: {d.get('overall_score', 50):.0f}/100 | Signal: {d.get('signal','?')}"
            for d in watchlist_data
        ])

        prompt = f"""Kamu adalah Chief Investment Officer (CIO) sebuah asset management ternama di Indonesia.
Berikan market outlook dan rekomendasi watchlist saham berikut dalam format JSON:

Saham Watchlist:
{stocks_summary}

Tanggal: {datetime.now().strftime('%d %B %Y, %H:%M WIB')}

Response JSON:
{{
  "market_sentiment": "BULLISH | BEARISH | NETRAL",
  "ihsg_outlook": "<outlook IHSG singkat>",
  "top_picks": ["<ticker1>", "<ticker2>", "<ticker3>"],
  "avoid_list": ["<ticker>"],
  "weekly_theme": "<tema investasi minggu ini>",
  "summary": "<ringkasan outlook market dalam 2-3 kalimat>"
}}

Hanya JSON, tidak ada teks lain."""

        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1000),
        )
        raw = resp.text.strip().replace("```json", "").replace("```", "").strip()
        return {"success": True, "data": json.loads(raw)}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Quick test — hanya jika API key sudah diset
    import os
    if os.getenv("GEMINI_API_KEY", "").startswith("AI") or len(os.getenv("GEMINI_API_KEY","")) > 10:
        result = analyze_stock_with_ai("BBCA", {}, {}, {}, {}, {})
        print(json.dumps(result, indent=2, ensure_ascii=False)[:500])
    else:
        print("[gemini] Set GEMINI_API_KEY di .env terlebih dahulu")
