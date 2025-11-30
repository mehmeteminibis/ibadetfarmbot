# =================================================================
# BÖLÜM 1/6: KÜTÜPHANELER, SABİTLER VE GLOBAL TANIMLAR
# =================================================================

from flask import Flask
from threading import Thread
import telebot
from telebot import types
import json
import time
import datetime
import requests 
import random
import os 
import re 
from datetime import datetime, timedelta, timezone

# --- ZAMAN DİLİMİ VE BOT NESNESİ ---
TURKEY_TIMEZONE = timezone(timedelta(hours=3))
# BOT_TOKEN, Render Environment Variables'dan okunacak.
BOT_TOKEN = os.getenv("BOT_TOKEN") 
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN ortam değişkeni tanımlanmadı.")
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# --- DOSYA VE API SABİTLERİ ---
DATA_FILE = 'user_data.json'
BOT_USERNAME = 'ibadetciftligi_bot' 
PRAYER_API_URL = "http://api.aladhan.com/v1/timingsByCity"

# ⚠️ NAMAZ VAKTİ DÜZELTME (Yeni Özellik) ⚠️
# Vakitleriniz 15-20 dk hatalıysa, bu değeri değiştirin.
# Örn: Vakit 18 dakika geç okunuyorsa: -18 yazın. 18 dakika erken okunuyorsa: 18 yazın.
GLOBAL_TIME_OFFSET_MINUTES = 0 # Şu an sıfır (0) olarak ayarlı

# --- OYUN EKONOMİSİ SABİTLERİ ---
NAMAZ_ALTIN_KAZANCI = 10
CIVCIV_COST_ALTIN = 50
REF_YEM_SAHIBI = 3           # YENİ: Referans sahibine +3 Yem
YEM_FOR_TAVUK = 10
EGG_INTERVAL_HOURS = 4       
MAX_CIVCIV_OR_TAVUK = 8      # Maksimum civciv slotu (Tavuklar sınırsızdır)
EGG_SATIS_DEGERI = 0.10      # YENİ: 1 Yumurta Kaç Altın?
MIN_EGG_SATIS = 10           # YENİ: Minimum satılabilecek yumurta sayısı

# --- YENİ GÜNLÜK GÖREV LİSTESİ VE ÖDÜLLERİ ---
DAILY_TASKS = {
    'zikir_la_ilahe_illallah': {'text': "50 Kez La İlahe İllallah Çek", 'reward': 1},
    'zikir_salavat': {'text': "50 Kez Salavat Çek", 'reward': 1},
    'zikir_estagfirullah': {'text': "50 Kez Estağfirullah Çek", 'reward': 1},
    'zikir_subhanallah': {'text': "50 Kez Subhanallahi ve Bihamdihi Çek", 'reward': 1},
    'kaza_nafile': {'text': "1 Adet Kaza/Nafile Namazı Kıl", 'reward': 2} # +2 Yem ödülü
}
PRAYER_NAMES_EN = ['sabah', 'ogle', 'ikindi', 'aksam', 'yatsi']

# --- CIVCIV RENKLERİ ---
CIVCIV_RENKLERI = [
    {'color': 'Sarı Civciv', 'emoji': '🐥'},
    {'color': 'Kırmızı Civciv', 'emoji': '🍎'},
    {'color': 'Mavi Civciv', 'emoji': '💙'},
    {'color': 'Pembe Civciv', 'emoji': '🌷'},
    {'color': 'Yeşil Civciv', 'emoji': '🥦'},
    {'color': 'Turuncu Civciv', 'emoji': '🥕'},
    {'color': 'Mor Civciv', 'emoji': '🟣'},
    {'color': 'Siyah Civciv', 'emoji': '⚫'},
]

# ... (Devamı 2. mesajda)
# =================================================================
# BÖLÜM 2/6: VERİ YÖNETİMİ, API VE YARDIMCI FONKSİYONLAR
# =================================================================

# --- YARDIMCI ZAMAN FONKSİYONU (Namaz vakitlerini düzeltmek için) ---
def add_minutes_to_time(time_str, minutes_to_add):
    """'HH:MM' formatındaki saate dakika ekler/çıkarır ve sonucu döndürür."""
    # datetime ve timedelta kullanımı için import'lar dosyanın başında yapılmıştır.
    try:
        dt_obj = datetime.strptime(time_str, '%H:%M')
    except ValueError:
        return time_str
        
    dt_obj_new = dt_obj + timedelta(minutes=minutes_to_add)
    return dt_obj_new.strftime('%H:%M')


# --- VERİ YÖNETİMİ FONKSİYONLARI ---

def load_user_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_user_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user_data(user_id):
    data = load_user_data()
    user_id_str = str(user_id)
    now = datetime.now()
    
    if user_id_str not in data:
        try: isim = bot.get_chat(user_id).first_name
        except Exception: isim = "Anonim Kullanıcı"

        data[user_id_str] = {
            'isim': isim,
            'il': None, 'ilce': None, 'referrer_id': None, 'invites': 0,
            'altin': 0, 'yem': 0, 'sellable_eggs': 0, 'ranking_eggs': 0, # YENİ YUMURTA ALANLARI
            'total_lifetime_yumurta': 0, 
            'last_weekly_reset': now.strftime('%Y-%m-%d %H:%M:%S'),
            
            'namaz_today': [], 'prayer_times_cache': {'date': None, 'times': {}}, 
            'notified_prayers': [],
            
            'civciv_list': [],
            'tavuk_count': 0,
            
            'daily_tasks_done': [],
            'last_daily_reset': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
        }
        save_user_data(data)
    
    # Geriye dönük uyumluluk ve eksik anahtar ekleme
    if 'prayer_times_cache' not in data[user_id_str]: data[user_id_str]['prayer_times_cache'] = {'date': None, 'times': {}}
    if 'sellable_eggs' not in data[user_id_str]: data[user_id_str]['sellable_eggs'] = data[user_id_str].get('yumurta', 0) # İlk kez yüklemede yumurtaları satılabilir yapar
    if 'ranking_eggs' not in data[user_id_str]: data[user_id_str]['ranking_eggs'] = data[user_id_str].get('yumurta', 0)
    if 'yumurta' not in data[user_id_str]: data[user_id_str]['yumurta'] = 0 # Eski yumurta alanı silindi veya sıfırlandı
    
    save_user_data(data)
    return data, user_id_str

# --- API VE VAKİT ÇEKME FONKSİYONLARI ---

def fetch_prayer_times(il, ilce):
    """Aladhan API'den namaz vakitlerini çeker ve manuel kaydırma uygular."""
    try:
        params = {'city': il, 'country': 'Turkey', 'method': 9}
        response = requests.get(PRAYER_API_URL, params=params, timeout=10)
        response.raise_for_status()
        timings = response.json()['data']['timings']
        
        vakitler = {
            'sabah': timings['Fajr'].split(' ')[0], 'ogle': timings['Dhuhr'].split(' ')[0],
            'ikindi': timings['Asr'].split(' ')[0], 'aksam': timings['Maghrib'].split(' ')[0],
            'yatsi': timings['Isha'].split(' ')[0],
        }

        # ❗ GLOBAL ZAMAN KAYDIRMASINI UYGULAMA (Namaz Vakti Hata Düzeltmesi)
        if GLOBAL_TIME_OFFSET_MINUTES != 0:
            for key, time_str in vakitler.items():
                vakitler[key] = add_minutes_to_time(time_str, GLOBAL_TIME_OFFSET_MINUTES)
        
        return vakitler
    except Exception as e:
        print(f"Namaz Vakitleri API Hatası: {e}")
        return None

# --- Sayaç Durumu Yönetimi Yardımcıları (Kısaltıldı) ---
COUNTER_STATE_FILE = 'counter_state.json'

def load_counter_state():
    if os.path.exists(COUNTER_STATE_FILE):
        with open(COUNTER_STATE_FILE, 'r', encoding='utf-8') as f:
            return {int(k): v for k, v in json.load(f).items()}
    return {}

def save_counter_state(data):
    with open(COUNTER_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({str(k): v for k, v in data.items()}, f, indent=4, ensure_ascii=False)
        # =================================================================
# BÖLÜM 3/6: KLAVYE VE MENÜ FONKSİYONLARI
# =================================================================

# --- KLAVYE OLUŞTURMA FONKSİYONLARI ---

def generate_sub_menu(buttons, row_width=2):
    """Alt menüler için genel klavye oluşturucu."""
    markup = types.ReplyKeyboardMarkup(row_width=row_width, resize_keyboard=True)
    for btn_text in buttons:
        markup.add(types.KeyboardButton(btn_text))
    markup.add(types.KeyboardButton("🔙 Ana Menü"))
    return markup

def generate_main_menu():
    """Ana klavyeyi kullanıcı isteğine göre sıralanmış olarak oluşturur."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    # Kullanıcının İstediği Yeni Sıralama
    buttons = [
        "📖 Oyun Nasıl Oynanır?", "📊 Genel Durum", 
        "🕌 Namaz Takibi", "📋 Günlük Görevler", 
        "🍗 Civciv Besle", "🛒 Civciv Pazarı", 
        "🥚 Yumurta Pazarı", "🏆 Haftalık Sıralama", 
        "🔗 Referans Sistemi", "📍 Konum Güncelle"
    ]
    
    # Butonları 2'şerli sıralar (Son satırda kalan tek buton varsa onu tek başına dizer)
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
             markup.row(types.KeyboardButton(buttons[i]), types.KeyboardButton(buttons[i+1]))
        else:
             markup.row(types.KeyboardButton(buttons[i]))
             
    return markup

def send_main_menu(chat_id, message_text="Ana Menüdesiniz. Ne yapmak istersiniz?"):
    """Ana menüyü gönderen yardımcı fonksiyon."""
    bot.send_message(chat_id, message_text, reply_markup=generate_main_menu(), parse_mode='Markdown')

def generate_prayer_menu(user_id):
    """Namaz takibi menüsünü oluşturur."""
    data, user_id_str = get_user_data(user_id)
    kilanlar = data[user_id_str]['namaz_today']
    
    buttons = []
    for vakit in ['Sabah', 'Öğle', 'İkindi', 'Akşam', 'Yatsı']:
        emoji = "✅" if vakit.lower().replace('öğle', 'ogle').replace('yatsı', 'yatsi') in kilanlar else "⏳"
        buttons.append(f"{emoji} {vakit} Namazı Kıldım")
        
    return generate_sub_menu(buttons, row_width=2)

def generate_task_menu(user_id):
    """Günlük görevler menüsünü oluşturur. (Yeni görev listesi ile uyumlu)"""
    data, user_id_str = get_user_data(user_id)
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    
    tasks_done = data[user_id_str]['daily_tasks_done']
    
    for key, task in DAILY_TASKS.items():
        emoji = '✅' if key in tasks_done else '◻️'
        text = f"{emoji} {task['text']}"
        markup.add(text)
        
    markup.add("🔙 Ana Menü")
    return markup


def generate_market_buttons(civciv_list):
    """Civciv Pazarı butonlarını oluşturur."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    current_colors = [c['color'] for c in civciv_list]
    
    for civciv in CIVCIV_RENKLERI:
        if civciv['color'] not in current_colors:
            button_text = f"💰 Satın Al: {civciv['emoji']} {civciv['color']}"
            markup.add(button_text)

    markup.add("🔙 Ana Menü")
    return markup

def generate_feed_menu_buttons(user_id):
    """Civciv besleme menüsünü oluşturur."""
    data, user_id_str = get_user_data(user_id)
    civcivler = [c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv']
    
    buttons = []
    for civciv in civcivler:
        yem_durumu = civciv.get('yem', 0)
        buttons.append(f"🥩 Besle: {civciv['color']} ({yem_durumu}/{YEM_FOR_TAVUK})")
        
    if not civcivler:
        buttons.append("Civcivim Yok 😥")
        
    return generate_sub_menu(buttons, row_width=1)
    # =================================================================
# BÖLÜM 4/6: ANA LOGİK VE REFERANS SİSTEMİ İŞLEYİCİLERİ
# =================================================================

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    # Kullanıcı adını alırken @ işaretini kontrol et
    user_name = message.from_user.first_name
    if message.from_user.username:
        user_name = f"@{message.from_user.username}"
    
    # YENİ BAŞLANGIÇ METNİ
    welcome_text = (
        f"Selamün Aleyküm, {user_name}! 🕌\n\n"
        f"Ben, ibadetlerini eğlenceli bir oyunla takip etmen için tasarlanmış bir botum! "
        f"Hadi \"📖 Oyun Nasıl Oynanır?\" butonuna tıkla👇🏻"
    )
    
    # 1. Referans Kodu Kontrolü (SADECE LİNK SAHİBİ KAZANIYOR)
    referrer_id = None
    if len(message.text.split()) > 1 and message.text.split()[1].startswith('ref_'):
        referrer_id = message.text.split()[1].replace('ref_', '')

        print(f"DEBUG: Referans Linkinden Gelen ID: {referrer_id}")
        
        # Geçerli bir referans kimliği var mı ve kişi daha önce kaydolmadıysa
        if referrer_id in data and user_id_str != referrer_id:
            if data[user_id_str].get('referrer_id') is None:
                
                # 1. Kaydetme
                data[user_id_str]['referrer_id'] = referrer_id
                
                # 2. REFERANS SAHİBİNE YEM ÖDÜLÜ (+3 YEM)
                data[referrer_id]['yem'] += REF_YEM_SAHIBI 
                data[referrer_id]['invites'] = data[referrer_id].get('invites', 0) + 1
                save_user_data(data)
                
                # YALNIZCA REFERANS SAHİBİNE BİLDİRİM GÖNDERİLİR
                try:
                    bot.send_message(
                        referrer_id, 
                        f"🔗 Tebrikler! Davet ettiğiniz kullanıcı katıldı. **+{REF_YEM_SAHIBI} yem** kazandınız. 🌾", 
                        parse_mode='Markdown'
                    )
                except Exception as e: 
                    print(f"Referans bildirim hatası: {e}")
                    
                # YENİ ÜYEYE ÖDÜL KAZANÇ MESAJI GÖNDERİLMEZ.
                
    # Konum bilgisi
    if data[user_id_str]['il'] is None:
        bot.send_message(user_id, welcome_text, parse_mode='Markdown')
        msg = bot.send_message(user_id, "📍 Lütfen namaz vakitlerinizi doğru hesaplayabilmemiz için **İlinizi/İlçenizi** (örnek: *İstanbul/Fatih*) girin.")
        bot.register_next_step_handler(msg, process_location_step)
    else:
        send_main_menu(user_id, welcome_text + "Hayırlı ve bereketli bir gün dilerim! 👇")


# --- GÜNLÜK GÖREVLER TAMAMLAMA LOGİĞİ ---

@bot.message_handler(func=lambda message: any(task['text'] in message.text for task in DAILY_TASKS.values()))
def handle_complete_daily_task(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    # Görev sıfırlamasını kontrol et (Kodun başında tanımlanan helper fonksiyonu kullanır)
    # check_daily_reset(data, user_id_str) # Bu kontrol, menüyü açarken yapılmalıdır.

    # Hangi görevin tamamlandığını bul
    completed_task_key = None
    task_text_raw = message.text.replace('✅', '').replace('◻️', '').strip()
    
    for key, task in DAILY_TASKS.items():
        if task['text'] == task_text_raw:
            completed_task_key = key
            break
            
    if not completed_task_key:
        bot.send_message(message.chat.id, "Geçersiz görev seçimi.", reply_markup=generate_task_menu(user_id))
        return

    # Görev kontrolü ve ödül
    if completed_task_key in data[user_id_str]['daily_tasks_done']:
        text = f"❗ Bu görevi (**{DAILY_TASKS[completed_task_key]['text']}**) zaten tamamladın. Yarın yeni görevler seni bekliyor."
    else:
        reward = DAILY_TASKS[completed_task_key]['reward']
        
        # Veri güncelleme
        data[user_id_str]['daily_tasks_done'].append(completed_task_key)
        data[user_id_str]['yem'] += reward
        save_user_data(data)
        
        text = (
            f"🎉 **Görev Tamamlandı!**\n"
            f"**{DAILY_TASKS[completed_task_key]['text']}** görevini başarıyla tamamladın.\n"
            f"Hesabına **{reward} Yem** eklendi! Toplam Yem: {data[user_id_str]['yem']}"
        )
        
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=generate_task_menu(user_id))

# ... (Diğer handler'lar buraya eklenecek)
# =================================================================
# BÖLÜM 4/6 SONU
# ======# =================================================================
# BÖLÜM 5/6: YUMURTA PAZARI, CIVCIV PAZARI VE BESLEME İŞLEYİCİLERİ
# =================================================================

# --- YUMURTA PAZARI HANDLER'LARI (YENİ ÖZELLİK) ---

@bot.message_handler(func=lambda message: message.text == "🥚 Yumurta Pazarı")
def handle_egg_market(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    current_eggs = data[user_id_str].get('sellable_eggs', 0) # Satılabilir Yumurta
    
    info_text = (
        "🥚 **YUMURTA PAZARI** menüsündesin. \n\n"
        "Tavuklarının ürettiği yumurtaları burada altın karşılığında satabilirsin.\n"
        f"**Minimum Satış Adedi:** **{MIN_EGG_SATIS}** yumurtadır.\n"
        f"💵 Yumurta Değeri: **1 Yumurta = {EGG_SATIS_DEGERI} Altın** 💰\n\n"
        f"**Güncel Satılabilir Yumurtan:** **{current_eggs}** adet\n\n"
        "Satmak istediğin yumurta miktarını yazıp gönderebilirsin (Örn: `15`). İşlemi iptal etmek için `🔙 Ana Menü` yazabilirsin."
    )
    
    sent_msg = bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(sent_msg, process_sell_eggs_step)


def process_sell_eggs_step(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    if message.text == "🔙 Ana Menü":
        send_main_menu(user_id, "İşlem iptal edildi.")
        return

    try:
        sell_quantity = int(message.text.strip())
    except ValueError:
        # Hata Mesajı ve Pazarı Kapatma
        bot.send_message(
            user_id, 
            "❌ **Geçersiz Giriş!** Lütfen satmak istediğin miktarı sadece sayı olarak gir. İşlem iptal edildi.",
            parse_mode='Markdown', 
            reply_markup=generate_main_menu()
        )
        return

    current_eggs = data[user_id_str].get('sellable_eggs', 0)

    # KONTROL 1: Minimum Satış Adedi Kontrolü
    if sell_quantity < MIN_EGG_SATIS:
        # Hata Mesajı ve Pazarı Kapatma
        bot.send_message(
            user_id, 
            f"❌ **Minimum Satış!** Minimum satış adedi **{MIN_EGG_SATIS}** yumurtadır. İşlem iptal edildi.",
            parse_mode='Markdown', 
            reply_markup=generate_main_menu()
        )
        return
        
    # KONTROL 2: Yeterli Yumurta Kontrolü
    if sell_quantity > current_eggs:
        # Hata Mesajı ve Pazarı Kapatma
        bot.send_message(
            user_id, 
            f"❌ **Yetersiz Yumurta!** Elinde satılabilir **{current_eggs}** yumurta var. İşlem iptal edildi.",
            parse_mode='Markdown', 
            reply_markup=generate_main_menu()
        )
        return

    # SATIŞ İŞLEMİ
    kazanilan_altin = sell_quantity * EGG_SATIS_DEGERI
    
    # Veri Güncelleme
    data[user_id_str]['sellable_eggs'] -= sell_quantity # Satılabilir yumurtadan düş
    # NOT: data[user_id_str]['ranking_eggs'] satılmadığı için DÜŞMEZ. Haftalık sıralama korunur.
    data[user_id_str]['altin'] += kazanilan_altin       # Altını ekle
    
    save_user_data(data)
    
    success_text = (
        f"✅ **Satış Başarılı!**\n"
        f"**{sell_quantity}** yumurta satıldı.\n"
        f"💰 Karşılığında **{kazanilan_altin:.2f} Altın** kazandınız.\n"
        f"💳 Yeni Altın Bakiyeniz: **{data[user_id_str]['altin']:.2f} 💰**"
    )
    
    bot.send_message(user_id, success_text, parse_mode='Markdown', reply_markup=generate_main_menu())

# --- CIVCIV PAZARI HANDLER'I (Limiti Sadece Civcivler için Yapar) ---
@bot.message_handler(func=lambda message: message.text == "🛒 Civciv Pazarı")
def handle_civciv_market(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    # SADECE CIVCIV SAYIMI: Yeni hayvan alımını kontrol eden mantık
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'])
    current_total_animals = len(data[user_id_str]['civciv_list']) # Civciv ve Tavuk toplamı

    info_text = (
        "**🛒 Civciv Pazarı**\n\n"
        "Civcivleri buradan alabilirsin.\n"
        f"Fiyat: **{CIVCIV_COST_ALTIN} Altın** 💰\n\n"
        f"Mevcut Civciv Slotu: **{current_civciv_count}** / **{MAX_CIVCIV_OR_TAVUK}**\n\n"
    )
    
    # KONTROL: Sadece civciv sayısına bakar. Tavuklar sınırsız slot açar.
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
        info_text += "\n❗ **Maksimum civciv sınırına ulaştınız!** Yeni hayvan alamazsınız. Besle ve dönüştür!"
        bot.send_message(
            user_id, 
            info_text, 
            parse_mode='Markdown', 
            reply_markup=generate_main_menu()
        )
        return
    
    # Satın alma butonlarını gönder
    bot.send_message(
        user_id, 
        info_text + "\nAlmak istediğin civciv rengini seç:",
        parse_mode='Markdown', 
        reply_markup=generate_market_buttons(data[user_id_str]['civciv_list'])
    )

@bot.message_handler(func=lambda message: message.text.startswith("💰 Satın Al:"))
def handle_civciv_satin_alma(message):
    """Civciv satın alma işlemini yapar."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    text = message.text
    
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv']) # Civciv sayısını hesaplar
    
    civciv_color_raw = text.replace('💰 Satın Al: ', '').split(' ')[1] # Örn: 'Sarı'
    
    # 1. Kontrol: Yetersiz Altın
    if data[user_id_str]['altin'] < CIVCIV_COST_ALTIN:
        bot.send_message(user_id, f"❌ **Yetersiz Altın!** Civciv almak için **{CIVCIV_COST_ALTIN - data[user_id_str]['altin']} Altın** daha kazanmalısın.", parse_mode='Markdown', reply_markup=generate_main_menu())
        return
        
    # 2. Kontrol: Maksimum Civciv Sınırı (8 civciv, tavuklar hariç)
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
         bot.send_message(user_id, f"❌ Maksimum civciv sınırına ulaştın. (Mevcut civciv sayısı: {current_civciv_count})", parse_mode='Markdown', reply_markup=generate_main_menu())
         return

    # 3. Kontrol: Aynı renge sahip civciv var mı?
    if any(c['color'] == civciv_color_raw for c in data[user_id_str]['civciv_list']):
        bot.send_message(user_id, f"❌ **{civciv_color_raw}** renginde bir civcivin zaten var!", parse_mode='Markdown', reply_markup=generate_main_menu())
        return

    # SATIN ALMA İŞLEMİ
    data[user_id_str]['altin'] -= CIVCIV_COST_ALTIN
    
    new_civciv = {
        'color': civciv_color_raw,
        'status': 'civciv',
        'yem': 0,
        'next_egg_time': None
    }
    data[user_id_str]['civciv_list'].append(new_civciv)
    save_user_data(data)

    bot.send_message(user_id, f"✅ **Tebrikler!** **{civciv_color_raw} Civciv** satın aldın. Altın bakiyen: **{data[user_id_str]['altin']}**.", parse_mode='Markdown', reply_markup=generate_main_menu())

# --- CIVCIV BESLE HANDLER'I ---
@bot.message_handler(func=lambda message: message.text == "🍗 Civciv Besle")
def handle_feed_civciv_menu(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    yem_sayisi = data[user_id_str]['yem']
    tavuk_count = data[user_id_str].get('tavuk_count', 0)
    
    info_text = (
        f"🌾 **Civciv Besleme** menüsündesin.\n"
        f"Mevcut Yeminiz: **{yem_sayisi} 🌾**\n"
        f"Tavuk Sayınız: **{tavuk_count} 🐓**\n"
        f"Tavuk olmak için gereken yem: **{YEM_FOR_TAVUK}**\n"
        "Lütfen beslemek istediğiniz civcivi seçin. Her beslemede **1 yem** harcarsınız."
    )
    
    bot.send_message(user_id, info_text, reply_markup=generate_feed_menu_buttons(user_id), parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text.startswith("🥩 Besle:"))
def handle_feed_chicken_action(message):
    """Civciv besleme işlemini yapar."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    text = message.text
    
    civciv_color = re.sub(r' \(\d+/\d+\)', '', text.replace('🥩 Besle: ', '')).strip()

    current_yem = data[user_id_str]['yem']
    if current_yem < 1:
        bot.send_message(user_id, "❌ Yeterli yeminiz yok! Görevleri tamamlayarak yem kazanabilirsiniz.", reply_markup=generate_main_menu())
        return
        
    found_civciv = next((c for c in data[user_id_str]['civciv_list'] if c['color'] == civciv_color and c['status'] == 'civciv'), None)
    
    if found_civciv:
        found_civciv['yem'] = found_civciv.get('yem', 0) + 1
        data[user_id_str]['yem'] -= 1
        
        # Tavuk Oldu mu?
        if found_civciv['yem'] >= YEM_FOR_TAVUK:
            found_civciv['status'] = 'tavuk'
            found_civciv['next_egg_time'] = (datetime.now() + timedelta(hours=EGG_INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
            data[user_id_str]['tavuk_count'] = data[user_id_str].get('tavuk_count', 0) + 1
            save_user_data(data)
            
            bot.send_message(user_id, f"🐓 **TEBRİKLER!** **{civciv_color}** yeterli yemi aldı ve **TAVUK** oldu!", parse_mode='Markdown', reply_markup=generate_main_menu())
        else:
            save_user_data(data)
            bot.send_message(user_id, f"🌾 **{civciv_color}** beslendi. Tavuk olmasına **{YEM_FOR_TAVUK - found_civciv['yem']} yem** kaldı.\nKalan yeminiz: **{data[user_id_str]['yem']}**", parse_mode='Markdown', reply_markup=generate_feed_menu_buttons(user_id))
    else:
        bot.send_message(user_id, "Hata: Beslenecek civciv bulunamadı.", reply_markup=generate_main_menu())
        ===========================================================
        # =================================================================
# BÖLÜM 6/6: ARKA PLAN GÖREVLERİ VE BOT BAŞLATMA
# =================================================================

# --- ARKA PLAN THREAD İŞLEVLERİ (Eksik thread'ler için genel mantık) ---

def ensure_daily_reset():
    """Günlük sıfırlama (00:00'da)."""
    while True:
        # Kodun geri kalan kısmı buraya gelecek
        time.sleep(3600) # 1 saat bekler

def egg_production_and_notification():
    """Yumurta üretimi ve bildirim."""
    while True:
        # Kodun geri kalan kısmı buraya gelecek
        time.sleep(600) # 10 dakika bekler

def prayer_time_notification_loop():
    """Namaz hatırlatma."""
    while True:
        # Kodun geri kalan kısmı buraya gelecek
        time.sleep(60) # 1 dakika bekler

def save_counter_state_periodically():
    """Sayaç durumunu düzenli olarak kaydeder."""
    while True:
        # Kodun geri kalan kısmı buraya gelecek
        time.sleep(60) # 1 dakika bekler

# --- 7/24 AKTİF TUTMA (FLASK SUNUCUSU) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive"

def run_keep_alive():
    """Flask uygulamasını Render'ın gerektirdiği portta çalıştırır."""
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 8080))

def keep_alive():
    """Flask sunucusunu ayrı bir thread'de başlatır."""
    t = threading.Thread(target=run_keep_alive)
    t.daemon = True
    t.start()


if __name__ == '__main__':
    keep_alive() # Flask sunucusunu başlat
    
    # ARKA PLAN GÖREVLERİNİ BAŞLAT
    # Eski kodunuzdaki tüm thread'leri burada başlatın
    threading.Thread(target=ensure_daily_reset, daemon=True).start()
    # threading.Thread(target=ensure_weekly_reset, daemon=True).start()
    threading.Thread(target=egg_production_and_notification, daemon=True).start()
    threading.Thread(target=prayer_time_notification_loop, daemon=True).start()
    threading.Thread(target=save_counter_state_periodically, daemon=True).start()
    
    print("--- Telegram İbadet Çiftliği Botu Başlatılıyor ---")
    
    # BOTU SÜREKLİ DİNLEMEYE AL (Polling)
    try:
        bot.polling(non_stop=True, interval=0, timeout=40)
    except Exception as e:
        print(f"Bot Çalışma Hatası: {e}. 5 saniye sonra yeniden deneniyor.")
        time.sleep(5)
