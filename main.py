import os
import time
import json
import logging
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from scipy.signal import argrelextrema

# ============================================================
# LOGLAMA
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bist_scanner")

# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MIN_TURNOVER_TL = 15_000_000
STATE_FILE = "state.json"

MAX_MAIN_BREAK_ALERTS = 8    # Ana direnç kırılımı (en yüksek güven)
MAX_LOCAL_BREAK_ALERTS = 8   # Yerel/erken kırılım (orta-yüksek güven, erken haber)
MAX_EXTENDED_ALERTS = 4      # Aşırı uzamış (kovalama riski uyarısı)
MAX_SETUP_ALERTS = 8         # Kurulum hazır, henüz kırılım yok
MAX_WATCH_ALERTS = 6         # İzleme (düşük güven)

# --- Veri kalitesi eşikleri ---
MAX_STALE_DAYS = 5
MIN_SUCCESS_RATE = 0.6
MAX_DAILY_JUMP_PCT = 60.0

# --- Confluence eşikleri (4 ana kategori üzerinden) ---
MIN_CONFLUENCE_STRONG = 3
MIN_CONFLUENCE_WATCH = 2
MIN_RR = 1.3
MIN_RR_WATCH = 1.0

# Düzeltme (pullback) parametreleri
PULLBACK_MIN_PCT = 4.0
PULLBACK_MAX_PCT = 22.0
LOOKBACK_SWING = 60
LOOKBACK_STRUCTURE = 120
SWING_ORDER = 3

# Volatilite sıkışması (Bollinger Band Width)
BBW_LOOKBACK = 120
BBW_SQUEEZE_PERCENTILE = 20

# Relatif güç (XU100'e göre)
RS_LOOKBACK = 20

# Ana direnç kırılımından sonra "çok geç kalındı" eşiği
BREAKOUT_EXTENDED_PCT = 8.0


def market_session_label():
    """
    Türkiye UTC+3'te sabit (yaz saati yok), bu yüzden basit ofset yeterli.
    Bot artık gün içinde de çalıştığı için, mesajlarda VERİNİN NE KADAR
    KESİNLEŞMİŞ olduğunu açıkça belirtmemiz gerekiyor — piyasa açıkken
    çekilen "bugünün mumu" henüz tamamlanmamıştır (hacim özellikle düşük
    görünür, RVOL yanıltıcı olabilir).
    """
    trt_now = datetime.utcnow() + timedelta(hours=3)
    minutes = trt_now.hour * 60 + trt_now.minute

    if minutes < 10 * 60:
        return "⏰ *Piyasa henüz açılmadı* — bu veriler önceki kapanışa ait, kesinleşmiş."
    elif minutes < 18 * 60:
        return ("⚠️ *Piyasa şu an AÇIK* — bugünün mumu henüz tamamlanmadı. "
                "Özellikle hacim (RVOL) düşük görünebilir, gün sonuna kadar değişebilir.")
    else:
        return "✅ *Piyasa kapandı* — bugünün verisi kesinleşmiş, güvenilirliği en yüksek tarama budur."

# Skor ağırlıkları — HENÜZ BACKTEST EDİLMEDİ. İlk mantıklı tahmin.
SCORE_WEIGHTS = {
    "trend": 0.20,
    "pullback": 0.15,
    "momentum": 0.20,
    "volume": 0.15,
    "structure": 0.10,
    "squeeze": 0.05,
    "relative_strength": 0.15,
}

# ============================================================
# BIST TÜM LİSTESİ
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
# STATE (JSON — kalıcılık workflow'da commit ile sağlanıyor)
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"state.json okunamadı, sıfırdan başlanıyor: {e}")
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"state.json yazılamadı: {e}")


def get_previous_state(state, ticker):
    return state.get(ticker)


def update_state(state, ticker, stage, score, rvol, close, position=None, clear_position=False):
    """
    ÖNEMLİ: position parametresi verilmezse (None) ve clear_position=False ise,
    varsa MEVCUT açık pozisyon KORUNUR. Aksi halde her sıradan WATCH/SETUP
    güncellemesinde, arkada takip edilen bir kırılım pozisyonu sessizce
    silinmiş olurdu — bu ciddi bir hata olurdu, bilerek böyle tasarlandı.
    """
    existing = state.get(ticker, {})
    entry = {
        "stage": stage, "score": score, "rvol": rvol, "close": close,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if position is not None:
        entry["position"] = position
    elif clear_position:
        entry["position"] = None
    else:
        entry["position"] = existing.get("position")
    state[ticker] = entry

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
        if r.status_code != 200:
            log.error(f"Telegram gönderim hatası ({r.status_code}): {r.text[:300]}")
        return r.status_code == 200
    except Exception as e:
        log.error(f"Telegram gönderim istisnası: {e}")
        return False

# ============================================================
# VERİ ÇEKME
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


def data_quality_check(df):
    if df is None or df.empty:
        return False, "boş veri"
    last_date = df.index[-1]
    if hasattr(last_date, "to_pydatetime"):
        last_date = last_date.to_pydatetime()
    if (datetime.now() - last_date.replace(tzinfo=None)) > timedelta(days=MAX_STALE_DAYS):
        return False, f"veri çok eski ({last_date.date()})"
    daily_change = df["Close"].pct_change().abs()
    if (daily_change > MAX_DAILY_JUMP_PCT / 100).tail(LOOKBACK_SWING).any():
        return False, "şüpheli tek günlük sıçrama"
    if (df["Close"] <= 0).any() or (df["Volume"] < 0).any():
        return False, "geçersiz fiyat/hacim"
    return True, "ok"


def batch_download(tickers, batch_size=40, retries=3, sleep_between=1.5):
    all_data = {}
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]

    for bi, batch in enumerate(batches, start=1):
        log.info(f"  Grup {bi}/{len(batches)} indiriliyor ({len(batch)} hisse)...")
        attempt = 0
        while attempt < retries:
            try:
                data = yf.download(
                    tickers=batch, period="1y", interval="1d",
                    group_by="ticker", progress=False, auto_adjust=True,
                    threads=True
                )
                for t in batch:
                    try:
                        sub = data[t] if len(batch) > 1 else data
                        cdf = clean_df(sub)
                        if cdf is None or len(cdf) < 70:
                            continue
                        ok, reason = data_quality_check(cdf)
                        if not ok:
                            log.debug(f"{t}: veri kalitesi reddi ({reason})")
                            continue
                        all_data[t] = cdf
                    except Exception:
                        continue
                break
            except Exception as e:
                attempt += 1
                log.warning(f"Grup hata (deneme {attempt}/{retries}): {e}")
                time.sleep(sleep_between * attempt)
        time.sleep(sleep_between)

    return all_data


def get_market_data():
    try:
        df = yf.download("XU100.IS", period="1y", interval="1d", progress=False, auto_adjust=True, threads=False)
        df = clean_df(df)
        return df if df is not None else None
    except Exception:
        return None

# ============================================================
# TEMEL İNDİKATÖRLER
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
    high, low, close, volume = df["High"], df["Low"], df["Close"], df["Volume"]
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mfv = mfm * volume
    cmf = mfv.rolling(period).sum() / volume.rolling(period).sum()
    return cmf.fillna(0)


def calc_bbw(close, period=20, num_std=2):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return (upper - lower) / sma

# ============================================================
# SWING (GERÇEK TEPE/DİP) TESPİTİ
# ============================================================

def _dedupe_consecutive(idx_array):
    if len(idx_array) == 0:
        return idx_array
    groups, current = [], [idx_array[0]]
    for x in idx_array[1:]:
        if x - current[-1] <= 1:
            current.append(x)
        else:
            groups.append(current)
            current = [x]
    groups.append(current)
    return np.array([g[-1] for g in groups])


def find_swings(series, order=SWING_ORDER, mode="max"):
    if len(series) < order * 2 + 1:
        return pd.Index([])
    arr = series.values.astype(float)
    comp = np.greater_equal if mode == "max" else np.less_equal
    idx = argrelextrema(arr, comp, order=order)[0]
    idx = _dedupe_consecutive(idx)
    return series.index[idx]

# ============================================================
# 1) TREND
# ============================================================

def weekly_trend_ok(df):
    try:
        w = df.resample("W-FRI").agg({"Close": "last"}).dropna()
        if len(w) < 15:
            return True
        close_w = w["Close"]
        sma10w = close_w.rolling(10).mean()
        if sma10w.isna().iloc[-1]:
            return True
        return bool(close_w.iloc[-1] > sma10w.iloc[-1])
    except Exception:
        return True


def hh_hl_structure(high, low, lookback=LOOKBACK_STRUCTURE, order=SWING_ORDER):
    h = high.tail(lookback)
    l = low.tail(lookback)
    sh_idx = find_swings(h, order, "max")
    sl_idx = find_swings(l, order, "min")
    sh_vals = h.loc[sh_idx]
    sl_vals = l.loc[sl_idx]
    hh = bool(len(sh_vals) >= 2 and sh_vals.iloc[-1] > sh_vals.iloc[-2])
    hl = bool(len(sl_vals) >= 2 and sl_vals.iloc[-1] > sl_vals.iloc[-2])
    return {"hh": hh, "hl": hl, "swing_highs": sh_vals, "swing_lows": sl_vals}


def trend_filter(df):
    close, high, low = df["Close"], df["High"], df["Low"]
    if len(close) < 210:
        return {"ok": False, "reason": "yetersiz veri"}

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    cp = float(close.iloc[-1])

    above20 = cp > float(sma20.iloc[-1])
    above50 = cp > float(sma50.iloc[-1])
    above200 = cp > float(sma200.iloc[-1])
    sma20_rising = float(sma20.iloc[-1]) > float(sma20.iloc[-5])
    sma50_rising = float(sma50.iloc[-1]) > float(sma50.iloc[-10])
    golden = float(sma50.iloc[-1]) > float(sma200.iloc[-1])

    structure = hh_hl_structure(high, low)
    weekly_ok = weekly_trend_ok(df)

    ok = above200 and sma50_rising and golden and (structure["hl"] or above50) and weekly_ok

    return {
        "ok": ok, "above20": above20, "above50": above50, "above200": above200,
        "sma20_rising": sma20_rising, "sma50_rising": sma50_rising, "golden": golden,
        "hh": structure["hh"], "hl": structure["hl"], "weekly_ok": weekly_ok,
    }

# ============================================================
# 2) DÜZELTME (PULLBACK)
# ============================================================

def detect_pullback(high, low, close, lookback=LOOKBACK_SWING, order=SWING_ORDER, context_buffer=30):
    window = lookback + context_buffer
    if len(close) < window:
        return {"ok": False}

    h = high.tail(window)
    l = low.tail(window)

    sh_idx = find_swings(h, order, "max")
    if len(sh_idx) == 0:
        return {"ok": False}

    cutoff = h.index[-lookback]
    recent_peaks = [idx for idx in sh_idx if idx >= cutoff]
    candidates = recent_peaks if recent_peaks else list(sh_idx)
    peak_idx = h.loc[candidates].idxmax()
    peak_price = float(h.loc[peak_idx])
    if peak_price <= 0:
        return {"ok": False}

    after_peak_low = l.loc[peak_idx:]
    if after_peak_low.empty:
        return {"ok": False}
    trough_idx = after_peak_low.idxmin()
    trough_price = float(after_peak_low.min())

    cp = float(close.iloc[-1])
    drawdown_pct = (peak_price - trough_price) / peak_price * 100
    recovery_from_low_pct = (cp - trough_price) / trough_price * 100 if trough_price > 0 else 0
    healthy_depth = PULLBACK_MIN_PCT <= drawdown_pct <= PULLBACK_MAX_PCT

    after_trough_low = l.loc[trough_idx:]
    sl_after = find_swings(after_trough_low, order, "min")
    higher_low_after_trough = False
    if len(sl_after) >= 2:
        vals = after_trough_low.loc[sl_after]
        higher_low_after_trough = bool(vals.iloc[-1] > vals.iloc[-2])

    near_recent_high = cp >= float(h.tail(5).max()) * 0.98
    solid_bounce = recovery_from_low_pct >= 3.0

    is_recovering = solid_bounce or higher_low_after_trough or near_recent_high

    return {
        "ok": healthy_depth and is_recovering,
        "peak_price": peak_price, "peak_idx": peak_idx,
        "trough_price": trough_price, "trough_idx": trough_idx,
        "drawdown_pct": drawdown_pct, "recovery_from_low_pct": recovery_from_low_pct,
        "higher_low_after_trough": higher_low_after_trough,
        "near_recent_high": near_recent_high,
    }

# ============================================================
# 3) MOMENTUM
# ============================================================

def rsi_bullish_divergence(close, rsi, peak_idx, order=SWING_ORDER):
    try:
        seg_close = close.loc[peak_idx:]
        seg_rsi = rsi.loc[peak_idx:]
        if len(seg_close) < order * 2 + 3:
            return False
        lows_idx = find_swings(seg_close, order, "min")
        if len(lows_idx) < 2:
            return False
        low1, low2 = lows_idx[-2], lows_idx[-1]
        price_lower = seg_close.loc[low2] < seg_close.loc[low1]
        rsi_higher = seg_rsi.loc[low2] > seg_rsi.loc[low1]
        return bool(price_lower and rsi_higher)
    except Exception:
        return False


def macd_confirm(hist, macd_line, signal_line):
    if len(hist) < 6:
        return False
    accelerating = (hist.iloc[-1] - hist.iloc[-2]) > (hist.iloc[-2] - hist.iloc[-3])
    rising = hist.iloc[-1] > hist.iloc[-3]
    recent_cross = False
    for i in range(1, 5):
        if len(macd_line) > i + 1 and macd_line.iloc[-i] > signal_line.iloc[-i] and macd_line.iloc[-i - 1] <= signal_line.iloc[-i - 1]:
            recent_cross = True
            break
    return bool((rising and accelerating) or recent_cross)

# ============================================================
# 4) HACİM
# ============================================================

def volume_profile(volume, peak_idx, trough_idx):
    try:
        decline = volume.loc[peak_idx:trough_idx]
        recovery = volume.loc[trough_idx:]
        decline_shrank = False
        if len(decline) >= 4:
            mid = len(decline) // 2
            decline_shrank = decline.iloc[mid:].mean() < decline.iloc[:mid].mean()
        recovery_rising = False
        if len(recovery) >= 4:
            mid = len(recovery) // 2
            recovery_rising = recovery.iloc[mid:].mean() > recovery.iloc[:mid].mean()
        elif len(recovery) >= 2:
            recovery_rising = recovery.iloc[-1] > recovery.mean()
        return bool(decline_shrank), bool(recovery_rising)
    except Exception:
        return False, False

# ============================================================
# 5) RELATİF GÜÇ
# ============================================================

def relative_strength(close, xu100_close, lookback=RS_LOOKBACK):
    try:
        if xu100_close is None:
            return {"ok": True, "rs_change_pct": 0.0, "available": False}
        aligned = pd.concat([close, xu100_close], axis=1, join="inner")
        aligned.columns = ["stock", "xu100"]
        if len(aligned) < lookback + 5:
            return {"ok": True, "rs_change_pct": 0.0, "available": False}
        ratio = aligned["stock"] / aligned["xu100"]
        rs_now = float(ratio.iloc[-1])
        rs_before = float(ratio.iloc[-lookback])
        change_pct = (rs_now - rs_before) / rs_before * 100 if rs_before else 0.0
        return {"ok": bool(change_pct > 0), "rs_change_pct": change_pct, "available": True}
    except Exception:
        return {"ok": True, "rs_change_pct": 0.0, "available": False}

# ============================================================
# 6) CONFLUENCE (4 ana kategori + sıkışma bonusu)
# ============================================================

def evaluate_confluence(df, pullback):
    close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
    peak_idx, trough_idx = pullback["peak_idx"], pullback["trough_idx"]

    rsi = calc_rsi(close)
    macd_line, signal_line, hist = calc_macd(close)
    obv = calc_obv(close, volume)
    cmf = calc_cmf(df)

    checks = {}

    decline_shrank, recovery_rising = volume_profile(volume, peak_idx, trough_idx)
    avg20 = volume.iloc[-21:-1].mean()
    rvol = float(volume.iloc[-1] / avg20) if avg20 > 0 else 1.0
    cmf_positive = float(cmf.iloc[-1]) > 0
    checks["hacim"] = bool(decline_shrank and (recovery_rising or rvol >= 1.15 or cmf_positive))

    divergence = rsi_bullish_divergence(close, rsi, peak_idx)
    rsi_now = float(rsi.iloc[-1])
    rsi_turning = rsi.iloc[-1] > rsi.iloc[-3] > rsi.iloc[-5] if len(rsi) >= 6 else False
    checks["momentum"] = bool(divergence or (rsi_turning and 40 <= rsi_now <= 68))

    checks["macd"] = macd_confirm(hist, macd_line, signal_line)

    structure = hh_hl_structure(high, low)
    obv5 = obv.tail(5).mean()
    obv20 = obv.iloc[-21:-1].mean() if len(obv) >= 21 else obv5
    obv_confirms = obv5 > obv20
    checks["yapi"] = bool(structure["hl"] or obv_confirms)

    bbw = calc_bbw(close)
    squeeze = False
    recent_bbw = bbw.tail(BBW_LOOKBACK).dropna()
    if len(recent_bbw) >= 30 and not pd.isna(bbw.iloc[-1]):
        threshold = np.percentile(recent_bbw, BBW_SQUEEZE_PERCENTILE)
        squeeze = bool(bbw.iloc[-1] <= threshold)
    checks["sikisma"] = squeeze  # bonus niteliğinde, ana sayıma dahil değil

    confluence_count = sum(v for k, v in checks.items() if k != "sikisma")

    return {
        "checks": checks, "count": confluence_count, "rvol": rvol,
        "cmf": float(cmf.iloc[-1]), "divergence": divergence, "rsi": rsi_now,
        "decline_shrank": decline_shrank, "recovery_rising": recovery_rising,
        "squeeze": squeeze, "obv_confirms": obv_confirms,
    }

# ============================================================
# 7) DİRENÇ SEVİYELERİ
# ============================================================

def find_resistances(high, close, lookback=LOOKBACK_STRUCTURE, order=SWING_ORDER):
    h = high.tail(lookback)
    sh_idx = find_swings(h, order, "max")
    sh_vals = h.loc[sh_idx].sort_values()
    cp = float(close.iloc[-1])
    above = sh_vals[sh_vals > cp * 1.005]
    nearest = float(above.iloc[0]) if len(above) >= 1 else None
    second = float(above.iloc[1]) if len(above) >= 2 else None
    return nearest, second

# ============================================================
# 8) GİRİŞ / STOP / HEDEF SEVİYELERİ
# ============================================================

def calc_levels(df, pullback, resistances):
    close, high = df["Close"], df["High"]
    atr = float(calc_atr(df).iloc[-1])
    trough = pullback["trough_price"]

    entry_early_low = trough * 1.005
    entry_early_high = trough * 1.05

    # Yerel (kısa vadeli) tetik: son 3 günün zirvesinin hafif üzeri.
    # DİKKAT: bu, hissenin GERÇEK yapısal direncinden (aşağıdaki nearest_res)
    # tamamen farklı ve genelde çok daha yakın bir seviyedir. Bunu "büyük
    # kırılım" ile karıştırmamak için stage belirlerken ikisini AYRI ayrı
    # kontrol ediyoruz (bkz. determine_stage).
    recent_high = float(high.tail(3).max())
    cp = float(close.iloc[-1])
    entry_trigger = max(recent_high * 1.001, cp)

    atr_stop = entry_trigger - 1.5 * atr
    stop = min(trough * 0.985, atr_stop) if trough > 0 else atr_stop
    if stop >= entry_trigger:
        stop = entry_trigger - 1.5 * atr

    risk = entry_trigger - stop
    if risk <= 0:
        return None

    nearest_res, second_res = resistances
    target1 = nearest_res if (nearest_res and nearest_res > entry_trigger) else entry_trigger + 2 * risk
    target2 = second_res if (second_res and second_res > target1) else entry_trigger + 3 * risk

    rr1 = (target1 - entry_trigger) / risk
    rr2 = (target2 - entry_trigger) / risk

    return {
        "entry_early_low": entry_early_low, "entry_early_high": entry_early_high,
        "entry_trigger": entry_trigger, "stop": stop,
        "target1": target1, "target2": target2, "target1_is_real_resistance": nearest_res is not None,
        "risk_pct": (risk / entry_trigger) * 100, "rr1": rr1, "rr2": rr2,
    }

# ============================================================
# 9) PİYASA REJİMİ
# ============================================================

def market_regime_ok(xu100_df):
    if xu100_df is None or len(xu100_df) < 60:
        return True
    close = xu100_df["Close"]
    sma50 = close.rolling(50).mean()
    return float(close.iloc[-1]) > float(sma50.iloc[-1])

# ============================================================
# 10) SKOR (0-100)
# ============================================================

def compute_score(trend, pullback, confluence, rs, rr1):
    """
    DÜZELTME (v3): Önceki sürümde `checks` alt-sözlüğü içinde olmayan
    'decline_shrank' anahtarı aranıyordu, bu yüzden ara puan (50) hiçbir
    zaman verilmiyordu. Artık `confluence` sözlüğünün TAMAMI alınıyor,
    'decline_shrank' doğru yerden (üst seviyeden) okunuyor.
    """
    checks = confluence["checks"]

    trend_flags = [trend["above20"], trend["above50"], trend["above200"], trend["sma50_rising"],
                   trend["golden"], trend["weekly_ok"], trend["hh"], trend["hl"]]
    trend_score = 100 * sum(bool(x) for x in trend_flags) / len(trend_flags)

    ideal_mid = (PULLBACK_MIN_PCT + PULLBACK_MAX_PCT) / 2
    dist = abs(pullback["drawdown_pct"] - ideal_mid) / (PULLBACK_MAX_PCT - PULLBACK_MIN_PCT)
    pullback_score = max(0.0, 100 * (1 - dist))

    momentum_score = 100 if checks["momentum"] and checks["macd"] else (60 if (checks["momentum"] or checks["macd"]) else 25)

    # DÜZELTİLMİŞ satır: artık gerçekten 100/50/25 üç seviyeli çalışıyor.
    if checks["hacim"]:
        volume_score = 100
    elif confluence.get("decline_shrank"):
        volume_score = 50
    else:
        volume_score = 25

    structure_score = 100 if checks["yapi"] else 30
    squeeze_score = 100 if checks["sikisma"] else 40
    rs_score = max(0.0, min(100.0, 50 + rs.get("rs_change_pct", 0.0) * 5))

    raw = (
        trend_score * SCORE_WEIGHTS["trend"] +
        pullback_score * SCORE_WEIGHTS["pullback"] +
        momentum_score * SCORE_WEIGHTS["momentum"] +
        volume_score * SCORE_WEIGHTS["volume"] +
        structure_score * SCORE_WEIGHTS["structure"] +
        squeeze_score * SCORE_WEIGHTS["squeeze"] +
        rs_score * SCORE_WEIGHTS["relative_strength"]
    )
    rr_bonus = min(rr1, 4) * 2.5
    score = min(100.0, raw * 0.9 + rr_bonus)
    return round(score, 1)

# ============================================================
# 11) DURUM MAKİNESİ (v3 — düzeltilmiş)
# ============================================================
#
# DEĞİŞİKLİK ÖZETİ (önceki hatalara karşı):
#   1) Artık HİÇBİR "kırılım" aşaması (yerel ya da ana) strong_ok=False
#      iken verilemiyor. Önceki sürümde zayıf confluence/trend'e sahip
#      bir hisse, sırf fiyatı son 3 günün tepesini geçtiği için en
#      yüksek öncelikli "TRIGGER" etiketini alabiliyordu — bu artık
#      imkansız. strong_ok=False olan her aday en fazla WATCH'ta kalır.
#   2) Yerel (kısa vadeli, 3 günlük) kırılım ile gerçek yapısal direnç
#      kırılımı ARTIK AYRI aşamalar: LOCAL_BREAK (erken haber, orta
#      güven) ve MAIN_BREAK (yüksek güven). İkisi karıştırılmıyor.

def determine_stage(trend, pullback, confluence, levels, cp, structural_resistance):
    loose_ok = pullback["ok"] and confluence["count"] >= MIN_CONFLUENCE_WATCH
    if not loose_ok:
        return None

    strong_ok = trend["ok"] and confluence["count"] >= MIN_CONFLUENCE_STRONG and levels["rr1"] >= MIN_RR

    # Zayıf adaylar (strong_ok değil) fiyat ne yaparsa yapsın WATCH'ta kalır.
    if not strong_ok:
        return "WATCH"

    local_triggered = cp >= levels["entry_trigger"]
    structural_triggered = structural_resistance is not None and cp >= structural_resistance
    extended = structural_triggered and cp >= structural_resistance * (1 + BREAKOUT_EXTENDED_PCT / 100)

    if extended:
        return "EXTENDED"
    if structural_triggered:
        return "MAIN_BREAK"
    if local_triggered:
        return "LOCAL_BREAK"
    return "SETUP"

# ============================================================
# MESAJ OLUŞTURMA (v3 — Türkçe, kategorik, daha anlaşılır)
# ============================================================

STAGE_INFO = {
    "WATCH": {
        "baslik": "🔵 İZLEME LİSTESİ",
        "ozet": "Erken aşama, düşük güven. Sadece radarına girsin.",
        "detay": "Kriterlerin bir kısmı sağlanıyor ama trend/teyit tam değil. Aksiyon sinyali değildir.",
    },
    "SETUP": {
        "baslik": "🟠 KURULUM HAZIR",
        "ozet": "Trend ve teyitler güçlü, kırılım henüz yok.",
        "detay": "Tüm kriterler olumlu ama fiyat henüz hiçbir seviyeyi kırmadı. Aşağıdaki seviyeleri takip et.",
    },
    "LOCAL_BREAK": {
        "baslik": "🟡 ERKEN KIRILIM (Yerel)",
        "ozet": "Kısa vadeli bant kırıldı — erken bir ipucu.",
        "detay": ("Fiyat kendi kısa vadeli (3 günlük) bandını kırdı ve teyitler güçlü. "
                   "Ancak hisse HÂLÂ gerçek (uzun vadeli) direncinden uzak olabilir — "
                   "bu erken bir sinyal, ana kırılım değil. Temkinli değerlendir."),
    },
    "MAIN_BREAK": {
        "baslik": "🟢 ANA DİRENÇ KIRILDI",
        "ozet": "Fiyat, geçmişteki gerçek direnci geçti.",
        "detay": "Bu, sistemin en yüksek güvenilirlikli aşaması: fiyat, son 120 günün gerçek direncini kırdı.",
    },
    "EXTENDED": {
        "baslik": "🔴 AŞIRI UZAMIŞ",
        "ozet": "Kırılımdan bu yana fiyat belirgin uzaklaşmış.",
        "detay": "Ana direnç kırıldıktan sonra fiyat hızla uzaklaşmış. Kovalama riski yüksek, dikkatli ol.",
    },
}


def build_message(ticker, item):
    stage = item["stage"]
    info = STAGE_INFO[stage]
    c, l, tr, pb, rs = item["confluence"], item["levels"], item["trend"], item["pullback"], item["rs"]
    nearest_res, second_res = item["resistances"]

    checks_text = ", ".join([k for k, v in c["checks"].items() if v and k != "sikisma"]) or "yok"
    squeeze_text = " + sıkışma ✓" if c["checks"]["sikisma"] else ""
    rs_text = f"{rs['rs_change_pct']:+.1f}%" if rs.get("available") else "veri yetersiz"
    res_text = f"{nearest_res:.2f}" if nearest_res else "tespit edilemedi (veri penceresi dışında)"

    msg = (
        f"{info['baslik']}\n"
        f"_{info['ozet']}_\n"
        f"{market_session_label()}\n\n"

        f"📌 *HİSSE*\n"
        f"`{ticker}`  |  Güncel fiyat: *{item['close']:.2f} TL*\n\n"

        f"📊 *GENEL DURUM*\n"
        f"Skor: *{item['score']:.1f}/100*\n"
        f"Confluence (teyit): {c['count']}/4 → {checks_text}{squeeze_text}\n"
        f"{info['detay']}\n\n"

        f"📈 *TEKNİK GÖRÜNÜM*\n"
        f"• Trend: {'Tam onaylı ✅' if tr['ok'] else 'Kısmi ⚠️'} (Haftalık: {'✅' if tr['weekly_ok'] else '⚠️'})\n"
        f"• RSI: {c['rsi']:.1f}{' — bullish divergence ✓' if c['divergence'] else ''}\n"
        f"• MACD: {'Dönüş teyitli ↑' if c['checks']['macd'] else 'Henüz teyit yok'}\n"
        f"• Hacim/Para girişi: {'Olumlu ✓' if c['checks']['hacim'] else ('Kısmen olumlu' if c['decline_shrank'] else 'Zayıf')} (CMF: {c['cmf']:+.2f}, RVOL: {c['rvol']:.2f}x)\n"
        f"• BIST'e göre görece güç (20G): {rs_text}\n\n"

        f"🪜 *DÜZELTME BİLGİSİ*\n"
        f"Tepe: {pb['peak_price']:.2f} → Dip: {pb['trough_price']:.2f}  (düzeltme: %{pb['drawdown_pct']:.1f})\n"
        f"Dipten toparlanma: %{pb['recovery_from_low_pct']:.1f}"
        f"{' | Higher-low ✓' if pb['higher_low_after_trough'] else ''}\n\n"

        f"🎯 *SEVİYELER*\n"
        f"🟢 Erken giriş bölgesi (agresif, teyitsiz): {l['entry_early_low']:.2f} - {l['entry_early_high']:.2f}\n"
        f"🟡 Yerel kırılım seviyesi: {l['entry_trigger']:.2f}\n"
        f"🟢 Gerçek yapısal direnç: {res_text}\n"
        f"🛑 Stop: {l['stop']:.2f}  (-%{l['risk_pct']:.1f})\n"
        f"🎯 Hedef 1: {l['target1']:.2f}  (R/R {l['rr1']:.1f}){' [gerçek direnç]' if l['target1_is_real_resistance'] else ' [hesaplanmış]'}\n"
        f"🎯 Hedef 2: {l['target2']:.2f}  (R/R {l['rr2']:.1f})\n\n"

        f"⚠️ _Yatırım tavsiyesi değildir, teknik analiz özetidir. Skor ağırlıkları henüz backtest edilmedi._"
    )
    return msg

# ============================================================
# POZİSYON TAKİBİ (v4 — yeni)
# ============================================================
#
# SADECE gerçekten "tetiklenmiş" sinyaller takip edilir: LOCAL_BREAK,
# MAIN_BREAK, EXTENDED. WATCH ve SETUP takip edilmez — SETUP'ta henüz
# fiyat hiçbir seviyeyi kırmadığı için somut bir "giriş" yok, WATCH zaten
# "aksiyon sinyali değildir" diye işaretleniyor, başarısını ölçmek
# anlamsız olurdu.

TRACKED_STAGES = {"LOCAL_BREAK", "MAIN_BREAK", "EXTENDED"}


def build_target_hit_message(ticker, position, current_price):
    entry = position["entry"]
    gain_pct = (current_price - entry) / entry * 100 if entry > 0 else 0.0
    return (
        f"🎉🎯🎉 *HEDEFE ULAŞILDI!* 🎉🎯🎉\n\n"
        f"📌 *{ticker}*\n"
        f"Giriş: {entry:.2f} TL  →  Güncel: {current_price:.2f} TL\n"
        f"🎯 Hedef seviyesi ({position['target1']:.2f} TL) görüldü!\n\n"
        f"📈 *KAZANÇ: +%{gain_pct:.1f}*\n\n"
        f"_Bu sinyalin takibi burada kapatıldı._"
    )


def build_stop_hit_message(ticker, position, current_price):
    entry = position["entry"]
    loss_pct = (current_price - entry) / entry * 100 if entry > 0 else 0.0
    sign = "-" if loss_pct < 0 else ""
    return (
        f"🛑 *STOP SEVİYESİ TETİKLENDİ* 🛑\n\n"
        f"📌 *{ticker}*\n"
        f"Giriş: {entry:.2f} TL  →  Güncel: {current_price:.2f} TL\n"
        f"Stop seviyesi ({position['stop']:.2f} TL) tetiklendi.\n\n"
        f"📉 *ZARAR: {sign}%{abs(loss_pct):.1f}*\n\n"
        f"_Bu sinyalin takibi burada kapatıldı._"
    )


def check_open_positions(state, all_data):
    """
    Daha önce LOCAL_BREAK/MAIN_BREAK/EXTENDED ile açılmış (ve henüz
    kapanmamış) takipteki her hisse için, bu turun güncel kapanış
    fiyatına bakar. Hedefe ulaşmış ya da stop'a çarpmışsa özel bir
    bildirim gönderir ve takibi kapatır. İkisi de olmamışsa hiçbir şey
    göndermez, sessizce açık kalır.
    """
    closed = 0
    for ticker, info in list(state.items()):
        position = info.get("position")
        if not position:
            continue
        if ticker not in all_data:
            continue  # bu turda veri gelmedi, bir sonraki taramaya bırakılır

        try:
            current_price = float(all_data[ticker]["Close"].iloc[-1])
        except Exception:
            continue

        if current_price >= position["target1"]:
            send_telegram(build_target_hit_message(ticker, position, current_price))
            state[ticker]["position"] = None
            closed += 1
            time.sleep(0.5)
        elif current_price <= position["stop"]:
            send_telegram(build_stop_hit_message(ticker, position, current_price))
            state[ticker]["position"] = None
            closed += 1
            time.sleep(0.5)

    return closed

# ============================================================
# GÜNLÜK ÖZET (v4 — yeni)
# ============================================================

def build_summary_message(stage_counts, total_scanned, total_universe, open_positions_count):
    return (
        f"📊 *TARAMA ÖZETİ*\n"
        f"{market_session_label()}\n\n"
        f"🔍 Taranan: {total_scanned}/{total_universe} hisse\n\n"
        f"🟢 Ana Kırılım: {stage_counts.get('MAIN_BREAK', 0)}\n"
        f"🟡 Yerel Kırılım: {stage_counts.get('LOCAL_BREAK', 0)}\n"
        f"🔴 Aşırı Uzamış: {stage_counts.get('EXTENDED', 0)}\n"
        f"🟠 Kurulum Hazır: {stage_counts.get('SETUP', 0)}\n"
        f"🔵 İzleme: {stage_counts.get('WATCH', 0)}\n\n"
        f"📌 Şu an takip edilen açık sinyal: {open_positions_count}"
    )

# ============================================================
# ANA TARAMA
# ============================================================

def main():
    log.info("============================================")
    log.info("🧠 BIST TREND+PULLBACK+CONFLUENCE ENGINE v3")
    log.info("============================================")

    state = load_state()
    log.info(f"📊 Taranacak toplam hisse: {len(BIST_TUM_LISTESI)}")

    xu100_df = get_market_data()
    xu100_close = xu100_df["Close"] if xu100_df is not None else None
    regime_ok = market_regime_ok(xu100_df)
    log.info(f"🌍 Piyasa rejimi (XU100 > SMA50): {'UYGUN ✅' if regime_ok else 'ZAYIF ⚠️'}")

    log.info("📥 Veri toplu indiriliyor...")
    all_data = batch_download(BIST_TUM_LISTESI)
    success_rate = len(all_data) / len(BIST_TUM_LISTESI) if BIST_TUM_LISTESI else 0
    log.info(f"✅ {len(all_data)}/{len(BIST_TUM_LISTESI)} hisse için veri alındı ({success_rate:.0%}).")

    if success_rate < MIN_SUCCESS_RATE:
        send_telegram(
            "⚠️ *TARAMA ŞÜPHELİ*\n\n"
            f"Sadece {len(all_data)}/{len(BIST_TUM_LISTESI)} hisse için veri alınabildi ({success_rate:.0%}).\n"
            "Bu çalıştırmadaki sinyaller güvenilir olmayabilir."
        )
        log.warning("Veri başarı oranı düşük.")

    # --- v4 YENİ: önce açık takipteki pozisyonları kontrol et (hedef/stop) ---
    log.info("📌 Açık takipteki sinyaller kontrol ediliyor...")
    closed_count = check_open_positions(state, all_data)
    log.info(f"   {closed_count} takip kapatıldı (hedef/stop).")

    results = []

    for i, (ticker, df) in enumerate(all_data.items(), start=1):
        try:
            close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
            if close.iloc[-1] <= 0:
                continue

            turnover = close * volume
            if turnover.tail(5).mean() < MIN_TURNOVER_TL:
                continue

            trend = trend_filter(df)
            if not trend.get("above200"):
                continue

            pullback = detect_pullback(high, low, close)
            if not pullback["ok"]:
                continue

            confluence = evaluate_confluence(df, pullback)
            resistances = find_resistances(high, close)
            levels = calc_levels(df, pullback, resistances)
            if levels is None:
                continue

            rs = relative_strength(close, xu100_close)
            cp = float(close.iloc[-1])
            nearest_res, _ = resistances

            stage = determine_stage(trend, pullback, confluence, levels, cp, nearest_res)
            if stage is None:
                continue

            score = compute_score(trend, pullback, confluence, rs, levels["rr1"])

            results.append({
                "ticker": ticker, "close": cp, "score": score,
                "confluence": confluence, "pullback": pullback, "levels": levels,
                "trend": trend, "rs": rs, "stage": stage, "resistances": resistances,
            })

        except Exception:
            continue

        if i % 50 == 0:
            log.info(f"  ...{i} hisse analiz edildi")

    stage_order = {"MAIN_BREAK": 4, "LOCAL_BREAK": 3, "EXTENDED": 2, "SETUP": 1, "WATCH": 0}
    results.sort(key=lambda x: (stage_order[x["stage"]], x["score"]), reverse=True)

    sent_counts = {"MAIN_BREAK": 0, "LOCAL_BREAK": 0, "EXTENDED": 0, "SETUP": 0, "WATCH": 0}
    max_counts = {
        "MAIN_BREAK": MAX_MAIN_BREAK_ALERTS, "LOCAL_BREAK": MAX_LOCAL_BREAK_ALERTS,
        "EXTENDED": MAX_EXTENDED_ALERTS, "SETUP": MAX_SETUP_ALERTS, "WATCH": MAX_WATCH_ALERTS,
    }

    for item in results:
        stage = item["stage"]
        if sent_counts[stage] >= max_counts[stage]:
            continue

        prev = get_previous_state(state, item["ticker"])
        stage_changed = prev is None or prev.get("stage") != stage
        score_improved = prev is not None and item["score"] >= (prev.get("score") or 0) + 8
        should_notify = stage_changed or score_improved

        if should_notify:
            msg = build_message(item["ticker"], item)
            send_telegram(msg)
            sent_counts[stage] += 1
            time.sleep(0.5)

            # v4 YENİ: sadece gerçekten tetiklenmiş (LOCAL_BREAK/MAIN_BREAK/EXTENDED)
            # ve YENİ gönderilen bir sinyal için takip pozisyonu aç/değiştir.
            # should_notify=False olan (yani mesaj gönderilmeyen, sadece aynı
            # aşamada kalan) durumlarda ESKİ pozisyon dokunulmadan kalır.
            if stage in TRACKED_STAGES:
                l = item["levels"]
                new_position = {
                    "entry": l["entry_trigger"], "stop": l["stop"],
                    "target1": l["target1"], "target2": l["target2"],
                    "opened_date": datetime.now().strftime("%Y-%m-%d"),
                }
                update_state(state, item["ticker"], stage, item["score"],
                             item["confluence"]["rvol"], item["close"], position=new_position)
                continue  # update_state zaten çağrıldı, aşağıdaki genel çağrıyı atla

        update_state(state, item["ticker"], stage, item["score"], item["confluence"]["rvol"], item["close"])

    # --- v4 YENİ: günlük özet mesajı (her taramada gönderilir, sessizlik ile arıza ayrımı için) ---
    stage_counts_all = {}
    for item in results:
        stage_counts_all[item["stage"]] = stage_counts_all.get(item["stage"], 0) + 1
    open_positions_count = sum(1 for v in state.values() if v.get("position"))
    summary_msg = build_summary_message(stage_counts_all, len(all_data), len(BIST_TUM_LISTESI), open_positions_count)
    send_telegram(summary_msg)

    save_state(state)

    log.info("============================================")
    log.info("✅ TARAMA TAMAMLANDI")
    log.info(f"📊 Eşleşen aday: {len(results)} | Gönderilen: {sent_counts}")
    log.info("============================================")

    if results:
        log.info("🏆 EN GÜÇLÜ ADAYLAR:")
        for item in results[:15]:
            log.info(f"{item['ticker']:12} | {item['stage']:12} | Skor {item['score']:5.1f} | "
                     f"Confluence {item['confluence']['count']}/4 | R/R {item['levels']['rr1']:.1f}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Tarama beklenmedik şekilde çöktü")
        send_telegram(f"🔴 *BOT ÇÖKTÜ*\n\n`{str(e)[:300]}`\n\nGitHub Actions loglarını kontrol edin.")
        raise
