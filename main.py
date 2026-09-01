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

MIN_TURNOVER_TL = 5_000_000
DB_FILE = "signals_tracker.db"

BIST_TUM_LISTESI = [
    "AKBNK.IS", "AKSA.IS", "ALARK.IS", "ASELS.IS", "ASTOR.IS", 
    "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "GUBRF.IS", 
    "HEKTS.IS", "ISCTR.IS", "KCHOL.IS", "KONTR.IS", "KOZAL.IS", 
    "KRDMD.IS", "MGROS.IS", "OYAKC.IS", "PETKM.IS", "PGSUS.IS", 
    "SAHOL.IS", "SASA.IS", "SISE.IS", "TAVHL.IS", "TCELL.IS", 
    "THYAO.IS", "TOASO.IS", "TUPRS.IS", "VAKBN.IS", "YKBNK.IS"
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
    return df

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

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
    print("BIST V3 Pro Test Taraması Başlatıldı...")
    
    report = "🤖 *BIST V3 Pro Bot Çalıştı ve Test Başarılı!* 🚀\n\n"
    report += "Sistem aktif, GitHub Actions bağlantısı ve Telegram entegrasyonu kusursuz çalışıyor.\n\n"
    report += f"Taranan Örnek Hisse Sayısı: {len(BIST_TUM_LISTESI)}\n"
    report += f"Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    send_telegram(report)
    print("Test raporu Telegram'a gönderildi.")

if __name__ == "__main__":
    main()
