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
    "AAVS.IS", "AFES.IS", "AGHOL.IS", "AGROT.IS", "AHGAZ.IS", "AKBNK.IS", "AKCNS.IS", 
    "AKFGY.IS", "AKFYE.IS", "AKMGY.IS", "AKSA.IS", "AKSEN.IS", "AKSUE.IS", "ALARK.IS", "ALBRK.IS", 
    "ALCAR.IS", "ALCTL.IS", "ALFAS.IS", "ALKA.IS", "ALKIM.IS", "ALMAD.IS", "ALTNY.IS", "ALVES.IS", 
    "ANELE.IS", "ANGEN.IS", "ANHYT.IS", "ANSGR.IS", "ARASE.IS", "ARCLK.IS", "ARDYZ.IS", "ARENA.IS", 
    "ARSAN.IS", "ARTMS.IS", "ASELS.IS", "ASGYO.IS", "ASTOR.IS", "ATAGY.IS", "ATAKP.IS", "ATATP.IS", 
    "ATEKS.IS", "ATSYH.IS", "AVPGY.IS", "AVTUR.IS", "AYCES.IS", "AYDEM.IS", "AYEN.IS", "AYGAZ.IS", 
    "AZTEK.IS", "BAGFS.IS", "BAKAB.IS", "BALAT.IS", "BANVT.IS", "BARMA.IS", "BASGZ.IS", "BAYRK.IS", 
    "BEGYO.IS", "BERA.IS", "BEYAZ.IS", "BFREN.IS", "BIENP.IS", "BIGCH.IS", "BIMAS.IS", "BINBN.IS", 
    "BINHO.IS", "BIOEN.IS", "BIZIM.IS", "BKEVP.IS", "BLCYT.IS", "BNTAS.IS", "BOBET.IS", "BORAB.IS", 
    "BORSK.IS", "BOSSA.IS", "BRISA.IS", "BRKO.IS", "BRKVY.IS", "BRMEN.IS", "BRSAN.IS", "BRYAT.IS", 
    "BSOKE.IS", "BTCIM.IS", "BUCIM.IS", "BURCE.IS", "BURVA.IS", "BVSAN.IS", "BYDNR.IS", "CANTE.IS", 
    "CASA.IS", "CCOLA.IS", "CELHA.IS", "CEMAS.IS", "CEMTS.IS", "CMBTN.IS", "CMENT.IS", "CLEBI.IS", 
    "CONSE.IS", "COSMO.IS", "CRDFA.IS", "CRFSA.IS", "CUSAN.IS", "CVKMD.IS", "CWENE.IS", "DAGI.IS", 
    "DAPGM.IS", "DARDL.IS", "DGATE.IS", "DGGYO.IS", "DITAS.IS", "DMRGD.IS", "DMSAS.IS", "DNISI.IS", 
    "DOAS.IS", "DOBUR.IS", "DOCO.IS", "DOHOL.IS", "DOKTA.IS", "DURDO.IS", "DYOBY.IS", "DZGYO.IS", 
    "EBEBK.IS", "ECILC.IS", "ECZYT.IS", "EDATA.IS", "EGEEN.IS", "EGGUB.IS", "EGPRO.IS", "EGSER.IS", 
    "EKGYO.IS", "EKOS.IS", "EKSUN.IS", "ELITE.IS", "EMKEL.IS", "EMNIS.IS", "ENJSA.IS", "ENKAI.IS", 
    "ENSRI.IS", "EPLAS.IS", "ERCB.IS", "EREGL.IS", "ERHS.IS", "ESCAR.IS", "ESCOM.IS", "ESEN.IS", 
    "ETILR.IS", "EUPWR.IS", "EURO.IS", "EYGYO.IS", "FADE.IS", "FLAP.IS", "FMIZP.IS", "FONET.IS", 
    "FORMT.IS", "FORTE.IS", "FRIGO.IS", "FROTO.IS", "FZLGY.IS", "GARAN.IS", "GARFA.IS", "GEDIK.IS", 
    "GEDZA.IS", "GENIL.IS", "GENTAS.IS", "GEREL.IS", "GESAN.IS", "GZNMI.IS", "GIREN.IS", "GIPTA.IS", 
    "GLBMD.IS", "GLYHO.IS", "GMTAS.IS", "GOKNR.IS", "GOLTS.IS", "GOODY.IS", "GOZDE.IS", "GRSEL.IS", 
    "GRTHO.IS", "GSDHO.IS", "GSDEO.IS", "GUBRF.IS", "GWIND.IS", "GZTAN.IS", "HALKB.IS", "HATEK.IS", 
    "HATSN.IS", "HEKTS.IS", "HKTM.IS", "HOLDR.IS", "HUBVC.IS", "HUNER.IS", "HURGZ.IS", "ICBCT.IS", 
    "IEYHO.IS", "IHAAS.IS", "IHEVA.IS", "IHGZT.IS", "IHLGM.IS", "IHYAY.IS", "IMASM.IS", "INDES.IS", 
    "INFO.IS", "INGRM.IS", "INTEM.IS", "INVEO.IS", "INVES.IS", "ISATR.IS", "ISBTR.IS", "ISCTR.IS", 
    "ISDMR.IS", "ISFIN.IS", "ISGSY.IS", "ISGYO.IS", "ISKPL.IS", "ISMEN.IS", "ISSEN.IS", "IZENR.IS", 
    "IZMDC.IS", "IZINV.IS", "JANTS.IS", "KFEIN.IS", "KALYON.IS", "KAPLM.IS", "KAREL.IS", "KARSN.IS", 
    "KARTN.IS", "KAYSE.IS", "KBORU.IS", "KCAER.IS", "KCHOL.IS", "KENT.IS", "KRTEK.IS", "KIMMR.IS", 
    "KLGYO.IS", "KLMSN.IS", "KLSER.IS", "KLRHO.IS", "KMPUR.IS", "KNFRT.IS", "KONTR.IS", "KONYA.IS", 
    "KORDS.IS", "KOZAA.IS", "KOZAL.IS", "KRDMD.IS", "KRONT.IS", "KRPLS.IS", "KRSTL.IS", "KRVGD.IS", 
    "KSTUR.IS", "KTLEV.IS", "KTSKR.IS", "KUTPO.IS", "KVBAN.IS", "KZBGY.IS", "KZGYO.IS", "LIDER.IS", 
    "LIDFA.IS", "LINK.IS", "LKMNH.IS", "LMKDC.IS", "LOGAS.IS", "LUKSK.IS", "MAALT.IS", "MACKO.IS", 
    "MAKIM.IS", "MAKTK.IS", "MANAS.IS", "MARKA.IS", "MARSH.IS", "MAVI.IS", "MEDTR.IS", "MEGAP.IS", 
    "MEGMT.IS", "MEPET.IS", "MERCN.IS", "MERIT.IS", "MERKO.IS", "METRO.IS", "METUR.IS", "MHRGY.IS", 
    "MGROS.IS", "MIATK.IS", "MMPRT.IS", "MOBTL.IS", "MOPAS.IS", "MPARK.IS", "MRGYO.IS", "MRSHL.IS", 
    "MSGYO.IS", "MTRKS.IS", "MTRON.IS", "NATEN.IS", "NETAS.IS", "NIBAS.IS", "NTGAZ.IS", "NTHOL.IS", 
    "NUGYO.IS", "OBAMS.IS", "ODAS.IS", "OFSYM.IS", "ONCSM.IS", "ORCA.IS", "ORGE.IS", "ORMA.IS", 
    "OSMEN.IS", "OSTIM.IS", "OTKAR.IS", "OTTO.IS", "OYAKC.IS", "OYYAT.IS", "OZKGY.IS", "OZRDN.IS", 
    "OZSUB.IS", "PAGYO.IS", "PAMEL.IS", "PAPIL.IS", "PARSN.IS", "PASEU.IS", "PATEK.IS", "PCILT.IS", 
    "PEKGY.IS", "PENGD.IS", "PENTA.IS", "PETKM.IS", "PETUN.IS", "PGSUS.IS", "PINSU.IS", "PKART.IS", 
    "PKENT.IS", "PLTUR.IS", "PNLSN.IS", "PNSUT.IS", "POLHO.IS", "POLTK.IS", "PRDGS.IS", "PRKAB.IS", 
    "PRKME.IS", "PRZMA.IS", "PSDTC.IS", "QUAGR.IS", "RALYH.IS", "RAYSG.IS", "REEDR.IS", "RGYAS.IS", 
    "RNPOL.IS", "RODRG.IS", "ROYAL.IS", "RTALB.IS", "RUBNS.IS", "RYGYO.IS", "RYSAS.IS", "SAHOL.IS", 
    "SAMAT.IS", "SANEL.IS", "SANFM.IS", "SANKO.IS", "SARKY.IS", "SASA.IS", "SAYAS.IS", "SDTTR.IS", 
    "SEGMN.IS", "SEKFK.IS", "SEKUR.IS", "SELEC.IS", "SELVA.IS", "SEYKM.IS", "SILVR.IS", "SISE.IS", 
    "SKBNK.IS", "SKTAS.IS", "SMART.IS", "SMRTG.IS", "SNAAM.IS", "SNGYO.IS", "SNICA.IS", "SNKRN.IS", 
    "SNPAM.IS", "SODSN.IS", "SOKE.IS", "SOKM.IS", "SONME.IS", "SRVGY.IS", "SUMAS.IS", "SUNTK.IS", 
    "SURGY.IS", "SUWEN.IS", "TATEN.IS", "TATGD.IS", "TAVHL.IS", "TBORG.IS", "TCELL.IS", "TDGYO.IS", 
    "TEKTN.IS", "TERA.IS", "TETMT.IS", "THYAO.IS", "TKFEN.IS", "TKNSA.IS", "TLMAN.IS", "TMPOL.IS", 
    "TMSN.IS", "TNZTP.IS", "TOASO.IS", "TRALT.IS", "TRCAS.IS", "TRGYO.IS", "TRILC.IS", "TSKB.IS", 
    "TSPOR.IS", "TTKOM.IS", "TTRAK.IS", "TUCLK.IS", "TUKAS.IS", "TUPRS.IS", "TURGG.IS", "TURSG.IS", 
    "UFUK.IS", "ULAS.IS", "ULKER.IS", "ULUFA.IS", "ULUSE.IS", "UNLU.IS", "USAK.IS", "VAKBN.IS", 
    "VAKFN.IS", "VAKKO.IS", "VANET.IS", "VBTYZ.IS", "VERTU.IS", "VERUS.IS", "VESBE.IS", "VESTL.IS", 
    "VKFYO.IS", "VKGYO.IS", "VKING.IS", "VRGYO.IS", "YAPRK.IS", "YATAS.IS", "YAYLA.IS", "YEOTK.IS", 
    "YGYO.IS", "YKBNK.IS", "YONGA.IS", "YUNSA.IS", "YYLGD.IS", "ZEDUR.IS", "ZOREN.IS"
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

def log_signal_to_db(ticker, score, price, stop, t1):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("INSERT INTO signals (date, ticker, score, price, stop, target1) VALUES (?, ?, ?, ?, ?, ?)",
                   (today, ticker, score, price, stop, t1))
    conn.commit()
    conn.close()

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
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

def atr_func(df, period=14):
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift()).abs()
    tr3 = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def light_scan(ticker):
    try:
        time.sleep(0.1)
        df = yf.download(ticker, period="60d", interval="1d", progress=False, auto_adjust=True, threads=False)
        df = clean_df(df)
        if df is None or len(df) < 30:
            return None
            
        close = float(df["Close"].iloc[-1])
        vol = float(df["Volume"].iloc[-1])
        if (close * vol) < MIN_TURNOVER_TL:
            return None
            
        ema20 = ema(df["Close"], 20).iloc[-1]
        ema50 = ema(df["Close"], 50).iloc[-1]
        r_val = float(rsi(df["Close"]).iloc[-1])
        
        light_score = 0
        if close > ema20: light_score += 30
        if ema20 > ema50: light_score += 30
        if 50 <= r_val <= 70: light_score += 40
        
        return {"ticker": ticker, "light_score": light_score, "close": close}
    except:
        return None

def deep_analyze(ticker, benchmark_close):
    try:
        time.sleep(0.15)
        daily = clean_df(yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True, threads=False))
        h1 = clean_df(yf.download(ticker, period="30d", interval="1h", progress=False, auto_adjust=True, threads=False))
        
        if daily is None or h1 is None or len(daily) < 120 or len(h1) < 40:
            return None
            
        daily["EMA20"] = ema(daily["Close"], 20)
        daily["EMA50"] = ema(daily["Close"], 50)
        daily["RSI"] = rsi(daily["Close"])
        daily["ATR"] = atr_func(daily)
        
        h1["VolMA"] = h1["Volume"].rolling(20).mean()
        h1["RVOL"] = h1["Volume"] / h1["VolMA"]
        
        d = daily.iloc[-1]
        one = h1.iloc[-1]
        close = float(d["Close"])
        
        score = 50 
        reasons = []
        warnings = []
        
        if d["Close"] > d["EMA20"] and d["EMA20"] > d["EMA50"]:
            score += 15
            reasons.append("Güçlü günlük trend (EMA20 > EMA50)")
            
        res_20 = daily["High"].iloc[-21:-1].max()
        if close > res_20:
            if float(one["RVOL"]) >= 1.5:
                score += 20
                reasons.append(f"20 günlük direnç hacimli kırıldı (RVOL: {float(one['RVOL']):.1f}x)")
            else:
                score -= 10
                warnings.append("Hacimsiz kırılım (False Breakout Riski)")
        elif close >= res_20 * 0.97:
            score += 10
            reasons.append("20 günlük dirence yakın (Pre-Breakout)")
            
        stock_perf = (daily["Close"].iloc[-1] / daily["Close"].iloc[-20]) - 1
        b_perf = (benchmark_close.iloc[-1] / benchmark_close.iloc[-20]) - 1
        rs = stock_perf - b_perf
        if rs > 0.05:
            score += 15
            reasons.append(f"BIST100'e göre pozitif ayrışma (RS: +{rs*100:.1f}%)")
            
        atr_val = float(d["ATR"])
        stop = close - (1.5 * atr_val)
        target1 = close + (2.0 * atr_val)
        risk_pct = ((close - stop) / close) * 100
        
        if score >= 70:
            return {
                "ticker": ticker.replace(".IS", ""),
                "score": int(score),
                "price": close,
                "stop": round(stop, 2),
                "target1": round(target1, 2),
                "risk_pct": round(risk_pct, 1),
                "reasons": reasons,
                "warnings": warnings
            }
    except Exception as e:
        print(f"Derin analiz hatası {ticker}: {e}")
    return None

def main():
    init_db()
    print("BIST V3 Pro Tarama Başlatıldı...")
    
    bench = yf.download("^XU100", period="6m", interval="1d", progress=False, auto_adjust=True)
    bench = clean_df(bench)
    if bench is not None:
        bench_ema50 = ema(bench["Close"], 50).iloc[-1]
        if bench["Close"].iloc[-1] < bench_ema50:
            send_telegram("⚠️ *BIST100 Rejim Uyarısı:* Endeks 50 EMA altında (Zayıf Rejim).")
            
    print("Aşama 1: Hızlı Tarama Başlıyor...")
    light_results = []
    for t in BIST_TUM_LISTESI:
        res = light_scan(t)
        if res:
            light_results.append(res)
            
    light_results.sort(key=lambda x: x["light_score"], reverse=True)
    top_20 = [item["ticker"] for item in light_results[:20]]
    print(f"Aşama 1 Tamamlandı. İlk 20 aday seçildi: {top_20}")
    
    print("Aşama 2: Derinlemesine Analiz Başlıyor...")
    final_signals = []
    for t in top_20:
        sig = deep_analyze(t, bench["Close"] if bench is not None else None)
        if sig:
            final_signals.append(sig)
            
    final_signals.sort(key=lambda x: x["score"], reverse=True)
    top_5 = final_signals[:5]
    
    if top_5:
        report = "🚀 *BIST V3 PRO - TOP 5 GÜÇLÜ ADAY* 🚀\n\n"
        for i, s in enumerate(top_5, 1):
            report += (
                f"{i}. *#{s['ticker']}* — Skor: {s['score']}/100\n"
                f"💰 Fiyat: {s['price']:.2f} TL\n"
                f"🛑 Stop: {s['stop']} TL (-{s['risk_pct']}%)\n"
                f"🎯 Hedef: {s['target1']} TL\n"
            )
            report += "💡 *Neden?* " + ", ".join(s['reasons']) + "\n\n"
            log_signal_to_db(s['ticker'], s['score'], s['price'], s['stop'], s['target1'])
            
        send_telegram(report)
        print("Rapor Telegram'a gönderildi.")
    else:
        print("Kriterleri sağlayan aday bulunamadı.")

if __name__ == "__main__":
    main()
