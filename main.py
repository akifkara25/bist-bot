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

# Borsa İstanbul'daki aktif ve popüler hisselerin genişletilmiş kapsamlı listesi (~500 hisse)
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
    "BRMEN.IS", "BRSAN.IS", "BRYAT.IS", "BSOKE.IS", "BTCIM.IS", "BUCIM.IS", "BURCE.IS", "BURVA.IS", "BVSAN.IS", "AYCES.IS",
    "CANTE.IS", "CASA.IS", "CATES.IS", "CCOLA.IS", "CELHA.IS", "CEMAS.IS", "CEMTS.IS", "CEOEM.IS", "CGCAN.IS", "CIMSA.IS",
    "CLEAS.IS", "CMBTN.IS", "CMENT.IS", "CONSE.IS", "COSMO.IS", "CRDFA.IS", "CRFSA.IS", "CASA.IS", "CWENE.IS", "DAGI.IS",
    "DAGHL.IS", "DAPGM.IS", "DARDL.IS", "DENGE.IS", "DERHL.IS", "DERIM.IS", "DESA.IS", "DESPC.IS", "DEVA.IS", "DGATE.IS",
    "DGNMO.IS", "DIRIT.IS", "DITAS.IS", "DMRGD.IS", "DMSAS.IS", "DNISI.IS", "DOAS.IS", "DOBUR.IS", "DOCO.IS", "DOGUB.IS",
    "DOHOL.IS", "DOKTA.IS", "ATSYH.IS", "DSIYE.IS", "DURDO.IS", "DYOBY.IS", "DZGYO.IS", "EBEBK.IS", "ECILC.IS", "Eczyt.IS",
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
    "SAFKR.IS", "SAHOL.IS", "AKBNK.IS", "SANKO.IS", "SARKY.IS", "SASA.IS", "SAYAS.IS", "SDTTR.IS", "SEGMN.IS", "SEGYO.IS",
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
    print(f"BIST V3 Pro Genişletilmiş Tarama Başlatıldı ({len(BIST_TUM_LISTESI)} Hisse taranacak)...")
    
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
            
            # Strateji Filtresi: Trend ve Momentum (RSI 50-75 arası)
            if current_price > sma_50 and 50 <= current_rsi <= 75:
                stop_loss = current_price * 0.95
                target = current_price * 1.10
                score = float(current_rsi)
                
                results.append({
                    "ticker": ticker,
                    "price": current_price,
                    "rsi": float(current_rsi),
                    "stop": stop_loss,
                    "target": target,
                    "score": score
                })
            
            time.sleep(0.05) # GitHub Actions akışının kesintisiz sürmesi için mini bekleme
        except Exception as e:
            # Hatalı/delist hisseleri sessizce geç
            continue
            
    if results:
        results.sort(key=lambda x: x["score"], reverse=True)
        top_candidates = results[:10]  # En güçlü ilk 10 aday
        
        report = "🚀 *BIST V3 Pro - Geniş Pazar Tarama Raporu* 📈\n\n"
        report += f"📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        report += f"🔍 Taranan Toplam Hisse: {len(BIST_TUM_LISTESI)}\n\n"
        
        for i, item in enumerate(top_candidates, 1):
            report += f"*{i}. {item['ticker']}*\n"
            report += f"   💰 Fiyat: {item['price']:.2f} TL\n"
            report += f"   📊 RSI: {item['rsi']:.1f}\n"
            report += f"   🛑 Stop: {item['stop']:.2f} TL\n"
            report += f"   🎯 Hedef: {item['target']:.2f} TL\n\n"
            
        send_telegram(report)
        print("Geniş tarama raporu Telegram'a gönderildi.")
    else:
        send_telegram("⚠️ BIST V3 Pro taraması tamamlandı. Kriterlere uyan hisse bulunamadı.")
        print("Kriterlere uyan aday bulunamadı.")

if __name__ == "__main__":
    main()
