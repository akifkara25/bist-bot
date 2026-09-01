import os
import requests
import pandas as pd
import yfinance as yf

# Telegram Bilgileri (GitHub Secrets'tan otomatik çekilir)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram_message(message):
    if not TOKEN or not CHAT_ID:
        print("Telegram token veya Chat ID bulunamadı!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram mesajı gönderilemedi: {response.text}")
    except Exception as e:
        print(f"Hata oluştu: {e}")

def run_screener():
    send_telegram_message("🤖 BIST Swing Screener Bot taramayı başlatıyor... Lütfen bekleyin.")
    
    # Örnek popüler BIST hisseleri listesi (İstediğin zaman genişletebilirsin)
    tickers = ["TUPRS.IS", "AKSA.IS", "FROTO.IS", "KONTR.IS", "KCAER.IS", "THYAO.IS", "EREGL.IS", "GARAN.IS", "ASELS.IS", "SASA.IS"]
    
    signals = []
    
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="6mo", interval="1d", progress=False)
            if df.empty or len(df) < 50:
                continue
            
            # Çoklu sütun düzeltmesi için kontrol
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            close = df['Close']
            sma20 = close.rolling(window=20).mean()
            sma50 = close.rolling(window=50).mean()
            
            last_close = float(close.iloc[-1])
            last_sma20 = float(sma20.iloc[-1])
            last_sma50 = float(sma50.iloc[-1])
            
            # Basit bir trend filtresi örneği (Fiyat SMA20 ve SMA50 üzerindeyse)
            if last_close > last_sma20 and last_sma20 > last_sma50:
                signals.append(f"✅ *{ticker.replace('.IS', '')}*: Fiyat hareketli ortalamaların üzerinde (Fiyat: {last_close:.2f} TL)")
        except Exception as e:
            print(f"{ticker} analiz edilirken hata: {e}")
            
    if signals:
        message = "📊 *BIST Tarama Sonuçları (Yükseliş Eğilimi)*:\n\n" + "\n".join(signals)
    else:
        message = "📊 BIST taraması tamamlandı. Şu an kriterlere uyan belirgin bir sinyal bulunamadı."
        
    send_telegram_message(message)

if __name__ == "__main__":
    run_screener()
