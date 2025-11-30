# =================================================================
# BÖLÜM 1/5: KÜTÜPHANELER, SABİTLER VE GLOBAL TANIMLAR
# =================================================================
import telebot
from telebot import types
import json
import time
import requests 
import random
import os 
import re 
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask # Flask en sona eklendi

# --- ZAMAN DİLİMİ VE BOT NESNESİ ---
TURKEY_TIMEZONE = timezone(timedelta(hours=3))
BOT_TOKEN = os.getenv("BOT_TOKEN") 
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN ortam değişkeni tanımlanmadı.")
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# --- SABİTLER ---
DATA_FILE = 'user_data.json'
BOT_USERNAME = 'ibadetciftligi_bot'
PRAYER_API_URL = "http://api.aladhan.com/v1/timingsByCity"

# EKONOMİ VE LİMİT
GLOBAL_TIME_OFFSET_MINUTES = 0 # Namaz vakti düzeltme offseti
NAMAZ_ALTIN_KAZANCI = 10
CIVCIV_COST_ALTIN = 50
REF_YEM_SAHIBI = 3           # +3 Yem
YEM_FOR_TAVUK = 10
MAX_CIVCIV_OR_TAVUK = 8      # Maksimum civciv slotu
EGG_SATIS_DEGERI = 0.10      
MIN_EGG_SATIS = 10           

# GÜNLÜK GÖREVLER
DAILY_TASKS = {
    'zikir_la_ilahe_illallah': {'text': "50 Kez La İlahe İllallah Çek", 'reward': 1},
    'zikir_salavat': {'text': "50 Kez Salavat Çek", 'reward': 1},
    'zikir_estagfirullah': {'text': "50 Kez Estağfirullah Çek", 'reward': 1},
    'zikir_subhanallah': {'text': "50 Kez Subhanallahi ve Bihamdihi Çek", 'reward': 1},
    'kaza_nafile': {'text': "1 Adet Kaza/Nafile Namazı Kıl", 'reward': 2}
}
PRAYER_NAMES_EN = ['sabah', 'ogle', 'ikindi', 'aksam', 'yatsi']

# CIVCIV RENKLERİ
CIVCIV_RENKLERI = [
    {'color': 'Sarı Civciv', 'emoji': '🐥'}, {'color': 'Kırmızı Civciv', 'emoji': '🍎'},
    {'color': 'Mavi Civciv', 'emoji': '💙'}, {'color': 'Pembe Civciv', 'emoji': '🌷'},
    {'color': 'Yeşil Civciv', 'emoji': '🥦'}, {'color': 'Turuncu Civciv', 'emoji': '🥕'},
    {'color': 'Mor Civciv', 'emoji': '🟣'}, {'color': 'Siyah Civciv', 'emoji': '⚫'},
]

# --- YARDIMCI ZAMAN FONKSİYONU ---
def add_minutes_to_time(time_str, minutes_to_add):
    try:
        dt_obj = datetime.strptime(time_str, '%H:%M')
    except ValueError:
        return time_str
        
    dt_obj_new = dt_obj + timedelta(minutes=minutes_to_add)
    return dt_obj_new.strftime('%H:%M')
    # =================================================================
# BÖLÜM 2/5: VERİ YÖNETİMİ VE API FONKSİYONLARI
# =================================================================

def load_user_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except json.JSONDecodeError: return {}
    return {}

def save_user_data(data):
    temp_file = DATA_FILE + '.tmp'
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(temp_file, DATA_FILE)
    except Exception as e:
        print(f"Hata: Veri kaydetme başarısız: {e}")
        
def get_user_data(user_id):
    data = load_user_data()
    user_id_str = str(user_id)
    now = datetime.now()
    
    if user_id_str not in data:
        try: isim = bot.get_chat(user_id).first_name
        except Exception: isim = "Kullanıcı"

        data[user_id_str] = {
            'isim': isim, 'il': None, 'ilce': None, 'referrer_id': None, 'invites': 0,
            'altin': 0, 'yem': 0, 'sellable_eggs': 0, 'ranking_eggs': 0, 
            'total_lifetime_yumurta': 0, 'last_weekly_reset': now.strftime('%Y-%m-%d %H:%M:%S'),
            'namaz_today': [], 'prayer_times_cache': {'date': None, 'times': {}}, 
            'notified_prayers': [], 'civciv_list': [], 'tavuk_count': 0,
            'daily_tasks_done': [], 'last_daily_reset': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
        }
    
    # Eksik anahtarları ekleme (Uyumluluk)
    if 'sellable_eggs' not in data[user_id_str]: data[user_id_str]['sellable_eggs'] = data[user_id_str].get('yumurta', 0)
    if 'ranking_eggs' not in data[user_id_str]: data[user_id_str]['ranking_eggs'] = data[user_id_str].get('yumurta', 0)
    if 'total_lifetime_yumurta' not in data[user_id_str]: data[user_id_str]['total_lifetime_yumurta'] = data[user_id_str].get('yumurta', 0)
    if 'yumurta' in data[user_id_str]: del data[user_id_str]['yumurta']

    return data, user_id_str

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

        # GLOBAL ZAMAN KAYDIRMASI UYGULANIR
        if GLOBAL_TIME_OFFSET_MINUTES != 0:
            for key, time_str in vakitler.items():
                vakitler[key] = add_minutes_to_time(time_str, GLOBAL_TIME_OFFSET_MINUTES)
        
        return vakitler
    except Exception as e:
        print(f"Namaz Vakitleri API Hatası: {e}. Konumunuzu kontrol edin.")
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
# BÖLÜM 3/5: KLAVYE, MENÜ VE BAŞLANGIÇ HANDLER'LARI
# =================================================================

# --- KLAVYE OLUŞTURMA FONKSİYONLARI ---

def generate_sub_menu(buttons, row_width=2):
    markup = types.ReplyKeyboardMarkup(row_width=row_width, resize_keyboard=True)
    for btn_text in buttons:
        markup.add(types.KeyboardButton(btn_text))
    markup.add(types.KeyboardButton("🔙 Ana Menü"))
    return markup

def generate_main_menu():
    """Ana klavyeyi kullanıcı isteğine göre sıralanmış olarak oluşturur."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    # KULLANICININ İSTEDİĞİ YENİ SIRALAMA
    buttons = [
        "📖 Oyun Nasıl Oynanır?", "📊 Genel Durum", 
        "🕌 Namaz Takibi", "📋 Günlük Görevler", 
        "🍗 Civciv Besle", "🛒 Civciv Pazarı", 
        "🥚 Yumurta Pazarı", "🏆 Haftalık Sıralama", 
        "🔗 Referans Sistemi", "📍 Konum Güncelle"
    ]
    
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
             markup.row(types.KeyboardButton(buttons[i]), types.KeyboardButton(buttons[i+1]))
        else:
             markup.row(types.KeyboardButton(buttons[i]))
             
    return markup

def send_main_menu(chat_id, message_text="Ana Menüdesiniz. Ne yapmak istersiniz?"):
    bot.send_message(chat_id, message_text, reply_markup=generate_main_menu(), parse_mode='Markdown')

def generate_prayer_menu(user_id):
    data, user_id_str = get_user_data(user_id)
    kilanlar = data[user_id_str]['namaz_today']
    
    buttons = []
    for vakit in ['Sabah', 'Öğle', 'İkindi', 'Akşam', 'Yatsı']:
        vakit_key = vakit.lower().replace('öğle', 'ogle').replace('yatsı', 'yatsi')
        emoji = "✅" if vakit_key in kilanlar else "⏳"
        buttons.append(f"{emoji} {vakit} Namazı Kıldım")
        
    return generate_sub_menu(buttons, row_width=2)

def generate_task_menu(user_id):
    data, user_id_str = get_user_data(user_id)
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    
    tasks_done = data[user_id_str]['daily_tasks_done']
    
    for key, task in DAILY_TASKS.items():
        emoji = '✅' if key in tasks_done else '◻️'
        text = f"{emoji} {task['text']} (+{task['reward']} Yem)"
        markup.add(text)
        
    markup.add("🔙 Ana Menü")
    return markup

def generate_market_buttons(civciv_list):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    current_colors = [c['color'] for c in civciv_list]
    for civciv in CIVCIV_RENKLERI:
        if civciv['color'] not in current_colors:
            button_text = f"💰 Satın Al: {civciv['emoji']} {civciv['color']}"
            markup.add(button_text)
    markup.add("🔙 Ana Menü")
    return markup

def generate_feed_menu_buttons(user_id):
    data, user_id_str = get_user_data(user_id)
    civcivler = [c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'] 
    
    buttons = []
    for civciv in civcivler:
        yem_durumu = civciv.get('yem', 0)
        buttons.append(f"🥩 Besle: {civciv['color']} ({yem_durumu}/{YEM_FOR_TAVUK})")
        
    if not civcivler:
        buttons.append("Civcivim Yok 😥")
        
    return generate_sub_menu(buttons, row_width=1)

# --- /start VE REFERANS SİSTEMİ LOGİĞİ ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    user_name = message.from_user.first_name if message.from_user.first_name else "Kullanıcı"
    
    # YENİ BAŞLANGIÇ METNİ
    welcome_text = (
        f"Selamün Aleyküm, {user_name}! 🕌\n\n"
        f"Ben, ibadetlerini eğlenceli bir oyunla takip etmen için tasarlanmış bir botum! "
        f"Hadi \"📖 Oyun Nasıl Oynanır?\" butonuna tıkla👇🏻"
    )
    
    # 1. Referans Kodu Kontrolü (SADECE LİNK SAHİBİ KAZANIYOR)
    if len(message.text.split()) > 1 and message.text.split()[1].startswith('ref_'):
        referrer_id_str = message.text.split()[1].replace('ref_', '')

        if referrer_id_str in data and user_id_str != referrer_id_str:
            if data[user_id_str].get('referrer_id') is None:
                
                data[user_id_str]['referrer_id'] = referrer_id_str
                
                # REFERANS SAHİBİNE YEM ÖDÜLÜ (+3 YEM)
                data[referrer_id_str]['yem'] += REF_YEM_SAHIBI 
                data[referrer_id_str]['invites'] = data[referrer_id_str].get('invites', 0) + 1
                save_user_data(data)
                
                # YALNIZCA REFERANS SAHİBİNE BİLDİRİM GÖNDERİLİR
                try:
                    bot.send_message(
                        referrer_id_str, 
                        f"🔗 Tebrikler! Davet ettiğiniz kullanıcı katıldı. **+{REF_YEM_SAHIBI} yem** kazandınız. 🌾", 
                        parse_mode='Markdown'
                    )
                except Exception as e: 
                    print(f"Referans bildirim hatası: {e}")
                    
                # YENİ ÜYEYE ÖDÜL KAZANÇ MESAJI GÖNDERİLMEZ (İstek Üzerine Düzeltildi).
                
    # Konum bilgisi
    if data[user_id_str]['il'] is None:
        bot.send_message(user_id, welcome_text, parse_mode='Markdown')
        msg = bot.send_message(user_id, "📍 Lütfen namaz vakitlerinizi doğru hesaplayabilmemiz için **İlinizi/İlçenizi** (örnek: *İstanbul/Fatih*) girin.")
        bot.register_next_step_handler(msg, process_location_step)
    else:
        send_main_menu(user_id, welcome_text + "\n\nHayırlı ve bereketli bir gün dilerim! 👇")
        # =================================================================
# BÖLÜM 4/5: AKSİYON VE MARKET HANDLER'LARI
# =================================================================

# --- MENÜ DİSPATCHER VE KONUM İŞLEME ---

@bot.message_handler(func=lambda message: message.text in [
    "📖 Oyun Nasıl Oynanır?", "📊 Genel Durum", "🕌 Namaz Takibi", 
    "📋 Günlük Görevler", "🍗 Civciv Besle", "🛒 Civciv Pazarı", 
    "🥚 Yumurta Pazarı", "🏆 Haftalık Sıralama", "🔗 Referans Sistemi", 
    "📍 Konum Güncelle", "🔙 Ana Menü"
])
def handle_main_menu_selection(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "🔙 Ana Menü":
        send_main_menu(user_id, "Ana Menüye dönüldü.")
    elif text == "📖 Oyun Nasıl Oynanır?":
        handle_how_to_play(message)
    elif text == "📊 Genel Durum":
        handle_general_status(message)
    elif text == "🕌 Namaz Takibi":
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

# --- KONUM GÜNCELLEME VE İŞLEME ---

@bot.message_handler(func=lambda message: message.text == "📍 Konum Güncelle")
def handle_location_update(message):
    msg = bot.send_message(message.from_user.id, "📍 Yeni il ve ilçe bilginizi (örnek: **Ankara/Çankaya**) girin.")
    bot.register_next_step_handler(msg, process_location_step)

def process_location_step(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    try:
        parts = [p.strip() for p in message.text.split('/')]
        if len(parts) < 2:
            raise ValueError
            
        il = parts[0]
        ilce = parts[1]
        
        prayer_times = fetch_prayer_times(il, ilce) 
        
        if prayer_times:
            data[user_id_str]['il'] = il
            data[user_id_str]['ilce'] = ilce
            data[user_id_str]['prayer_times_cache'] = {'date': datetime.now(TURKEY_TIMEZONE).strftime('%Y-%m-%d'), 'times': prayer_times}
            save_user_data(data)
            
            bot.send_message(user_id, f"✅ Konumunuz **{il}/{ilce}** olarak ayarlandı. Namaz vakitleriniz artık doğru hesaplanacaktır.", parse_mode='Markdown')
        else:
            bot.send_message(user_id, "❌ Belirttiğiniz konum için namaz vakitlerini bulamadım. Lütfen şehir/ilçe adını kontrol ederek tekrar deneyin.")
            msg = bot.send_message(user_id, "📍 Konumunuzu (örnek: *İstanbul/Fatih*) tekrar girin.")
            bot.register_next_step_handler(msg, process_location_step)
            return

    except ValueError:
        bot.send_message(user_id, "❌ Lütfen konumu **İl/İlçe** formatında (Örn: İstanbul/Fatih) girin.")
        msg = bot.send_message(user_id, "📍 Konumunuzu tekrar girin.")
        bot.register_next_step_handler(msg, process_location_step)
        return
        
    send_main_menu(user_id)
    # =================================================================
# BÖLÜM 5/5: FİNAL HANDLER'LAR, YUMURTA PAZARI VE BOT BAŞLATMA
# =================================================================

# --- NAMAZ TAKİBİ HANDLER'I ---
# [handle_prayer_done] bu kısımdan önce tanımlı olmalıdır.

# --- GÜNLÜK GÖREVLER HANDLER'LARI ---
# [handle_daily_tasks_menu], [handle_complete_daily_task] bu kısımdan önce tanımlı olmalıdır.

# --- YUMURTA PAZARI HANDLER'LARI ---

@bot.message_handler(func=lambda message: message.text == "🥚 Yumurta Pazarı")
def handle_egg_market(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    current_eggs = data[user_id_str].get('sellable_eggs', 0) # Satılabilir Yumurta
    
    info_text = (
        "🥚 **YUMURTA PAZARI** menüsündesin. \n\n"
        f"💵 Yumurta Değeri: **1 Yumurta = {EGG_SATIS_DEGERI:.2f} Altın** 💰\n"
        f"**Minimum Satış Adedi:** **{MIN_EGG_SATIS}** yumurtadır.\n\n"
        f"**Satılabilir Yumurtan:** **{current_eggs}** adet 🥚\n\n"
        "Satmak istediğin yumurta miktarını yazıp gönder. İşlemi iptal etmek için `🔙 Ana Menü` yazabilirsin."
    )
    
    sent_msg = bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(sent_msg, process_sell_eggs_step)


def process_sell_eggs_step(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    if message.text == "🔙 Ana Menü":
        send_main_menu(user_id, "Yumurta satış işlemi iptal edildi.")
        return

    try:
        sell_quantity = int(message.text.strip())
    except ValueError:
        # Hata Mesajı ve PAZARI KAPATMA (İstenen Özellik)
        bot.send_message(user_id, "❌ **Geçersiz Giriş!** Lütfen satmak istediğin miktarı sadece sayı olarak girin. İşlem iptal edildi.", parse_mode='Markdown', reply_markup=generate_main_menu())
        return

    current_eggs = data[user_id_str].get('sellable_eggs', 0)

    # ZORUNLU KONTROL 1: Minimum Satış Adedi
    if sell_quantity < MIN_EGG_SATIS:
        bot.send_message(user_id, f"❌ **Minimum Satış!** Minimum satış adedi **{MIN_EGG_SATIS}** yumurtadır. İşlem iptal edildi.", parse_mode='Markdown', reply_markup=generate_main_menu())
        return
        
    # ZORUNLU KONTROL 2: Yeterli Yumurta
    if sell_quantity > current_eggs:
        bot.send_message(user_id, f"❌ **Yetersiz Yumurta!** Elinde satılabilir **{current_eggs}** yumurta var. İşlem iptal edildi.", parse_mode='Markdown', reply_markup=generate_main_menu())
        return

    # SATIŞ İŞLEMİ
    kazanilan_altin = sell_quantity * EGG_SATIS_DEGERI
    
    data[user_id_str]['sellable_eggs'] -= sell_quantity # Satılabilir yumurtadan düşer
    # 'ranking_eggs' alanı haftalık sıralama için KORUNUR.
    data[user_id_str]['altin'] += kazanilan_altin       
    save_user_data(data)
    
    success_text = (
        f"✅ **Satış Başarılı!**\n"
        f"**{sell_quantity}** yumurta satıldı.\n"
        f"💰 Karşılığında **{kazanilan_altin:.2f} Altın** kazandınız.\n"
        f"💳 Yeni Altın Bakiyeniz: **{data[user_id_str]['altin']:.2f} 💰**"
    )
    
    bot.send_message(user_id, success_text, parse_mode='Markdown', reply_markup=generate_main_menu())


# --- SIVCIV PAZARI HANDLER'LARI VE BESLEME (Kısaltılmış Kısımlar) ---
# [handle_civciv_market], [handle_civciv_satin_alma], [handle_feed_chicken_action] gibi fonksiyonların 
# BÖLÜM 4/5 ve BÖLÜM 9/10 mesajlarında zaten tanımlı olduğu varsayılır.


# --- ARKA PLAN VE BOT BAŞLATMA ---

def ensure_daily_reset_loop():
    while True:
        # Bu fonksiyonun tam içeriği daha önceki mesajlarda var
        time.sleep(3600)

def egg_production_and_notification():
    while True:
        # Bu fonksiyonun tam içeriği daha önceki mesajlarda var
        time.sleep(600) 

def prayer_time_notification_loop():
    while True:
        # Bu fonksiyonun tam içeriği daha önceki mesajlarda var
        time.sleep(60)
        
def save_counter_state_periodically():
    while True:
        time.sleep(3600)

# --- 7/24 AKTİF TUTMA (FLASK SUNUCUSU) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive"

def run_keep_alive():
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 8080))

def keep_alive():
    t = threading.Thread(target=run_keep_alive)
    t.daemon = True
    t.start()
    
# --- BOT BAŞLATMA ---

if __name__ == '__main__':
    keep_alive() # Flask sunucusunu başlat

    # ARKA PLAN GÖREVLERİNİ BAŞLAT
    threading.Thread(target=ensure_daily_reset_loop, daemon=True).start()
    threading.Thread(target=egg_production_and_notification, daemon=True).start()
    threading.Thread(target=prayer_time_notification_loop, daemon=True).start()
    threading.Thread(target=save_counter_state_periodically, daemon=True).start()
    
    print("--- Telegram İbadet Çiftliği Botu Başlatılıyor ---")
    
    # BOTU SÜREKLİ DİNLEMEYE AL (Polling)
    try:
        print("Bot Polling başlıyor.")
        bot.polling(non_stop=True, interval=0, timeout=40) 
        
    except Exception as e:
        print(f"Bot Çalışma Hatası: {e}. 5 saniye sonra yeniden deneniyor.")
        time.sleep(5)
