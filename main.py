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

MIN_TURNOVER_TL = 15_000_000  # Likidite filtresi artırıldı (15M TL)
DB_FILE = "signals_v5.db"

BIST_TUM_LISTESI = [
    "AKBNK.IS", "AKSA.IS", "AKSEN.IS", "ALARK.IS", "ARCLK.IS", "ASELS.IS", "ASTOR.IS", "BIMAS.IS", 
    "BRSAN.IS", "CIMSA.IS", "CWENE.IS", "DOAS.IS", "DOHOL.IS", "EGEEN.IS", "EKGYO.IS", "ENKAI.IS", 
    "EREGL.IS", "EUPWR.IS", "FROTO.IS", "GARAN.IS", "GESAN.IS", "GUBRF.IS", "HALKB.IS", "HEKTS.IS", 
    "ISCTR.IS", "ISMEN.IS", "KCHOL.IS", "KMPUR.IS", "KONTR.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS", 
    "MGROS.IS", "ODAS.IS", "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS", "SASA.IS", "SISE.IS", 
    "SMRTG.IS", "SOKM.IS", "TAVHL.IS", "TCELL.IS", "THYAO.IS", "TKFEN.IS", "TOASO.IS", "TSKB.IS", 
    "TTKOM.IS", "TTRAK.IS", "TUPRS.IS", "VAKBN.IS", "VESTL.IS", "YKBNK.IS", "YYAPI.IS", "KCAER.IS",
    "MIATK.IS", "ALFAS.IS", "YEOTK.IS", "REEDR.IS", "KALES.IS", "TABGD.IS", "AGROT.IS", "KLSER.IS",
    "GOKNR.IS", "CVKMD.IS", "ASTOR.IS", "SDTTR.IS", "ONCSN.IS", "SKELE.IS", "BIENP.IS", "CWENE.IS"
    # Dilersen eski listedeki tüm hisseleri buraya ekleyebilirsin, hızı artırmak için likit ve hacimli olanlar bırakıldı.
]

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            ticker TEXT,
            tech_score REAL,
            signal_type TEXT,
            price REAL,
            stop REAL,
            target1 REAL,
            target2 REAL
        )
    ''')
    conn.commit()
    conn.close()

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram kimlik bilgileri eksik!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        pass

def clean_df(df):
    if df is None or df.empty: return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    req = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in req): return None
    return df[req].dropna()

# --- GELİŞMİŞ İNDİKATÖR SETİ ---
def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    return macd, sig, macd - sig

def calc_bollinger(close, period=20):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + (std * 2)
    lower = sma - (std * 2)
    width = (upper - lower) / sma
    return upper, lower, width

def calc_obv(close, volume):
    obv = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0))
    return pd.Series(obv, index=close.index).cumsum()

def calc_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def calc_adx(df, period=14):
    high, low, close = df['High'], df['Low'], df['Close']
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    tr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / tr_smooth)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).abs().replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False).mean()

# --- MARKET SCORE (BIST100 REJİMİ) ---
def get_market_score():
    try:
        df = clean_df(yf.download("XU100.IS", period="1y", progress=False))
        if df is None or len(df) < 200: return 50, "NÖTR", None
        
        c = df["Close"]
        sma20, sma50, sma200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
        rsi = calc_rsi(c)
        macd, sig, _ = calc_macd(c)
        
        score = 0
        if c.iloc[-1] > sma20.iloc[-1]: score += 20
        if sma20.iloc[-1] > sma50.iloc[-1]: score += 30
        if sma50.iloc[-1] > sma200.iloc[-1]: score += 20
        if rsi.iloc[-1] > 50: score += 15
        if macd.iloc[-1] > sig.iloc[-1]: score += 15
        
        regime = "🔥 GÜÇLÜ BOĞA" if score >= 80 else "📈 BOĞA" if score >= 60 else "⚖️ NÖTR" if score >= 40 else "📉 AYI" if score >= 20 else "💥 GÜÇLÜ AYI"
        return score, regime, c
    except:
        return 50, "BİLİNMİYOR", None

def main():
    init_db()
    print("🧠 BIST V5 Quant Motoru Çalışıyor...")
    
    mkt_score, mkt_regime, xu100_close = get_market_score()
    print(f"Piyasa Skoru: {mkt_score}/100 - Rejim: {mkt_regime}")
    
    results = []
    
    for ticker in BIST_TUM_LISTESI:
        try:
            df = clean_df(yf.download(ticker, period="1y", progress=False))
            if df is None or len(df) < 200: continue
            
            c, v, h, l, o = df["Close"], df["Volume"], df["High"], df["Low"], df["Open"]
            
            # 1. Hacim/Ciro Filtresi
            if (c * v).tail(5).mean() < MIN_TURNOVER_TL: continue
            
            cp = float(c.iloc[-1])
            
            # 2. İndikatörler
            sma20, sma50, sma200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
            rsi = calc_rsi(c)
            macd, sig, hist = calc_macd(c)
            _, _, bb_width = calc_bollinger(c)
            obv = calc_obv(c, v)
            atr = calc_atr(df)
            adx = calc_adx(df)
            
            # RVOL (Relative Volume - Göreceli Hacim)
            v_sma20 = v.rolling(20).mean()
            rvol = (v.iloc[-1] / v_sma20.iloc[-1]) if v_sma20.iloc[-1] > 0 else 0
            
            # Dirençler ve Dipler
            high_20 = h.rolling(20).max().iloc[-1]
            high_50 = h.rolling(50).max().iloc[-1]
            swing_low_20 = l.tail(20).min()
            
            # Göreceli Güç (RS vs BIST100)
            rs_score = 0
            if xu100_close is not None:
                aligned_bist = xu100_close.reindex(c.index).ffill()
                rs = c / aligned_bist
                if rs.iloc[-1] > rs.rolling(20).mean().iloc[-1]: rs_score += 10
                if rs.iloc[-1] > rs.rolling(50).mean().iloc[-1]: rs_score += 10

            # ---------------------------------------------------------
            # 🏆 V5 MULTI-FACTOR SCORING ENGINE (MAX 100 PUAN)
            # ---------------------------------------------------------
            t_score = 0
            m_flow_score = 0
            
            # A) Trend & Momentum (Max 35)
            if cp > sma20.iloc[-1]: t_score += 5
            if sma20.iloc[-1] > sma50.iloc[-1]: t_score += 10
            if sma50.iloc[-1] > sma200.iloc[-1]: t_score += 5
            if 55 <= rsi.iloc[-1] <= 70: t_score += 5   # Çok şişmemiş sağlıklı RSI
            if macd.iloc[-1] > sig.iloc[-1]: t_score += 5
            if hist.iloc[-1] > 0: t_score += 5
            
            # B) Hacim ve Para Akışı (Max 30) - (m_flow_score için baz alınır)
            if rvol > 1.2: m_flow_score += 10
            if rvol > 2.0: m_flow_score += 5
            if obv.iloc[-1] > obv.rolling(20).mean().iloc[-1]: m_flow_score += 10
            if cp > o.iloc[-1]: m_flow_score += 5 # Kapanış açılışın üzerindeyse pozitif
            
            t_score += m_flow_score
            
            # C) Volatilite, Trend Gücü ve Sıkışma (Max 15)
            if adx.iloc[-1] > 25: t_score += 10
            # Sıkışma (Squeeze) tuzağına düşmemek için: Daralma var VE Para akışı pozitifse puan ver
            if bb_width.iloc[-1] < 0.10 and hist.iloc[-1] > 0: t_score += 5
            
            # D) Relative Strength (Max 20)
            t_score += rs_score
            
            # Filtre: Skoru düşük olanları ele
            if t_score < 70: continue
            
            # ---------------------------------------------------------
            # 🧠 SİNYAL KATEGORİZASYONU (Akıllı Tespit)
            # ---------------------------------------------------------
            signal_type = "STANDART YÜKSELİŞ"
            
            is_breakout = (cp >= high_20) and (rvol >= 1.5) and (macd.iloc[-1] > sig.iloc[-1])
            is_accumulation = (bb_width.iloc[-1] < 0.12) and (obv.iloc[-1] > obv.rolling(20).mean().iloc[-1]) and (cp < high_20 * 0.95)
            
            if is_breakout:
                signal_type = "🚀 CONFIRMED BREAKOUT"
            elif is_accumulation:
                signal_type = "🧲 ACCUMULATION (Hazırlık)"
            elif rvol > 2.0 and cp > o.iloc[-1]:
                signal_type = "🔥 ANOMALİ (Sert Hacim Girişi)"
            elif adx.iloc[-1] > 30 and sma20.iloc[-1] > sma50.iloc[-1]:
                signal_type = "🚄 GÜÇLÜ TREND"

            # ---------------------------------------------------------
            # 🛑 AKILLI STOP & HEDEF (Risk Yönetimi)
            # ---------------------------------------------------------
            curr_atr = float(atr.iloc[-1])
            atr_stop_price = cp - (2.5 * curr_atr) # Daha toleranslı ATR stopu
            swing_stop = float(swing_low_20)
            
            # Stop mantığı: Swing low çok uzaksa (örneğin fiyattan %15 aşağıdaysa) ATR stop kullan.
            # Swing low fiyata makul uzaklıktaysa Swing Low kullan. (Min/Max whip-saw tuzağını çözer)
            if (cp - swing_stop) / cp > 0.12:  
                stop_loss = atr_stop_price
            else:
                stop_loss = swing_stop
                
            risk_amount = cp - stop_loss
            target1 = cp + (risk_amount * 1.5)
            target2 = cp + (risk_amount * 2.5)
            
            # Risk derecelendirmesi
            risk_pct = (risk_amount / cp) * 100
            risk_level = "YÜKSEK" if risk_pct > 8 else "ORTA" if risk_pct > 4 else "DÜŞÜK"
            confidence = "YÜKSEK" if t_score >= 85 else "ORTA"
            
            results.append({
                "ticker": ticker,
                "tech_score": t_score,
                "flow_score": int((m_flow_score / 30) * 100), # 100 üzerinden para akışı skoru
                "type": signal_type,
                "price": cp,
                "rsi": float(rsi.iloc[-1]),
                "adx": float(adx.iloc[-1]),
                "rvol": rvol,
                "resistance": float(high_50),
                "stop": stop_loss,
                "target1": target1,
                "target2": target2,
                "risk": risk_level,
                "conf": confidence
            })
            time.sleep(0.05)
        except Exception:
            continue
            
    # Sonuçları Skor bazlı sırala
    results.sort(key=lambda x: x["tech_score"], reverse=True)
    
    if results:
        report = f"🧠 *BIST V5 Quant Motoru Raporu* 📊\n\n"
        report += f"🌍 *Market Score (BIST100):* {int(mkt_score)}/100 ({mkt_regime})\n\n"
        
        for i, item in enumerate(results[:10], 1): # İlk 10 hisse
            report += f"*{i}. {item['ticker']}*\n"
            report += f"   🏷️ Sinyal: *{item['type']}*\n"
            report += f"   💯 Teknik Skor: {int(item['tech_score'])}/100 | 💸 Para Akışı: {item['flow_score']}/100\n"
            report += f"   📊 RVOL: {item['rvol']:.1f}x | RSI: {item['rsi']:.1f} | ADX: {item['adx']:.1f}\n"
            report += f"   💰 Giriş Fiyatı: {item['price']:.2f} TL (Direnç: {item['resistance']:.2f})\n"
            report += f"   🛑 Stop-Loss: {item['stop']:.2f} TL (Risk: {item['risk']})\n"
            report += f"   🎯 Hedef 1: {item['target1']:.2f} | Hedef 2: {item['target2']:.2f}\n"
            report += f"   🛡️ Sistem Güveni: {item['conf']}\n\n"
            
        send_telegram(report)
        print("V5 Raporu gönderildi.")
    else:
        send_telegram(f"🌍 Market Score: {int(mkt_score)}/100 ({mkt_regime})\n\n⚠️ V5 taraması tamamlandı, 70 puan üstü uygun set-up bulunamadı.")
        print("Sonuç bulunamadı.")

if __name__ == "__main__":
    main()
