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

MIN_TURNOVER_TL = 10_000_000  
DB_FILE = "signals_tracker.db"

BIST_TUM_LISTESI = [
    "ACSEL.IS", "ADEL.IS", "ADESE.IS", "ADGYO.IS", "AEFES.IS", "AFYON.IS", "AGESA.IS", "AGHOL.IS", "AGROT.IS", "AGYO.IS",
    "AHGAZ.IS", "AKBNK.IS", "AKCNS.IS", "AKENR.IS", "AKFGY.IS", "AKFYE.IS", "AKGRT.IS", "AKMGY.IS", "AKSA.IS", "AKSEN.IS",
    "AKSGY.IS", "AKSUE.IS", "AKYHO.IS", "ALARK.IS", "ALBRK.IS", "ALCAR.IS", "ALKLC.IS", "ALFAS.IS", "ALGYO.IS", "ALKA.IS",
    "ALKLC.IS", "ALMAD.IS", "ALTNY.IS", "ANELE.IS", "ANGEN.IS", "ANACM.IS", "ANHYT.IS", "ANSGR.IS", "ARASE.IS", "ARCLK.IS",
    "ARDYZ.IS", "ARENA.IS", "ARSAN.IS", "ARZUM.IS", "ASELS.IS", "ASTOR.IS", "ASUZU.IS", "ATAGY.IS", "ATAKP.IS", "ATATP.IS",
    "ATEKS.IS", "ATSYH.IS", "AVOD.IS", "AVPGY.IS", "AYCES.IS", "AYDEM.IS", "AYEN.IS", "AYES.IS", "AYGAZ.IS", "AZTEK.IS",
    "BAGFS.IS", "BAKAB.IS", "BALAT.IS", "BANVT.IS", "BARMA.IS", "BASGZ.IS", "BASCM.IS", "BAYRK.IS", "BEGYO.IS", "BERA.IS",
    "BEYAZ.IS", "BFREN.IS", "BIENP.IS", "BIGCH.IS", "BIMAS.IS", "BINHO.IS", "BIOEN.IS", "BIZIM.IS", "BJKAS.IS", "BLCYT.IS",
    "BMSCH.IS", "BMSTL.IS", "BNTAS.IS", "BOBET.IS", "BORLS.IS", "BORSK.IS", "BOSSA.IS", "BRISA.IS", "BRKO.IS", "BRKSN.IS",
    "BRMEN.IS", "BRSAN.IS", "BRYAT.IS", "BSOKE.IS", "BTCIM.IS", "BUCIM.IS", "BURCE.IS", "BURVA.IS", "BVSAN.IS",
    "CANTE.IS", "CASA.IS", "CATES.IS", "CCOLA.IS", "CELHA.IS", "CEMAS.IS", "CEMTS.IS", "CEOEM.IS", "CGCAN.IS", "CIMSA.IS",
    "CLEAS.IS", "CMBTN.IS", "CMENT.IS", "CONSE.IS", "COSMO.IS", "CRDFA.IS", "CRFSA.IS", "CWENE.IS", "DAGI.IS",
    "DAGHL.IS", "DAPGM.IS", "DARDL.IS", "DENGE.IS", "DERHL.IS", "DERIM.IS", "DESA.IS", "DESPC.IS", "DEVA.IS", "DGATE.IS",
    "DGNMO.IS", "DIRIT.IS", "DITAS.IS", "DMRGD.IS", "DMSAS.IS", "DNISI.IS", "DOAS.IS", "DOBUR.IS", "DOCO.IS", "DOGUB.IS",
    "DOHOL.IS", "DOKTA.IS", "DSIYE.IS", "DURDO.IS", "DYOBY.IS", "DZGYO.IS", "EBEBK.IS", "ECILC.IS", "Eczyt.IS",
    "EDIP.IS", "EGEEN.IS", "EGEPO.IS", "EGGUB.IS", "EGPRO.IS", "EGSER.IS", "EKGYO.IS", "EKOS.IS", "EKSUN.IS", "ELITE.IS",
    "EMKEL.IS", "ENERY.IS", "ENKAI.IS", "ENSRI.IS", "EPLAS.IS", "ERBOS.IS", "ERCB.IS", "EREGL.IS", "ERSU.IS", "ESCAR.IS",
    "ESCOM.IS", "ESEN.IS", "ETILR.IS", "EUHOL.IS", "EUKYO.IS", "EUPWR.IS", "EUREN.IS", "EUYO.IS", "EYGYO.IS", "FADE.IS",
    "FENER.IS", "FLAP.IS", "FMIZP.IS", "FONET.IS", "FORMT.IS", "FORTE.IS", "FROTO.IS", "GARAN.IS", "GARFA.IS", "GEDIK.IS",
    "GEDAN.IS", "GENIL.IS", "GENTS.IS", "GEREL.IS", "GESAN.IS", "GLBMD.IS", "GLCVY.IS", "GLRYH.IS", "GLYHO.IS", "GMTAS.IS",
    "GOKNR.IS", "GOLTS.IS", "GOODY.IS", "GOZDE.IS", "GRNYO.IS", "GRSEL.IS", "GSDDE.IS", "GSDHO.IS", "GSRAY.IS", "GUBRF.IS",
    "GWIND.IS", "GZNMI.IS", "HALKB.IS", "HATEK.IS", "HATSN.IS", "HEDEF.IS", "HEKTS.IS", "HKTM.IS", "HLGYO.IS", "HTTBT.IS",
    "HUBVC.IS", "HUNER.IS", "HURGZ.IS", "ICBCT.IS", "IDEAS.IS", "IDGYO.IS", "IHEVA.IS", "IHGZT.IS", "IHLAS.IS", "IHLGM.IS",
    "IHYVA.IS", "IMASM.IS", "INDES.IS", "INFO.IS", "INTEM.IS", "INVEO.IS", "INVES.IS", "IPEKE.IS", "ISATR.IS", "ISBIR.IS",
    "ISBTR.IS", "ISCGR.IS", "ISCTR.IS", "ISDMR.IS", "ISFIN.IS", "ISGSY.IS", "ISGYO.IS", "ISKPL.IS", "ISMEN.IS", "ISSEN.IS",
    "IZENR.IS", "IZFAS.IS", "IZINV.IS", "IZMDC.IS", "JANTS.IS", "KAFIN.IS", "KAPLM.IS", "KAREL.IS", "KARSN.IS", "KARTN.IS",
    "KARYE.IS", "KASTB.IS", "KATMR.IS", "KAYSE.IS", "KBORU.IS", "KCAER.IS", "KCHOL.IS", "KENT.IS", "KERVT.IS", "KFEIN.IS",
    "KGYO.IS", "KIMMR.IS", "KLGYO.IS", "KLKIM.IS", "KLRHO.IS", "KLSYN.IS", "KMPUR.IS", "KNFRT.IS", "KONKA.IS", "KONTR.IS",
    "KONYA.IS", "KOPOL.IS", "KORDS.IS", "KOTON.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS", "KRGYO.IS", "KRONT.IS", "KRPLS.IS",
    "KRSTL.IS", "KRTEK.IS", "KZBGY.IS", "KZYGZ.IS", "LIDER.IS", "LIDFA.IS", "LKMNH.IS", "LOGO.IS", "LUKSK.IS", "MAALT.IS",
    "MAKIM.IS", "MAKTK.IS", "MANAS.IS", "MARKA.IS", "MARTI.IS", "MAVI.IS", "MEDTR.IS", "MEGAP.IS", "MEKAG.IS", "MEMUR.IS",
    "MEPET.IS", "MERCN.IS", "MERKO.IS", "METUR.IS", "MGROS.IS", "MHRGY.IS", "MIATK.IS", "MMCAS.IS", "MNDRS.IS", "MNDTR.IS",
    "MOBTL.IS", "MPARK.IS", "MRSHL.IS", "MSGYO.IS", "MTRKS.IS", "MZYGZ.IS", "NATEN.IS", "NETAS.IS", "NIBAS.IS", "NTGAZ.IS",
    "NUGYO.IS", "NUHCM.IS", "OBASE.IS", "ODAS.IS", "OFSYM.IS", "ONCSN.IS", "ORCAY.IS", "OYYAT.IS", "OYAKC.IS", "OZATD.IS",
    "OZGYO.IS", "OZKGY.IS", "OZRDN.IS", "PASTR.IS", "PAGYO.IS", "PAMEL.IS", "PAKMD.IS", "PAPIL.IS", "PARSN.IS", "PATEK.IS",
    "PCILT.IS", "PEKGY.IS", "PENGD.IS", "PENTA.IS", "PETKM.IS", "PETUN.IS", "PGSUS.IS", "PINSU.IS", "PKART.IS", "PKENT.IS",
    "PNSUT.IS", "POLHO.IS", "POLTK.IS", "PRKME.IS", "PRDGS.IS", "PRZMA.IS", "PSDTC.IS", "QNBFB.IS", "QNBFL.IS", "QUAGR.IS",
    "RALYH.IS", "RAYSG.IS", "REEDR.IS", "RNPAS.IS", "RODRG.IS", "ROYAL.IS", "RTALB.IS", "RUBNS.IS", "RYGYO.IS", "RYSAS.IS",
    "SAFKR.IS", "SAHOL.IS", "SANKO.IS", "SARKY.IS", "SASA.IS", "SAYAS.IS", "SDTTR.IS", "SEGMN.IS", "SEGYO.IS",
    "SEKFK.IS", "SEKUR.IS", "SELEC.IS", "SELGD.IS", "SELVA.IS", "SEYKM.IS", "SILVR.IS", "SISE.IS", "SKBNK.IS", "SKTAS.IS",
    "SMART.IS", "SMRTG.IS", "SNGYO.IS", "SNICA.IS", "SOKE.IS", "SOKM.IS", "SONME.IS", "SRVGY.IS", "SUMAS.IS", "SUNTK.IS",
    "SUWEN.IS", "TABGD.IS", "TARKM.IS", "TATEN.IS", "TATGD.IS", "TAVHL.IS", "TBORG.IS", "TCELL.IS", "TDGYO.IS", "TEKFN.IS",
    "TEKTN.IS", "TETMT.IS", "TFGYO.IS", "THYAO.IS", "TIRE.IS", "TKFEN.IS", "TKNSA.IS", "TMPOL.IS", "TMSN.IS", "TOASO.IS",
    "TRGYO.IS", "TRILC.IS", "TSKB.IS", "TSPOR.IS", "TTKOM.IS", "TTRAK.IS", "TUCLK.IS", "TUPRS.IS", "Tureks.IS", "TURGG.IS",
    "UFUK.IS", "ULAS.IS", "ULKER.IS", "ULUUN.IS", "UNLU.IS", "USAK.IS", "VAKBN.IS", "VAKFN.IS", "VAKKO.IS", "VANGD.IS",
    "VBTYZ.IS", "VERTU.IS", "VERUS.IS", "VESBE.IS", "VESTL.IS", "VKGYO.IS", "VKING.IS", "YAPRK.IS", "YATAS.IS", "YAYLA.IS",
    "YBTAS.IS", "YEOTK.IS", "YESIL.IS", "YGGYO.IS", "YIGIT.IS", "YKBNK.IS", "YKSLN.IS", "YUNSA.IS", "YYAPI.IS", "ZEDUR.IS",
    "ZOREN.IS", "ZRGYO.IS"
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
            signal_type TEXT,
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
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        pass

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

# --- TEKNİK İNDİKATÖR FONKSİYONLARI ---
def get_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def get_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def get_bollinger(close, period=20):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + (std * 2)
    lower = sma - (std * 2)
    width = (upper - lower) / sma
    return upper, lower, width

def get_obv(close, volume):
    obv = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0))
    obv = pd.Series(obv, index=close.index).cumsum()
    return obv

def get_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def get_adx(df, period=14):
    high, low, close = df['High'], df['Low'], df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    tr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / tr_smooth)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).abs().replace(0, np.nan)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def get_market_regime():
    try:
        df = clean_df(yf.download("XU100.IS", period="1y", progress=False))
        if df is not None and len(df) > 50:
            close = df["Close"].iloc[-1]
            sma50 = df["Close"].rolling(50).mean().iloc[-1]
            return "BULLISH" if close > sma50 else "BEARISH", df["Close"]
        return "UNKNOWN", None
    except:
        return "UNKNOWN", None

def main():
    init_db()
    print("BIST V4 Quant Engine Başlatıldı...")
    
    # 1. Piyasa Rejimi (Market Regime) Analizi
    market_regime, xu100_close = get_market_regime()
    print(f"Piyasa Rejimi: {market_regime}")
    
    results = []
    
    for ticker in BIST_TUM_LISTESI:
        try:
            df = clean_df(yf.download(ticker, period="1y", progress=False))
            if df is None or len(df) < 200:
                continue
            
            close = df["Close"]
            vol = df["Volume"]
            high = df["High"]
            low = df["Low"]
            
            # Ciro Kontrolü (Minimum 10M TL)
            turnover = (close * vol).tail(5).mean()
            if turnover < MIN_TURNOVER_TL:
                continue
                
            current_price = float(close.iloc[-1])
            
            # İndikatör Hesaplamaları
            sma20 = close.rolling(20).mean()
            sma50 = close.rolling(50).mean()
            sma200 = close.rolling(200).mean()
            
            rsi = get_rsi(close)
            macd_line, signal_line, macd_hist = get_macd(close)
            upper_bb, lower_bb, bb_width = get_bollinger(close)
            obv = get_obv(close, vol)
            obv_sma20 = obv.rolling(20).mean()
            atr = get_atr(df)
            adx = get_adx(df)
            
            # Hacim Anomalisi (Son 20 Güne Kıyasla)
            vol_sma20 = vol.rolling(20).mean()
            rel_vol = (vol.iloc[-1] / vol_sma20.iloc[-1]) if vol_sma20.iloc[-1] > 0 else 0
            
            # Zirve / Breakout Kontrolü
            high_20 = high.rolling(20).max().iloc[-1]
            
            # Göreceli Güç (RS) vs BIST100
            rs_score = 0
            if xu100_close is not None:
                aligned_bist = xu100_close.reindex(close.index).ffill()
                rs_ratio = close / aligned_bist
                rs_sma20 = rs_ratio.rolling(20).mean()
                if rs_ratio.iloc[-1] > rs_sma20.iloc[-1]:
                    rs_score = 5

            # --- MULTI-FACTOR SCORING ENGINE (0-100) ---
            score = 0
            
            # 1. Trend (Max 20 Puan)
            if current_price > sma20.iloc[-1]: score += 5
            if sma20.iloc[-1] > sma50.iloc[-1]: score += 10
            if sma50.iloc[-1] > sma200.iloc[-1]: score += 5
            
            # 2. Momentum (Max 15 Puan)
            if 50 <= rsi.iloc[-1] <= 70: score += 5
            if macd_line.iloc[-1] > signal_line.iloc[-1]: score += 5
            if macd_hist.iloc[-1] > 0: score += 5
            
            # 3. Hacim Anomalisi (Max 15 Puan)
            if rel_vol > 1.5: score += 10
            if rel_vol > 2.0: score += 5
            
            # 4. Volatilite / Sıkışma (Max 10 Puan)
            if bb_width.iloc[-1] < 0.10: score += 10
            
            # 5. Kırılım / Fiyat Aksiyonu (Max 15 Puan)
            if current_price >= (high_20 * 0.98): score += 15
            
            # 6. Para Akışı (Max 10 Puan)
            if obv.iloc[-1] > obv_sma20.iloc[-1]: score += 10
            
            # 7. ADX Trend Gücü (Max 10 Puan)
            if adx.iloc[-1] > 25: score += 10
            
            # 8. Göreceli Güç
            score += rs_score
            
            # --- SADECE SKORU YÜKSEK (65+) OLANLARI FİLTRELE ---
            if score < 65:
                continue
                
            # --- SİNYAL KATEGORİZASYONU ---
            signal_type = "STANDART"
            if bb_width.iloc[-1] < 0.10 and obv.iloc[-1] > obv_sma20.iloc[-1]:
                signal_type = "🧲 ACCUMULATION (Toplama)"
            elif current_price >= high_20 and rel_vol > 1.5:
                signal_type = "🚀 BREAKOUT (Kırılım)"
            elif adx.iloc[-1] > 25 and current_price > sma20.iloc[-1] > sma50.iloc[-1]:
                signal_type = "🚄 MOMENTUM"

            # --- DİNAMİK STOP & HEDEF HESAPLAMA ---
            current_atr = float(atr.iloc[-1])
            recent_swing_low = float(low.tail(20).min())
            atr_stop = current_price - (2 * current_atr)
            
            # Swing Low ve ATR Stop arasında mantıklı olanı (genelde daha sıkı olanı ama gürültüye kurban gitmeyecek olanı) seç
            stop_loss = max(recent_swing_low, atr_stop)
            
            # Hedef: Direnç hesabı yapamadığımız için risk/ödül matematiği ve ATR bazlı hedef
            risk = current_price - stop_loss
            target = current_price + (risk * 2.5) # Minimum 1'e 2.5 Risk/Ödül oranı
            
            results.append({
                "ticker": ticker,
                "score": score,
                "type": signal_type,
                "price": current_price,
                "rsi": float(rsi.iloc[-1]),
                "adx": float(adx.iloc[-1]),
                "rel_vol": rel_vol,
                "stop": stop_loss,
                "target": target
            })
            
            time.sleep(0.05)
        except Exception as e:
            continue
            
    if results:
        results.sort(key=lambda x: x["score"], reverse=True)
        top_candidates = results[:15]  
        
        report = "🧠 *BIST V4 Quant - Multi-Factor Raporu* 📊\n\n"
        report += f"📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        report += f"🌍 BIST100 Rejimi: *{market_regime}*\n\n"
        
        for i, item in enumerate(top_candidates, 1):
            rating = "🔥 ÇOK GÜÇLÜ" if item['score'] >= 85 else "⚡ GÜÇLÜ" if item['score'] >= 75 else "👀 İZLEME"
            report += f"*{i}. {item['ticker']}* ({rating})\n"
            report += f"   🏷️ Sinyal: {item['type']}\n"
            report += f"   💯 Skor: {item['score']}/100\n"
            report += f"   💰 Fiyat: {item['price']:.2f} TL\n"
            report += f"   📊 RSI: {item['rsi']:.1f} | ADX: {item['adx']:.1f}\n"
            report += f"   📈 Hacim Etkisi: {item['rel_vol']:.1f}x Katı\n"
            report += f"   🛑 Stop: {item['stop']:.2f} TL\n"
            report += f"   🎯 Hedef: {item['target']:.2f} TL\n\n"
            
        send_telegram(report)
        print("V4 Quant Raporu Telegram'a gönderildi.")
    else:
        send_telegram(f"🌍 BIST100 Rejimi: {market_regime}\n⚠️ V4 taraması tamamlandı. 65 puan üstü güçlü hisse bulunamadı.")
        print("Kriterlere uyan aday bulunamadı.")

if __name__ == "__main__":
    main()
