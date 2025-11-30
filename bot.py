# bot.py
import os
import time
import json
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from functools import wraps
from flask import Flask, request, abort

import pytz
import requests
import telebot
from telebot import types

# ---------------------------
# ============ AYARLAR =======
# ---------------------------
# Sabitler (soru metnine göre)
NAMAZ_ALTIN_KAZANCI = 10
CIVCIV_COST_ALTIN = 50
REF_YEM_SAHIBI = 3
MAX_CIVCIV_OR_TAVUK = 8
EGG_SATIS_DEGERI = 0.10
MIN_EGG_SATIS = 10

GLOBAL_TIME_OFFSET_MINUTES = 0  # Aladhan düzeltme
EGG_INTERVAL_HOURS = 6  # Tavuk başına yumurta süresi (varsayılan, gerektiğinde değiştir)
DATA_SAVE_INTERVAL_SECONDS = 60  # periyodik kaydetme
PERIODIC_CHECK_SECONDS = 60

# Dosyalar / ortam
DATA_FILE = "user_data.json"
LOG_FILE = "bot.log"

# Zaman dilimi - talimatlarda Istanbul verildi
TZ = pytz.timezone("Europe/Istanbul")

# Telegram / Render ortam değişkenleri
BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")  # e.g. myapp.onrender.com
PORT = int(os.getenv("PORT", "5000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

WEBHOOK_PATH = f"/{BOT_TOKEN}"
if RENDER_EXTERNAL_HOSTNAME:
    WEBHOOK_URL_BASE = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    WEBHOOK_URL = f"{WEBHOOK_URL_BASE}{WEBHOOK_PATH}"
else:
    WEBHOOK_URL = None

# Logging
logging.basicConfig(level=logging.INFO, filename=LOG_FILE,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------
# ============ TELEBOT =======
# ---------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ---------------------------
# ============ DATA LAYER ====
# ---------------------------
data_lock = threading.Lock()
data: Dict[str, Any] = {"users": {}, "meta": {"last_daily_reset": None, "week_start": None}}

def load_data():
    global data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info("Data loaded.")
        except Exception as e:
            logger.exception("Failed to load data: %s", e)
            data = {"users": {}, "meta": {"last_daily_reset": None, "week_start": None}}
    else:
        data = {"users": {}, "meta": {"last_daily_reset": None, "week_start": None}}
        save_data()

def save_data():
    with data_lock:
        tmp = f"{DATA_FILE}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_FILE)
            logger.info("Data saved.")
        except Exception as e:
            logger.exception("Failed to save data: %s", e)

def ensure_user(user_id: int, first_name: str = ""):
    uid = str(user_id)
    with data_lock:
        if uid not in data["users"]:
            data["users"][uid] = {
                "id": user_id,
                "first_name": first_name or "",
                "altin": 0,
                "yem": 0,
                "sellable_eggs": 0,
                "ranking_eggs": 0,
                "location": "",
                "namaz_today": [],
                "daily_tasks_done": [],
                "civciv_list": [],  # list of dicts
                "created_at": datetime.now(TZ).isoformat(),
                "last_namaz_mark": {},  # namaz_name -> iso timestamp
            }
            save_data()
        return data["users"][uid]

# ---------------------------
# ============ HELPERS =======
# ---------------------------
def only_private(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.chat.type != "private":
            bot.reply_to(message, "Lütfen bu komutu özel sohbet üzerinden kullan.")
            return
        return func(message, *args, **kwargs)
    return wrapper

def build_main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [
        "📖 Oyun Nasıl Oynanır?",
        "📊 Genel Durum",
        "🕌 Namaz Takibi",
        "📋 Günlük Görevler",
        "🍗 Civciv Besle",
        "🛒 Civciv Pazarı",
        "🥚 Yumurta Pazarı",
        "🏆 Haftalık Sıralama",
        "🔗 Referans Sistemi",
        "📍 Konum Güncelle"
    ]
    for i in range(0, len(buttons), 2):
        row = []
        row.append(types.KeyboardButton(buttons[i]))
        if i+1 < len(buttons):
            row.append(types.KeyboardButton(buttons[i+1]))
        markup.row(*row)
    return markup

def format_user_status(u: Dict[str, Any]) -> str:
    lines = [
        f"👤 {u.get('first_name','Kullanıcı')}",
        f"💰 Altın: {u.get('altin',0)}",
        f"🌾 Yem: {u.get('yem',0)}",
        f"🥚 Satılabilir Yumurta: {u.get('sellable_eggs',0)}",
        f"🏅 Haftalık Puan (ranking_eggs): {u.get('ranking_eggs',0)}",
        f"📍 Konum: {u.get('location','Belirtilmedi')}",
        f"🐥 Civciv/Tavuk Sayısı: {len(u.get('civciv_list',[]))}"
    ]
    return "\n".join(lines)

def fetch_prayer_times(city: str = None, country: str = "Turkey") -> Dict[str, str]:
    """
    Basit çağrı: Aladhan API method=9. city param optional; fallback to Turkey-wide if not set.
    Returns dict of prayer_name -> time string (HH:MM)
    """
    try:
        params = {"method": 9}
        if city:
            url = f"http://api.aladhan.com/v1/timingsByCity"
            params.update({"city": city, "country": country, "school": 1})
        else:
            # fallback: Istanbul
            url = f"http://api.aladhan.com/v1/timingsByCity"
            params.update({"city": "Istanbul", "country": "Turkey", "school": 1})
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 200:
            return {}
        timings = payload["data"]["timings"]
        # apply GLOBAL_TIME_OFFSET_MINUTES
        out = {}
        for k, v in timings.items():
            # v like "05:12"
            try:
                hh, mm = map(int, v.split(":")[:2])
                dt = datetime.now(TZ).replace(hour=hh, minute=mm, second=0, microsecond=0)
                dt = dt + timedelta(minutes=GLOBAL_TIME_OFFSET_MINUTES)
                out[k] = dt.strftime("%H:%M")
            except:
                out[k] = v
        return out
    except Exception as e:
        logger.exception("Namaz vakti çekilemedi: %s", e)
        return {}

# ---------------------------
# ============ START HANDLER ==
# ---------------------------
@bot.message_handler(commands=['start'])
def handle_start(message: types.Message):
    try:
        args = ""
        if message.text and len(message.text.split()) > 1:
            args = message.text.split(maxsplit=1)[1].strip()
        user = ensure_user(message.from_user.id, message.from_user.first_name or "")
        # referral logic
        if args.startswith("ref"):
            try:
                ref_id = args[3:]
                # Only inviter gets reward
                inviter = data["users"].get(str(ref_id))
                if inviter:
                    inviter["yem"] = inviter.get("yem", 0) + REF_YEM_SAHIBI
                    save_data()
                    try:
                        bot.send_message(inviter["id"], "Tebrikler! +3 Yem kazandın.")
                    except Exception:
                        logger.exception("Referans sahibine bildirim gönderilemedi.")
            except Exception:
                logger.exception("ref processing error")
        # If user has no location, prompt for location after welcome
        txt = f"Selamün Aleyküm, {message.from_user.first_name or 'kardeşim'}! 🕌\n\n" \
              "İbadet Çiftliği Botuna hoş geldin. Oyuna başlamak için konumunu 'İl/İlçe' formatında paylaşmanı istiyorum (ör: İstanbul/Beşiktaş)."
        markup = build_main_menu()
        bot.send_message(message.chat.id, txt, reply_markup=markup)
        if not data["users"][str(message.from_user.id)].get("location"):
            msg = bot.send_message(message.chat.id, "Lütfen konumunu 'İl/İlçe' formatında yaz.", reply_markup=types.ForceReply(selective=True))
            # next message handled by text handler saving location
    except Exception as e:
        logger.exception("start handler error: %s", e)

# ---------------------------
# ============ TEXT HANDLER ===
# ---------------------------
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message: types.Message):
    try:
        user = ensure_user(message.from_user.id, message.from_user.first_name or "")
        text = message.text.strip()

        # Konum güncelleme isteği veya kullanıcı yeni ve yazıyorsa 'İl/İlçe' formatı
        if text == "📍 Konum Güncelle" or ("/start" not in text and "/" in text and len(text.split("/")) >= 2):
            # treat as location update
            parts = text.split("/")
            if len(parts) >= 2:
                user["location"] = text
                save_data()
                bot.reply_to(message, f"Konum kaydedildi: {text}", reply_markup=build_main_menu())
                return
            else:
                bot.reply_to(message, "Konum hatalı. Lütfen 'İl/İlçe' formatında yeniden yazınız.")
                return

        # Menu options
        if text == "📖 Oyun Nasıl Oynanır?":
            bot.send_message(message.chat.id,
                             "İbadet Çiftliği: Namaz kılarak altın kazanır, civciv alır, beslersin. 10 yem ile civciv tavuk olur ve yumurta üretir. Yumurtaları satıp altın kazan.\n\n"
                             "Detaylı komutlar ana menüden seçilebilir.", reply_markup=build_main_menu())
            return

        if text == "📊 Genel Durum":
            bot.send_message(message.chat.id, format_user_status(user), reply_markup=build_main_menu())
            return

        if text == "🕌 Namaz Takibi":
            send_prayer_menu(message)
            return

        if text == "📋 Günlük Görevler":
            send_daily_tasks(message)
            return

        if text == "🍗 Civciv Besle":
            send_feed_menu(message)
            return

        if text == "🛒 Civciv Pazarı":
            send_civciv_market(message)
            return

        if text == "🥚 Yumurta Pazarı":
            bot.send_message(message.chat.id, "Kaç adet yumurta satmak istiyorsunuz? (Sayısal değer giriniz)\nMinimum: " + str(MIN_EGG_SATIS),
                             reply_markup=types.ForceReply(selective=True))
            # Next message numeric handler handles it
            return

        if text == "🏆 Haftalık Sıralama":
            send_weekly_ranking(message)
            return

        if text == "🔗 Referans Sistemi":
            bot_name = os.getenv("BOT_USERNAME") or "YOUR_BOT_NAME"
            uid = message.from_user.id
            link = f"https://t.me/{bot_name}?start=ref{uid}"
            bot.send_message(message.chat.id, f"Davet linkiniz: {link}\nNot: Davet eden kişi +3 yem alır, yeni kullanıcıya ödül gitmez.", reply_markup=build_main_menu())
            return

        # If user wrote a number in response to Yumurta Pazarı:
        if text.isdigit():
            num = int(text)
            if user.get("sellable_eggs", 0) < num:
                bot.send_message(message.chat.id, "Yeterli satılabilir yumurta yok. İşlem iptal edildi.", reply_markup=build_main_menu())
                return
            if num < MIN_EGG_SATIS:
                bot.send_message(message.chat.id, f"Minimum satış adedi {MIN_EGG_SATIS}. İşlem iptal edildi.", reply_markup=build_main_menu())
                return
            # proceed sale
            gained = round(num * EGG_SATIS_DEGERI, 2)
            user["sellable_eggs"] -= num
            user["altin"] = round(user.get("altin", 0) + gained, 2)
            save_data()
            bot.send_message(message.chat.id, f"{num} yumurta satıldı. Kazanç: {gained} Altın.", reply_markup=build_main_menu())
            return

        # fallback
        bot.send_message(message.chat.id, "Seçiminizi menüden yapınız.", reply_markup=build_main_menu())

    except Exception as e:
        logger.exception("text handler error: %s", e)
        try:
            bot.send_message(message.chat.id, "Bir hata oluştu. Lütfen tekrar deneyiniz.", reply_markup=build_main_menu())
        except:
            pass

# ---------------------------
# ============ PRAYER MENU ===
# ---------------------------
def send_prayer_menu(message: types.Message):
    try:
        user = ensure_user(message.from_user.id, message.from_user.first_name or "")
        loc = user.get("location")
        city = None
        if loc:
            city = loc.split("/")[0]
        times = fetch_prayer_times(city)
        if not times:
            bot.send_message(message.chat.id, "Namaz vakitleri alınamadı. Lütfen daha sonra tekrar deneyin.", reply_markup=build_main_menu())
            return
        text_lines = ["Bugünkü namaz vakitleri:"]
        important = ["Fajr","Dhuhr","Asr","Maghrib","Isha"]
        for k in important:
            t = times.get(k) or times.get(k.capitalize()) or times.get(k.lower(), "—")
            text_lines.append(f"{k}: {t}")
        text = "\n".join(text_lines)
        markup = types.InlineKeyboardMarkup()
        for k in important:
            btn = types.InlineKeyboardButton(f"{k} - Kıldım", callback_data=f"mark_namaz|{k}")
            markup.add(btn)
        bot.send_message(message.chat.id, text, reply_markup=markup)
    except Exception as e:
        logger.exception("send_prayer_menu error: %s", e)
        bot.send_message(message.chat.id, "Namaz takibi sırasında hata oluştu.", reply_markup=build_main_menu())

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("mark_namaz"))
def callback_mark_namaz(call: types.CallbackQuery):
    try:
        _, namaz = call.data.split("|", 1)
        user = ensure_user(call.from_user.id, call.from_user.first_name or "")
        # Check 24h rule
        last_marks = user.get("last_namaz_mark", {})
        last_iso = last_marks.get(namaz)
        can_mark = True
        if last_iso:
            try:
                last_dt = datetime.fromisoformat(last_iso)
                if last_dt.tzinfo is None:
                    last_dt = TZ.localize(last_dt)
                if datetime.now(TZ) - last_dt < timedelta(hours=24):
                    can_mark = False
            except Exception:
                pass
        if not can_mark:
            bot.answer_callback_query(call.id, f"{namaz} zaten son 24 saatte işaretlendi.", show_alert=True)
            return
        # mark
        now_iso = datetime.now(TZ).isoformat()
        user["last_namaz_mark"][namaz] = now_iso
        # add to namaz_today if not present
        if namaz not in user["namaz_today"]:
            user["namaz_today"].append(namaz)
        user["altin"] = round(user.get("altin", 0) + NAMAZ_ALTIN_KAZANCI, 2)
        save_data()
        bot.answer_callback_query(call.id, f"{namaz} için +{NAMAZ_ALTIN_KAZANCI} Altın verildi.")
        bot.send_message(call.from_user.id, f"{namaz} işaretlendi. +{NAMAZ_ALTIN_KAZANCI} Altın kazandınız.", reply_markup=build_main_menu())
    except Exception as e:
        logger.exception("callback mark namaz error: %s", e)
        bot.answer_callback_query(call.id, "Bir hata oldu.")

# ---------------------------
# ============ DAILY TASKS ===
# ---------------------------
DAILY_TASKS = [
    ("zikir_la_ilahe_illallah", "50 Kez La İlahe İllallah Çek", 1),
    ("zikir_salavat", "50 Kez Salavat Çek", 1),
    ("zikir_estagfirullah", "50 Kez Estağfirullah Çek", 1),
    ("zikir_subhanallah", "50 Kez Subhanallahi ve Bihamdihi Çek", 1),
    ("kaza_nafile", "1 Adet Kaza/Nafile Namazı Kıl", 2),
]

def send_daily_tasks(message: types.Message):
    try:
        user = ensure_user(message.from_user.id, message.from_user.first_name or "")
        done = set(user.get("daily_tasks_done", []))
        text = "Günlük Görevler:\n\n"
        markup = types.InlineKeyboardMarkup()
        for key, desc, reward in DAILY_TASKS:
            status = "✅" if key in done else "◻️"
            text += f"{status} {desc} — Ödül: {reward} Yem\n"
            if key not in done:
                markup.add(types.InlineKeyboardButton(f"Tamamla: {desc}", callback_data=f"task_done|{key}|{reward}"))
        bot.send_message(message.chat.id, text, reply_markup=markup if markup.keyboard else None)
    except Exception as e:
        logger.exception("send_daily_tasks error: %s", e)
        bot.send_message(message.chat.id, "Görevler alınamadı.", reply_markup=build_main_menu())

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("task_done"))
def callback_task_done(call: types.CallbackQuery):
    try:
        _, key, reward = call.data.split("|")
        reward = int(reward)
        user = ensure_user(call.from_user.id, call.from_user.first_name or "")
        if key in user.get("daily_tasks_done", []):
            bot.answer_callback_query(call.id, "Bu görev zaten tamamlanmış.")
            return
        user["daily_tasks_done"].append(key)
        user["yem"] = user.get("yem", 0) + reward
        save_data()
        bot.answer_callback_query(call.id, f"Görev tamamlandı. +{reward} Yem verildi.")
        bot.send_message(call.from_user.id, f"Görev tamamlandı. +{reward} Yem verildi.", reply_markup=build_main_menu())
    except Exception as e:
        logger.exception("callback task done error: %s", e)
        bot.answer_callback_query(call.id, "Bir hata oluştu.")

# ---------------------------
# ============ CIVCIV MARKET & FEED ==
# ---------------------------
def send_civciv_market(message: types.Message):
    try:
        user = ensure_user(message.from_user.id, message.from_user.first_name or "")
        # Check limit
        civcount = len([c for c in user.get("civciv_list", []) if c.get("status") == "civciv"])
        if civcount >= MAX_CIVCIV_OR_TAVUK:
            bot.send_message(message.chat.id, f"Civciv alım limiti: {MAX_CIVCIV_OR_TAVUK}. Daha fazla civciv alamazsınız.", reply_markup=build_main_menu())
            return
        text = f"Civciv satın almak için {CIVCIV_COST_ALTIN} Altın gerekiyor. Mevcut Altınınız: {user.get('altin',0)}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Civciv Satın Al", callback_data="buy_civciv"))
        bot.send_message(message.chat.id, text, reply_markup=markup)
    except Exception as e:
        logger.exception("civciv market error: %s", e)
        bot.send_message(message.chat.id, "Market açılamadı.", reply_markup=build_main_menu())

@bot.callback_query_handler(func=lambda c: c.data == "buy_civciv")
def callback_buy_civciv(call: types.CallbackQuery):
    try:
        user = ensure_user(call.from_user.id, call.from_user.first_name or "")
        # enforce limits: count only civciv status for limit
        civcount = len([c for c in user.get("civciv_list", []) if c.get("status") == "civciv"])
        if civcount >= MAX_CIVCIV_OR_TAVUK:
            bot.answer_callback_query(call.id, "Civciv limiti dolu.")
            return
        if user.get("altin", 0) < CIVCIV_COST_ALTIN:
            bot.answer_callback_query(call.id, "Yeterli altın yok.")
            return
        user["altin"] = round(user.get("altin", 0) - CIVCIV_COST_ALTIN, 2)
        # create civciv
        c = {
            "id": int(time.time()*1000),
            "color": "Sarı Civciv",
            "status": "civciv",
            "yem_count": 0,
            "next_egg_time": None  # not until tavuk
        }
        user["civciv_list"].append(c)
        save_data()
        bot.answer_callback_query(call.id, "Civciv satın alındı.")
        bot.send_message(call.from_user.id, "Civciv satın alındı. Beslemek için '🍗 Civciv Besle' menüsünü kullanın.", reply_markup=build_main_menu())
    except Exception as e:
        logger.exception("buy civciv callback error: %s", e)
        bot.answer_callback_query(call.id, "Bir hata oldu.")

def send_feed_menu(message: types.Message):
    try:
        user = ensure_user(message.from_user.id, message.from_user.first_name or "")
        civs = user.get("civciv_list", [])
        if not civs:
            bot.send_message(message.chat.id, "Hiç civciviniz yok. Civciv pazardan alın.", reply_markup=build_main_menu())
            return
        markup = types.InlineKeyboardMarkup()
        for c in civs:
            label = f"{c.get('color')} - {c.get('status')} - Yem:{c.get('yem_count',0)}"
            markup.add(types.InlineKeyboardButton(label, callback_data=f"feed|{c.get('id')}"))
        bot.send_message(message.chat.id, "Beslemek istediğiniz hayvanı seçin (1 yem harcar):", reply_markup=markup)
    except Exception as e:
        logger.exception("send_feed_menu error: %s", e)
        bot.send_message(message.chat.id, "Besleme menüsü açılmadı.", reply_markup=build_main_menu())

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("feed|"))
def callback_feed(call: types.CallbackQuery):
    try:
        _, cid = call.data.split("|", 1)
        user = ensure_user(call.from_user.id, call.from_user.first_name or "")
        if user.get("yem", 0) < 1:
            bot.answer_callback_query(call.id, "Yeterli yem yok.")
            return
        # find civ
        civ = next((x for x in user.get("civciv_list", []) if str(x.get("id")) == cid), None)
        if not civ:
            bot.answer_callback_query(call.id, "Hayvan bulunamadı.")
            return
        user["yem"] -= 1
        civ["yem_count"] = civ.get("yem_count", 0) + 1
        # if reaches 10 -> becomes tavuk
        if civ["status"] == "civciv" and civ["yem_count"] >= 10:
            civ["status"] = "tavuk"
            # schedule first egg
            civ["next_egg_time"] = (datetime.now(TZ) + timedelta(hours=EGG_INTERVAL_HOURS)).isoformat()
            bot.send_message(call.from_user.id, "Tebrikler! Civciv tavuk oldu ve yumurta üretimine başlayacak.")
        save_data()
        bot.answer_callback_query(call.id, "Beslediniz. -1 Yem.")
    except Exception as e:
        logger.exception("feed callback error: %s", e)
        bot.answer_callback_query(call.id, "Bir hata oluştu.")

# ---------------------------
# ============ WEEKLY RANKING ==
# ---------------------------
def send_weekly_ranking(message: types.Message):
    try:
        with data_lock:
            users = list(data.get("users", {}).values())
        users_sorted = sorted(users, key=lambda u: u.get("ranking_eggs", 0), reverse=True)[:10]
        if not users_sorted:
            bot.send_message(message.chat.id, "Sıralama boş.")
            return
        text = "Haftalık Sıralama (ilk 10):\n\n"
        i = 1
        for u in users_sorted:
            text += f"{i}. {u.get('first_name','-')} — {u.get('ranking_eggs',0)} yumurta puanı\n"
            i += 1
        bot.send_message(message.chat.id, text, reply_markup=build_main_menu())
    except Exception as e:
        logger.exception("ranking error: %s", e)
        bot.send_message(message.chat.id, "Sıralama alınamadı.", reply_markup=build_main_menu())

# ---------------------------
# ============ BACKGROUND TASKS ==
# ---------------------------
def egg_production_worker():
    """Periyodik olarak tavukların next_egg_time kontrolü ve üretim"""
    while True:
        try:
            now = datetime.now(TZ)
            changed = False
            with data_lock:
                for uid, u in data.get("users", {}).items():
                    for c in u.get("civciv_list", []):
                        if c.get("status") == "tavuk":
                            next_iso = c.get("next_egg_time")
                            if next_iso:
                                try:
                                    nxt = datetime.fromisoformat(next_iso)
                                    if nxt.tzinfo is None:
                                        nxt = TZ.localize(nxt)
                                except Exception:
                                    nxt = datetime.fromisoformat(next_iso)
                                if now >= nxt:
                                    # produce egg
                                    u["sellable_eggs"] = u.get("sellable_eggs", 0) + 1
                                    u["ranking_eggs"] = u.get("ranking_eggs", 0) + 1
                                    # schedule next egg
                                    c["next_egg_time"] = (nxt + timedelta(hours=EGG_INTERVAL_HOURS)).isoformat()
                                    changed = True
                                    # notify user
                                    try:
                                        bot.send_message(int(u["id"]), "🐣 Tavuk yumurta üretti! Yumurtanızı kontrol edin.")
                                    except Exception:
                                        logger.exception("notify egg production failed for user %s", u.get("id"))
            if changed:
                save_data()
        except Exception as e:
            logger.exception("egg_production_worker error: %s", e)
        time.sleep(PERIODIC_CHECK_SECONDS)

def daily_reset_worker():
    """Günlük görev ve sayaç sıfırlama (gün değişince çalışır)"""
    last_reset_date = None
    while True:
        try:
            now = datetime.now(TZ)
            today_date = now.date()
            if last_reset_date is None or today_date != last_reset_date:
                # perform reset (once per day at midnight Istanbul)
                with data_lock:
                    for uid, u in data.get("users", {}).items():
                        u["namaz_today"] = []
                        u["daily_tasks_done"] = []
                        # Note: do not touch ranking_eggs
                    data["meta"]["last_daily_reset"] = datetime.now(TZ).isoformat()
                save_data()
                logger.info("Daily reset completed.")
                last_reset_date = today_date
        except Exception as e:
            logger.exception("daily_reset_worker error: %s", e)
        # sleep until next check
        time.sleep(60)

def periodic_save_worker():
    while True:
        try:
            save_data()
        except Exception as e:
            logger.exception("periodic_save error: %s", e)
        time.sleep(DATA_SAVE_INTERVAL_SECONDS)

# ---------------------------
# ============ FLASK / WEBHOOK ==
# ---------------------------
@app.route("/")
def index():
    return "İbadet Çiftliği Botu çalışıyor."

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        try:
            bot.process_new_updates([update])
        except Exception as e:
            logger.exception("process update error: %s", e)
        return "", 200
    else:
        abort(403)

def setup_webhook():
    try:
        bot.remove_webhook()
    except Exception:
        pass
    if WEBHOOK_URL:
        # Ensure webhook set
        success = bot.set_webhook(url=WEBHOOK_URL)
        if success:
            logger.info("Webhook kuruldu: %s", WEBHOOK_URL)
        else:
            logger.error("Webhook kurulamadı: %s", WEBHOOK_URL)
    else:
        logger.warning("WEBHOOK_URL yapılandırılmamış. RENDER_EXTERNAL_HOSTNAME yok.")

# ---------------------------
# ============ STARTUP =======
# ---------------------------
def start_background_tasks():
    threads = []
    t1 = threading.Thread(target=egg_production_worker, daemon=True, name="egg_worker")
    t2 = threading.Thread(target=daily_reset_worker, daemon=True, name="daily_reset")
    t3 = threading.Thread(target=periodic_save_worker, daemon=True, name="periodic_save")
    threads.extend([t1, t2, t3])
    for t in threads:
        t.start()
    logger.info("Background threads started.")

if __name__ == "__main__":
    # load data, setup webhook, start threads, run flask (gunicorn recommended on render)
    load_data()
    start_background_tasks()
    setup_webhook()
    # If running directly (dev), use Flask dev server
    app.run(host="0.0.0.0", port=PORT)
