# ==============================================================================
# BÖLÜM 1/6: KÜTÜPHANELER, SABİTLER VE GLOBAL TANIMLAR
# ==============================================================================
import os
import json
import time
import random
import threading
from datetime import datetime, timedelta, timezone

# Webhook ve Render için zorunlu import'lar
from flask import Flask, request
import telebot
from telebot import types

# --- ZAMAN DİLİMİ VE BOT NESNESİ ---
TURKEY_TIMEZONE = timezone(timedelta(hours=3))
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = 'ibadetciftligi_bot'  # Referans linkleri için bot kullanıcı adınız

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN ortam değişkeni tanımlanmadı.")

# Bot ve Flask Uygulaması
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)  # Webhook için threaded=False
app = Flask(__name__)

# --- SABİTLER VE OYUN EKONOMİSİ ---
DATA_FILE = 'user_data.json'
PRAYER_API_URL = "http://api.aladhan.com/v1/timingsByCity"

# EKONOMİ VE LİMİT
NAMAZ_ALTIN_KAZANCI = 10
CIVCIV_COST_ALTIN = 50
REF_YEM_SAHIBI = 3           
YEM_FOR_TAVUK = 10
EGG_INTERVAL_HOURS = 4       # Tavukların yumurta üretim aralığı (saat)
MAX_CIVCIV_OR_TAVUK = 8      # Maksimum civciv sayısı (Tavuk sayısı sınırsızdır)
EGG_SATIS_DEGERI = 0.10      # Yumurtanın altın karşılığı satış değeri
MIN_EGG_SATIS = 10           # Minimum satılabilecek yumurta sayısı

# GÜNLÜK GÖREVLER
DAILY_TASKS = {
    'zikir_la_ilahe_illallah': {'text': "50 Kez La İlahe İllallah Çek", 'reward': 1},
    'zikir_salavat': {'text': "50 Kez Salavat Çek", 'reward': 1},
    'zikir_estagfirullah': {'text': "50 Kez Estağfirullah Çek", 'reward': 1},
    'zikir_subhanallah': {'text': "50 Kez Subhanallahi ve Bihamdihi Çek", 'reward': 1},
    'kaza_nafile': {'text': "1 Adet Kaza/Nafile Namazı Kıl", 'reward': 2}
}

# NAMAZ İSİMLERİ VE EMOJİLER
PRAYER_NAMES_TR = ['Sabah', 'Öğle', 'İkindi', 'Akşam', 'Yatsı']
PRAYER_NAMES_EN = ['Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha'] # API için

# CIVCIV RENKLERİ (Satın alma için kullanılacak 8 renk)
CIVCIV_RENKLERI = [
    {'color': 'Sarı Civciv', 'emoji': '🐥'},
    {'color': 'Kırmızı Civciv', 'emoji': '🍎'},
    {'color': 'Mavi Civciv', 'emoji': '💧'},
    {'color': 'Pembe Civciv', 'emoji': '💖'},
    {'color': 'Yeşil Civciv', 'emoji': '🍏'},
    {'color': 'Turuncu Civciv', 'emoji': '🍊'},
    {'color': 'Mor Civciv', 'emoji': '🍇'},
    {'color': 'Beyaz Civciv', 'emoji': '🥚'}
]

# ==============================================================================
# BÖLÜM 2/6: VERİ YÖNETİMİ VE YARDIMCI FONKSİYONLAR
# ==============================================================================

def load_data():
    """Kullanıcı verilerini JSON dosyasından yükler."""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    """Kullanıcı verilerini JSON dosyasına kaydeder."""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Veri kaydı sırasında hata oluştu: {e}")

def get_user_data(user_id):
    """Kullanıcı verisini alır veya ilk kez başlatır."""
    data = load_data()
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        data[user_id_str] = init_user(user_id)
        save_data(data)
    
    return data, user_id_str

def init_user(user_id):
    """Yeni kullanıcı için başlangıç verilerini oluşturur."""
    now_utc = datetime.now(TURKEY_TIMEZONE)
    return {
        'username': bot.get_chat(user_id).username if bot.get_chat(user_id).username else str(user_id),
        'altin': 0,
        'yem': 0,
        'yumurta': 0,
        'location': None,
        'civciv_list': [],
        'last_daily_reset': now_utc.strftime('%Y-%m-%d'),
        'last_weekly_reset': now_utc.strftime('%Y-%W'), # Yılın hafta numarası
        'daily_tasks': {task_key: {'done': False, 'progress': 0} for task_key in DAILY_TASKS},
        'prayer_tracker': {prayer: now_utc - timedelta(days=1) for prayer in PRAYER_NAMES_EN}, # Son namaz kılma zamanı (datetime objesi)
        'ref_id': None,
        'ref_count': 0,
        'weekly_ranking_score': 0, # Haftalık skor
        'eggs_last_checked': now_utc.strftime('%Y-%m-%d %H:%M:%S') # Yumurta kontrolü için
    }

def get_now():
    """Şu anki zamanı Türkiye zaman diliminde döndürür."""
    return datetime.now(TURKEY_TIMEZONE)

# --- KLAVYE OLUŞTURUCULAR ---

def send_main_menu(user_id, text="Ana Menüdesiniz."):
    """Ana menü klavyesini gönderir."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [
        types.KeyboardButton("📖 Oyun Nasıl Oynanır?"),
        types.KeyboardButton("📊 Genel Durum"),
        types.KeyboardButton("🕌 Namaz Takibi"),
        types.KeyboardButton("📋 Günlük Görevler"),
        types.KeyboardButton("🍗 Civciv Besle"),
        types.KeyboardButton("🛒 Civciv Pazarı"),
        types.KeyboardButton("🥚 Yumurta Pazarı"),
        types.KeyboardButton("🏆 Haftalık Sıralama"),
        types.KeyboardButton("🔗 Referans Sistemi"),
        types.KeyboardButton("📍 Konum Güncelle"),
    ]
    markup.add(*buttons)
    bot.send_message(user_id, text, reply_markup=markup, parse_mode='Markdown')

def generate_prayer_menu(user_id):
    """Namaz takibi için inline klavye oluşturur."""
    data, user_id_str = get_user_data(user_id)
    now = get_now()
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    
    for tr_name, en_name in zip(PRAYER_NAMES_TR, PRAYER_NAMES_EN):
        last_prayer_time = datetime.strptime(data[user_id_str]['prayer_tracker'][en_name], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE) if isinstance(data[user_id_str]['prayer_tracker'][en_name], str) else data[user_id_str]['prayer_tracker'][en_name]

        # Namazı en son 24 saatten önce kıldıysa işaretlemeye izin ver
        if now - last_prayer_time >= timedelta(hours=24):
            button_text = f"✅ {tr_name}"
        else:
            button_text = f"❌ {tr_name}"
            
        buttons.append(types.InlineKeyboardButton(button_text, callback_data=f"prayer_{en_name}"))
        
    markup.add(*buttons)
    return markup

def generate_market_menu(user_id):
    """Civciv pazarı için inline klavye oluşturur."""
    data, user_id_str = get_user_data(user_id)
    current_civciv_colors = [c['color'] for c in data[user_id_str]['civciv_list']]
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    # Sadece sahip olunmayan renkler listelenir
    for civciv in CIVCIV_RENKLERI:
        color = civciv['color']
        emoji = civciv['emoji']
        if color not in current_civciv_colors:
            buttons.append(types.InlineKeyboardButton(f"Satın Al: {emoji} {color}", callback_data=f"buy_{color}"))

    if not buttons:
        return None # Eğer tüm renkler alınmışsa klavye oluşturulmaz
        
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("🔙 Ana Menü", callback_data="back_main_menu"))
    return markup

# ==============================================================================
# BÖLÜM 3/6: ARKA PLAN GÖREVLERİ (THREADING)
# ==============================================================================

def ensure_daily_reset_loop():
    """Günlük görevleri ve sayaçları sıfırlayan döngü."""
    while True:
        now = get_now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time_to_sleep = (tomorrow - now).total_seconds()
        
        print(f"Günlük sıfırlamaya kadar bekleme: {time_to_sleep / 3600:.2f} saat")
        time.sleep(time_to_sleep + 5) # +5 saniye gecikme ile yarını garantiler

        data = load_data()
        today_date = get_now().strftime('%Y-%m-%d')
        
        for user_id_str, user_data in data.items():
            if user_data.get('last_daily_reset') != today_date:
                # Günlük görevleri sıfırla
                user_data['daily_tasks'] = {task_key: {'done': False, 'progress': 0} for task_key in DAILY_TASKS}
                user_data['last_daily_reset'] = today_date
                
                # Haftalık sıfırlama kontrolü (Pazartesi kontrolü)
                current_week = get_now().strftime('%Y-%W')
                if user_data.get('last_weekly_reset') != current_week:
                    user_data['weekly_ranking_score'] = 0 # Skoru sıfırla
                    user_data['last_weekly_reset'] = current_week
                    bot.send_message(int(user_id_str), "🏆 Haftalık sıralama puanınız sıfırlandı. Yeni hafta, yeni hedefler!")

        save_data(data)
        print("Günlük sıfırlama işlemi tamamlandı.")

def egg_production_and_notification():
    """Tavukların yumurta üretmesini ve kullanıcıları bilgilendirmesini sağlar."""
    while True:
        # 1 saatte bir kontrol et (daha kısa aralıkta da olabilir)
        time.sleep(3600) 
        
        data = load_data()
        now = get_now()

        for user_id_str, user_data in data.items():
            if not user_data.get('civciv_list'):
                continue
            
            user_id = int(user_id_str)
            eggs_added = 0
            
            # Son kontrol zamanını al
            last_checked = datetime.strptime(user_data['eggs_last_checked'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE)

            for civciv in user_data['civciv_list']:
                if civciv['status'] == 'tavuk':
                    last_egg_time = datetime.strptime(civciv['last_egg_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE)
                    
                    # Son yumurta zamanı ile şimdi arasındaki farkı kontrol et
                    # Birden fazla aralık geçmiş olabilir
                    while now - last_egg_time >= timedelta(hours=EGG_INTERVAL_HOURS):
                        civciv['last_egg_time'] = (last_egg_time + timedelta(hours=EGG_INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
                        user_data['yumurta'] += 1
                        eggs_added += 1
                        last_egg_time = last_egg_time + timedelta(hours=EGG_INTERVAL_HOURS) # Yeni yumurta zamanını güncelle

            # Bildirim gönder
            if eggs_added > 0:
                bot.send_message(
                    user_id, 
                    f"🥚 Yumurta! 🐓 **{eggs_added}** adet yeni yumurta üretildi! Toplam yumurta sayınız: **{user_data['yumurta']}**",
                    parse_mode='Markdown'
                )

            # Son kontrol zamanını güncelle
            user_data['eggs_last_checked'] = now.strftime('%Y-%m-%d %H:%M:%S')

        save_data(data)
        print(f"Yumurta üretimi kontrolü tamamlandı. ({now.strftime('%H:%M')})")

def save_counter_state_periodically():
    """Verileri her 30 saniyede bir kaydeder."""
    while True:
        time.sleep(30)
        try:
            # Sadece kritik verileri değil, genel veriyi kaydetmek daha güvenlidir.
            data = load_data()
            save_data(data)
            print(f"Veriler otomatik olarak kaydedildi. ({get_now().strftime('%H:%M:%S')})")
        except Exception as e:
            print(f"Periyodik kaydetme hatası: {e}")

# ==============================================================================
# BÖLÜM 4/6: BOT HANDLER'LAR (KOMUT İŞLEYİCİLER)
# ==============================================================================

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # Referans kontrolü (Örn: /start ref12345)
    ref_id = None
    if len(message.text.split()) > 1:
        ref_id_str = message.text.split()[1]
        if ref_id_str.startswith('ref') and ref_id_str[3:].isdigit():
            ref_id = int(ref_id_str[3:])

    data, _ = get_user_data(user_id)
    
    # Kullanıcı yeni mi?
    if user_id_str not in data or data[user_id_str].get('ref_id') is None:
        
        # Eğer referans ile geldiyse
        if ref_id and str(ref_id) in data and str(ref_id) != user_id_str:
            data[user_id_str]['ref_id'] = ref_id
            data[str(ref_id)]['yem'] += REF_YEM_SAHIBI
            data[str(ref_id)]['ref_count'] += 1
            save_data(data)
            
            # Bildirim
            try:
                bot.send_message(ref_id, f"🎉 **{message.from_user.first_name}** referans linkinle katıldı! **+{REF_YEM_SAHIBI} Yem** kazandın.", parse_mode='Markdown')
            except Exception:
                pass # Bot sahibini engellemiş olabilir
            
            send_main_menu(user_id, f"Hoş geldin! 🎉 {data[str(ref_id)]['username']} referansıyla katıldın ve oyuna başladın!")
        else:
            # Normal başlangıç
            send_main_menu(user_id, "Hoş geldin! İbadet Çiftliği oyununa başlamak için menüyü kullan.")
    else:
        # Zaten kayıtlı
        send_main_menu(user_id, "Ana Menüye dönüldü.")

# Ana menü seçimlerini işler (En son yapılan hata ayıklama bloğu dahil)
@bot.message_handler(func=lambda message: message.text in [
    "📖 Oyun Nasıl Oynanır?", "📊 Genel Durum", "🕌 Namaz Takibi", "📋 Günlük Görevler", 
    "🍗 Civciv Besle", "🛒 Civciv Pazarı", "🥚 Yumurta Pazarı", "🏆 Haftalık Sıralama", 
    "🔗 Referans Sistemi", "📍 Konum Güncelle", "🔙 Ana Menü"
])
def handle_main_menu_selection(message):
    user_id = message.from_user.id
    text = message.text
    
    try: # Hata yakalama bloğunu başlat
        if text == "🔙 Ana Menü":
            send_main_menu(user_id, "Ana Menüye dönüldü.")
        elif text == "📖 Oyun Nasıl Oynanır?":
            handle_how_to_play(message)
        elif text == "📊 Genel Durum":
            handle_general_status(message)
        elif text == "🕌 Namaz Takibi":
            # API URL kontrolü ve konuma yönlendirme (Konum Güncelle fonksiyonu çağrılacak)
            data, user_id_str = get_user_data(user_id)
            if not data[user_id_str]['location']:
                handle_location_update(message, location_required=True)
                return
            
            bot.send_message(user_id, "Hangi namazı kıldınız? Lütfen işaretleyin. (Günde 1 kez Altın kazanımı)", reply_markup=generate_prayer_menu(user_id), parse_mode='Markdown')
        elif text == "📋 Günlük Görevler":
            handle_daily_tasks_menu(message)
        elif text == "🍗 Civciv Besle":
            handle_feed_chicken_menu(message)
        elif text == "🛒 Civciv Pazarı":
            handle_civciv_market(message)
        elif text == "🥚 Yumurta Pazarı":
            handle_egg_market(message)
        elif text == "🏆 Haftalık Sıralama":
            handle_weekly_ranking(message)
        elif text == "🔗 Referans Sistemi":
            handle_referans_sistemi(message)
        elif text == "📍 Konum Güncelle":
            handle_location_update(message)
    
    except Exception as e:
        # Hata mesajını Telegram'a gönder
        bot.send_message(
            user_id, 
            f"❌ **KRİTİK HATA!** İşlem sırasında bir sorun oluştu.\nDetay: {type(e).__name__}: {str(e)}", 
            parse_mode='Markdown'
        )
        # Hatanın Render loglarına da gitmesi için hatayı tekrar fırlat
        raise e

# ==============================================================================
# BÖLÜM 5/6: ÖZELLİK FONKSİYONLARI (Kapsamlı)
# ==============================================================================

def handle_how_to_play(message):
    """Oyun kurallarını gönderir."""
    user_id = message.from_user.id
    rules = (
        "📜 **OYUN NASIL OYNANIR?**\n\n"
        "1. **Altın Kazan:** Namaz Takibi ve Günlük Görevler yaparak Altın 🥇 kazanın.\n"
        "2. **Civciv Al:** Altınlarınızla Civciv Pazarından 🐣 civciv satın alın (Max. {MAX_CIVCIV_OR_TAVUK} adet).\n"
        "3. **Besle:** Civcivlerinizi Yem 🌽 ile besleyerek Tavuk 🐓 yapın (Her civciv için {YEM_FOR_TAVUK} Yem gerekir).\n"
        "4. **Yumurta Üret:** Tavuklarınız her {EGG_INTERVAL_HOURS} saatte bir yumurta 🥚 üretir.\n"
        "5. **Yumurta Sat:** Yumurtaları Altın karşılığında Pazar'da satın.\n"
        "6. **Sıralama:** En çok Altın/Yumurta kazanan Haftalık Sıralama'da 🏆 yer alır.\n"
        "7. **Yem Kazan:** Referans sistemi ile arkadaşlarınızı davet ederek Yem kazanın!"
    ).format(MAX_CIVCIV_OR_TAVUK=MAX_CIVCIV_OR_TAVUK, YEM_FOR_TAVUK=YEM_FOR_TAVUK, EGG_INTERVAL_HOURS=EGG_INTERVAL_HOURS)
    bot.send_message(user_id, rules, parse_mode='Markdown')

def handle_general_status(message):
    """Kullanıcının genel durumunu gösterir."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    user_data = data[user_id_str]
    
    civciv_count = len([c for c in user_data['civciv_list'] if c['status'] == 'civciv'])
    tavuk_count = len([c for c in user_data['civciv_list'] if c['status'] == 'tavuk'])
    
    status_text = (
        "📊 **GENEL DURUM**\n\n"
        "👤 Kullanıcı: *{username}*\n"
        "🥇 Altın: **{altin}**\n"
        "🌽 Yem: **{yem}**\n"
        "🥚 Yumurta: **{yumurta}**\n\n"
        "🐣 Civciv Sayısı: **{civciv_count}** / {MAX_CIVCIV_OR_TAVUK}\n"
        "🐓 Tavuk Sayısı: **{tavuk_count}**\n\n"
        "📍 Konum: *{location}*"
    ).format(
        username=user_data['username'],
        altin=user_data['altin'],
        yem=user_data['yem'],
        yumurta=user_data['yumurta'],
        civciv_count=civciv_count,
        tavuk_count=tavuk_count,
        MAX_CIVCIV_OR_TAVUK=MAX_CIVCIV_OR_TAVUK,
        location=user_data['location'] if user_data['location'] else "Ayarlanmadı"
    )
    bot.send_message(user_id, status_text, parse_mode='Markdown')

def handle_location_update(message, location_required=False):
    """Kullanıcıdan konum bilgisi ister."""
    user_id = message.from_user.id
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Konumumu Gönder", request_location=True))
    markup.add(types.KeyboardButton("🔙 Ana Menü"))

    prompt_text = "Namaz vakitlerini takip edebilmek için lütfen bulunduğunuz şehir bilgisini konumunuzu paylaşarak veya 'Şehir, Ülke' formatında yazarak güncelleyin."
    if location_required:
        prompt_text = "🕌 Namaz takibi yapabilmeniz için konumunuzun ayarlanması zorunludur. Lütfen konumunuzu güncelleyin."

    msg = bot.send_message(user_id, prompt_text, reply_markup=markup)
    bot.register_next_step_handler(msg, process_location_step)

def process_location_step(message):
    """Konum bilgisini işler."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    location = None
    if message.location:
        # API ile coğrafi koordinatlardan şehir/ülke çevirisi yapılır (Basitlik için bu adım atlanabilir, varsayalım ki sadece şehir adını alıyoruz)
        location = "Coğrafi Konum Alındı (API ile işlenecek)"
    elif message.text and message.text != "🔙 Ana Menü":
        location = message.text

    if location and location != "Coğrafi Konum Alındı (API ile işlenecek)":
        data[user_id_str]['location'] = location
        save_data(data)
        send_main_menu(user_id, f"📍 Konumunuz **{location}** olarak güncellendi. Artık Namaz Takibi yapabilirsiniz.")
    else:
        send_main_menu(user_id, "Konum güncelleme iptal edildi.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('prayer_'))
def handle_prayer_callback(call):
    """Namaz takibi inline tuşlarını işler."""
    user_id = call.from_user.id
    data, user_id_str = get_user_data(user_id)
    prayer_en_name = call.data.split('_')[1]
    
    if not data[user_id_str]['location']:
        bot.answer_callback_query(call.id, "Önce Konumunuzu güncelleyin!")
        return
        
    now = get_now()
    last_prayer_time = datetime.strptime(data[user_id_str]['prayer_tracker'][prayer_en_name], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE) if isinstance(data[user_id_str]['prayer_tracker'][prayer_en_name], str) else data[user_id_str]['prayer_tracker'][prayer_en_name]
    
    # 24 saat kontrolü
    if now - last_prayer_time < timedelta(hours=24):
        bot.answer_callback_query(call.id, f"Bu namazı son kılışınızın üzerinden henüz 24 saat geçmedi.")
        return

    # Namazı kıldı, ödül ver
    data[user_id_str]['altin'] += NAMAZ_ALTIN_KAZANCI
    data[user_id_str]['prayer_tracker'][prayer_en_name] = now.strftime('%Y-%m-%d %H:%M:%S')
    data[user_id_str]['weekly_ranking_score'] += NAMAZ_ALTIN_KAZANCI # Sıralama skoru ekle
    save_data(data)
    
    bot.answer_callback_query(call.id, f"✅ {PRAYER_NAMES_TR[PRAYER_NAMES_EN.index(prayer_en_name)]} namazı kaydedildi. +{NAMAZ_ALTIN_KAZANCI} Altın 🥇 kazandınız!")
    
    # Menüyü güncelle
    try:
        bot.edit_message_text(
            "Hangi namazı kıldınız? Lütfen işaretleyin. (Günde 1 kez Altın kazanımı)", 
            user_id, 
            call.message.message_id, 
            reply_markup=generate_prayer_menu(user_id),
            parse_mode='Markdown'
        )
    except Exception:
        pass # Mesaj düzenlenemezse görmezden gel

# --- MARKET VE TİCARET ---

def handle_civciv_market(message):
    """Civciv Pazarını gösterir."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'])
    
    info_text = (
        "🛒 **CİVCİV PAZARI**\n\n"
        "Fiyat: **{CIVCIV_COST_ALTIN} Altın 🥇**\n"
        "Mevcut Civciv: **{current_civciv_count}** / {MAX_CIVCIV_OR_TAVUK}\n\n"
        "Civcivler sadece **{MAX_CIVCIV_OR_TAVUK}** adete kadar satın alınabilir (Tavuk sayısı sınırsızdır)."
    ).format(
        CIVCIV_COST_ALTIN=CIVCIV_COST_ALTIN, 
        current_civciv_count=current_civciv_count, 
        MAX_CIVCIV_OR_TAVUK=MAX_CIVCIV_OR_TAVUK
    )
    
    # Maksimum limite ulaşıldıysa satış butonları gösterilmez
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
        info_text += "\n\n❌ **Maksimum civciv sınırına ulaştınız!** Yeni civciv almak için öncekileri besleyip tavuk yapın."
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🔙 Ana Menü", callback_data="back_main_menu"))
    else:
        markup = generate_market_menu(user_id)

    bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_civciv_satin_alma(call):
    """Civciv satın alma inline tuşlarını işler."""
    user_id = call.from_user.id
    data, user_id_str = get_user_data(user_id)
    civciv_color = call.data.split('_')[1]
    
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'])

    # 1. Altın Kontrolü
    if data[user_id_str]['altin'] < CIVCIV_COST_ALTIN:
        bot.answer_callback_query(call.id, f"Yetersiz Altın! {CIVCIV_COST_ALTIN - data[user_id_str]['altin']} Altın 🥇 daha kazanmalısın.")
        return

    # 2. Limit Kontrolü (Tekrar kontrol)
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
        bot.answer_callback_query(call.id, f"Maksimum {MAX_CIVCIV_OR_TAVUK} civciv sınırına ulaştınız.")
        return

    # 3. Aynı Renk Kontrolü (Güvenlik)
    if any(c['color'] == civciv_color for c in data[user_id_str]['civciv_list']):
        bot.answer_callback_query(call.id, f"{civciv_color} renginde bir civcivin zaten var.")
        return

    # 4. Satın Alma İşlemi
    data[user_id_str]['altin'] -= CIVCIV_COST_ALTIN
    
    # Yeni civciv nesnesini oluştur
    new_civciv = {
        'id': len(data[user_id_str]['civciv_list']) + 1,
        'color': civciv_color,
        'status': 'civciv',  # Başlangıç durumu
        'yem_count': 0,
        'last_egg_time': get_now().strftime('%Y-%m-%d %H:%M:%S') # Hemen yumurta üretmemesi için
    }
    data[user_id_str]['civciv_list'].append(new_civciv)
    save_data(data)
    
    bot.answer_callback_query(call.id, f"✅ {civciv_color} başarıyla satın alındı!")
    
    # Menüyü güncelle
    try:
        bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=generate_market_menu(user_id))
    except Exception:
        handle_civciv_market(call.message) # Mesaj düzenlenemezse yeni mesaj gönder

def handle_feed_chicken_menu(message):
    """Civciv besleme menüsünü gösterir."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    civcivs = [c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv']
    
    if not civcivs:
        send_main_menu(user_id, "🐣 Şu anda beslenecek civciviniz bulunmamaktadır. Civciv Pazarından satın alabilirsiniz.")
        return
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    for civciv in civcivs:
        emoji = next(c['emoji'] for c in CIVCIV_RENKLERI if c['color'] == civciv['color'])
        progress = int((civciv['yem_count'] / YEM_FOR_TAVUK) * 10)
        progress_bar = "◼️" * progress + "◻️" * (10 - progress)
        
        button_text = f"Besle: {emoji} {civciv['color']} ({civciv['yem_count']}/{YEM_FOR_TAVUK} Yem) {progress_bar}"
        markup.add(types.InlineKeyboardButton(button_text, callback_data=f"feed_{civciv['id']}"))

    bot.send_message(
        user_id, 
        f"🍗 **CİVCİV BESLE**\n\nBesleme maliyeti: **1 Yem 🌽**\nToplam {YEM_FOR_TAVUK} Yem 🌽 ile civciviniz Tavuk 🐓 olur.\n\nMevcut Yeminiz: **{data[user_id_str]['yem']}**", 
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('feed_'))
def handle_feed_chicken_callback(call):
    """Civciv besleme işlemini yapar."""
    user_id = call.from_user.id
    data, user_id_str = get_user_data(user_id)
    civciv_id = int(call.data.split('_')[1])
    
    # 1. Yem Kontrolü
    if data[user_id_str]['yem'] <= 0:
        bot.answer_callback_query(call.id, "Yetersiz Yem! 🌽 Referans sistemi ile Yem kazanabilirsiniz.")
        return

    # Civcivi bul
    civciv_to_feed = next((c for c in data[user_id_str]['civciv_list'] if c['id'] == civciv_id and c['status'] == 'civciv'), None)

    if not civciv_to_feed:
        bot.answer_callback_query(call.id, "Civciv bulunamadı veya zaten Tavuk oldu.")
        return

    # 2. Besleme İşlemi
    data[user_id_str]['yem'] -= 1
    civciv_to_feed['yem_count'] += 1
    
    # Tavuk Kontrolü
    if civciv_to_feed['yem_count'] >= YEM_FOR_TAVUK:
        civciv_to_feed['status'] = 'tavuk'
        civciv_to_feed['last_egg_time'] = get_now().strftime('%Y-%m-%d %H:%M:%S')
        save_data(data)
        
        bot.answer_callback_query(call.id, f"🎉 Tebrikler! {civciv_to_feed['color']} civciviniz Tavuk 🐓 oldu!")
        handle_feed_chicken_menu(call.message) # Menüyü tekrar gönder (tavuk menüden kalktı)
        return

    save_data(data)
    
    bot.answer_callback_query(call.id, f"✅ {civciv_to_feed['color']} beslendi! Kalan yem: {YEM_FOR_TAVUK - civciv_to_feed['yem_count']}")
    
    # Menüyü güncelle
    try:
        bot.edit_message_reply_markup(user_id, call.message.message_id, reply_markup=call.message.reply_markup)
    except Exception:
        pass # Mesaj düzenlenemezse görmezden gel

def handle_egg_market(message):
    """Yumurta pazarını gösterir ve satış işlemini yapar."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    yumurta_sayisi = data[user_id_str]['yumurta']
    
    info_text = (
        "🥚 **YUMURTA PAZARI**\n\n"
        "Mevcut Yumurtanız: **{yumurta_sayisi}**\n"
        "Satış Değeri: **1 Yumurta** = **{EGG_SATIS_DEGERI} Altın 🥇**\n"
        "Minimum Satış Miktarı: **{MIN_EGG_SATIS} adet**"
    ).format(
        yumurta_sayisi=yumurta_sayisi, 
        EGG_SATIS_DEGERI=EGG_SATIS_DEGERI,
        MIN_EGG_SATIS=MIN_EGG_SATIS
    )
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if yumurta_sayisi >= MIN_EGG_SATIS:
        markup.add(types.InlineKeyboardButton(f"Sat: {yumurta_sayisi} Yumurta", callback_data=f"sell_all_eggs"))
    
    markup.add(types.InlineKeyboardButton("🔙 Ana Menü", callback_data="back_main_menu"))

    bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'sell_all_eggs')
def handle_sell_eggs_callback(call):
    """Tüm yumurtaları satar."""
    user_id = call.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    yumurta_sayisi = data[user_id_str]['yumurta']
    
    if yumurta_sayisi < MIN_EGG_SATIS:
        bot.answer_callback_query(call.id, f"Minimum satış için {MIN_EGG_SATIS} yumurta gerekli.")
        return

    kazanilan_altin = yumurta_sayisi * EGG_SATIS_DEGERI
    
    data[user_id_str]['altin'] += kazanilan_altin
    data[user_id_str]['yumurta'] = 0
    data[user_id_str]['weekly_ranking_score'] += kazanilan_altin # Sıralama skoru ekle
    save_data(data)
    
    bot.answer_callback_query(call.id, f"✅ {yumurta_sayisi} yumurta satıldı. +{kazanilan_altin:.2f} Altın 🥇 kazandınız!")
    
    # Menüyü güncelle
    try:
        bot.edit_message_text(
            f"🥚 **YUMURTA PAZARI**\n\nMevcut Yumurtanız: **0**\nSatış Değeri: **1 Yumurta** = **{EGG_SATIS_DEGERI} Altın 🥇**\nMinimum Satış Miktarı: **{MIN_EGG_SATIS} adet**",
            user_id, 
            call.message.message_id, 
            reply_markup=None, # Satış butonu kalmasın
            parse_mode='Markdown'
        )
        send_main_menu(user_id, "Yumurta satışınız tamamlandı.")
    except Exception:
        handle_egg_market(call.message) # Yeni mesaj gönder

def handle_daily_tasks_menu(message):
    """Günlük görevler menüsünü gösterir."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    task_text = "📋 **GÜNLÜK GÖREVLER**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for task_key, task_info in DAILY_TASKS.items():
        done = data[user_id_str]['daily_tasks'][task_key]['done']
        
        status = "✅ TAMAMLANDI" if done else f"❌ {task_info['reward']} Altın Ödülü"
        button_text = f"{task_info['text']} | {status}"
        
        if not done:
            markup.add(types.InlineKeyboardButton(button_text, callback_data=f"task_{task_key}"))
        else:
             # Tamamlanmış görevler için pasif tuş
            markup.add(types.InlineKeyboardButton(button_text, callback_data="none"))
            
        task_text += f"{status}\n"

    markup.add(types.InlineKeyboardButton("🔙 Ana Menü", callback_data="back_main_menu"))
    
    bot.send_message(user_id, task_text, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('task_'))
def handle_daily_task_callback(call):
    """Günlük görev tamamlama inline tuşlarını işler."""
    user_id = call.from_user.id
    data, user_id_str = get_user_data(user_id)
    task_key = call.data.split('_')[1]
    
    task_info = DAILY_TASKS.get(task_key)

    if not task_info or data[user_id_str]['daily_tasks'][task_key]['done']:
        bot.answer_callback_query(call.id, "Görev zaten tamamlandı veya geçersiz.")
        return

    # Görevi tamamla ve ödül ver
    data[user_id_str]['daily_tasks'][task_key]['done'] = True
    data[user_id_str]['altin'] += task_info['reward']
    data[user_id_str]['weekly_ranking_score'] += task_info['reward'] # Sıralama skoru ekle
    save_data(data)
    
    bot.answer_callback_query(call.id, f"🎉 Görev tamamlandı! +{task_info['reward']} Altın 🥇 kazandınız!")
    
    # Menüyü güncelle
    try:
        handle_daily_tasks_menu(call.message)
    except Exception:
        pass

def handle_weekly_ranking(message):
    """Haftalık sıralamayı gösterir."""
    user_id = message.from_user.id
    data = load_data()
    
    # Skorları al ve sırala
    ranking = []
    for uid, udata in data.items():
        if udata.get('weekly_ranking_score', 0) > 0:
            ranking.append({
                'id': int(uid),
                'username': udata['username'],
                'score': udata['weekly_ranking_score']
            })
    
    # En yüksek puana göre sırala (Ters)
    ranking.sort(key=lambda x: x['score'], reverse=True)
    
    ranking_text = "🏆 **HAFTALIK SIRALAMA**\n\n"
    
    if not ranking:
        ranking_text += "Henüz sıralamaya girecek kimse yok. İlk Altın'ınızı kazanarak başlayın!"
    else:
        for i, rank in enumerate(ranking[:10]): # İlk 10
            emoji = ""
            if i == 0: emoji = "🥇"
            elif i == 1: emoji = "🥈"
            elif i == 2: emoji = "🥉"
            else: emoji = f"{i+1}."
            
            ranking_text += f"{emoji} {rank['username']}: **{rank['score']:.2f}** Puan\n"

    bot.send_message(user_id, ranking_text, parse_mode='Markdown')

def handle_referans_sistemi(message):
    """Referans sistemini gösterir."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{user_id}"
    
    ref_text = (
        "🔗 **REFERANS SİSTEMİ**\n\n"
        "Arkadaşını davet et, ikiniz de kazanın!\n\n"
        "Kazanç:\n"
        "👉 Senin Kazanman: Davet ettiğin her kişi için **+{REF_YEM_SAHIBI} Yem 🌽**\n"
        "🤝 Toplam Davetin: **{ref_count}** kişi\n\n"
        "Referans Linkin: `{ref_link}`\n\n"
        "Bu linki arkadaşlarına göndererek oyuna başlamalarını sağlayabilirsin!"
    ).format(
        REF_YEM_SAHIBI=REF_YEM_SAHIBI,
        ref_count=data[user_id_str]['ref_count'],
        ref_link=ref_link
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Linkimi Paylaş", url=f"tg://msg?text=İbadet Çiftliğine%20Katıl!%20{ref_link}"))
    
    bot.send_message(user_id, ref_text, parse_mode='Markdown', reply_markup=markup)

# Diğer inline callback'leri
@bot.callback_query_handler(func=lambda call: call.data == 'back_main_menu')
def handle_back_menu_callback(call):
    """Geri tuşunu işler."""
    bot.delete_message(call.from_user.id, call.message.message_id)
    send_main_menu(call.from_user.id, "Ana Menüye dönüldü.")

@bot.callback_query_handler(func=lambda call: call.data == 'none')
def handle_none_callback(call):
    """Pasif butonları işler."""
    bot.answer_callback_query(call.id, "Bu işlem şu anda yapılamaz.")


# ==============================================================================
# BÖLÜM 6/6: WEBHOOK İLE BOTU BAŞLATMA (Render için Kritik)
# ==============================================================================

# Telegram'dan gelen mesajları işlemek için bir URL yolu belirleyin
WEBHOOK_PATH = "/{}".format(BOT_TOKEN)
# Render'ın size atadığı host adını otomatik olarak alır
WEBHOOK_URL = "https://{}/{}".format(os.environ.get("RENDER_EXTERNAL_HOSTNAME"), BOT_TOKEN)

# Flask sunucusunun Webhook'u dinlemesini sağlar
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Content-Type Error', 403

# Diğer tüm arka plan thread'leri buraya dahil edilmelidir
def start_threads():
    threading.Thread(target=ensure_daily_reset_loop, daemon=True).start()
    threading.Thread(target=egg_production_and_notification, daemon=True).start()
    threading.Thread(target=save_counter_state_periodically, daemon=True).start()
    print("Arka plan thread'leri (Günlük Sıfırlama, Yumurta Üretimi, Kaydetme) başlatıldı.")

if __name__ == '__main__':
    # Tüm eski Polling/Webhook bağlantılarını sıfırla
    try:
        bot.remove_webhook()
        time.sleep(1) 
    except Exception as e:
        print(f"Webhook temizleme sırasında hata oluştu: {e}")

    # Yeni Webhook'u ayarla
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"--- Telegram İbadet Çiftliği Botu Başlatılıyor (WEBHOOK) ---")
        print(f"Webhook URL'si ayarlandı: {WEBHOOK_URL}")
        
        # Arka plan görevlerini başlat
        start_threads()
        
        # Flask uygulamasını Render'ın gerektirdiği portta başlat
        # Render'ın dinamik olarak atadığı PORT değişkeni kullanılır
        port = os.environ.get('PORT', 8080)
        app.run(host='0.0.0.0', port=port)

    except Exception as e:
        print(f"Kritik Başlatma Hatası: {e}")
