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

MIN_TURNOVER_TL = 10_000_000  # Minimum günlük ciro filtresi (TL)
DB_FILE = "signals_tracker.db"

# Genişletilmiş ve Güvenli BIST Hisse Havuzu
BIST_TUM_LISTESI = [
    "AKBNK.IS", "AKSA.IS", "ALARK.IS", "ALBRK.IS", "ARCLK.IS", "ASELS.IS", "ASTOR.IS",
    "BIMAS.IS", "BRSAN.IS", "CWENE.IS", "ECZYT.IS", "EGEEN.IS", "EKGYO.IS", "ENKAI.IS",
    "EREGL.IS", "FROTO.IS", "GARAN.IS", "GESAN.IS", "GUBRF.IS", "HEKTS.IS", "ISCTR.IS",
    "KCHOL.IS", "KONTR.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS", "MAVI.IS", "MGROS.IS",
    "ODAS.IS", "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS", "SASA.IS", "SISE.IS",
    "TAVHL.IS", "TCELL.IS", "THYAO.IS", "TOASO.IS", "TUPRS.IS", "ULKER.IS", "VAKBN.IS", "YKBNK.IS"
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
    print("BIST V3 Pro Gerçek Tarama Başlatıldı...")
    
    results = []
    
    for ticker in BIST_TUM_LISTESI:
        try:
            df = clean_df(yf.download(ticker, period="6mo", progress=False))
            if df is None or len(df) < 50:
                continue
            
            close = df["Close"]
            vol = df["Volume"]
            
            # Ciro Kontrolü (Son 5 gün ortalaması)
            turnover = (close * vol).tail(5).mean()
            if turnover < MIN_TURNOVER_TL:
                continue
            
            # Teknik Hesaplamalar
            current_rsi = rsi(close).iloc[-1]
            sma_50 = close.rolling(window=50).mean().iloc[-1]
            current_price = float(close.iloc[-1])
            
            # Strateji Filtresi: Fiyat 50 günlük ortalamanın üstünde VE RSI 50-75 aralığında (Yükseliş Trendi ve Momentum)
            if current_price > sma_50 and 50 <= current_rsi <= 75:
                stop_loss = current_price * 0.95  # %5 altı stop
                target = current_price * 1.10     # %10 üstü hedef
                score = float(current_rsi)
                
                results.append({
                    "ticker": ticker,
                    "price": current_price,
                    "rsi": float(current_rsi),
                    "stop": stop_loss,
                    "target": target,
                    "score": score
                })
            
            time.sleep(0.1)
        except Exception as e:
            print(f"Hata {ticker}: {e}")
            
    if results:
        results.sort(key=lambda x: x["score"], reverse=True)
        top_candidates = results[:5]  # En güçlü ilk 5 aday
        
        report = "🚀 *BIST V3 Pro - Gerçek Sinyal Raporu* 📈\n\n"
        report += f"📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        
        for i, item in enumerate(top_candidates, 1):
            report += f"*{i}. {item['ticker']}*\n"
            report += f"   💰 Fiyat: {item['price']:.2f} TL\n"
            report += f"   📊 RSI: {item['rsi']:.1f}\n"
            report += f"   🛑 Stop: {item['stop']:.2f} TL\n"
            report += f"   🎯 Hedef: {item['target']:.2f} TL\n\n"
            
        send_telegram(report)
        print("Gerçek tarama raporu Telegram'a gönderildi.")
    else:
        send_telegram("⚠️ BIST V3 Pro taraması tamamlandı. Belirtilen katı kriterlere (Trend + RSI) uyan hisse bulunamadı.")
        print("Kriterlere uyan aday bulunamadı.")

if __name__ == "__main__":
    main()
