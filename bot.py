# bot.py
import os
import time
import json
import threading
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, abort
import telebot
import requests

# =================================================================
# SABİTLER VE AYARLAR
# =================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{BOT_TOKEN}"
NAMAZ_ALTIN_KAZANCI = 10
CIVCIV_COST_ALTIN = 50
REF_YEM_SAHIBI = 3
MAX_CIVCIV_OR_TAVUK = 8
EGG_SATIS_DEGERI = 0.10
MIN_EGG_SATIS = 10
EGG_INTERVAL_HOURS = 12
GLOBAL_TIME_OFFSET_MINUTES = 0
DATA_FILE = "user_data.json"

# =================================================================
# VERİ YÖNETİMİ
# =================================================================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

user_data = load_data()

# =================================================================
# TELEGRAM BOT AYARLARI
# =================================================================
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# =================================================================
# YARDIMCI FONKSİYONLAR
# =================================================================
def get_user(chat_id):
    if str(chat_id) not in user_data:
        user_data[str(chat_id)] = {
            "altin": 0,
            "yem": 0,
            "sellable_eggs": 0,
            "ranking_eggs": 0,
            "location": "",
            "namaz_today": [],
            "daily_tasks_done": [],
            "civciv_list": []
        }
        save_data(user_data)
    return user_data[str(chat_id)]

def namaz_vakitleri(location):
    # Aladhan API ile namaz vakitlerini çek
    url = f"http://api.aladhan.com/v1/timingsByCity?city={location}&country=Turkey&method=9"
    try:
        resp = requests.get(url).json()
        timings = resp["data"]["timings"]
        # Global offset
        for k in timings:
            t = datetime.strptime(timings[k], "%H:%M")
            t += timedelta(minutes=GLOBAL_TIME_OFFSET_MINUTES)
            timings[k] = t.strftime("%H:%M")
        return timings
    except:
        return {}

# =================================================================
# KOMUTLAR VE MENÜ
# =================================================================
@bot.message_handler(commands=["start"])
def start_handler(message):
    chat_id = message.chat.id
    user = get_user(chat_id)
    if not user["location"]:
        bot.send_message(chat_id, f"Selamün Aleyküm, {message.from_user.first_name}! 🕌\nLütfen il/ilçe bilgini gir.")
        bot.register_next_step_handler(message, set_location)
    else:
        send_main_menu(chat_id)

def set_location(message):
    chat_id = message.chat.id
    text = message.text.strip()
    user = get_user(chat_id)
    user["location"] = text
    save_data(user_data)
    bot.send_message(chat_id, f"Konumunuz {text} olarak kaydedildi.")
    send_main_menu(chat_id)

def send_main_menu(chat_id):
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [
        "📖 Oyun Nasıl Oynanır?", "📊 Genel Durum",
        "🕌 Namaz Takibi", "📋 Günlük Görevler",
        "🍗 Civciv Besle", "🛒 Civciv Pazarı",
        "🥚 Yumurta Pazarı", "🏆 Haftalık Sıralama",
        "🔗 Referans Sistemi", "📍 Konum Güncelle"
    ]
    markup.add(*[telebot.types.KeyboardButton(b) for b in buttons])
    bot.send_message(chat_id, "Ana Menü:", reply_markup=markup)

# =================================================================
# ANA MENÜ BUTONLARI
# =================================================================
@bot.message_handler(func=lambda message: True)
def menu_handler(message):
    chat_id = message.chat.id
    text = message.text
    if text == "📖 Oyun Nasıl Oynanır?":
        bot.send_message(chat_id, "Oyun, civciv besleyip yumurta satma üzerine kuruludur...")
    elif text == "📊 Genel Durum":
        user = get_user(chat_id)
        bot.send_message(chat_id, f"Altın: {user['altin']}\nYem: {user['yem']}\nSatılabilir Yumurta: {user['sellable_eggs']}")
    elif text == "🕌 Namaz Takibi":
        user = get_user(chat_id)
        timings = namaz_vakitleri(user['location'])
        msg = "Namaz Vakitleri:\n" + "\n".join([f"{k}: {v}" for k,v in timings.items()])
        bot.send_message(chat_id, msg)
    elif text == "📋 Günlük Görevler":
        user = get_user(chat_id)
        tasks = [
            ("zikir_la_ilahe_illallah", "50 Kez La İlahe İllallah Çek", 1),
            ("zikir_salavat", "50 Kez Salavat Çek",1),
            ("zikir_estagfirullah", "50 Kez Estağfirullah Çek",1),
            ("zikir_subhanallah", "50 Kez Subhanallahi ve Bihamdihi Çek",1),
            ("kaza_nafile","1 Adet Kaza/Nafile Namazı Kıl",2)
        ]
        msg = ""
        for t in tasks:
            status = "✅" if t[0] in user['daily_tasks_done'] else "◻️"
            msg += f"{status} {t[1]} (Ödül: {t[2]} Yem)\n"
        bot.send_message(chat_id, msg)
    elif text == "🍗 Civciv Besle":
        feed_civciv(chat_id)
    elif text == "🛒 Civciv Pazarı":
        buy_civciv(chat_id)
    elif text == "🥚 Yumurta Pazarı":
        sell_eggs(chat_id)
    elif text == "🏆 Haftalık Sıralama":
        show_ranking(chat_id)
    elif text == "🔗 Referans Sistemi":
        bot.send_message(chat_id, f"Davet Linkin: https://t.me/{bot.get_me().username}?start=ref{chat_id}")
    elif text == "📍 Konum Güncelle":
        bot.send_message(chat_id, "Yeni konumunuzu giriniz:")
        bot.register_next_step_handler(message, set_location)
    else:
        bot.send_message(chat_id, "Lütfen menüden bir seçenek seçiniz.")

# =================================================================
# CİVCİV VE YUMURTA SİSTEMİ
# =================================================================
def feed_civciv(chat_id):
    user = get_user(chat_id)
    if user["yem"] < 1:
        bot.send_message(chat_id, "Yeminiz yeterli değil!")
        return
    if not user["civciv_list"]:
        bot.send_message(chat_id, "Henüz civciviniz yok.")
        return
    user["yem"] -= 1
    for c in user["civciv_list"]:
        if c["status"] == "civciv":
            c["yem_count"] += 1
            if c["yem_count"] >= 10:
                c["status"] = "tavuk"
                c["next_egg_time"] = (datetime.utcnow() + timedelta(hours=EGG_INTERVAL_HOURS)).isoformat()
    save_data(user_data)
    bot.send_message(chat_id, "Civciv beslendi!")

def buy_civciv(chat_id):
    user = get_user(chat_id)
    current_civciv_count = sum(1 for c in user["civciv_list"] if c["status"]=="civciv")
    if user["altin"] < CIVCIV_COST_ALTIN:
        bot.send_message(chat_id, "Altınınız yeterli değil!")
        return
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
        bot.send_message(chat_id, f"Maksimum civciv sayısına ulaştınız ({MAX_CIVCIV_OR_TAVUK})")
        return
    user["altin"] -= CIVCIV_COST_ALTIN
    user["civciv_list"].append({"color":"Sarı Civciv", "status":"civciv", "yem_count":0, "next_egg_time": None})
    save_data(user_data)
    bot.send_message(chat_id, "Yeni civciv satın alındı!")

def sell_eggs(chat_id):
    user = get_user(chat_id)
    if user["sellable_eggs"] < MIN_EGG_SATIS:
        bot.send_message(chat_id, f"Satış için minimum {MIN_EGG_SATIS} yumurta gerekir!")
        return
    sold = user["sellable_eggs"]
    user["altin"] += sold * EGG_SATIS_DEGERI
    user["sellable_eggs"] = 0
    save_data(user_data)
    bot.send_message(chat_id, f"{sold} yumurta satıldı, altın kazandınız!")

def show_ranking(chat_id):
    ranking = sorted(user_data.items(), key=lambda x: x[1]["ranking_eggs"], reverse=True)[:100]
    msg = "🏆 Haftalık Top 100 Sıralama:\n"
    for i, (uid, u) in enumerate(ranking, 1):
        msg += f"{i}. {uid} - {u['ranking_eggs']} yumurta\n"
    bot.send_message(chat_id, msg)

# =================================================================
# ARKA PLAN THREADLERİ
# =================================================================
def egg_production_loop():
    while True:
        now = datetime.utcnow()
        for user in user_data.values():
            for c in user["civciv_list"]:
                if c["status"]=="tavuk" and c["next_egg_time"]:
                    next_time = datetime.fromisoformat(c["next_egg_time"])
                    if now >= next_time:
                        user["sellable_eggs"] += 1
                        user["ranking_eggs"] += 1
                        c["next_egg_time"] = (now + timedelta(hours=EGG_INTERVAL_HOURS)).isoformat()
        save_data(user_data)
        time.sleep(60)

def daily_reset_loop():
    while True:
        now = datetime.utcnow()
        if now.hour == 0 and now.minute == 0:
            for user in user_data.values():
                user["namaz_today"] = []
                user["daily_tasks_done"] = []
            save_data(user_data)
        time.sleep(60)

threading.Thread(target=egg_production_loop, daemon=True).start()
threading.Thread(target=daily_reset_loop, daemon=True).start()

# =================================================================
# FLASK WEBHOOK
# =================================================================
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return ""
    else:
        abort(403)

def setup_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)

setup_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
