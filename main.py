import os
import time
import sqlite3
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MIN_TURNOVER_TL = 1_000_000
DB_FILE = "signals_tracker.db"

# Güvenilir ve aktif BIST 30/50 sembolleri havuzu
BIST_TUM_LISTESI = [
    "AKBNK.IS", "AKSA.IS", "ALARK.IS", "ASELS.IS", "ASTOR.IS", 
    "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "HEKTS.IS", 
    "ISCTR.IS", "KCHOL.IS", "KONTR.IS", "KRDMD.IS", "MGROS.IS", 
    "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS", "SASA.IS", 
    "SISE.IS", "TAVHL.IS", "TCELL.IS", "THYAO.IS", "TOASO.IS", 
    "TUPRS.IS", "VAKBN.IS", "YKBNK.IS", "ENKAI.IS", "EREGL.IS"
]

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            ticker TEXT,
            score REAL,
            price REAL,
            stop REAL,
            target1 REAL
        )
    ''')
    conn.commit()
    conn.close()

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram token veya Chat ID eksik!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"Telegram Yanıt Durumu: {response.status_code}")
    except Exception as e:
        print(f"Telegram Hatası: {e}")

def clean_df(df):
    if df is None or df.empty:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    req = ["Open", "High", "Low", "Close", "Volume"]
    for c in req:
        if c not in df.columns:
            return None
    df = df[req].dropna()
    if len(df) < 20:
        return None
    return df

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def main():
    init_db()
    print("BIST V3 Pro Güvenli Tarama Başlatıldı...")
    
    light_results = []
    
    for ticker in BIST_TUM_LISTESI:
        try:
            df = yf.download(ticker, period="3mo", progress=False)
            df = clean_df(df)
            if df is None:
                continue
            
            close = df["Close"]
            curr_rsi = rsi(close).iloc[-1]
            turnover = (df["Close"] * df["Volume"]).iloc[-5:].mean()
            
            if turnover >= MIN_TURNOVER_TL:
                light_results.append({
                    "ticker": ticker,
                    "light_score": float(curr_rsi),
                    "price": float(close.iloc[-1])
                })
        except Exception as e:
            print(f"Tarama hatası {ticker}: {e}")
            continue

    if not light_results:
        msg = "🤖 *BIST V3 Pro Raporu*\n\nHiçbir hisse hacim kriterini sağlamadı veya veri alınamadı."
        send_telegram(msg)
        print("Kriter sağlayan aday bulunamadı, bilgilendirme gönderildi.")
        return

    # Skorlama ve Sıralama
    light_results.sort(key=lambda x: x["light_score"], reverse=True)
    top_candidates = light_results[:5]

    report = "🤖 *BIST V3 Pro - Tarama Sonuçları* 🚀\n\n"
    for i, c in enumerate(top_candidates, 1):
        report += f"{i}. 📌 *{c['ticker']}* - RSI: {c['light_score']:.1f}\n"
        report += f"   💰 Fiyat: {c['price']:.2f} TL\n\n"

    report += f"Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    send_telegram(report)
    print("Başarılı tarama raporu Telegram'a gönderildi.")

if __name__ == "__main__":
    main()
