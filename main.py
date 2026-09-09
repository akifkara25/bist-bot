import os
import time
import json
import logging
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone
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
MAX_WATCH_ALERTS = 3         # İzleme: sadece EN YÜKSEK SKORLU 3 tanesi mesaj alır, gerisi özette listelenir
MAX_WATCH_IN_SUMMARY = 15    # Günlük özette en fazla kaç izleme hissesi ismen yazılsın
POSITION_TIMEOUT_DAYS = 40   # Bir takip ne hedefe ne stop'a ulaşmadan bu kadar gün geçerse zaman aşımıyla kapatılır

# --- Veri kalitesi eşikleri ---
MAX_STALE_DAYS = 5
MIN_SUCCESS_RATE = 0.6
# İlk turda alınamayan hisseler için ikinci tur ayarları. Yahoo yoğun istekte
# sessizce boş veri döndürebiliyor; daha küçük grup + daha uzun bekleme bunu
# büyük ölçüde telafi eder.
RETRY_BATCH_SIZE = 15
RETRY_SLEEP_SECONDS = 4.0
MAX_DAILY_JUMP_PCT = 60.0

# --- Confluence eşikleri (4 ana kategori üzerinden) ---
MIN_CONFLUENCE_STRONG = 3
MIN_CONFLUENCE_WATCH = 2
MIN_RR = 1.3
# WATCH için ayrı (daha gevşek ama SIFIR OLMAYAN) bir R/R tabanı. Bu olmadan
# sistem R/R 0.1 gibi finansal olarak anlamsız ("1 lira riske at, 10 kuruş
# kazan") sinyalleri de listeliyordu -- stres testinde tespit edildi.
MIN_RR_WATCH = 1.0
# Yapısal stop (düzeltme dibinin altı) girişten bu orandan daha uzaktaysa,
# sinyal TAMAMEN elenir. Gerçek state.json verisinde stop'un girişin %43.8
# altında kaldığı bir pozisyon (NETAS) tespit edildikten sonra eklendi:
# fiyat düzeltme dibinden çok uzaklaşmışsa, yapısal stop orantısız uzak
# kalıyor ve hem risk hem de ondan türeyen hedef gerçekçiliğini yitiriyor.
# Stop'u yapay olarak yakınlaştırmak yerine sinyali elemeyi seçiyoruz --
# çünkü dibin üstüne çekilen bir stop, dayandığı yapısal mantığı kaybeder.
MAX_RISK_PCT = 20.0
# Bir direnç seviyesinin "Hedef 1" olarak kullanılabilmesi için, alınan riske
# göre en az bu oranda kazanç sunması gerekir. Altında kalırsa o direnç
# atlanır (bir sonrakine ya da hesaplanmış hedefe geçilir). Bkz. calc_levels.
MIN_TARGET_RR_RATIO = 1.0
# UYUMSUZLUK (divergence) puan etkileri. Bunlar sinyal KAPILARINI değiştirmez
# (bir hissenin sinyal olup olmayacağını etkilemez), sadece skoru düzenler.
DIV_BULL_BONUS = 4.0     # her pozitif uyumsuzluk (RSI ve MACD ayrı ayrı) puan ekler
DIV_BEAR_PENALTY = 5.0   # her negatif uyumsuzluk puan kırar (bilerek daha ağır)

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
    trt_now = datetime.now(timezone.utc) + timedelta(hours=3)
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
    """
    Telegram'a mesaj gönderir. 429 (rate-limit) ve geçici sunucu hatalarında
    TEKRAR DENER -- eskiden denemiyordu ve rate-limit'e takılan mesaj sessizce
    KAYBOLUYORDU (ör. hedefe ulaşma bildirimi hiç gelmeyebilirdi).
    Kalıcı hatalarda (400 gibi, bozuk Markdown) tekrar denemek anlamsızdır,
    hemen vazgeçilir.
    """
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}

    for deneme in range(1, TELEGRAM_MAX_RETRIES + 1):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                return True

            if r.status_code == 429:
                bekle = 5
                try:
                    bekle = int(r.json().get("parameters", {}).get("retry_after", 5))
                except Exception:
                    pass
                bekle = max(1, min(bekle, 60))   # 1-60 sn arasında tut
                log.warning(f"Telegram rate-limit (429), {bekle}sn bekleniyor "
                            f"(deneme {deneme}/{TELEGRAM_MAX_RETRIES})")
                time.sleep(bekle)
                continue

            if 500 <= r.status_code < 600:
                log.warning(f"Telegram sunucu hatası ({r.status_code}), tekrar denenecek "
                            f"(deneme {deneme}/{TELEGRAM_MAX_RETRIES})")
                time.sleep(3 * deneme)
                continue

            # 400 vb. kalıcı hata -> tekrar denemek anlamsız
            log.error(f"Telegram gönderim hatası ({r.status_code}): {r.text[:300]}")
            return False

        except Exception as e:
            log.error(f"Telegram gönderim istisnası (deneme {deneme}/{TELEGRAM_MAX_RETRIES}): {e}")
            if deneme < TELEGRAM_MAX_RETRIES:
                time.sleep(3 * deneme)

    log.error("Telegram mesajı tüm denemelere rağmen gönderilemedi.")
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
    # NOT: last_date tz-aware gelirse (.replace(tzinfo=None)) saat dilimi
    # DÖNÜŞÜMÜ yapmadan direkt siliyoruz -- bu birkaç saatlik bir yaklaşıklık
    # yaratabilir. Gerçek yfinance çıktısıyla test edilemediği için (bu ortamda
    # ağ erişimi yok) bilerek DOKUNULMADI: MAX_STALE_DAYS=5 günlük tampon payı,
    # birkaç saatlik bu farkı zaten fazlasıyla yutuyor, pratik bir etkisi yok.
    if (datetime.now() - last_date.replace(tzinfo=None)) > timedelta(days=MAX_STALE_DAYS):
        return False, f"veri çok eski ({last_date.date()})"
    daily_change = df["Close"].pct_change().abs()
    if (daily_change > MAX_DAILY_JUMP_PCT / 100).tail(LOOKBACK_SWING).any():
        return False, "şüpheli tek günlük sıçrama"
    if (df["Close"] <= 0).any() or (df["Volume"] < 0).any():
        return False, "geçersiz fiyat/hacim"
    return True, "ok"


def batch_download(tickers, batch_size=40, retries=3, sleep_between=1.5):
    """
    TEŞHİS EKLENDİ: Eskiden elenen hisseler SESSİZCE atlanıyordu (log.debug
    seviyesinde, yani GitHub Actions logunda hiç görünmüyordu). Bir taramada
    466 hisseden sadece 22'si alınabildiğinde neden olduğunu anlamak imkansızdı.
    Artık her eleme sebebi sayılıyor ve tarama sonunda özet olarak yazılıyor.

    İKİNCİ TUR: İlk turda alınamayan hisseler, daha küçük gruplar ve daha uzun
    beklemeyle yeniden denenir. Yahoo yoğunlukta sessizce boş veri döndürebiliyor;
    ikinci tur bunu büyük ölçüde telafi eder.
    """
    all_data = {}
    sebepler = {"bos_veri": 0, "kisa_gecmis": 0, "kalite_reddi": 0, "istisna": 0}
    kalite_detay = {}

    def _grubu_isle(batch, data):
        for t in batch:
            try:
                sub = data[t] if len(batch) > 1 else data
                cdf = clean_df(sub)
                if cdf is None:
                    sebepler["bos_veri"] += 1
                    continue
                if len(cdf) < 70:
                    sebepler["kisa_gecmis"] += 1
                    continue
                ok, reason = data_quality_check(cdf)
                if not ok:
                    sebepler["kalite_reddi"] += 1
                    kalite_detay[reason] = kalite_detay.get(reason, 0) + 1
                    continue
                all_data[t] = cdf
            except Exception:
                sebepler["istisna"] += 1
                continue

    def _tur(liste, bsize, bekleme, etiket):
        gruplar = [liste[i:i + bsize] for i in range(0, len(liste), bsize)]
        for bi, batch in enumerate(gruplar, start=1):
            log.info(f"  {etiket} {bi}/{len(gruplar)} indiriliyor ({len(batch)} hisse)...")
            attempt = 0
            while attempt < retries:
                try:
                    data = yf.download(
                        tickers=batch, period="1y", interval="1d",
                        group_by="ticker", progress=False, auto_adjust=True,
                        threads=True
                    )
                    _grubu_isle(batch, data)
                    break
                except Exception as e:
                    attempt += 1
                    log.warning(f"Grup hata (deneme {attempt}/{retries}): {e}")
                    time.sleep(bekleme * attempt)
            time.sleep(bekleme)

    # 1. TUR
    _tur(tickers, batch_size, sleep_between, "Grup")

    # 2. TUR: eksik kalanları daha yavaş ve küçük gruplarla yeniden dene
    eksik = [t for t in tickers if t not in all_data]
    if eksik and len(eksik) > len(tickers) * 0.10:
        log.warning(f"⚠️ {len(eksik)} hisse alınamadı, ikinci tur deneniyor "
                    f"(daha küçük grup, daha uzun bekleme)...")
        onceki_sebepler = dict(sebepler)
        _tur(eksik, RETRY_BATCH_SIZE, RETRY_SLEEP_SECONDS, "Tekrar")
        kazanilan = len(tickers) - len(all_data)
        log.info(f"   İkinci tur sonrası hâlâ eksik: {kazanilan}")

    # TEŞHİS ÖZETİ -- neden elendiklerini görünür kılar
    toplam_elenen = len(tickers) - len(all_data)
    if toplam_elenen > 0:
        log.warning(f"📋 Eleme sebepleri (toplam {toplam_elenen} hisse alınamadı):")
        log.warning(f"    Boş/geçersiz veri (Yahoo veri döndürmedi) : {sebepler['bos_veri']}")
        log.warning(f"    70 günden az geçmiş                       : {sebepler['kisa_gecmis']}")
        log.warning(f"    Kalite kontrolünden geçemedi              : {sebepler['kalite_reddi']}")
        for r, adet in sorted(kalite_detay.items(), key=lambda x: -x[1]):
            log.warning(f"        └─ {r}: {adet}")
        log.warning(f"    İşleme sırasında istisna                  : {sebepler['istisna']}")

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
    rsi = 100 - (100 / (1 + rs))

    # UÇ DURUM DÜZELTMESİ: avg_loss == 0 iken (hiç düşüş günü yok) yukarıdaki
    # bölme NaN üretiyordu -- oysa tanım gereği RSI 100 olmalı. NaN, mesajda
    # "RSI nan" olarak görünür ve momentum kontrollerini sessizce False yapardı.
    # Gerçek hisselerde nadir ama mümkün (çok kısa/kesintisiz yükseliş serileri).
    hic_kayip_yok = (avg_loss == 0) & (avg_gain > 0)
    rsi = rsi.mask(hic_kayip_yok, 100.0)
    # Hem kayıp hem kazanç sıfırsa (fiyat hiç değişmemiş) nötr kabul edilir.
    hic_hareket_yok = (avg_loss == 0) & (avg_gain == 0)
    rsi = rsi.mask(hic_hareket_yok, 50.0)
    return rsi


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


# NEDEN 15: Referans Pine Script'in varsayılanıyla aynı. Ayrıca test ettik:
# botun PULLBACK_MIN_PCT=4 hedefi (en sığ %4'lik düzeltmeleri bile yakalama)
# ile 15 uyumlu, ama period=20/30 kullanıldığında sığ (~%5) bir düzeltme
# TAMAMEN KAÇIRILIYOR (test: gerçek ~%5 düzeltmeli sentetik veride period=15
# doğru yakaladı, period=20 ve 30 hiç pivot bulamadı). Yani 15'in üzerine
# çıkmak, botun kendi amacıyla doğrudan çelişir — bu bir tercih değil, ölçülmüş
# bir uyumluluk sınırı.
ZIGZAG_PERIOD = 15
# Saklanacak en fazla pivot sayısı. 1 yıllık veride tipik olarak 10-40 pivot
# oluşur; bu sınır analiz penceresini (LOOKBACK_STRUCTURE=120 gün) rahatça
# kapsar. Bkz. compute_zigzag içindeki açıklama.
MAX_ZIGZAG_PIVOTS = 100

# --- TELEGRAM GÖNDERİM AYARLARI ---
# Telegram'ın grup sohbetleri için pratik sınırı ~20 mesaj/dakika. Eskiden
# mesajlar arası 0.5sn bekleniyordu (=120 mesaj/dk) -- yani sınırın 6 katı,
# yoğun bir taramada 429 alıp mesaj KAYBETME riski vardı. 3 saniye, sınırın
# güvenli tarafında kalır (~20/dk) ve en yoğun taramada bile toplam süreye
# yalnızca ~2 dakika ekler (30 dakikalık iş limitinin çok altında).
MESSAGE_DELAY_SECONDS = 3.0
TELEGRAM_MAX_RETRIES = 3


def compute_zigzag(df, period=ZIGZAG_PERIOD):
    """
    Gönderdiğin "ZigZag with Fibonacci Levels" (LonesomeTheBlue) Pine Script'inin
    BİREBİR AYNI mantığı: ATR değil, sabit bir gün penceresi (period) kullanır.

    Her gün için: "bugünün High'ı, geriye dönük son `period` günün en yükseği mi?"
    ve "bugünün Low'u, geriye dönük son `period` günün en düşüğü mü?" diye bakılır
    (Pine'daki highestbars/lowestbars==0 kontrolüyle birebir aynı).

    Yön (dir) değiştiğinde YENİ bir pivot onaylanır (kalıcı, bir daha değişmez).
    Yön değişmediği sürece, mevcut (henüz "canlı"/onaylanmamış) pivot daha
    ekstrem bir değer bulundukça güncellenir — tıpkı Pine'daki add_to_zigzag /
    update_zigzag çiftinin yaptığı gibi.

    Döner: (swing_highs, swing_lows) — SADECE ONAYLANMIŞ pivotlar (son, hâlâ
    "canlı" olan uç nokta dahil değildir — Pine'daki zigzag[0] karşılığı).
    """
    high, low = df["High"], df["Low"]
    n = len(df)
    if n < period + 5:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    roll_high = high.rolling(period, min_periods=period).max()
    roll_low = low.rolling(period, min_periods=period).min()

    # stack: en yeni pivot en başta (Pine'daki zigzag dizisiyle aynı sırada).
    # Her eleman: {"price":..., "idx":..., "type": "H"/"L"}
    stack = []
    dir_ = 0

    for i in range(period - 1, n):
        idx = df.index[i]
        h, l = float(high.iloc[i]), float(low.iloc[i])
        rh, rl = roll_high.iloc[i], roll_low.iloc[i]
        if pd.isna(rh) or pd.isna(rl):
            continue

        ph = h if h >= rh else None   # bugün, son `period` günün en yükseği mi
        pl = l if l <= rl else None   # bugün, son `period` günün en düşüğü mü

        new_dir = dir_
        if ph is not None and pl is None:
            new_dir = 1
        elif pl is not None and ph is None:
            new_dir = -1
        # ikisi de aynı anda True/None ise yön DEĞİŞTİRİLMEZ (Pine'daki gibi)

        if new_dir == 0:
            continue  # henüz hiç yön belirlenmedi, atla

        dirchanged = (new_dir != dir_) and dir_ != 0
        dir_ = new_dir
        value = h if dir_ == 1 else l
        ptype = "H" if dir_ == 1 else "L"

        if len(stack) == 0 or dirchanged:
            stack.insert(0, {"price": value, "idx": idx, "type": ptype})
            # KRİTİK DÜZELTME: burada eskiden sınır 5'ti (referans Pine
            # Script'inden birebir alınmıştı). Ama o script pivotları SADECE
            # son çizgiyi çizmek için kullanıyor; BİZ ise 120 günlük pencerede
            # DİRENÇ ve HH/HL YAPI analizi yapıyoruz. 5'lik sınır yüzünden
            # 300 günlük seride yalnızca 4 pivot kalıyordu ve son 120 günde
            # çoğu zaman tek bir tepe bulunabiliyordu -> find_resistances
            # sürekli "direnç yok" dönüyor, hedefler gerçek dirence değil
            # hesaplanmış tahmine düşüyordu. Sınır, analiz penceresini
            # rahatça kapsayacak şekilde yükseltildi.
            if len(stack) > MAX_ZIGZAG_PIVOTS:
                stack.pop()
        else:
            current = stack[0]
            if (dir_ == 1 and value > current["price"]) or (dir_ == -1 and value < current["price"]):
                current["price"] = value
                current["idx"] = idx

    # stack[0] hâlâ "canlı" (onaylanmamış) -- dışarıda bırakıyoruz, geri kalanı onaylı.
    confirmed = stack[1:]

    def _to_price_series(pivot_list):
        """
        KRİTİK DÜZELTME: pd.Series({}, dtype=float) -- yani hiç pivot
        bulunamadığında -- pandas'ta boş bir Series üretir ama index'i
        DatetimeIndex DEĞİL, sıradan (Range/object) bir index olur. Bu da
        ileride ".index >= bir_tarih" gibi karşılaştırmalarda ("TypeError:
        '>=' not supported between numpy.ndarray and Timestamp") ÇÖKMEYE
        yol açıyordu -- özellikle çok güçlü, kesintisiz trendli hisselerde
        (hiç düzeltme onaylanmadığında) gerçekleşiyordu. Şimdi boş durumda
        bile index'i EXPLICIT olarak DatetimeIndex yapıyoruz.
        """
        if not pivot_list:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        idx = pd.DatetimeIndex([p["idx"] for p in pivot_list])
        vals = [p["price"] for p in pivot_list]
        return pd.Series(vals, index=idx).sort_index()

    swing_highs = _to_price_series([p for p in confirmed if p["type"] == "H"])
    swing_lows = _to_price_series([p for p in confirmed if p["type"] == "L"])
    return swing_highs, swing_lows


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


def calc_fibonacci_levels(peak_price, trough_price):
    """
    SADECE BİLGİ AMAÇLI — Giriş/Stop/Hedef kararına hiçbir etkisi yok.
    detect_pullback()'in ZATEN bulduğu aynı tepe/dip noktalarından
    hesaplanır; yeni bir tespit algoritması eklenmiyor, sadece aritmetik.

    ÖLÇÜM YÖNÜ (düzeltildi): Geri çekilme seviyeleri TEPEDEN AŞAĞIYA doğru
    ölçülür -- yani "%61.8", fiyatın tepeden dibe doğru yolun %61.8'ini geri
    verdiği seviyedir. Bu, TradingView'in ve genel teknik analiz literatürünün
    standart yönüdür.

    Eskiden DİPTEN YUKARIYA ölçülüyordu; fiyatlar aynıydı ama etiketler
    TERSTİ (bizim "%38.2" dediğimiz, TradingView'in "%61.8"iydi). Kullanıcı
    grafikle karşılaştırdığında kafa karışıklığı yaratıyordu ve "altın oran
    %61.8 desteği" gibi yerleşik kavramlar yanlış seviyeye işaret ediyordu.

    Uzatma (extension) seviyeleri tepenin ÜZERİNDEDİR ve dipten ölçülen
    klasik 1.272 / 1.618 çarpanlarıdır (TradingView bunları -0.272 / -0.618
    olarak etiketler; fiyatlar birebir aynıdır).
    """
    diff = peak_price - trough_price
    if diff <= 0:
        return None

    return {
        "peak_used": peak_price,      # şeffaflık: hangi tepe/dipten hesaplandığı
        "trough_used": trough_price,  # mesajda gösteriliyor, elle teyit edilebilsin
        "retr_236": peak_price - diff * 0.236,
        "retr_382": peak_price - diff * 0.382,
        "retr_500": peak_price - diff * 0.5,
        "retr_618": peak_price - diff * 0.618,
        "retr_786": peak_price - diff * 0.786,
        "ext_1272": trough_price + diff * 1.272,
        "ext_1618": trough_price + diff * 1.618,
    }


def get_confirmed_fib_leg(peak_idx, peak_price, swing_lows):
    """
    Gönderdiğin Pine Script'in mantığı: Fibonacci, HENÜZ ONAYLANMAMIŞ
    (hâlâ hareket edebilecek) bir uç noktadan değil, TAMAMEN KESİNLEŞMİŞ
    bir bacaktan çizilir (script'te zigzag[4]->zigzag[2], yani en son değil,
    ondan önceki tamamlanmış bacak).

    Bizim durumumuzda: pullback'in TEPESİ zaten kesinleşmiş bir ZigZag
    pivotu (detect_pullback bunu zaten öyle seçiyor). Ama DİP, henüz ZigZag
    tarafından onaylanmamış olabilir (düşüş/toparlanma hâlâ "canlı" olabilir,
    ki botun mantığı gereği genelde tam da bu durumdayken sinyal üretiyoruz).

    Bu yüzden: tepeden SONRA ZigZag'ın gerçekten onayladığı bir dip varsa
    onu kullanırız. Yoksa Fibonacci'yi HİÇ göstermeyiz — kararsız/değişebilir
    bir sayı göstermektense hiç göstermemek, script'in felsefesine daha sadık.
    """
    confirmed_after_peak = swing_lows[swing_lows.index > peak_idx]
    if len(confirmed_after_peak) == 0:
        return None
    trough_price = float(confirmed_after_peak.iloc[-1])
    return calc_fibonacci_levels(peak_price, trough_price)

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


def hh_hl_structure(df, swing_highs, swing_lows, lookback=LOOKBACK_STRUCTURE):
    """
    ZigZag ile ÖNCEDEN (bir kez) hesaplanmış swing_highs/swing_lows'u alır,
    sadece son `lookback` gün içine düşenleri filtreler. Böylece tüm
    fonksiyonlar AYNI pivot noktalarını kullanır — tutarlılık garantisi.
    """
    if len(df) < lookback:
        cutoff = df.index[0]
    else:
        cutoff = df.index[-lookback]
    sh_vals = swing_highs[swing_highs.index >= cutoff]
    sl_vals = swing_lows[swing_lows.index >= cutoff]
    hh = bool(len(sh_vals) >= 2 and sh_vals.iloc[-1] > sh_vals.iloc[-2])
    hl = bool(len(sl_vals) >= 2 and sl_vals.iloc[-1] > sl_vals.iloc[-2])
    return {"hh": hh, "hl": hl, "swing_highs": sh_vals, "swing_lows": sl_vals}


def trend_filter(df, swing_highs, swing_lows):
    close = df["Close"]
    if len(close) < 210:
        return {"ok": False, "reason": "yetersiz veri"}

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    cp = float(close.iloc[-1])

    above20 = cp > float(sma20.iloc[-1])
    above50 = cp > float(sma50.iloc[-1])
    above200 = cp > float(sma200.iloc[-1])
    sma50_rising = float(sma50.iloc[-1]) > float(sma50.iloc[-10])
    golden = float(sma50.iloc[-1]) > float(sma200.iloc[-1])

    structure = hh_hl_structure(df, swing_highs, swing_lows)
    weekly_ok = weekly_trend_ok(df)

    ok = above200 and sma50_rising and golden and (structure["hl"] or above50) and weekly_ok

    return {
        "ok": ok, "above20": above20, "above50": above50, "above200": above200,
        "sma50_rising": sma50_rising, "golden": golden,
        "hh": structure["hh"], "hl": structure["hl"], "weekly_ok": weekly_ok,
    }

# ============================================================
# 2) DÜZELTME (PULLBACK)
# ============================================================

def detect_pullback(df, swing_highs, swing_lows, lookback=LOOKBACK_SWING, order=SWING_ORDER, context_buffer=30):
    high, low, close = df["High"], df["Low"], df["Close"]
    window = lookback + context_buffer
    if len(close) < window:
        return {"ok": False}

    h = high.tail(window)
    l = low.tail(window)

    # ZigZag ile önceden bulunmuş tepe noktalarından, bu pencereye düşenler
    window_start = h.index[0]
    candidates_all = swing_highs[swing_highs.index >= window_start]
    if len(candidates_all) == 0:
        return {"ok": False}

    cutoff = h.index[-lookback]
    recent_peaks = candidates_all[candidates_all.index >= cutoff]
    candidates = recent_peaks if len(recent_peaks) > 0 else candidates_all
    peak_idx = candidates.idxmax()
    peak_price = float(candidates.loc[peak_idx])
    if peak_price <= 0:
        return {"ok": False}

    # Dip: ZigZag'a gerek yok, tepeden bugüne kadarki ham minimum (daha duyarlı ve basit)
    after_peak_low = l.loc[peak_idx:]
    if after_peak_low.empty:
        return {"ok": False}
    trough_idx = after_peak_low.idxmin()
    trough_price = float(after_peak_low.min())

    cp = float(close.iloc[-1])
    drawdown_pct = (peak_price - trough_price) / peak_price * 100
    recovery_from_low_pct = (cp - trough_price) / trough_price * 100 if trough_price > 0 else 0
    healthy_depth = PULLBACK_MIN_PCT <= drawdown_pct <= PULLBACK_MAX_PCT

    # Dipten sonra higher-low oluşmuş mu — YİNE aynı ZigZag dip pivotlarından bakıyoruz
    lows_after_trough = swing_lows[swing_lows.index >= trough_idx]
    higher_low_after_trough = False
    if len(lows_after_trough) >= 2:
        higher_low_after_trough = bool(lows_after_trough.iloc[-1] > lows_after_trough.iloc[-2])

    near_recent_high = cp >= float(h.tail(5).max()) * 0.98
    solid_bounce = recovery_from_low_pct >= 3.0

    is_recovering = solid_bounce or higher_low_after_trough or near_recent_high

    return {
        "ok": healthy_depth and is_recovering,
        "peak_price": peak_price, "peak_idx": peak_idx,
        "trough_price": trough_price, "trough_idx": trough_idx,
        "drawdown_pct": drawdown_pct, "recovery_from_low_pct": recovery_from_low_pct,
    }

# ============================================================
# 3) MOMENTUM
# ============================================================

def _bullish_divergence(close, indicator, peak_idx, order=SWING_ORDER):
    """
    POZİTİF UYUMSUZLUK: düzeltme sonrasında fiyat DAHA DÜŞÜK dip yaparken
    göstergenin DAHA YÜKSEK dip yapması. Satış baskısının gücünü yitirdiğine
    dair klasik ve güçlü bir işaret.
    `indicator` herhangi bir gösterge olabilir (RSI, MACD çizgisi...).
    """
    try:
        seg_close = close.loc[peak_idx:]
        seg_ind = indicator.loc[peak_idx:]
        if len(seg_close) < order * 2 + 3:
            return False
        lows_idx = find_swings(seg_close, order, "min")
        if len(lows_idx) < 2:
            return False
        low1, low2 = lows_idx[-2], lows_idx[-1]
        price_lower = seg_close.loc[low2] < seg_close.loc[low1]
        ind_higher = seg_ind.loc[low2] > seg_ind.loc[low1]
        return bool(price_lower and ind_higher)
    except Exception:
        return False


def _bearish_divergence(df, indicator, swing_highs, lookback=LOOKBACK_STRUCTURE):
    """
    NEGATİF UYUMSUZLUK: fiyat DAHA YÜKSEK tepe yaparken göstergenin DAHA DÜŞÜK
    tepe yapması -- yükseliş sürüyor ama arkasındaki güç zayıflıyor demektir.
    ZigZag'ın ONAYLADIĞI tepeler kullanılır (uydurma tepe üzerinden karar
    verilmesin diye). Sinyali ENGELLEMEZ, sadece skoru düşürür.
    """
    try:
        if len(swing_highs) < 2:
            return False
        cutoff = df.index[0] if len(df) < lookback else df.index[-lookback]
        tepeler = swing_highs[swing_highs.index >= cutoff]
        if len(tepeler) < 2:
            return False
        t1, t2 = tepeler.index[-2], tepeler.index[-1]
        if t1 not in indicator.index or t2 not in indicator.index:
            return False
        fiyat_daha_yuksek = tepeler.loc[t2] > tepeler.loc[t1]
        gosterge_daha_dusuk = indicator.loc[t2] < indicator.loc[t1]
        return bool(fiyat_daha_yuksek and gosterge_daha_dusuk)
    except Exception:
        return False


def rsi_bullish_divergence(close, rsi, peak_idx, order=SWING_ORDER):
    """Geriye dönük uyumluluk için korunan sarmalayıcı (davranış birebir aynı)."""
    return _bullish_divergence(close, rsi, peak_idx, order)


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

def evaluate_confluence(df, pullback, swing_highs, swing_lows):
    close, volume = df["Close"], df["Volume"]
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

    # --- UYUMSUZLUK (DIVERGENCE) ANALİZİ ---
    # ÖNEMLİ TASARIM KARARI: bunlar `checks` sözlüğüne EKLENMEZ, yani hangi
    # hissenin sinyal olacağını DEĞİŞTİRMEZ. Sadece skoru düzenler (pozitif
    # ekler, negatif kırar). Böylece mevcut sinyal kapıları aynen korunur,
    # ama kalite ayrımı keskinleşir. checks["macd"]'a "veya divergence" diye
    # eklenseydi kriter GEVŞERDİ ve daha çok zayıf sinyal geçerdi.
    div_rsi_bull = divergence
    div_macd_bull = _bullish_divergence(close, macd_line, peak_idx)
    div_rsi_bear = _bearish_divergence(df, rsi, swing_highs)
    div_macd_bear = _bearish_divergence(df, macd_line, swing_highs)

    structure = hh_hl_structure(df, swing_highs, swing_lows)
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
        "checks": checks, "count": confluence_count, "rvol": rvol, "rsi": rsi_now,
        "decline_shrank": decline_shrank, "squeeze": squeeze,
        "div_rsi_bull": div_rsi_bull, "div_macd_bull": div_macd_bull,
        "div_rsi_bear": div_rsi_bear, "div_macd_bear": div_macd_bear,
    }

# ============================================================
# 7) DİRENÇ SEVİYELERİ
# ============================================================

def find_resistances(df, swing_highs, close, lookback=LOOKBACK_STRUCTURE):
    if len(df) < lookback:
        cutoff = df.index[0]
    else:
        cutoff = df.index[-lookback]
    sh_vals = swing_highs[swing_highs.index >= cutoff].sort_values()
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

    # Aşırı uzak yapısal stop = gerçekçi olmayan risk VE ondan türeyen
    # gerçekçi olmayan hedef. Böyle kurulumlar tamamen elenir (bkz. MAX_RISK_PCT).
    if (risk / entry_trigger) * 100 > MAX_RISK_PCT:
        return None

    # HEDEF SEÇİMİ (tasarım düzeltmesi):
    # Bu strateji "düzeltme bitti, hisse eski gücüne dönüyor" üzerine kurulu.
    # Böyle bir kurulumda düzeltmenin ESKİ TEPESİ bir hedef değil, KIRILIM
    # noktasıdır -- asıl hedef onun ötesindedir. Eskiden en yakın direnç
    # koşulsuz Hedef 1 yapılıyordu; fiyat toparlanıp eski tepeye yaklaştığında
    # bu, "24 puan riske at, 5 puan kazan" gibi anlamsız bir R/R üretiyor ve
    # bot TAM DA BULMAK İÇİN TASARLANDIĞI kurulumları eliyordu (ölçüldü:
    # klasik pullback senaryolarının sadece %4'ü yakalanıyordu).
    #
    # Artık bir direnç, alınan riske göre anlamlı bir kazanç sunmuyorsa
    # (MIN_TARGET_RR_RATIO'dan az) Hedef 1 olarak kullanılmaz; bir sonraki
    # dirence ya da hesaplanmış hedefe geçilir.
    nearest_res, second_res = resistances

    def anlamli_hedef(seviye):
        """Seviye, girişin üzerinde VE riske göre anlamlı kazanç sunuyor mu?"""
        if not seviye or seviye <= entry_trigger:
            return False
        return (seviye - entry_trigger) >= risk * MIN_TARGET_RR_RATIO

    if anlamli_hedef(nearest_res):
        target1 = nearest_res
    elif anlamli_hedef(second_res):
        # En yakın direnç çok yakın kaldı -> bir sonrakini hedef al
        target1 = second_res
        second_res = None  # Hedef 2 için artık kullanılamaz, hesaplanana düşecek
    else:
        target1 = entry_trigger + 2 * risk

    target2 = second_res if (second_res and second_res > target1) else max(target1 + risk, entry_trigger + 3 * risk)

    rr1 = (target1 - entry_trigger) / risk
    rr2 = (target2 - entry_trigger) / risk

    return {
        "entry_trigger": entry_trigger, "stop": stop,
        "target1": target1, "target2": target2,
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

    # --- UYUMSUZLUK (DIVERGENCE) PUAN DÜZENLEMESİ ---
    # Pozitif uyumsuzluk EKLER, negatif uyumsuzluk KIRAR.
    # Negatif ceza bilerek biraz DAHA AĞIR: "yükseliyor ama gücü tükeniyor"
    # uyarısı, olumlu bir işaretten daha kritiktir (temkinli taraf ağır basar).
    div_ayar = 0.0
    if confluence.get("div_rsi_bull"):
        div_ayar += DIV_BULL_BONUS
    if confluence.get("div_macd_bull"):
        div_ayar += DIV_BULL_BONUS
    if confluence.get("div_rsi_bear"):
        div_ayar -= DIV_BEAR_PENALTY
    if confluence.get("div_macd_bear"):
        div_ayar -= DIV_BEAR_PENALTY

    score = raw * 0.9 + rr_bonus + div_ayar
    score = max(0.0, min(100.0, score))   # 0-100 aralığında kalmayı garanti et
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
    # En gevşek giriş şartı: pullback geçerli + minimum teyit + ANLAMLI bir R/R.
    # MIN_RR_WATCH olmadan R/R 0.1 gibi finansal olarak anlamsız sinyaller de
    # listeye giriyordu (stres testinde tespit edildi).
    loose_ok = (
        pullback["ok"]
        and confluence["count"] >= MIN_CONFLUENCE_WATCH
        and levels["rr1"] >= MIN_RR_WATCH
    )
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

# Fiyat yükseldikçe aşamalar KRONOLOJİK olarak şöyle ilerler:
#   SETUP -> LOCAL_BREAK -> MAIN_BREAK -> EXTENDED
# Bu, main() içindeki `stage_order`dan (GÖRÜNTÜLEME önceliği) FARKLIDIR:
# orada EXTENDED bilerek düşük tutulur, çünkü "kovalama riski" uyarısıdır ve
# listenin başında yer almamalıdır. İki kavramı tek sözlükle yönetmek şu
# hataya yol açıyordu: fiyat GERİLEYİP EXTENDED'den MAIN_BREAK'e düştüğünde
# bot "⬆️ AŞAMA YÜKSELDİ" diyordu. Artık ilerleme tespiti buradan yapılıyor.
STAGE_PROGRESS = {"WATCH": 0, "SETUP": 1, "LOCAL_BREAK": 2, "MAIN_BREAK": 3, "EXTENDED": 4}

# Özet mesajında hangi hissenin hangi aşamada olduğunu tek bakışta göstermek için.
# STAGE_INFO'daki başlıklarla aynı renk kodları kullanılır.
STAGE_EMOJI = {"WATCH": "🔵", "SETUP": "🟠", "LOCAL_BREAK": "🟡",
               "MAIN_BREAK": "🟢", "EXTENDED": "🔴"}

STAGE_INFO = {
    "WATCH": {"baslik": "🔵 İZLEME LİSTESİ"},
    "SETUP": {"baslik": "🟠 KURULUM HAZIR"},
    "LOCAL_BREAK": {"baslik": "🟡 ERKEN KIRILIM (Yerel)"},
    "MAIN_BREAK": {"baslik": "🟢 DÜZELTME TEPESİ AŞILDI"},
    "EXTENDED": {"baslik": "🔴 AŞIRI UZAMIŞ"},
}


def build_message(ticker, item):
    stage = item["stage"]
    info = STAGE_INFO[stage]
    c, l, pb, rs = item["confluence"], item["levels"], item["pullback"], item["rs"]
    fib = item.get("fib")

    rs_text = f"{rs['rs_change_pct']:+.1f}%" if rs.get("available") else "n/a"

    # Teyit kriterleri: her biri ✅ / ❌ ile, tek satırda, sayaçla birlikte
    kriter_isimleri = {"hacim": "Hacim", "momentum": "Momentum", "macd": "MACD", "yapi": "Yapı"}
    kriter_parcalari = []
    for anahtar, gosterim in kriter_isimleri.items():
        isaret = "✅" if c["checks"].get(anahtar) else "❌"
        kriter_parcalari.append(f"{isaret} {gosterim}")
    kriterler_satiri = "   ".join(kriter_parcalari)

    fib_block = (
        f"\n📐 *FİB* (tepe {fib['peak_used']:.2f} → dip {fib['trough_used']:.2f})\n"
        f"_geri çekilme (destek):_\n"
        f"23.6% {fib['retr_236']:.2f} · 38.2% {fib['retr_382']:.2f} · 50% {fib['retr_500']:.2f}\n"
        f"61.8% {fib['retr_618']:.2f} · 78.6% {fib['retr_786']:.2f}\n"
        f"_uzatma (hedef):_ 1.272 {fib['ext_1272']:.2f} · 1.618 {fib['ext_1618']:.2f}\n"
    ) if fib else ""

    # DÜZELTME: MAIN_BREAK/EXTENDED'de "Giriş" olarak entry_trigger (yerel,
    # 3 günlük referans) gösterilirse, bu bazen güncel fiyatın ÜZERİNDE
    # kalabiliyor -- "kırılım zaten oldu" mesajıyla çelişen bir görüntü
    # yaratıyor (bkz. BIMAS örneği: Giriş 418.17 > güncel fiyat 415.75).
    # Bu aşamalarda artık GÜNCEL FİYAT referans alınıyor (zaten kırılmış,
    # buradan takip edilir), Stop/Hedef/R-R de buna göre TUTARLI şekilde
    # yeniden hesaplanıyor. Sinyal kararı (determine_stage, MIN_RR eşiği)
    # buna dokunmuyor, SADECE mesajdaki gösterim tutarlılığı düzeliyor.
    if stage in ("MAIN_BREAK", "EXTENDED"):
        display_entry = item["close"]
        entry_not = " _(zaten kırılmış)_"
    else:
        display_entry = l["entry_trigger"]
        entry_not = ""

    display_risk = display_entry - l["stop"]
    if display_risk > 0:
        display_risk_pct = display_risk / display_entry * 100
        display_rr1 = (l["target1"] - display_entry) / display_risk
        display_rr2 = (l["target2"] - display_entry) / display_risk
    else:
        # Güvenlik: beklenmedik durumda (stop >= güncel fiyat) orijinal
        # değerlere geri dön, çökme veya anlamsız sayı üretme.
        display_entry, display_risk_pct = l["entry_trigger"], l["risk_pct"]
        display_rr1, display_rr2 = l["rr1"], l["rr2"]
        entry_not = ""

    # Hedeflerin GİRİŞE göre kazanç yüzdeleri. Stop satırındaki kayıp
    # yüzdesiyle SİMETRİK olsun diye aynı `display_entry` referansı kullanılır --
    # böylece "ne kaybederim / ne kazanırım" aynı temelden okunur.
    hedef1_pct = (l["target1"] - display_entry) / display_entry * 100 if display_entry > 0 else 0.0
    hedef2_pct = (l["target2"] - display_entry) / display_entry * 100 if display_entry > 0 else 0.0

    macd_isaret = "↗️" if c["checks"]["macd"] else "➖"

    # Uyumsuzluk satırı: sadece gerçekten bir uyumsuzluk varsa gösterilir.
    pozitifler = []
    if c.get("div_rsi_bull"):
        pozitifler.append("RSI")
    if c.get("div_macd_bull"):
        pozitifler.append("MACD")
    negatifler = []
    if c.get("div_rsi_bear"):
        negatifler.append("RSI")
    if c.get("div_macd_bear"):
        negatifler.append("MACD")

    div_parcalari = []
    if pozitifler:
        div_parcalari.append(f"✅ Pozitif uyumsuzluk: {', '.join(pozitifler)}")
    if negatifler:
        div_parcalari.append(f"⚠️ Negatif uyumsuzluk: {', '.join(negatifler)}")
    div_satiri = ("🔀 " + "  ·  ".join(div_parcalari) + "\n") if div_parcalari else ""

    msg = (
        f"{info['baslik']}\n"
        f"📌 *{ticker}* · {item['close']:.2f} TL · ⭐ {item['score']:.1f}\n\n"

        f"*{c['count']}/4* {kriterler_satiri}\n\n"

        f"🎯 *GİRİŞ*      `{display_entry:.2f}`{entry_not}\n"
        f"🛑 *STOP*       `{l['stop']:.2f}`  ▼ %{display_risk_pct:.1f}\n"
        f"🥇 *HEDEF 1*    `{l['target1']:.2f}`  ▲ %{hedef1_pct:.1f}  ⚖️ {display_rr1:.1f}\n"
        f"🥈 *HEDEF 2*    `{l['target2']:.2f}`  ▲ %{hedef2_pct:.1f}  ⚖️ {display_rr2:.1f}\n\n"

        f"📉 Düzeltme %{pb['drawdown_pct']:.1f}  ({pb['peak_price']:.2f} → {pb['trough_price']:.2f})\n"
        f"📈 Toparlanma +%{pb['recovery_from_low_pct']:.1f}\n"
        f"〽️ RSI {c['rsi']:.1f} · MACD {macd_isaret} · RVOL {c['rvol']:.2f}x\n"
        f"{div_satiri}"
        f"🌍 BIST'e göre {rs_text} (20g)\n"
        f"{fib_block}"
        f"\n_yatırım tavsiyesi değildir_"
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
        f"🎉 *HEDEFE ULAŞILDI*\n"
        f"📌 *{ticker}* · ✅ *+%{gain_pct:.1f}*\n\n"
        f"🎯 Giriş `{entry:.2f}` → Güncel `{current_price:.2f}`\n"
        f"🥇 Hedef `{position['target1']:.2f}` görüldü\n\n"
        f"_takip kapatıldı_"
    )


def build_stop_hit_message(ticker, position, current_price):
    entry = position["entry"]
    loss_pct = (current_price - entry) / entry * 100 if entry > 0 else 0.0
    sign = "-" if loss_pct < 0 else "+"
    return (
        f"🛑 *STOP TETİKLENDİ*\n"
        f"📌 *{ticker}* · ❌ *{sign}%{abs(loss_pct):.1f}*\n\n"
        f"🎯 Giriş `{entry:.2f}` → Güncel `{current_price:.2f}`\n"
        f"🛑 Stop `{position['stop']:.2f}` kırıldı\n\n"
        f"_takip kapatıldı_"
    )


HISTORY_KEY = "__history__"   # state.json içinde ayrı, ticker olmayan özel bir anahtar
PERF_LAST_SENT_KEY = "__perf_last_sent__"  # performans özetinin en son ne zaman gönderildiği
PERF_SUMMARY_INTERVAL_DAYS = 7  # performans özeti kaç günde bir gönderilsin
MAX_HISTORY_ENTRIES = 300     # state.json'un sınırsız büyümesini önlemek için


def add_to_history(state, ticker, outcome, position, exit_price):
    """Kapanan bir sinyali (hedef/stop) kalıcı geçmişe ekler. En eski kayıtlar,
    MAX_HISTORY_ENTRIES aşılırsa budanır (state.json şişmesin diye)."""
    entry = position["entry"]
    pct_change = (exit_price - entry) / entry * 100 if entry > 0 else 0.0
    record = {
        "ticker": ticker, "outcome": outcome, "entry": entry, "exit_price": exit_price,
        "pct_change": round(pct_change, 2), "opened_date": position.get("opened_date"),
        "closed_date": datetime.now().strftime("%Y-%m-%d"),
    }
    history = state.get(HISTORY_KEY, [])
    history.append(record)
    if len(history) > MAX_HISTORY_ENTRIES:
        history = history[-MAX_HISTORY_ENTRIES:]
    state[HISTORY_KEY] = history


def build_timeout_message(ticker, position, current_price, gun_sayisi):
    entry = position["entry"]
    pct = (current_price - entry) / entry * 100 if entry > 0 else 0.0
    sign = "-" if pct < 0 else "+"
    return (
        f"⏳ *ZAMAN AŞIMI*\n"
        f"📌 *{ticker}* · {sign}%{abs(pct):.1f}\n\n"
        f"🎯 Giriş `{entry:.2f}` → Güncel `{current_price:.2f}`\n"
        f"📅 {gun_sayisi} gündür ne hedef ne stop\n\n"
        f"_takip kapatıldı_"
    )


def check_open_positions(state, all_data):
    """
    Daha önce LOCAL_BREAK/MAIN_BREAK/EXTENDED ile açılmış (ve henüz
    kapanmamış) takipteki her hisse için, bu turun güncel kapanış
    fiyatına bakar. Hedefe ulaşmış ya da stop'a çarpmışsa özel bir
    bildirim gönderir, takibi kapatır VE kalıcı geçmişe (performans
    istatistikleri için) kaydeder. İkisi de olmamışsa hiçbir şey
    göndermez, sessizce açık kalır.
    """
    closed = 0
    for ticker, info in list(state.items()):
        if ticker == HISTORY_KEY or ticker == PERF_LAST_SENT_KEY:
            continue

        # DAYANIKLILIK (bakım turunda tespit edildi): state.json elle
        # düzenlenmiş, yarıda kesilmiş ya da eski bir sürümden kalmışsa
        # kayıtlar bozuk olabilir. Bu fonksiyon taramanın EN BAŞINDA
        # çalıştığı için, buradaki bir çökme TÜM taramayı öldürür.
        # O yüzden her kaydın yapısını kullanmadan ÖNCE doğruluyoruz.
        if not isinstance(info, dict):
            log.warning(f"{ticker}: state kaydı sözlük değil, atlandı")
            continue
        position = info.get("position")
        if not position:
            continue
        if not isinstance(position, dict):
            log.warning(f"{ticker}: position bozuk (sözlük değil), temizlendi")
            state[ticker]["position"] = None
            continue
        gerekli = ("entry", "stop", "target1")
        if not all(k in position for k in gerekli):
            log.warning(f"{ticker}: position eksik alanlı, temizlendi")
            state[ticker]["position"] = None
            continue
        try:
            if not all(isinstance(position[k], (int, float)) for k in gerekli):
                raise TypeError("sayısal olmayan seviye")
        except Exception:
            log.warning(f"{ticker}: position seviyeleri sayısal değil, temizlendi")
            state[ticker]["position"] = None
            continue

        if ticker not in all_data:
            continue  # bu turda veri gelmedi, bir sonraki taramaya bırakılır

        try:
            current_price = float(all_data[ticker]["Close"].iloc[-1])
        except Exception:
            continue

        if current_price >= position["target1"]:
            send_telegram(build_target_hit_message(ticker, position, current_price))
            add_to_history(state, ticker, "target", position, current_price)
            state[ticker]["position"] = None
            closed += 1
            time.sleep(MESSAGE_DELAY_SECONDS)
        elif current_price <= position["stop"]:
            send_telegram(build_stop_hit_message(ticker, position, current_price))
            add_to_history(state, ticker, "stop", position, current_price)
            state[ticker]["position"] = None
            closed += 1
            time.sleep(MESSAGE_DELAY_SECONDS)
        else:
            # v5 YENİ (3): ZAMAN AŞIMI. Ne hedefe ne stop'a ulaşmadan çok uzun
            # süre açık kalan takipler birikiyor, hem listeyi şişiriyor hem de
            # performans istatistiklerinde sonsuza kadar "sonuçsuz" kalıyordu.
            opened = position.get("opened_date")
            if not opened:
                continue
            try:
                opened_date = datetime.strptime(opened, "%Y-%m-%d").date()
            except Exception:
                continue  # bozuk tarih -> dokunma, açık kalsın
            gun_gecti = (datetime.now().date() - opened_date).days
            if gun_gecti >= POSITION_TIMEOUT_DAYS:
                send_telegram(build_timeout_message(ticker, position, current_price, gun_gecti))
                add_to_history(state, ticker, "timeout", position, current_price)
                state[ticker]["position"] = None
                closed += 1
                time.sleep(MESSAGE_DELAY_SECONDS)

    return closed

# ============================================================
# GÜNLÜK ÖZET (v4 — yeni)
# ============================================================

def build_summary_message(stage_counts, total_scanned, total_universe, open_positions_count, regime_ok, top3, watch_list=None):
    regime_text = "Güçlü ✅" if regime_ok else "Zayıf ⚠️"
    # top3 artık (ticker, skor, aşama) üçlüsü. Aşama emojisi gösteriliyor ki
    # "en güçlü listesinde başta ama neden mesaj gelmedi?" sorusu oluşmasın:
    # 🔵 (İzleme) ayrı mesaj almaz, sadece bu özette listelenir.
    if top3:
        parcalar = []
        for kayit in top3:
            if len(kayit) == 3:
                t, s, stg = kayit
                parcalar.append(f"{STAGE_EMOJI.get(stg, '')}{t.replace('.IS', '')} ({s:.1f})")
            else:   # geriye dönük uyumluluk (eski 2'li format)
                t, s = kayit
                parcalar.append(f"{t.replace('.IS', '')} ({s:.1f})")
        top3_text = ", ".join(parcalar)
    else:
        top3_text = "yok"

    # v5 YENİ: WATCH artık ayrı mesaj göndermiyor, bunun yerine burada
    # tek satırda listeleniyor (bildirim gürültüsünü azaltmak için).
    # İlk 3'ü SKORUYLA gösteriliyor -- izleme listesinin en güçlüleri hangileri,
    # tek bakışta görünsün diye. Liste zaten skora göre sıralı gelir.
    watch_block = ""
    if watch_list:
        gosterilen = watch_list[:MAX_WATCH_IN_SUMMARY]
        parcalar = []
        for i, kayit in enumerate(gosterilen):
            if isinstance(kayit, (tuple, list)) and len(kayit) == 2:
                t, s = kayit
                ad = t.replace(".IS", "")
                parcalar.append(f"*{ad}* ({s:.1f})" if i < 3 else ad)
            else:   # geriye dönük uyumluluk (sadece ticker listesi)
                parcalar.append(str(kayit).replace(".IS", ""))
        fazla = len(watch_list) - len(gosterilen)
        watch_block = (f"\n\n🔵 İzleme ({len(watch_list)}): " + ", ".join(parcalar)
                       + (f" +{fazla} daha" if fazla > 0 else ""))

    return (
        f"📊 *TARAMA ÖZETİ*\n"
        f"{market_session_label()}\n"
        f"🌍 Piyasa: {regime_text} | Taranan: {total_scanned}/{total_universe}\n\n"
        f"🟢{stage_counts.get('MAIN_BREAK', 0)} 🟡{stage_counts.get('LOCAL_BREAK', 0)} "
        f"🔴{stage_counts.get('EXTENDED', 0)} 🟠{stage_counts.get('SETUP', 0)} "
        f"🔵{stage_counts.get('WATCH', 0)} | Açık takip: {open_positions_count}\n\n"
        f"🏆 En güçlü: {top3_text}"
        f"{watch_block}"
    )


def build_performance_summary(history):
    """
    Kalıcı geçmişten (state.json'daki HISTORY_KEY) kısa bir performans özeti
    üretir. Backtest DEĞİLDİR — botun gerçek zamanlı, gerçekleşmiş sinyal
    sonuçlarının basit bir özeti.

    NOT: Bu özet HER ZAMAN o ana kadar birikmiş TÜM geçmişi kapsar (en fazla
    MAX_HISTORY_ENTRIES kayıt) -- PERF_SUMMARY_INTERVAL_DAYS sadece ne
    sıklıkla GÖNDERİLECEĞİNİ belirler, özetin kapsadığı süreyi değil. Yani
    bu "haftalık performans" değil, "haftada bir hatırlatılan, o güne kadarki
    TOPLAM performans"tır. Mesaj metni bunu "kümülatif" diyerek açıkça belirtir.
    """
    if not history:
        return None
    total = len(history)
    wins = sum(1 for h in history if h["outcome"] == "target")
    losses = sum(1 for h in history if h["outcome"] == "stop")
    # v5: zaman aşımları AYRI sayılır. Eskiden "losses = total - wins" idi ve
    # timeout'lar yanlışlıkla STOP gibi sayılıyordu -- kazanma oranını
    # olduğundan kötü gösterirdi.
    timeouts = sum(1 for h in history if h["outcome"] == "timeout")

    # Kazanma oranı sadece NET sonuçlanan (hedef/stop) işlemler üzerinden.
    decided = wins + losses
    win_rate = (wins / decided * 100) if decided > 0 else 0.0
    avg_pct = sum(h["pct_change"] for h in history) / total if total > 0 else 0.0

    timeout_text = f" | Zaman aşımı: {timeouts} ⏳" if timeouts else ""
    return (
        f"📈 *PERFORMANS ÖZETİ* (kümülatif, toplam {total} kapanan sinyal)\n"
        f"Hedef: {wins} ✅ | Stop: {losses} 🛑{timeout_text}\n"
        f"Kazanma oranı: %{win_rate:.0f} (hedef/stop arasında)\n"
        f"Ortalama getiri: {'+' if avg_pct >= 0 else ''}%{avg_pct:.1f}\n"
        f"_Backtest değildir, botun bugüne kadarki gerçek sinyal geçmişidir._"
    )


def maybe_send_performance_summary(state):
    """Son gönderimden bu yana PERF_SUMMARY_INTERVAL_DAYS gün geçtiyse
    performans özetini gönderir. Geçmiş yoksa hiçbir şey göndermez."""
    last_sent_str = state.get(PERF_LAST_SENT_KEY)
    today = datetime.now().date()
    if last_sent_str:
        try:
            last_sent = datetime.strptime(last_sent_str, "%Y-%m-%d").date()
            if (today - last_sent).days < PERF_SUMMARY_INTERVAL_DAYS:
                return  # henüz zamanı gelmedi
        except Exception:
            pass  # bozuk tarih varsa, aşağıda yine de göndermeyi dener

    history = state.get(HISTORY_KEY, [])
    msg = build_performance_summary(history)
    if msg:
        send_telegram(msg)
    state[PERF_LAST_SENT_KEY] = today.strftime("%Y-%m-%d")

# ============================================================
# ANA TARAMA
# ============================================================

def main():
    log.info("============================================")
    log.info("🧠 BIST TREND+PULLBACK+CONFLUENCE ENGINE v3")
    # SÜRÜM KAYDI: requirements.txt "yfinance>=0.2.60" dediği için her
    # çalıştırmada EN SON sürüm kurulur. yfinance'te bozucu değişiklikler
    # sık olur (Yahoo arayüzü değiştikçe kütüphane de değişiyor). Bir gün
    # veri gelmemeye başlarsa, "hangi sürümle çalışıyordu" sorusunu
    # cevaplayabilmek için sürümleri loga yazıyoruz.
    try:
        log.info(f"📦 yfinance {getattr(yf, '__version__', '?')} | pandas {pd.__version__} | numpy {np.__version__}")
    except Exception:
        pass
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

    # KRİTİK: kapanış bildirimleri ZATEN GÖNDERİLDİ. Eğer state'i sadece en
    # sonda kaydedersek ve arada bir çökme olursa, workflow commit adımına hiç
    # ulaşmaz -> pozisyon "hâlâ açık" kalır -> bir sonraki taramada AYNI
    # "hedefe ulaşıldı/stop" mesajı TEKRAR gönderilir. Bu yüzden kapanışları
    # hemen burada kalıcı hale getiriyoruz.
    if closed_count > 0:
        save_state(state)
        log.info("   Kapanışlar kalıcı olarak kaydedildi (mükerrer bildirim koruması).")

    results = []
    error_count = 0

    for i, (ticker, df) in enumerate(all_data.items(), start=1):
        try:
            close, volume = df["Close"], df["Volume"]
            if close.iloc[-1] <= 0:
                continue

            turnover = close * volume
            if turnover.tail(5).mean() < MIN_TURNOVER_TL:
                continue

            # ZigZag SADECE BİR KEZ hesaplanır; trend/pullback/confluence/direnç
            # HEPSİ aynı pivot noktalarını kullanır -- tutarlılık garantisi.
            swing_highs, swing_lows = compute_zigzag(df)

            trend = trend_filter(df, swing_highs, swing_lows)
            if not trend.get("above200"):
                continue

            pullback = detect_pullback(df, swing_highs, swing_lows)
            if not pullback["ok"]:
                continue

            confluence = evaluate_confluence(df, pullback, swing_highs, swing_lows)
            resistances = find_resistances(df, swing_highs, close)
            levels = calc_levels(df, pullback, resistances)
            if levels is None:
                continue

            rs = relative_strength(close, xu100_close)
            cp = float(close.iloc[-1])

            # ÖNEMLİ DÜZELTME: "Ana Kırılım" kontrolü, find_resistances'ın bulduğu
            # (yapı gereği HER ZAMAN cp'nin üzerinde olan) bir seviyeye göre DEĞİL,
            # pullback'in KENDİ tepesine göre yapılıyor. Aksi halde "cp >= direnç"
            # koşulu, direnç zaten "cp'nin üzerinde" seçildiği için MATEMATİKSEL
            # OLARAK ASLA doğru olamazdı (bulundu ve test edildi).
            stage = determine_stage(trend, pullback, confluence, levels, cp, pullback["peak_price"])
            if stage is None:
                continue

            score = compute_score(trend, pullback, confluence, rs, levels["rr1"])
            fib = get_confirmed_fib_leg(pullback["peak_idx"], pullback["peak_price"], swing_lows)

            results.append({
                "ticker": ticker, "close": cp, "score": score,
                "confluence": confluence, "pullback": pullback, "levels": levels,
                "rs": rs, "stage": stage, "fib": fib,
            })

        except Exception as e:
            # ÖNEMLİ: eskiden burası SESSİZCE atlıyordu (sadece 'continue').
            # Bu yüzden gerçek bir kod hatası (ör. bulunan ZigZag boş-index
            # çökmesi) fark edilmeden onlarca hisseyi analiz dışı bırakabiliyordu.
            # Artık sayılıyor ve loglanıyor; toplu bir sorun varsa tarama
            # sonunda uyarı olarak da görünüyor.
            error_count += 1
            if error_count <= 5:  # log'u boğmamak için sadece ilk birkaçını detaylı yaz
                log.warning(f"{ticker}: analiz hatası -> {type(e).__name__}: {e}")
            continue

        if i % 50 == 0:
            log.info(f"  ...{i} hisse analiz edildi")

    if error_count > 0:
        log.warning(f"⚠️ {error_count} hisse analiz sırasında hata verdi ve atlandı.")
        if error_count > len(all_data) * 0.10:
            send_telegram(
                f"⚠️ *TARAMA UYARISI*\n\n{error_count}/{len(all_data)} hisse analiz "
                f"sırasında hata verdi. Bu turdaki sonuçlar eksik olabilir — "
                f"GitHub Actions loglarını kontrol edin."
            )

    stage_order = {"MAIN_BREAK": 4, "LOCAL_BREAK": 3, "EXTENDED": 2, "SETUP": 1, "WATCH": 0}
    results.sort(key=lambda x: (stage_order[x["stage"]], x["score"]), reverse=True)

    sent_counts = {"MAIN_BREAK": 0, "LOCAL_BREAK": 0, "EXTENDED": 0, "SETUP": 0, "WATCH": 0}
    max_counts = {
        "MAIN_BREAK": MAX_MAIN_BREAK_ALERTS, "LOCAL_BREAK": MAX_LOCAL_BREAK_ALERTS,
        "EXTENDED": MAX_EXTENDED_ALERTS, "SETUP": MAX_SETUP_ALERTS, "WATCH": MAX_WATCH_ALERTS,
    }

    for item in results:
        stage = item["stage"]
        ticker = item["ticker"]
        prev = get_previous_state(state, ticker)
        prev_stage = prev.get("stage") if prev else None

        stage_changed = prev_stage != stage
        score_improved = prev is not None and item["score"] >= (prev.get("score") or 0) + 8

        # WATCH artık SINIRLI olarak mesaj gönderir: sadece en yüksek skorlu
        # MAX_WATCH_ALERTS tanesi. `results` önce aşamaya sonra skora göre
        # sıralı geldiği için, WATCH'lar kendi içinde skora göre sıralıdır --
        # yani ilk karşılaşılanlar en güçlü olanlardır. Geri kalanı yine
        # sadece günlük özette listelenir (bildirim gürültüsü olmasın diye).
        if sent_counts[stage] >= max_counts[stage]:
            update_state(state, ticker, stage, item["score"], item["confluence"]["rvol"], item["close"])
            continue

        should_notify = stage_changed or score_improved

        if should_notify:
            # v5 YENİ (2): Aşama YÜKSELDİYSE, mesajın başına bunu belirten bir
            # satır eklenir ("Kurulum Hazır -> Erken Kırılım"). Böylece bir
            # hissenin olgunlaştığı an ("tren kalkıyor") net görünür.
            upgrade_line = ""
            # İlerleme tespiti KRONOLOJİK sıralamadan (STAGE_PROGRESS) yapılır,
            # görüntüleme önceliğinden (stage_order) DEĞİL -- ikisi farklı şeyler.
            # EXTENDED'e geçişte bu satır GÖSTERİLMEZ: teknik olarak ileri bir
            # aşama ama "aşırı uzamış, kovalama riski" uyarısıdır; başına
            # "⬆️ AŞAMA YÜKSELDİ" yazmak yanıltıcı olur (başlık zaten uyarıyor).
            if (prev_stage and stage != "EXTENDED"
                    and STAGE_PROGRESS.get(stage, 0) > STAGE_PROGRESS.get(prev_stage, 0)):
                # Sadece ÖNCEKİ aşamayı yaz -- yeni aşama zaten hemen altındaki
                # başlıkta görünüyor, tekrar etmeye gerek yok.
                upgrade_line = f"⬆️ *AŞAMA YÜKSELDİ* — önceki: {STAGE_INFO[prev_stage]['baslik']}\n\n"

            msg = upgrade_line + build_message(ticker, item)
            send_telegram(msg)
            sent_counts[stage] += 1
            time.sleep(MESSAGE_DELAY_SECONDS)

            # Sadece gerçekten tetiklenmiş (LOCAL_BREAK/MAIN_BREAK/EXTENDED)
            # ve YENİ gönderilen bir sinyal için takip pozisyonu açılır.
            if stage in TRACKED_STAGES:
                mevcut_pozisyon = prev.get("position") if isinstance(prev, dict) else None

                # KRİTİK DÜZELTME: Zaten AÇIK bir pozisyon varsa ÜZERİNE YAZILMAZ.
                # Eskiden yazılıyordu ve bu, aşamalar gidip geldiğinde
                # (ör. MAIN_BREAK -> WATCH -> MAIN_BREAK) üç ayrı soruna yol
                # açıyordu:
                #  1) İlk pozisyon hiç sonuçlanmadan siliniyordu -> gerçekleşen
                #     zarar geçmişe HİÇ yazılmıyor, performans istatistikleri
                #     olduğundan iyi görünüyordu.
                #  2) Fiyat düştüğü için stop yeniden ve DAHA AŞAĞIDAN
                #     hesaplanıyordu -> risk sessizce büyüyordu.
                #  3) Zaman aşımı sayacı sıfırlanıyordu -> sürekli gidip gelen
                #     bir hisse asla zaman aşımına düşmüyordu.
                # Artık açık pozisyon, hedefe/stopa/zaman aşımına ulaşana kadar
                # OLDUĞU GİBİ korunur; yeni pozisyon ancak eski kapandıysa açılır.
                if mevcut_pozisyon:
                    update_state(state, ticker, stage, item["score"],
                                 item["confluence"]["rvol"], item["close"])
                else:
                    l = item["levels"]
                    new_position = {
                        "entry": l["entry_trigger"], "stop": l["stop"],
                        "target1": l["target1"], "target2": l["target2"],
                        "opened_date": datetime.now().strftime("%Y-%m-%d"),
                    }
                    update_state(state, ticker, stage, item["score"],
                                 item["confluence"]["rvol"], item["close"], position=new_position)
                continue  # update_state zaten çağrıldı, aşağıdaki genel çağrıyı atla

        update_state(state, ticker, stage, item["score"], item["confluence"]["rvol"], item["close"])

    # --- v4 YENİ: günlük özet mesajı (her taramada gönderilir, sessizlik ile arıza ayrımı için) ---
    stage_counts_all = {}
    for item in results:
        stage_counts_all[item["stage"]] = stage_counts_all.get(item["stage"], 0) + 1

    # DİKKAT: HISTORY_KEY (liste) ve PERF_LAST_SENT_KEY (string) birer ticker
    # DEĞİL, özel anahtarlar -- .get("position") çağrısı bunlarda ÇÖKER, o
    # yüzden isinstance kontrolüyle hariç tutuyoruz.
    open_positions_count = sum(
        1 for k, v in state.items()
        if k not in (HISTORY_KEY, PERF_LAST_SENT_KEY) and isinstance(v, dict) and v.get("position")
    )

    # DÜZELTME: results, ÖNCE aşamaya sonra skora göre sıralı olduğu için
    # results[:3] almak "en yüksek skorlu 3" DEĞİL, "en ileri aşamadaki 3"
    # veriyordu -- başlık "En güçlü" dediği halde düşük skorlu bir hisse
    # yüksek skorlunun önüne geçebiliyordu (ör. ALARK 78.2 > SOKM 82.3).
    # Artık gerçekten skora göre sıralanıyor.
    #
    # EK: aşama emojisi de gönderiliyor. Çünkü skor ("kurulum ne kadar iyi")
    # ile aşama ("fiyat nerede") FARKLI şeylerdir: en yüksek skorlu hisse
    # WATCH'ta olabilir ve o zaman ayrı mesaj GÖNDERİLMEZ. Emoji olmadan
    # "listede başta ama mesajı gelmedi" durumu kafa karıştırıyordu.
    top3 = [(item["ticker"], item["score"], item["stage"])
            for item in sorted(results, key=lambda x: x["score"], reverse=True)[:3]]

    # v5 YENİ: WATCH hisseleri artık ayrı mesaj almıyor, özette listeleniyor.
    # Skorla birlikte gönderiliyor ki ilk 3'ü skoruyla gösterilebilsin.
    # results zaten skora göre sıralı geldiği için liste de sıralı olur.
    watch_list = [(item["ticker"], item["score"]) for item in results if item["stage"] == "WATCH"]

    summary_msg = build_summary_message(stage_counts_all, len(all_data), len(BIST_TUM_LISTESI), open_positions_count, regime_ok, top3, watch_list)
    send_telegram(summary_msg)

    maybe_send_performance_summary(state)

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
