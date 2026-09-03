import os
import time
import json
import sqlite3
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MIN_TURNOVER_TL = 15_000_000
DB_FILE = "signals_v9_trend_pullback.db"
MAX_ALERTS = 10

# Confluence eşikleri (kaç bağımsız teyit şart)
MIN_CONFLUENCE = 3          # 4 kategoriden en az kaçı onaylamalı
MIN_RR = 1.3                # Bu R/R oranının altındaki sinyaller elenir

# Düzeltme (pullback) parametreleri
PULLBACK_MIN_PCT = 4.0      # Tepeden en az %4 geri çekilme
PULLBACK_MAX_PCT = 22.0     # %22'den fazla düşüş = trend bozulmuş sayılır
LOOKBACK_SWING = 60         # Tepe/dip aramak için gün penceresi

# ============================================================
# BIST TÜM LİSTESİ (değişmedi, kısaltıldı gösterim için)
# ============================================================

_raw_bist_list = [
    "ACSEL.IS", "ADEL.IS", "ADESE.IS", "ADGYO.IS", "AEFES.IS", "AFYON.IS", "AGESA.IS", "AGHOL.IS", "AGROT.IS", "AGYO.IS",
    "AHGAZ.IS", "AKBNK.IS", "AKCNS.IS", "AKENR.IS", "AKFGY.IS", "AKFYE.IS", "AKGRT.IS", "AKMGY.IS", "AKSA.IS", "AKSEN.IS",
    "AKSGY.IS", "AKSUE.IS", "AKYHO.IS", "ALARK.IS", "ALBRK.IS", "ALCAR.IS", "ALKLC.IS", "ALFAS.IS", "ALGYO.IS", "ALKA.IS",
    "ALMAD.IS", "ALTNY.IS", "ANELE.IS", "ANGEN.IS", "ANHYT.IS", "ANSGR.IS", "ARASE.IS", "ARCLK.IS", "ARDYZ.IS", "ARENA.IS",
    "ARSAN.IS", "ARZUM.IS", "ASELS.IS", "ASTOR.IS", "ASUZU.IS", "ATAGY.IS", "ATAKP.IS", "ATATP.IS", "ATEKS.IS", "ATSYH.IS",
    "AVOD.IS", "AVPGY.IS", "AYCES.IS", "AYDEM.IS", "AYEN.IS", "AYES.IS", "AYGAZ.IS", "AZTEK.IS", "BAGFS.IS", "BAKAB.IS",
    "BALAT.IS", "BANVT.IS", "BARMA.IS", "BASGZ.IS", "BASCM.IS", "BAYRK.IS", "BEGYO.IS", "BERA.IS", "BEYAZ.IS", "BFREN.IS",
    "BIENP.IS", "BIGCH.IS", "BIMAS.IS", "BINHO.IS", "BIOEN.IS", "BIZIM.IS", "BJKAS.IS", "BLCYT.IS", "BMSCH.IS", "BMSTL.IS",
    "BNTAS.IS", "BOBET.IS", "BORLS.IS", "BORSK.IS", "BOSSA.IS", "BRISA.IS", "BRKO.IS", "BRKSN.IS", "BRMEN.IS", "BRSAN.IS",
    "BRYAT.IS", "BSOKE.IS", "BTCIM.IS", "BUCIM.IS", "BURCE.IS", "BURVA.IS", "BVSAN.IS", "CANTE.IS", "CASA.IS", "CATES.IS",
    "CCOLA.IS", "CELHA.IS", "CEMAS.IS", "CEMTS.IS", "CEOEM.IS", "CGCAN.IS", "CIMSA.IS", "CLEAS.IS", "CMBTN.IS", "CMENT.IS",
    "CONSE.IS", "COSMO.IS", "CRDFA.IS", "CRFSA.IS", "CVKMD.IS", "CWENE.IS", "DAGI.IS", "DAGHL.IS", "DAPGM.IS", "DARDL.IS",
    "DENGE.IS", "DERHL.IS", "DERIM.IS", "DESA.IS", "DESPC.IS", "DEVA.IS", "DGATE.IS", "DGNMO.IS", "DIRIT.IS", "DITAS.IS",
    "DMRGD.IS", "DMSAS.IS", "DNISI.IS", "DOAS.IS", "DOBUR.IS", "DOCO.IS", "DOGUB.IS", "DOHOL.IS", "DOKTA.IS", "DURDO.IS",
    "DYOBY.IS", "DZGYO.IS", "EBEBK.IS", "ECILC.IS", "ECZYT.IS", "EDIP.IS", "EGEEN.IS", "EGEPO.IS", "EGGUB.IS", "EGPRO.IS",
    "EGSER.IS", "EKGYO.IS", "EKOS.IS", "EKSUN.IS", "ELITE.IS", "EMKEL.IS", "ENERY.IS", "ENKAI.IS", "ENSRI.IS", "EPLAS.IS",
    "ERBOS.IS", "ERCB.IS", "EREGL.IS", "ERSU.IS", "ESCAR.IS", "ESCOM.IS", "ESEN.IS", "ETILR.IS", "EUHOL.IS", "EUKYO.IS",
    "EUPWR.IS", "EUREN.IS", "EUYO.IS", "EYGYO.IS", "FADE.IS", "FENER.IS", "FLAP.IS", "FMIZP.IS", "FONET.IS", "FORMT.IS",
    "FORTE.IS", "FROTO.IS", "GARAN.IS", "GARFA.IS", "GEDIK.IS", "GEDAN.IS", "GENIL.IS", "GENTS.IS", "GEREL.IS", "GESAN.IS",
    "GLBMD.IS", "GLCVY.IS", "GLRYH.IS", "GLYHO.IS", "GMTAS.IS", "GOKNR.IS", "GOLTS.IS", "GOODY.IS", "GOZDE.IS", "GRNYO.IS",
    "GRSEL.IS", "GSDDE.IS", "GSDHO.IS", "GSRAY.IS", "GUBRF.IS", "GWIND.IS", "GZNMI.IS", "HALKB.IS", "HATEK.IS", "HATSN.IS",
    "HEDEF.IS", "HEKTS.IS", "HKTM.IS", "HLGYO.IS", "HTTBT.IS", "HUBVC.IS", "HUNER.IS", "HURGZ.IS", "ICBCT.IS", "IDEAS.IS",
    "IDGYO.IS", "IHEVA.IS", "IHGZT.IS", "IHLAS.IS", "IHLGM.IS", "IHYVA.IS", "IMASM.IS", "INDES.IS", "INFO.IS", "INTEM.IS",
    "INVEO.IS", "INVES.IS", "IPEKE.IS", "ISATR.IS", "ISBIR.IS", "ISBTR.IS", "ISCGR.IS", "ISCTR.IS", "ISDMR.IS", "ISFIN.IS",
    "ISGSY.IS", "ISGYO.IS", "ISKPL.IS", "ISMEN.IS", "ISSEN.IS", "IZENR.IS", "IZFAS.IS", "IZINV.IS", "IZMDC.IS", "JANTS.IS",
    "KAFIN.IS", "KAPLM.IS", "KAREL.IS", "KARSN.IS", "KARTN.IS", "KARYE.IS", "KASTB.IS", "KATMR.IS", "KAYSE.IS", "KBORU.IS",
    "KCAER.IS", "KCHOL.IS", "KENT.IS", "KERVT.IS", "KFEIN.IS", "KGYO.IS", "KIMMR.IS", "KLGYO.IS", "KLKIM.IS", "KLRHO.IS",
    "KLSYN.IS", "KMPUR.IS", "KNFRT.IS", "KONKA.IS", "KONTR.IS", "KONYA.IS", "KOPOL.IS", "KORDS.IS", "KOTON.IS", "KOZAA.IS",
    "KOZAL.IS", "KRDMD.IS", "KRGYO.IS", "KRONT.IS", "KRPLS.IS", "KRSTL.IS", "KRTEK.IS", "KZBGY.IS", "KZYGZ.IS", "LIDER.IS",
    "LIDFA.IS", "LKMNH.IS", "LOGO.IS", "LUKSK.IS", "MAALT.IS", "MAKIM.IS", "MAKTK.IS", "MANAS.IS", "MARKA.IS", "MARTI.IS",
    "MAVI.IS", "MEDTR.IS", "MEGAP.IS", "MEKAG.IS", "MEMUR.IS", "MEPET.IS", "MERCN.IS", "MERKO.IS", "METUR.IS", "MGROS.IS",
    "MHRGY.IS", "MIATK.IS", "MMCAS.IS", "MNDRS.IS", "MNDTR.IS", "MOBTL.IS", "MPARK.IS", "MRSHL.IS", "MSGYO.IS", "MTRKS.IS",
    "MZYGZ.IS", "NATEN.IS", "NETAS.IS", "NIBAS.IS", "NTGAZ.IS", "NUGYO.IS", "NUHCM.IS", "OBASE.IS", "ODAS.IS", "OFSYM.IS",
    "ONCSN.IS", "ORCAY.IS", "OYYAT.IS", "OYAKC.IS", "OZATD.IS", "OZGYO.IS", "OZKGY.IS", "OZRDN.IS", "PASTR.IS", "PAGYO.IS",
    "PAMEL.IS", "PAKMD.IS", "PAPIL.IS", "PARSN.IS", "PATEK.IS", "PCILT.IS", "PEKGY.IS", "PENGD.IS", "PENTA.IS", "PETKM.IS",
    "PETUN.IS", "PGSUS.IS", "PINSU.IS", "PKART.IS", "PKENT.IS", "PNSUT.IS", "POLHO.IS", "POLTK.IS", "PRKME.IS", "PRDGS.IS",
    "PRZMA.IS", "PSDTC.IS", "QNBFB.IS", "QNBFL.IS", "QUAGR.IS", "RALYH.IS", "RAYSG.IS", "REEDR.IS", "RNPAS.IS", "RODRG.IS",
    "ROYAL.IS", "RTALB.IS", "RUBNS.IS", "RYGYO.IS", "RYSAS.IS", "SAFKR.IS", "SAHOL.IS", "SANKO.IS", "SARKY.IS", "SASA.IS",
    "SAYAS.IS", "SDTTR.IS", "SEGMN.IS", "SEGYO.IS", "SEKFK.IS", "SEKUR.IS", "SELEC.IS", "SELGD.IS", "SELVA.IS", "SEYKM.IS",
    "SILVR.IS", "SISE.IS", "SKBNK.IS", "SKTAS.IS", "SMART.IS", "SMRTG.IS", "SNGYO.IS", "SNICA.IS", "SOKE.IS", "SOKM.IS",
    "SONME.IS", "SRVGY.IS", "SUMAS.IS", "SUNTK.IS", "SUWEN.IS", "TABGD.IS", "TARKM.IS", "TATEN.IS", "TATGD.IS", "TAVHL.IS",
    "TBORG.IS", "TCELL.IS", "TDGYO.IS", "TEKFN.IS", "TEKTN.IS", "TETMT.IS", "TFGYO.IS", "THYAO.IS", "TIRE.IS", "TKFEN.IS",
    "TKNSA.IS", "TMPOL.IS", "TMSN.IS", "TOASO.IS", "TRGYO.IS", "TRILC.IS", "TSKB.IS", "TSPOR.IS", "TTKOM.IS", "TTRAK.IS",
    "TUCLK.IS", "TUPRS.IS", "TUREKS.IS", "TURGG.IS", "UFUK.IS", "ULAS.IS", "ULKER.IS", "ULUUN.IS", "UNLU.IS", "USAK.IS",
    "VAKBN.IS", "VAKFN.IS", "VAKKO.IS", "VANGD.IS", "VBTYZ.IS", "VERTU.IS", "VERUS.IS", "VESBE.IS", "VESTL.IS", "VKGYO.IS",
    "VKING.IS", "YAPRK.IS", "YATAS.IS", "YAYLA.IS", "YBTAS.IS", "YEOTK.IS", "YESIL.IS", "YGGYO.IS", "YIGIT.IS", "YKBNK.IS",
    "YKSLN.IS", "YUNSA.IS", "YYAPI.IS", "ZEDUR.IS", "ZOREN.IS", "ZRGYO.IS"
]

BIST_TUM_LISTESI = sorted(set(t.strip().upper() for t in _raw_bist_list if t and t.strip()))

# ============================================================
# DATABASE (kalıcılık: GitHub Actions workflow'da cache+commit ile sağlanır — bkz. scan.yml)
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_state (
            ticker TEXT PRIMARY KEY,
            last_tier TEXT,
            last_score REAL,
            last_rvol REAL,
            last_close REAL,
            last_date TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_previous_state(ticker):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT last_tier, last_score, last_rvol, last_close, last_date FROM stock_state WHERE ticker=?", (ticker,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {"tier": row[0], "score": row[1], "rvol": row[2], "close": row[3], "date": row[4]}


def update_state(ticker, tier, score, rvol, close):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO stock_state (ticker, last_tier, last_score, last_rvol, last_close, last_date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ticker, tier, score, rvol, close, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.status_code == 200
    except Exception:
        return False

# ============================================================
# VERİ ÇEKME (toplu + retry)
# ============================================================

def clean_df(df):
    if df is None or df.empty:
        return None
    try:
        df = df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            if "Close" in df.columns.get_level_values(0):
                df.columns = df.columns.get_level_values(0)
            else:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.columns = [str(c).capitalize() for c in df.columns]
        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in required):
            return None
        df = df[required].copy()
        for c in required:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna()
        return df if not df.empty else None
    except Exception:
        return None


def batch_download(tickers, batch_size=40, retries=3, sleep_between=1.5):
    """
    500 hisseyi tek tek değil, gruplar halinde indirir.
    Yahoo rate-limit'e takılan grupları retry eder.
    Döner: {ticker: DataFrame}
    """
    all_data = {}
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]

    for bi, batch in enumerate(batches, start=1):
        print(f"  Grup {bi}/{len(batches)} indiriliyor ({len(batch)} hisse)...")
        attempt = 0
        while attempt < retries:
            try:
                data = yf.download(
                    tickers=batch, period="1y", interval="1d",
                    group_by="ticker", progress=False, auto_adjust=False,
                    threads=True
                )
                for t in batch:
                    try:
                        sub = data[t] if len(batch) > 1 else data
                        cdf = clean_df(sub)
                        if cdf is not None and len(cdf) >= 70:
                            all_data[t] = cdf
                    except Exception:
                        continue
                break
            except Exception as e:
                attempt += 1
                print(f"    Grup hata (deneme {attempt}/{retries}): {e}")
                time.sleep(sleep_between * attempt)
        time.sleep(sleep_between)

    return all_data


def get_market_data():
    try:
        df = yf.download("XU100.IS", period="1y", interval="1d", progress=False, auto_adjust=False, threads=False)
        df = clean_df(df)
        return df if df is not None else None
    except Exception:
        return None

# ============================================================
# İNDİKATÖRLER
# ============================================================

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def calc_obv(close, volume):
    direction = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0))
    return pd.Series(direction, index=close.index).cumsum()


def calc_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_cmf(df, period=20):
    """Chaikin Money Flow - hacmi kapanışın mum içindeki konumuna göre ağırlıklandırır."""
    high, low, close, volume = df["High"], df["Low"], df["Close"], df["Volume"]
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mfv = mfm * volume
    cmf = mfv.rolling(period).sum() / volume.rolling(period).sum()
    return cmf.fillna(0)

# ============================================================
# 1) TREND FİLTRESİ (günlük SMA50/SMA200 ile)
# ============================================================

def trend_filter(close):
    if len(close) < 210:
        return {"ok": False, "reason": "yetersiz veri"}

    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    cp = float(close.iloc[-1])

    above50 = cp > float(sma50.iloc[-1])
    above200 = cp > float(sma200.iloc[-1])
    sma50_rising = float(sma50.iloc[-1]) > float(sma50.iloc[-10])
    golden = float(sma50.iloc[-1]) > float(sma200.iloc[-1])

    ok = above200 and sma50_rising and golden
    return {
        "ok": ok, "above50": above50, "above200": above200,
        "sma50_rising": sma50_rising, "golden": golden,
        "sma50": float(sma50.iloc[-1]), "sma200": float(sma200.iloc[-1])
    }

# ============================================================
# 2) DÜZELTME (PULLBACK) TESPİTİ
# ============================================================

def detect_pullback(high, low, close):
    """
    Son LOOKBACK_SWING gün içindeki tepeyi bulur, oradan şu ana kadarki
    geri çekilme yüzdesini hesaplar. Ayrıca düzeltme sırasında hacmin
    azalıp azalmadığını (sağlıklı pullback imzası) döner.
    """
    if len(close) < LOOKBACK_SWING:
        return {"ok": False}

    window_high = high.tail(LOOKBACK_SWING)
    peak_idx = window_high.idxmax()
    peak_price = float(window_high.max())
    cp = float(close.iloc[-1])

    # tepeden bugüne kadar oluşan en düşük nokta (düzeltmenin dibi)
    after_peak_low = low.loc[peak_idx:].min()
    if pd.isna(after_peak_low) or peak_price <= 0:
        return {"ok": False}

    drawdown_pct = (peak_price - float(after_peak_low)) / peak_price * 100
    recovery_from_low_pct = (cp - float(after_peak_low)) / float(after_peak_low) * 100 if after_peak_low > 0 else 0

    healthy_depth = PULLBACK_MIN_PCT <= drawdown_pct <= PULLBACK_MAX_PCT
    is_recovering = cp > float(after_peak_low) * 1.01  # dipten en az %1 toparlanmış

    return {
        "ok": healthy_depth and is_recovering,
        "peak_price": peak_price,
        "trough_price": float(after_peak_low),
        "drawdown_pct": drawdown_pct,
        "recovery_from_low_pct": recovery_from_low_pct,
        "peak_idx": peak_idx
    }


def volume_during_pullback(volume, peak_idx, pullback_info):
    """Düzeltme sırasında hacim gerçekten azaldı mı (satış baskısı zayıflıyor mu)?"""
    try:
        during = volume.loc[peak_idx:]
        if len(during) < 4:
            return False
        first_half = during.iloc[:len(during) // 2].mean()
        second_half = during.iloc[len(during) // 2:].mean()
        return second_half < first_half
    except Exception:
        return False

# ============================================================
# 3) TOPARLANMA / CONFLUENCE SİSTEMİ
# ============================================================

def rsi_bullish_divergence(close, rsi, peak_idx):
    """Fiyat düşük dip yaparken RSI daha yüksek dip yapıyor mu (klasik bullish divergence)."""
    try:
        seg_close = close.loc[peak_idx:]
        seg_rsi = rsi.loc[peak_idx:]
        if len(seg_close) < 6:
            return False
        mid = len(seg_close) // 2
        low1_idx = seg_close.iloc[:mid].idxmin()
        low2_idx = seg_close.iloc[mid:].idxmin()
        if low1_idx == low2_idx:
            return False
        price_lower = seg_close[low2_idx] < seg_close[low1_idx]
        rsi_higher = seg_rsi[low2_idx] > seg_rsi[low1_idx]
        return bool(price_lower and rsi_higher)
    except Exception:
        return False


def evaluate_confluence(df, pullback_info):
    """
    4 bağımsız kategori kontrol edilir:
    1. Hacim/para girişi (rvol + CMF)
    2. Momentum dönüşü (RSI divergence veya güçlü RSI ivmesi)
    3. MACD histogram dönüşü
    4. Fiyat yapısı (higher-low, OBV teyidi)
    Her kategori True/False döner, kaç tanesinin onayladığı sayılır.
    """
    close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
    peak_idx = pullback_info["peak_idx"]

    rsi = calc_rsi(close)
    _, _, hist = calc_macd(close)
    obv = calc_obv(close, volume)
    cmf = calc_cmf(df)

    checks = {}

    # 1) Hacim / para girişi
    avg20 = volume.iloc[-21:-1].mean()
    rvol = float(volume.iloc[-1] / avg20) if avg20 > 0 else 1.0
    vol_shrank_in_pullback = volume_during_pullback(volume, peak_idx, pullback_info)
    cmf_positive = float(cmf.iloc[-1]) > 0
    checks["volume"] = bool((rvol >= 1.15 or cmf_positive) and vol_shrank_in_pullback)

    # 2) Momentum dönüşü
    divergence = rsi_bullish_divergence(close, rsi, peak_idx)
    rsi_now = float(rsi.iloc[-1])
    rsi_turning = rsi.iloc[-1] > rsi.iloc[-3] > rsi.iloc[-5] if len(rsi) >= 6 else False
    checks["momentum"] = bool(divergence or (rsi_turning and 40 <= rsi_now <= 68))

    # 3) MACD dönüşü
    macd_turning = float(hist.iloc[-1]) > float(hist.iloc[-3]) if len(hist) >= 4 else False
    checks["macd"] = bool(macd_turning)

    # 4) Fiyat yapısı (higher-low + OBV teyidi)
    hl = detect_higher_lows(low)
    obv5 = obv.tail(5).mean()
    obv20 = obv.iloc[-21:-1].mean() if len(obv) >= 21 else obv5
    obv_confirms = obv5 > obv20
    checks["structure"] = bool(hl or obv_confirms)

    confluence_count = sum(checks.values())

    return {
        "checks": checks,
        "count": confluence_count,
        "rvol": rvol,
        "cmf": float(cmf.iloc[-1]),
        "divergence": divergence,
        "rsi": rsi_now,
        "hist": float(hist.iloc[-1]),
        "higher_lows": hl,
        "obv_confirms": obv_confirms
    }


def detect_higher_lows(low_series):
    if len(low_series) < 15:
        return False
    lows = low_series.tail(15).values
    swing_lows = [lows[i] for i in range(1, len(lows) - 1) if lows[i] < lows[i - 1] and lows[i] <= lows[i + 1]]
    if len(swing_lows) < 2:
        return False
    return swing_lows[-1] > swing_lows[-2]

# ============================================================
# 4) PİYASA REJİMİ FİLTRESİ
# ============================================================

def market_regime_ok(xu100_df):
    if xu100_df is None or len(xu100_df) < 60:
        return True  # veri yoksa filtreyi devre dışı bırak, botu tamamen durdurma
    close = xu100_df["Close"]
    sma50 = close.rolling(50).mean()
    return float(close.iloc[-1]) > float(sma50.iloc[-1])

# ============================================================
# 5) GİRİŞ / STOP / HEDEF SEVİYELERİ
# ============================================================

def calc_levels(df, pullback_info, resistance):
    close, high, low = df["Close"], df["High"], df["Low"]
    cp = float(close.iloc[-1])
    atr = float(calc_atr(df).iloc[-1])

    # Giriş: son birkaç günün en yükseği (kırılım teyidi) ile şu anki fiyatın ortalaması
    recent_high = float(high.tail(3).max())
    entry = max(cp, recent_high * 0.995)

    # Stop: düzeltmenin dibi ile ATR bazlı mesafenin daha temkinlisi
    trough = pullback_info["trough_price"]
    atr_stop = entry - 1.5 * atr
    stop = min(trough * 0.985, atr_stop) if trough > 0 else atr_stop
    if stop >= entry:
        stop = entry - 1.5 * atr

    risk = entry - stop
    if risk <= 0:
        return None

    target1 = resistance if resistance > entry else entry + 2 * risk
    target2 = entry + 3 * risk

    rr1 = (target1 - entry) / risk
    rr2 = (target2 - entry) / risk

    return {
        "entry": entry, "stop": stop, "target1": target1, "target2": target2,
        "risk_pct": (risk / entry) * 100, "rr1": rr1, "rr2": rr2
    }

# ============================================================
# ANA TARAMA
# ============================================================

def main():
    print("\n============================================")
    print("🧠 BIST TREND+PULLBACK+CONFLUENCE ENGINE")
    print("============================================\n")

    init_db()
    print(f"📊 Taranacak toplam hisse: {len(BIST_TUM_LISTESI)}")

    xu100_df = get_market_data()
    regime_ok = market_regime_ok(xu100_df)
    print(f"🌍 Piyasa rejimi (XU100 > SMA50): {'UYGUN ✅' if regime_ok else 'ZAYIF ⚠️ (filtre gevşetildi, dikkatli olun)'}")

    print("\n📥 Veri toplu indiriliyor...")
    all_data = batch_download(BIST_TUM_LISTESI)
    print(f"✅ {len(all_data)}/{len(BIST_TUM_LISTESI)} hisse için veri alındı.\n")

    results = []

    for i, (ticker, df) in enumerate(all_data.items(), start=1):
        try:
            close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
            if close.iloc[-1] <= 0:
                continue

            turnover = close * volume
            if turnover.tail(5).mean() < MIN_TURNOVER_TL:
                continue

            trend = trend_filter(close)
            if not trend["ok"]:
                continue

            pullback = detect_pullback(high, low, close)
            if not pullback["ok"]:
                continue

            confluence = evaluate_confluence(df, pullback)
            if confluence["count"] < MIN_CONFLUENCE:
                continue

            resistance_window = high.iloc[-LOOKBACK_SWING:-1]
            resistance = float(resistance_window.max()) if not resistance_window.empty else pullback["peak_price"]

            levels = calc_levels(df, pullback, resistance)
            if levels is None or levels["rr1"] < MIN_RR:
                continue

            # Piyasa zayıfsa daha sıkı confluence şartı ara (regime filtresi)
            if not regime_ok and confluence["count"] < MIN_CONFLUENCE + 1:
                continue

            score = (confluence["count"] / 4) * 60 + min(levels["rr1"], 4) * 10
            score = round(min(100, score), 1)

            results.append({
                "ticker": ticker, "close": float(close.iloc[-1]), "score": score,
                "confluence": confluence, "pullback": pullback, "levels": levels,
                "trend": trend
            })

        except Exception:
            continue

        if i % 50 == 0:
            print(f"  ...{i} hisse analiz edildi")

    results.sort(key=lambda x: x["score"], reverse=True)

    sent = 0
    for item in results:
        if sent >= MAX_ALERTS:
            break

        prev = get_previous_state(item["ticker"])
        should_notify = prev is None or item["score"] >= (prev["score"] or 0) + 5 or item["confluence"]["rvol"] >= (prev["rvol"] or 1) + 0.3

        if should_notify:
            c, l, tr, pb = item["confluence"], item["levels"], item["trend"], item["pullback"]
            checks_text = ", ".join([k for k, v in c["checks"].items() if v]) or "yok"

            msg = (
                f"⚡ *TREND İÇİ TOPARLANMA SİNYALİ*\n\n"
                f"📌 *Hisse:* `{item['ticker']}`\n"
                f"🎯 *Skor:* {item['score']:.1f}/100 | Confluence: {c['count']}/4 ({checks_text})\n\n"
                f"💰 *Fiyat:* {item['close']:.2f}\n"
                f"📉 *Düzeltme derinliği:* %{pb['drawdown_pct']:.1f} (tepe {pb['peak_price']:.2f} → dip {pb['trough_price']:.2f})\n"
                f"📈 *Dipten toparlanma:* %{pb['recovery_from_low_pct']:.1f}\n"
                f"🔀 *RSI:* {c['rsi']:.1f}{' (bullish divergence ✓)' if c['divergence'] else ''}\n"
                f"🌊 *MACD histogram:* {'dönüş ↑' if c['checks']['macd'] else 'nötr'}\n"
                f"💵 *CMF:* {c['cmf']:+.2f} | *RVOL:* {c['rvol']:.2f}x\n\n"
                f"🎯 *Giriş:* {l['entry']:.2f}\n"
                f"🛑 *Stop:* {l['stop']:.2f} (-%{l['risk_pct']:.1f})\n"
                f"🎯 *Hedef 1:* {l['target1']:.2f} (R/R {l['rr1']:.1f})\n"
                f"🎯 *Hedef 2:* {l['target2']:.2f} (R/R {l['rr2']:.1f})\n\n"
                f"_Bu bir yatırım tavsiyesi değildir, teknik bir analiz özetidir._"
            )
            send_telegram(msg)
            sent += 1
            time.sleep(0.5)

        update_state(item["ticker"], "PULLBACK_RESUME", item["score"], item["confluence"]["rvol"], item["close"])

    print("\n============================================")
    print("✅ TARAMA TAMAMLANDI")
    print(f"📊 Eşleşen aday: {len(results)} | 📨 Gönderilen: {sent}")
    print("============================================")

    if results:
        print("\n🏆 EN GÜÇLÜ ADAYLAR:\n")
        for item in results[:15]:
            print(f"{item['ticker']:12} | Skor {item['score']:5.1f} | Confluence {item['confluence']['count']}/4 | "
                  f"R/R {item['levels']['rr1']:.1f} | Düzeltme %{item['pullback']['drawdown_pct']:.1f}")


if __name__ == "__main__":
    main()
