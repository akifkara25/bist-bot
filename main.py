import os
import time
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

# Ana likidite filtresi
MIN_TURNOVER_TL = 15_000_000

# SQLite
DB_FILE = "signals_v8_behavior.db"

# Kaç hisse Telegram'a gönderilecek?
MAX_ALERTS = 10

# ============================================================
# BIST TÜM LİSTESİ (Tam ve Yahoo Uyumlu ~500 Hisse)
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

BIST_TUM_LISTESI = sorted(
    list(
        set(
            ticker.strip().upper()
            for ticker in _raw_bist_list
            if ticker and ticker.strip()
        )
    )
)


# ============================================================
# DATABASE
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_state (
            ticker TEXT PRIMARY KEY,
            last_tier TEXT,
            last_score REAL,
            last_pct5d REAL,
            last_rvol REAL,
            last_rsi REAL,
            last_hist REAL,
            last_behavior_score REAL,
            last_early_score REAL,
            last_close REAL,
            last_date TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_previous_state(ticker):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            last_tier, last_score, last_pct5d, last_rvol, last_rsi,
            last_hist, last_behavior_score, last_early_score, last_close, last_date
        FROM stock_state
        WHERE ticker = ?
    """, (ticker,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "tier": row[0],
        "score": row[1],
        "pct5d": row[2],
        "rvol": row[3],
        "rsi": row[4],
        "hist": row[5],
        "behavior": row[6],
        "early": row[7],
        "close": row[8],
        "date": row[9]
    }


def update_state(ticker, data):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO stock_state (
            ticker, last_tier, last_score, last_pct5d, last_rvol, last_rsi,
            last_hist, last_behavior_score, last_early_score, last_close, last_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker,
        data["tier"],
        data["score"],
        data["pct5d"],
        data["rvol"],
        data["rsi"],
        data["hist"],
        data["behavior_score"],
        data["early_score"],
        data["close"],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            return True
    except Exception:
        pass
    return False


# ============================================================
# DATA TEMİZLEME & STANDARTLAŞTIRMA
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
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

        # Sütun isimlerini standardize et (Büyük harfe çevir)
        df.columns = [str(col).capitalize() for col in df.columns]

        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required):
            return None

        df = df[required].copy()
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna()
        if df.empty:
            return None

        return df
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
    histogram = macd - signal
    return macd, signal, histogram


def calc_bollinger(close, period=20):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + (std * 2)
    lower = sma - (std * 2)
    width = (upper - lower) / sma
    return upper, lower, width


def calc_obv(close, volume):
    direction = np.where(close > close.shift(1), volume, np.where(close < close.shift(1), -volume, 0))
    return pd.Series(direction, index=close.index).cumsum()


def calc_atr(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def get_market_data():
    try:
        df = yf.download(
            "XU100.IS", period="1y", interval="1d",
            progress=False, auto_adjust=False, threads=False
        )
        df = clean_df(df)
        return df["Close"] if df is not None else None
    except Exception:
        return None


# ============================================================
# ANALİZ MODÜLLERİ
# ============================================================

def detect_higher_lows(low_series):
    if len(low_series) < 15:
        return False
    lows = low_series.tail(15).values
    swing_lows = [lows[i] for i in range(1, len(lows) - 1) if lows[i] < lows[i - 1] and lows[i] <= lows[i + 1]]
    if len(swing_lows) < 2:
        return False
    return swing_lows[-1] > swing_lows[-2]


def volume_analysis(volume):
    if len(volume) < 25:
        return {"rvol": 1.0, "vol_3d": 1.0, "vol_growth": False, "volume_score": 0}

    avg20 = volume.iloc[-21:-1].mean()
    if avg20 <= 0:
        return {"rvol": 1.0, "vol_3d": 1.0, "vol_growth": False, "volume_score": 0}

    rvol = volume.iloc[-1] / avg20
    vol_3d_avg = volume.tail(3).mean()
    vol_3d = vol_3d_avg / avg20
    last4 = volume.tail(4).values / avg20
    rising_count = sum(1 for i in range(1, len(last4)) if last4[i] > last4[i - 1])

    volume_score = 0
    if rvol >= 1.8: volume_score += 10
    elif rvol >= 1.5: volume_score += 8
    elif rvol >= 1.3: volume_score += 6
    elif rvol >= 1.15: volume_score += 4

    if vol_3d >= 1.5: volume_score += 7
    elif vol_3d >= 1.25: volume_score += 5
    elif vol_3d >= 1.10: volume_score += 3

    if rising_count >= 3: volume_score += 8
    elif rising_count >= 2: volume_score += 5
    elif rising_count >= 1 and rvol > 1.2: volume_score += 3

    volume_score = min(volume_score, 25)
    vol_growth = (vol_3d >= 1.10 and (rising_count >= 2 or rvol >= 1.3))

    return {"rvol": float(rvol), "vol_3d": float(vol_3d), "vol_growth": vol_growth, "volume_score": volume_score}


def rsi_analysis(rsi):
    if len(rsi) < 8:
        return {"score": 0, "improving": False, "acceleration": 0}

    r1, r2, r3 = float(rsi.iloc[-5]), float(rsi.iloc[-3]), float(rsi.iloc[-1])
    acceleration = r3 - r1
    improving = (r3 > r2 > r1)

    score = 0
    if improving:
        if 45 <= r3 <= 65: score = 15
        elif 40 <= r3 <= 70: score = 11
        elif r3 < 75: score = 7
    elif acceleration > 4:
        score = 5

    return {"score": score, "improving": improving, "acceleration": acceleration}


def macd_analysis(hist):
    if len(hist) < 8:
        return {"score": 0, "accelerating": False}

    h1, h2, h3 = float(hist.iloc[-5]), float(hist.iloc[-3]), float(hist.iloc[-1])
    accelerating = (h3 > h2 > h1)

    score = 0
    if accelerating:
        if h3 > 0 and h1 < h3: score = 12
        elif h3 >= 0: score = 10
        else: score = 7
    elif h3 > h2:
        score = 4

    return {"score": score, "accelerating": accelerating}


def obv_analysis(obv):
    if len(obv) < 25:
        return {"score": 0, "rising": False, "leading": False}

    obv5 = obv.tail(5).mean()
    obv20 = obv.iloc[-21:-1].mean()
    rising = obv5 > obv20
    slope = obv.iloc[-1] - obv.iloc[-6]
    rising_slope = slope > 0

    score = 0
    if rising and rising_slope: score = 10
    elif rising: score = 6
    elif rising_slope: score = 4

    return {"score": score, "rising": rising, "leading": rising_slope}


def bollinger_analysis(bb_width):
    if len(bb_width) < 65:
        return {"score": 0, "expanding": False, "squeeze": False, "percentile": 50}

    recent = bb_width.tail(60)
    current = float(bb_width.iloc[-1])
    percentile = recent.rank(pct=True).iloc[-1] * 100
    previous = float(bb_width.iloc[-2])
    expanding = current > previous
    squeeze = percentile <= 30
    strong_expansion = (expanding and current > float(bb_width.iloc[-3]))

    score = 0
    if squeeze and strong_expansion: score = 8
    elif squeeze and expanding: score = 6
    elif strong_expansion: score = 4
    elif expanding: score = 2

    return {"score": score, "expanding": expanding, "squeeze": squeeze, "percentile": percentile}


def relative_strength_analysis(close, xu100_close):
    if xu100_close is None:
        return {"score": 0, "excess5": 0, "excess20": 0, "excess60": 0}

    try:
        aligned = xu100_close.reindex(close.index).ffill()
        if len(aligned.dropna()) < 65:
            return {"score": 0, "excess5": 0, "excess20": 0, "excess60": 0}

        stock5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100
        bist5 = (aligned.iloc[-1] / aligned.iloc[-6] - 1) * 100
        stock20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100
        bist20 = (aligned.iloc[-1] / aligned.iloc[-21] - 1) * 100
        stock60 = (close.iloc[-1] / close.iloc[-61] - 1) * 100
        bist60 = (aligned.iloc[-1] / aligned.iloc[-61] - 1) * 100

        excess5, excess20, excess60 = stock5 - bist5, stock20 - bist20, stock60 - bist60
        score = 0
        if excess5 >= 8: score += 6
        elif excess5 >= 4: score += 4
        elif excess5 >= 1: score += 2

        if excess20 >= 10: score += 5
        elif excess20 >= 5: score += 3
        elif excess20 >= 2: score += 2

        if excess60 >= 15: score += 4
        elif excess60 >= 8: score += 3
        elif excess60 >= 3: score += 1

        return {"score": min(score, 15), "excess5": excess5, "excess20": excess20, "excess60": excess60}
    except Exception:
        return {"score": 0, "excess5": 0, "excess20": 0, "excess60": 0}


def price_timing_score(pct5d):
    if pct5d < -2: return 0
    if pct5d < 0: return 2
    if pct5d < 2: return 7
    if pct5d < 3: return 10
    if pct5d < 5: return 12
    if pct5d < 7: return 10
    if pct5d < 10: return 8
    if pct5d < 15: return 5
    if pct5d < 20: return 2
    return 0


def calculate_behavior_score(volume_data, rsi_data, macd_data, obv_data, higher_lows, bb_data, rel_data, previous_state, pct5d):
    score = 0
    score += volume_data["volume_score"] * 0.30
    score += rsi_data["score"] * 0.25
    score += macd_data["score"] * 0.20
    score += obv_data["score"] * 0.15
    if higher_lows: score += 6
    score += bb_data["score"] * 0.35
    score += rel_data["score"] * 0.20

    if previous_state:
        if previous_state.get("rsi") is not None and rsi_data["acceleration"] > 3: score += 3
        if previous_state.get("rvol") is not None and volume_data["rvol"] > previous_state["rvol"] + 0.20: score += 4
        if previous_state.get("score") is not None and score > previous_state["score"] + 5: score += 4

    if pct5d > 0: score += 3
    if pct5d >= 3: score += 2

    return max(0, min(100, round(score, 1)))


def calculate_early_score(pct5d, volume_data, rsi_data, macd_data, obv_data, higher_lows, bb_data, rel_data, dist_res, atr_expanding):
    score = 0
    score += price_timing_score(pct5d)
    score += volume_data["volume_score"] * 0.80
    score += rsi_data["score"] * 0.70
    score += macd_data["score"] * 0.60
    score += obv_data["score"] * 0.70
    if higher_lows: score += 8
    score += bb_data["score"]
    score += rel_data["score"] * 0.50

    if 0 <= dist_res <= 2: score += 8
    elif 2 < dist_res <= 4: score += 6
    elif 4 < dist_res <= 7: score += 4
    elif 7 < dist_res <= 12: score += 2

    if atr_expanding: score += 4

    return max(0, min(100, round(score, 1)))


# ============================================================
# ANA TARAMA
# ============================================================

def main():
    print("\n============================================")
    print("🧠 BIST V8 BEHAVIOR ENGINE (500+ HİSSE)")
    print("============================================\n")

    init_db()
    if not BIST_TUM_LISTESI:
        print("❌ BIST_TUM_LISTESI boş.")
        return

    print(f"📊 Taranacak toplam hisse sayısı: {len(BIST_TUM_LISTESI)}")
    xu100_close = get_market_data()
    results = []

    for index, ticker in enumerate(BIST_TUM_LISTESI, start=1):
        try:
            print(f"[{index}/{len(BIST_TUM_LISTESI)}] {ticker} taranıyor...")
            df = yf.download(
                ticker, period="1y", interval="1d",
                progress=False, auto_adjust=False, threads=False
            )
            df = clean_df(df)
            if df is None or len(df) < 70:
                continue

            c, v, h, l = df["Close"], df["Volume"], df["High"], df["Low"]
            if c.iloc[-1] <= 0 or v.tail(20).mean() <= 0:
                continue

            # Likidite filtresi
            turnover = c * v
            if turnover.tail(5).mean() < MIN_TURNOVER_TL:
                continue

            # Pandas yerleşik pct_change ile güvenli 5 günlük getiri
            pct5d = float(c.pct_change(periods=5).iloc[-1]) * 100
            if pct5d < -10:
                continue

            cp = float(c.iloc[-1])

            # İndikatörler
            rsi = calc_rsi(c)
            _, _, hist = calc_macd(c)
            _, _, bb_width = calc_bollinger(c)
            obv = calc_obv(c, v)
            atr = calc_atr(df)

            rsi_data = rsi_analysis(rsi)
            macd_data = macd_analysis(hist)
            volume_data = volume_analysis(v)
            obv_data = obv_analysis(obv)
            bb_data = bollinger_analysis(bb_width)
            higher_lows = detect_higher_lows(l)

            atr_expanding = False
            if len(atr) >= 25:
                atr_now = float(atr.iloc[-1])
                atr_avg = float(atr.iloc[-21:-1].mean())
                if atr_avg > 0:
                    atr_expanding = atr_now > atr_avg * 1.05

            resistance_window = h.iloc[-21:-1]
            if resistance_window.empty:
                continue
            resistance = float(resistance_window.max())
            if resistance <= 0:
                continue

            dist_res = ((resistance - cp) / cp) * 100
            rel_data = relative_strength_analysis(c, xu100_close)
            previous_state = get_previous_state(ticker)

            early_score = calculate_early_score(
                pct5d, volume_data, rsi_data, macd_data, obv_data,
                higher_lows, bb_data, rel_data, dist_res, atr_expanding
            )
            behavior_score = calculate_behavior_score(
                volume_data, rsi_data, macd_data, obv_data,
                higher_lows, bb_data, rel_data, previous_state, pct5d
            )

            final_score = round(max(0, min(100, (behavior_score * 0.60 + early_score * 0.40))), 1)
            rvol = volume_data["rvol"]
            breakout = (cp > resistance and rvol >= 1.40)

            if breakout:
                tier = "🚀 BREAKOUT / GÜÇLÜ HAREKET"
            elif (
                final_score >= 74 and behavior_score >= 68 and pct5d > 0 and
                volume_data["vol_3d"] >= 1.05 and (rsi_data["improving"] or macd_data["accelerating"] or higher_lows)
            ):
                tier = "🟡 HAREKET BAŞLADI"
            elif final_score >= 57 and behavior_score >= 50:
                tier = "🟢 KIPIRDANMA"
            else:
                continue

            score_change = (final_score - previous_state["score"]) if (previous_state and previous_state["score"] is not None) else 0

            results.append({
                "ticker": ticker,
                "tier": tier,
                "score": final_score,
                "behavior_score": behavior_score,
                "early_score": early_score,
                "pct5d": pct5d,
                "rvol": rvol,
                "vol_3d": volume_data["vol_3d"],
                "rsi": float(rsi.iloc[-1]),
                "rsi_acceleration": rsi_data["acceleration"],
                "hist": float(hist.iloc[-1]),
                "higher_lows": higher_lows,
                "obv_rising": obv_data["rising"],
                "obv_leading": obv_data["leading"],
                "bb_expanding": bb_data["expanding"],
                "bb_squeeze": bb_data["squeeze"],
                "dist_res": dist_res,
                "excess5": rel_data["excess5"],
                "excess20": rel_data["excess20"],
                "atr_expanding": atr_expanding,
                "close": cp
            })

            # Yahoo rate-limit koruması için optimize edilmiş uyku süresi
            time.sleep(0.04)

        except Exception:
            continue

    tier_priority = {
        "🚀 BREAKOUT / GÜÇLÜ HAREKET": 3,
        "🟡 HAREKET BAŞLADI": 2,
        "🟢 KIPIRDANMA": 1
    }

    results.sort(key=lambda x: (tier_priority.get(x["tier"], 0), x["score"], x["behavior_score"]), reverse=True)

    sent_count = 0
    for item in results:
        if sent_count >= MAX_ALERTS:
            break

        previous = get_previous_state(item["ticker"])
        should_notify = False

        if previous is None:
            should_notify = True
        else:
            old_tier = previous["tier"]
            old_score = previous["score"] if previous["score"] is not None else 0
            old_rvol = previous["rvol"] if previous["rvol"] is not None else 1

            new_priority = tier_priority.get(item["tier"], 0)
            old_priority = tier_priority.get(old_tier, 0)

            if new_priority > old_priority:
                should_notify = True
            elif item["score"] >= old_score + 6:
                should_notify = True
            elif item["rvol"] >= old_rvol + 0.35:
                should_notify = True

        if should_notify:
            if item["tier"].startswith("🚀"):
                header = "🚨 *GÜÇLÜ HAREKET / BREAKOUT*"
            elif item["tier"].startswith("🟡"):
                header = "⚡ *HAREKET BAŞLADI*"
            else:
                header = "👀 *KIPIRDANMA TESPİT EDİLDİ*"

            bb_text = "Sıkışma → genişleme" if item["bb_squeeze"] else ("Genişliyor ↗" if item["bb_expanding"] else "Normal")
            hl_text = "Higher-Low ✓" if item["higher_lows"] else "Nötr"
            obv_text = "Önden para girişi ✓" if item["obv_leading"] else ("Yükseliyor ↗" if item["obv_rising"] else "Nötr")

            message = (
                f"{header}\n\n"
                f"📌 *Hisse:* `{item['ticker']}`\n"
                f"🎯 *Final Score:* {item['score']:.1f}/100\n"
                f"🧠 *Behavior Score:* {item['behavior_score']:.1f}/100\n"
                f"🚀 *Early Score:* {item['early_score']:.1f}/100\n\n"
                f"💰 *Fiyat:* {item['close']:.2f}\n"
                f"📈 *5G Değişim:* %{item['pct5d']:.1f}\n"
                f"📊 *RVOL:* {item['rvol']:.2f}x\n"
                f"📊 *3G Hacim / 20G:* {item['vol_3d']:.2f}x\n\n"
                f"📉 *RSI:* {item['rsi']:.1f}\n"
                f"⚡ *RSI İvmesi:* {item['rsi_acceleration']:+.1f}\n"
                f"🌊 *MACD:* {'İvme artıyor ↑' if item['hist'] > 0 else 'Negatif'}\n"
                f"💰 *OBV:* {obv_text}\n"
                f"🔺 *Yapı:* {hl_text}\n"
                f"🌪️ *Bollinger:* {bb_text}\n\n"
                f"📐 *Dirence Mesafe:* %{item['dist_res']:.1f}\n"
                f"📊 *BIST'e Göre RS:* {item['excess5']:+.1f}% / {item['excess20']:+.1f}%\n"
                f"🔥 *ATR:* {'Genişliyor' if item['atr_expanding'] else 'Normal'}\n\n"
                f"🧠 *Yorum:* "
            )

            if item["tier"].startswith("🚀"):
                message += "Fiyat önceki direnci aşmış ve hacim destekli güçlü hareket oluşmuş durumda."
            elif item["tier"].startswith("🟡"):
                message += "Hissenin davranışında belirgin değişim var. Hacim/ivme/fiyat yapısı hareketin başladığını gösteriyor."
            else:
                message += "Henüz güçlü breakout yok; ancak hacim, momentum veya fiyat yapısında erken uyanış belirtileri oluşuyor."

            send_telegram(message)
            sent_count += 1
            time.sleep(0.5)

        update_state(item["ticker"], item)

    print("\n============================================")
    print("✅ TARAMA TAMAMLANDI")
    print("============================================")
    print(f"📊 Eşleşen Aday Sayısı: {len(results)}")
    print(f"📨 Telegram'a Gönderilen: {sent_count}")

    if results:
        print("\n🏆 EN GÜÇLÜ ADAYLAR:\n")
        for item in results[:15]:
            print(
                f"{item['ticker']:12} | "
                f"{item['tier']:30} | "
                f"Score {item['score']:5.1f} | "
                f"Behavior {item['behavior_score']:5.1f} | "
                f"5G %{item['pct5d']:6.1f} | "
                f"RVOL {item['rvol']:.2f}"
            )
    else:
        print("⚠️ Uygun davranış değişimi bulunamadı.")


if __name__ == "__main__":
    main()
