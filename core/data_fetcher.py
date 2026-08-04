"""
core/data_fetcher.py — Pengambil data saham IDX dari yfinance + Yahoo Finance
Mendukung data OHLCV, info perusahaan, dan historical price
"""
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import TIMEZONE

logger = logging.getLogger(__name__)


def to_jk(ticker: str) -> str:
    """Konversi ticker IDX ke format yfinance (tambahkan .JK)"""
    t = ticker.upper().strip()
    return t if t.endswith(".JK") else f"{t}.JK"


def get_stock_info(ticker: str) -> Dict[str, Any]:
    """
    Ambil informasi lengkap perusahaan dari Yahoo Finance.
    Returns dict dengan data fundamental, harga, volume, dll.
    """
    try:
        jk = to_jk(ticker)
        stock = yf.Ticker(jk)
        
        info = {}
        try:
            info = stock.info
            if not info or not isinstance(info, dict) or "currentPrice" not in info:
                raise ValueError("info is empty or missing currentPrice")
        except Exception as e:
            logger.warning(f"[data_fetcher] stock.info failed for {ticker}: {e}. Trying fast_info fallback...")
            try:
                fast_info = stock.fast_info
                def get_fast(attr, default=0):
                    try:
                        val = getattr(fast_info, attr, None)
                        if val is not None:
                            return val
                    except Exception:
                        pass
                    try:
                        val = fast_info.get(attr)
                        if val is not None:
                            return val
                    except Exception:
                        pass
                    return default

                info = {
                    "currentPrice": get_fast("last_price") or get_fast("previous_close"),
                    "previousClose": get_fast("previous_close"),
                    "open": get_fast("open"),
                    "dayHigh": get_fast("day_high"),
                    "dayLow": get_fast("day_low"),
                    "volume": get_fast("last_volume"),
                    "averageVolume": get_fast("three_month_average_volume"),
                    "marketCap": get_fast("market_cap"),
                }
            except Exception as fe:
                logger.warning(f"[data_fetcher] fast_info failed for {ticker}: {fe}. Downloading 5d history...")
                try:
                    df_5d = stock.history(period="5d")
                    if not df_5d.empty:
                        last_row = df_5d.iloc[-1]
                        prev_row = df_5d.iloc[-2] if len(df_5d) > 1 else last_row
                        info = {
                            "currentPrice": float(last_row["Close"]),
                            "previousClose": float(prev_row["Close"]),
                            "open": float(last_row["Open"]),
                            "dayHigh": float(last_row["High"]),
                            "dayLow": float(last_row["Low"]),
                            "volume": int(last_row["Volume"]),
                        }
                    else:
                        raise ValueError("Empty history")
                except Exception as he:
                    logger.error(f"[data_fetcher] All fallbacks failed for {ticker}: {he}")
                    return {"success": False, "error": f"Failed to fetch stock data: {he}", "data": {}}

        # Harga real-time
        current_price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose", 0)
        )
        prev_close = info.get("previousClose", current_price)
        change = current_price - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0

        result = {
            "ticker": ticker.upper(),
            "ticker_jk": jk,
            "company_name": info.get("longName") or info.get("shortName", ticker),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "description": (info.get("longBusinessSummary", "") or "")[:500],
            "website": info.get("website", ""),
            "employees": info.get("fullTimeEmployees", 0),
            # Harga
            "current_price": current_price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "open": info.get("open", 0),
            "high": info.get("dayHigh", 0),
            "low": info.get("dayLow", 0),
            "volume": info.get("volume", 0) or info.get("regularMarketVolume", 0),
            "avg_volume": info.get("averageVolume", 0),
            "bid": info.get("bid", 0),
            "ask": info.get("ask", 0),
            # Market cap & shares
            "market_cap": info.get("marketCap", 0),
            "shares_outstanding": info.get("sharesOutstanding", 0),
            "float_shares": info.get("floatShares", 0),
            # 52-week
            "week52_high": info.get("fiftyTwoWeekHigh", 0),
            "week52_low": info.get("fiftyTwoWeekLow", 0),
            # Valuation
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE", 0),
            "forward_pe": info.get("forwardPE", 0),
            "pb_ratio": info.get("priceToBook", 0),
            "ps_ratio": info.get("priceToSalesTrailing12Months", 0),
            "peg_ratio": info.get("pegRatio", 0),
            "ev_ebitda": info.get("enterpriseToEbitda", 0),
            # Profitability
            "roe": info.get("returnOnEquity", 0),
            "roa": info.get("returnOnAssets", 0),
            "profit_margin": info.get("profitMargins", 0),
            "operating_margin": info.get("operatingMargins", 0),
            "gross_margin": info.get("grossMargins", 0),
            # Growth
            "earnings_growth": info.get("earningsGrowth", 0),
            "revenue_growth": info.get("revenueGrowth", 0),
            # Balance sheet
            "total_cash": info.get("totalCash", 0),
            "total_debt": info.get("totalDebt", 0),
            "current_ratio": info.get("currentRatio", 0),
            "quick_ratio": info.get("quickRatio", 0),
            "debt_to_equity": info.get("debtToEquity", 0),
            # Dividend
            "dividend_yield": info.get("dividendYield", 0) or 0,
            "dividend_rate": info.get("dividendRate", 0) or 0,
            "payout_ratio": info.get("payoutRatio", 0) or 0,
            "ex_dividend_date": str(info.get("exDividendDate", "")),
            # EPS
            "eps_ttm": info.get("trailingEps", 0),
            "eps_forward": info.get("forwardEps", 0),
            # Beta
            "beta": info.get("beta", 1.0) or 1.0,
            # Analyst targets
            "analyst_target_mean": info.get("targetMeanPrice", 0),
            "analyst_target_high": info.get("targetHighPrice", 0),
            "analyst_target_low": info.get("targetLowPrice", 0),
            "analyst_recommendation": info.get("recommendationKey", "N/A"),
            "analyst_count": info.get("numberOfAnalystOpinions", 0),
            # Timestamps
            "fetched_at": datetime.now().isoformat(),
        }

        return {"success": True, "data": result}

    except Exception as e:
        logger.error(f"[data_fetcher] get_stock_info error for {ticker}: {e}")
        return {"success": False, "error": str(e), "data": {}}


def get_price_history(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d"
) -> Dict[str, Any]:
    """
    Ambil historical OHLCV data.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y
    interval: 1m, 5m, 15m, 1h, 1d, 1wk, 1mo
    
    Catatan timezone:
    - yfinance mengembalikan data dengan timezone Asia/Jakarta untuk saham .JK
    - Untuk intraday: timestamp dikembalikan sebagai string "YYYY-MM-DD HH:MM:SS" WIB
    - Untuk daily: timestamp dikembalikan sebagai string "YYYY-MM-DD"
    """
    INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
    is_intraday = interval in INTRADAY_INTERVALS

    try:
        jk = to_jk(ticker)
        df = yf.download(jk, period=period, interval=interval, auto_adjust=True, progress=False)

        if df.empty:
            return {"success": False, "error": "No data returned", "data": []}

        df = df.reset_index()

        # Flatten MultiIndex columns if any
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if col[1] == "" else col[0] for col in df.columns]

        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"date": "timestamp", "datetime": "timestamp"})

        # ─── Timezone handling ───────────────────────────────────────
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        if is_intraday:
            # yfinance untuk .JK mengembalikan UTC dalam beberapa versi,
            # atau sudah tz-aware Asia/Jakarta di versi lain.
            # Normalisasi ke WIB (UTC+7) lalu format sebagai string WIB naive.
            if df["timestamp"].dt.tz is not None:
                # Ada timezone info — konversi ke WIB
                df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Jakarta").dt.tz_localize(None)
            else:
                # Tidak ada tz info: cek apakah jam wajar untuk WIB (09:00-16:30)
                # Jika rata-rata jam < 7, kemungkinan masih UTC → tambah 7 jam
                sample_hours = df["timestamp"].dt.hour.mean() if len(df) > 0 else 12
                if sample_hours < 7:
                    df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=7)
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            # Daily/weekly/monthly: strip timezone, format tanggal saja
            if df["timestamp"].dt.tz is not None:
                df["timestamp"] = df["timestamp"].dt.tz_localize(None)
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d")

        # ─── Convert to list of dicts ─────────────────────────────────
        records = []
        for _, row in df.iterrows():
            ts = row.get("timestamp", "")
            if not ts:
                continue
            o = float(row.get("open",  0) or 0)
            h = float(row.get("high",  0) or 0)
            l = float(row.get("low",   0) or 0)
            c = float(row.get("close", 0) or 0)
            v = int(row.get("volume",  0) or 0)
            # Skip baris dengan semua harga = 0 (hari libur/gap)
            if not c and not o:
                continue
            records.append({
                "timestamp": ts,
                "open":   round(o, 2),
                "high":   round(h, 2),
                "low":    round(l, 2),
                "close":  round(c, 2),
                "volume": v,
            })

        return {"success": True, "data": records, "count": len(records), "interval": interval}

    except Exception as e:
        logger.error(f"[data_fetcher] get_price_history error for {ticker}: {e}")
        return {"success": False, "error": str(e), "data": []}


def get_financials(ticker: str) -> Dict[str, Any]:
    """
    Ambil laporan keuangan: Income Statement, Balance Sheet, Cash Flow.
    """
    try:
        jk = to_jk(ticker)
        stock = yf.Ticker(jk)

        def df_to_dict(df):
            if df is None or df.empty:
                return {}
            df = df.copy()
            df.columns = [str(c).split(" ")[0] for c in df.columns]
            result = {}
            for idx, row in df.iterrows():
                key = str(idx).strip()
                result[key] = {str(col): (None if pd.isna(val) else float(val))
                               for col, val in row.items()}
            return result

        income_stmt = df_to_dict(stock.financials)
        balance_sheet = df_to_dict(stock.balance_sheet)
        cash_flow = df_to_dict(stock.cashflow)

        return {
            "success": True,
            "income_statement": income_stmt,
            "balance_sheet": balance_sheet,
            "cash_flow": cash_flow,
        }

    except Exception as e:
        logger.error(f"[data_fetcher] get_financials error for {ticker}: {e}")
        return {"success": False, "error": str(e)}


def get_ihsg_data(period: str = "1mo") -> Dict[str, Any]:
    """Ambil data IHSG (^JKSE) sebagai benchmark."""
    try:
        df = yf.download("^JKSE", period=period, interval="1d", auto_adjust=True, progress=False)
        if df.empty:
            return {"success": False, "data": []}
        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"date": "timestamp", "datetime": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d")
        records = [
            {
                "timestamp": row.get("timestamp", ""),
                "close": round(float(row.get("close", 0) or 0), 2),
                "volume": int(row.get("volume", 0) or 0),
            }
            for _, row in df.iterrows()
        ]
        return {"success": True, "data": records}
    except Exception as e:
        return {"success": False, "error": str(e), "data": []}


def search_stocks(query: str) -> List[Dict]:
    """Cari saham IDX berdasarkan nama atau kode."""
    try:
        tickers = yf.Tickers(f"{query.upper()}.JK")
        results = []
        for t, obj in tickers.tickers.items():
            info = obj.info
            if info.get("longName"):
                results.append({
                    "ticker": t.replace(".JK", ""),
                    "name": info.get("longName", t),
                    "sector": info.get("sector", "N/A"),
                    "price": info.get("currentPrice", 0),
                    "market_cap": info.get("marketCap", 0),
                })
        return results
    except Exception:
        return []


if __name__ == "__main__":
    # Quick test
    result = get_stock_info("BBCA")
    if result["success"]:
        d = result["data"]
        print(f"✅ {d['company_name']} ({d['ticker']})")
        print(f"   Harga: Rp {d['current_price']:,.0f} ({d['change_pct']:+.2f}%)")
        print(f"   PER: {d['pe_ratio']:.1f}x | PBV: {d['pb_ratio']:.1f}x | ROE: {(d['roe'] or 0)*100:.1f}%")
    else:
        print(f"❌ Error: {result['error']}")
