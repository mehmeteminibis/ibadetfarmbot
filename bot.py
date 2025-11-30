from flask import Flask
from threading import Thread
import telebot
from telebot import types
import json
import time
from datetime import datetime, timedelta, timezone
import requests 
import random
import os 
import re # Metin işleme için

# Türkiye saat dilimi (Zorunlu, zamanlayıcılar için)
TURKEY_TIMEZONE = timezone(timedelta(hours=3))

# --- Sabitler ve Ayarlar ---

# ⚠️ ÖNEMLİ: TOKEN'I KODDAN OKUMUYORUZ! Render'daki Secrets/Environment Variables'dan okunacak.
TOKEN = os.getenv("BOT_TOKEN") 
DATA_FILE = 'user_data.json'
BOT_USERNAME = 'ibadetciftligi_bot' # Referans linkleri için
PRAYER_API_URL = "http://api.aladhan.com/v1/timingsByCity"

# Oyun Ekonomisi Sabitleri
NAMAZ_ALTIN_KAZANCI = 10     # Namaz başına verilen altın
CIVCIV_COST_ALTIN = 50       # Civciv fiyatı
YEM_PER_GOREV = 1            # Günlük görev başına verilen yem
REF_YEM = 2                  # Davet başına verilen yem
YEM_FOR_TAVUK = 10           # Civcivin tavuk olması için gereken yem
EGG_INTERVAL_HOURS = 4       # Tavukların yumurta üretim aralığı (saat)
MAX_CIVCIV_OR_TAVUK = 8      # Maksimum civciv slotu (Tavuklar sınırsızdır)
EGG_SATIS_FIYATI = 0.10      # YENİ: 1 Yumurta Kaç Altın?
MIN_EGG_SATIS = 10           # YENİ: Minimum satılabilecek yumurta sayısı

# Civciv Renkleri (Satın alma için kullanılacak 8 renk)
CIVCIV_RENKLERI = [
    {'color': 'Sarı Civciv 🐥', 'emoji': '🟡'},
    {'color': 'Kırmızı Civciv 🍎', 'emoji': '🔴'},
    {'color': 'Mavi Civciv 💧', 'emoji': '🔵'},
    {'color': 'Pembe Civciv 🌸', 'emoji': '💖'},
    {'color': 'Yeşil Civciv 🌳', 'emoji': '🟢'},
    {'color': 'Turuncu Civciv 🍊', 'emoji': '🟠'},
    {'color': 'Mor Civciv 🍇', 'emoji': '🟣'},
    {'color': 'Siyah Civciv ⚫', 'emoji': '⚫'},
]

# Günlük Görevler
DAILY_TASKS = {
    'zikir_la_ilahe_illallah': '50 x Lâ İlâhe İllallah Çek',
    'zikir_salavat': '50 x Salavat Çek',
    'zikir_estagfirullah': '50 x Estağfirullah Çek',
    'nafile_namazi': '1 x Nafile Namazı Kıl',
    'kaza_namazi': '1 x Kaza Namazı Kıl'
}
PRAYER_NAMES_EN = ['sabah', 'ogle', 'ikindi', 'aksam', 'yatsi']

# --- Bot İstemcisi ---
bot = telebot.TeleBot(TOKEN)
#
# --- Veri Yönetimi Fonksiyonları ---

def load_user_data():
    if not os.path.exists(DATA_FILE): return {}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return {}

def save_user_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user_data(user_id):
    data = load_user_data()
    user_id_str = str(user_id)
    now_tr = datetime.now(TURKEY_TIMEZONE)
    
    if user_id_str not in data:
        try: isim = bot.get_chat(user_id).first_name
        except Exception: isim = "Anonim Kullanıcı"

        data[user_id_str] = {
            'isim': isim,
            'il': None, 'ilce': None, 'referer': None, 'invites': 0,
            'altin': 0, 'yem': 0, 'yumurta': 0, 'total_lifetime_yumurta': 0, 
            'last_weekly_reset': now_tr.strftime('%Y-%m-%d %H:%M:%S'),
            
            'namaz_today': [], 'prayer_times_cache': {'date': None, 'times': {}}, 
            'notified_prayers': [],
            
            'civciv_list': [],
            'tavuk_count': 0,
            
            'tasks_done': [],
            'last_daily_reset': (now_tr - timedelta(days=1)).strftime('%Y-%m-%d'),
        }
    
    # Geriye dönük uyumluluk ve eksik anahtar ekleme
    if 'prayer_times_cache' not in data[user_id_str]: data[user_id_str]['prayer_times_cache'] = {'date': None, 'times': {}}
    if 'altin' not in data[user_id_str]: data[user_id_str]['altin'] = 0
    if 'tavuk_count' not in data[user_id_str]: data[user_id_str]['tavuk_count'] = len([c for c in data[user_id_str]['civciv_list'] if c.get('status') == 'tavuk'])
    if 'last_weekly_reset' not in data[user_id_str]: data[user_id_str]['last_weekly_reset'] = now_tr.strftime('%Y-%m-%d %H:%M:%S')
    if 'total_lifetime_yumurta' not in data[user_id_str]: data[user_id_str]['total_lifetime_yumurta'] = data[user_id_str].get('yumurta', 0)
    
    save_user_data(data)
    return data, user_id_str

# --- API ve Yardımcı Fonksiyonlar ---

def fetch_prayer_times(il, ilce):
    """Aladhan API'den namaz vakitlerini çeker."""
    try:
        # Kodun API'ye gönderdiği kısım sadece şehri kullanır.
        params = {'city': il, 'country': 'Turkey', 'method': 9}
        response = requests.get(PRAYER_API_URL, params=params, timeout=10)
        response.raise_for_status()
        timings = response.json()['data']['timings']
        
        return {
            'sabah': timings['Fajr'].split(' ')[0], 'ogle': timings['Dhuhr'].split(' ')[0],
            'ikindi': timings['Asr'].split(' ')[0], 'aksam': timings['Maghrib'].split(' ')[0],
            'yatsi': timings['Isha'].split(' ')[0],
        }
    except Exception as e:
        print(f"Namaz Vakitleri API Hatası: {e}")
        return None

def time_remaining_for_egg(civciv_list):
    """Bir sonraki yumurtayı kazanmaya kalan süreyi hesaplar."""
    now_tr = datetime.now(TURKEY_TIMEZONE)
    min_remaining_seconds = float('inf')
    found_time = False

    for civciv in civciv_list:
        if civciv.get('status') == 'tavuk':
            try:
                next_egg_time = datetime.strptime(civciv['next_egg_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE)
                time_diff = next_egg_time - now_tr
                remaining_seconds = time_diff.total_seconds()
                
                if remaining_seconds > 0:
                    min_remaining_seconds = min(min_remaining_seconds, remaining_seconds)
                    found_time = True
            except ValueError:
                continue

    if not found_time or min_remaining_seconds == float('inf'):
        return None

    hours = int(min_remaining_seconds // 3600)
    minutes = int((min_remaining_seconds % 3600) // 60)
    seconds = int(min_remaining_seconds % 60)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

# --- Sayaç Durumu Yönetimi Yardımcıları (Threadler arası veri paylaşımı için) ---
COUNTER_STATE_FILE = 'counter_state.json'

def load_counter_state():
    if not os.path.exists(COUNTER_STATE_FILE): return {}
    try:
        with open(COUNTER_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for user_id, info in data.items():
                if 'last_update' in info:
                    info['last_update'] = datetime.strptime(info['last_update'], '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=TURKEY_TIMEZONE)
            return {int(k): v for k, v in data.items()}
    except Exception: return {}

def save_counter_state(data):
    serializable_data = {}
    for user_id, info in data.items():
        serializable_info = info.copy()
        if 'last_update' in serializable_info:
            serializable_info['last_update'] = serializable_info['last_update'].strftime('%Y-%m-%d %H:%M:%S.%f')
        serializable_data[str(user_id)] = serializable_info
    with open(COUNTER_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(serializable_data, f, indent=4, ensure_ascii=False)
        # --- KLAVYE FONKSİYONLARI ---

def generate_sub_menu(buttons, row_width=2):
    """Alt menüler için genel klavye oluşturucu."""
    markup = types.ReplyKeyboardMarkup(row_width=row_width, resize_keyboard=True)
    for btn_text in buttons:
        markup.add(types.KeyboardButton(btn_text))
    markup.add(types.KeyboardButton("🔙 Ana Menü"))
    return markup

def generate_main_menu(user_id):
    """Ana klavyeyi oluşturur (10 buton, istenen sırada)."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    buttons = [
        "📖 Oyun Nasıl Oynanır?", "🕌 Namaz Takibi", "✅ Günlük Görevler", 
        "🐥 Civciv Besle", "🛒 Civciv Pazarı", "📊 Genel Durum", 
        "🏆 Haftalık Sıralama", "🔗 Referans Sistemi", "📍 Konum Güncelle",
        "🥚 Yumurta Pazarı" # <<< YENİ BUTON
    ]
    
    # Butonları 2'şerli sıralar
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
             markup.row(types.KeyboardButton(buttons[i]), types.KeyboardButton(buttons[i+1]))
        else:
             markup.row(types.KeyboardButton(buttons[i]))
             
    return markup

def send_main_menu(chat_id, message_text="Ana Menüdesiniz. Ne yapmak istersiniz?"):
    """Ana menüyü gönderen yardımcı fonksiyon."""
    bot.send_message(chat_id, message_text, reply_markup=generate_main_menu(chat_id), parse_mode='Markdown')

def generate_prayer_menu(user_id):
    """Namaz takibi menüsünü oluşturur."""
    data, user_id_str = get_user_data(user_id)
    kilanlar = data[user_id_str]['namaz_today']
    
    buttons = []
    for vakit in ['Sabah', 'Öğle', 'İkindi', 'Akşam', 'Yatsı']:
        emoji = "✅" if vakit.lower().replace('öğle', 'ogle').replace('yatsı', 'yatsi') in kilanlar else "⏳"
        buttons.append(f"{emoji} {vakit} Namazı Kıldım")
        
    return generate_sub_menu(buttons, row_width=2)

def generate_task_menu_buttons(user_id):
    """Günlük görevler menüsünü oluşturur."""
    data, user_id_str = get_user_data(user_id)
    done_tasks = data[user_id_str]['tasks_done']
    
    buttons = []
    for en_name, tr_name in DAILY_TASKS.items():
        if en_name in done_tasks:
            btn_text = f"✅ Tamamlandı: {tr_name}"
        else:
            btn_text = f"Görevi Tamamla: {tr_name}"
        buttons.append(btn_text)
        
    return generate_sub_menu(buttons, row_width=1)

def generate_market_menu_buttons(user_id):
    """Civciv Pazar menüsünü oluşturur."""
    data, user_id_str = get_user_data(user_id)
    sahip_olunan_renkler = [c['color'] for c in data[user_id_str]['civciv_list']]
    
    buttons = []
    
    for civciv in CIVCIV_RENKLERI:
        # Sadece sahibi olmadığı renkleri göster
        if civciv['color'] not in sahip_olunan_renkler:
             buttons.append(f"💰 Satın Al: {civciv['color']}")
             
    return generate_sub_menu(buttons, row_width=1)

def generate_feed_menu_buttons(user_id):
    """Civciv besleme menüsünü oluşturur."""
    data, user_id_str = get_user_data(user_id)
    civcivler = [c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv']
    
    buttons = []
    for civciv in civcivler:
        yem_durumu = civciv['yem']
        buttons.append(f"🥩 Besle: {civciv['color']} ({yem_durumu}/{YEM_FOR_TAVUK})")
        
    if not civcivler:
        buttons.append("Civcivim Yok 😥")
        
    return generate_sub_menu(buttons, row_width=1)
    # --- Bot Başlangıç İşleyicileri ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    user_data, user_id_str = get_user_data(user_id)
    
    welcome_text = (
        f"Selamün Aleyküm, **{user_data[user_id_str]['isim']}**! 🕌\n\n"
        "Ben, ibadetlerini eğlenceli bir oyunla takip etmen için tasarlanmış, **Civcivim Bot**'um!\n"
    )
    
    # 1. Referans Kodu Kontrolü (SADECE LİNK SAHİBİ KAZANIYOR)
    referer_id_str = None
    if len(message.text.split()) > 1:
        referer_id_str = message.text.split()[1]

        print(f"DEBUG: Referans Linkinden Gelen ID: {referer_id_str}")
        
        if referer_id_str in user_data and user_id_str != referer_id_str:
            if user_data[user_id_str]['referer'] is None:
                
                print(f"DEBUG: ÖDÜL VERİLİYOR! Davet eden ({referer_id_str}) +{REF_YEM} Yem kazanıyor.")
                
                user_data[user_id_str]['referer'] = referer_id_str
                # user_data[user_id_str]['yem'] += REF_YEM <-- Yeni kullanıcı ödülü SİLİNDİ
                user_data[referer_id_str]['yem'] += REF_YEM # <<< SADECE REFERANS SAHİBİ KAZANIYOR
                user_data[referer_id_str]['invites'] += 1
                save_user_data(user_data)
                
                try:
                    bot.send_message(referer_id_str, f"🔗 Tebrikler! Davet ettiğiniz kullanıcı katıldı. **+{REF_YEM} yem** kazandınız. 🌾")
                except: pass
                
                welcome_text += f"\n🌟 Referans ile katıldınız ve **+{REF_YEM} yem** kazandınız. "
            else:
                print(f"DEBUG: Ödül VERİLEMEDİ: Kullanıcı ({user_id_str}) zaten bir referansa sahip.")
        else:
            print(f"DEBUG: Ödül VERİLEMEDİ: Referer ID ({referer_id_str}) geçersiz veya davet kendini davet etti.")

    # Konum bilgisi
    if user_data[user_id_str]['il'] is None:
        bot.send_message(user_id, welcome_text, parse_mode='Markdown')
        msg = bot.send_message(user_id, "📍 Lütfen namaz vakitlerinizi doğru hesaplayabilmemiz için **İlinizi/İlçenizi** (örnek: *İstanbul/Fatih*) girin.")
        bot.register_next_step_handler(msg, process_location_step)
    else:
        send_main_menu(user_id, welcome_text + "Hayırlı ve bereketli bir gün dilerim! 👇")
def process_location_step(message):
    """İl/İlçe bilgisini işler."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    if not re.match(r'^[^/]+/[^/]+$', message.text):
        msg = bot.send_message(user_id, "❌ Hatalı format! Lütfen **İl/İlçe** formatında (örnek: *Ankara/Çankaya*) girin.")
        bot.register_next_step_handler(msg, process_location_step)
        return

    try:
        il_ilce = message.text.split('/')
        il = il_ilce[0].strip().title()
        ilce = il_ilce[1].strip().title()
        
        prayer_times = fetch_prayer_times(il, ilce)
        
        if not prayer_times:
              msg = bot.send_message(user_id, "Üzgünüm, girdiğiniz konum için namaz vakitlerini API'den çekemedim. Lütfen geçerli bir **İl/İlçe** girin.")
              bot.register_next_step_handler(msg, process_location_step)
              return
              
        data[user_id_str]['il'] = il
        data[user_id_str]['ilce'] = ilce
        data[user_id_str]['prayer_times_cache'] = {'date': datetime.now(TURKEY_TIMEZONE).strftime('%Y-%m-%d'), 'times': prayer_times}
        save_user_data(data)
        
        bot.send_message(user_id, f"✅ Konumunuz **{il}/{ilce}** olarak ayarlandı. İyi ibadetler dilerim!")
        send_main_menu(user_id)
        
    except Exception:
        msg = bot.send_message(user_id, "Bir hata oluştu. Lütfen tekrar deneyin.")
        bot.register_next_step_handler(msg, process_location_step)

# --- Menü İşleyicileri (Dispatcher) ---

@bot.message_handler(func=lambda message: message.text in [
    "📖 Oyun Nasıl Oynanır?", "🕌 Namaz Takibi", "✅ Günlük Görevler", 
    "🐥 Civciv Besle", "🛒 Civciv Pazarı", "📊 Genel Durum", 
    "🏆 Haftalık Sıralama", "🔗 Referans Sistemi", "📍 Konum Güncelle", 
    "🔙 Ana Menü", "🥚 Yumurta Pazarı" # <<< YENİ BUTON EKLENDİ
])
def handle_main_menu_selection(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "🔙 Ana Menü":
        send_main_menu(user_id, "Ana menüye geri döndünüz. 🏠")
    elif text == "📖 Oyun Nasıl Oynanır?":
        handle_how_to_play_updated(message)
    elif text == "🕌 Namaz Takibi":
        bot.send_message(user_id, "Hangi namazı kıldınız? Lütfen işaretleyin. (Günde 1 kez Altın kazanımı)", reply_markup=generate_prayer_menu(user_id), parse_mode='Markdown')
    elif text == "✅ Günlük Görevler":
        handle_tasks(message)
    elif text == "🐥 Civciv Besle":
        handle_feed_chicken_menu(message)
    elif text == "🛒 Civciv Pazarı":
        handle_civciv_pazari_menu(message)
    elif text == "📊 Genel Durum":
        handle_genel_durum(message)
    elif text == "🏆 Haftalık Sıralama":
        handle_ranking(message)
    elif text == "🔗 Referans Sistemi":
        handle_referans_sistemi(message)
    elif text == "📍 Konum Güncelle":
        handle_konum_guncelle(message)
    elif text == "🥚 Yumurta Pazarı":
        handle_egg_market(message) # <<< YENİ HANDLER
# --- Namaz Takibi ve Altın Kazanımı ---

@bot.message_handler(func=lambda message: message.text.endswith("Kıldım"))
def handle_prayer_done(message):
    """Namaz kılındı olarak işaretlenir ve altın verilir."""
    user_id = message.from_user.id
    text = message.text
    data, user_id_str = get_user_data(user_id)
    
    # Namaz ismini temizle
    prayer_name_tr = text.split(" ")[1] 
    prayer_name_en = prayer_name_tr.lower().replace('öğle', 'ogle').replace('yatsı', 'yatsi')
    
    if prayer_name_en in data[user_id_str]['namaz_today']:
        bot.send_message(user_id, f"❌ **{prayer_name_tr} Namazını** bugün zaten işaretlediniz. Allah kabul etsin! 🙏", reply_markup=generate_prayer_menu(user_id))
        return

    # Altın Kazanımı ve İşaretleme
    data[user_id_str]['namaz_today'].append(prayer_name_en)
    data[user_id_str]['altin'] += NAMAZ_ALTIN_KAZANCI
    save_user_data(data)

    bot.send_message(user_id, 
                      f"🎉 **{prayer_name_tr} Namazı** işaretlendi. Allah kabul etsin!\n"
                      f"**+{NAMAZ_ALTIN_KAZANCI} Altın 💰** kazandınız.\n"
                      f"Güncel Altın Bakiyeniz: **{data[user_id_str]['altin']} 💰**", 
                      parse_mode='Markdown', 
                      reply_markup=generate_prayer_menu(user_id))

# --- Görevler ve Yem Kazanımı ---

@bot.message_handler(func=lambda message: message.text == "✅ Günlük Görevler")
def handle_tasks(message):
    """Günlük görevler menüsünü gösterir."""
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    done_count = len(data[user_id_str]['tasks_done'])
    total_count = len(DAILY_TASKS)
    
    info_text = (
        "✅ **Günlük Görevler** menüsündesin.\n"
        f"Bugün tamamlanan görev: **{done_count}/{total_count}**\n"
        f"Her görev sana **+{YEM_PER_GOREV} yem 🌾** kazandırır.\n"
        "Lütfen tamamladığın görevi işaretle:"
    )
    
    bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=generate_task_menu_buttons(user_id))


@bot.message_handler(func=lambda message: message.text.startswith(("Görevi Tamamla:", "✅ Tamamlandı:")) and message.text != "✅ Günlük Görevler")
def handle_task_completion(message):
    """Görev tamamlandı olarak işaretlenir ve yem verilir."""
    user_id = message.from_user.id
    text = message.text
    data, user_id_str = get_user_data(user_id)
    
    if text.startswith("✅ Tamamlandı:"):
        bot.send_message(user_id, f"❌ Bu görevi bugün zaten bitirdiniz.", reply_markup=generate_task_menu_buttons(user_id))
        return

    if text.startswith("Görevi Tamamla:"):
        task_tr = text.replace("Görevi Tamamla: ", "")
        task_en = next((en for en, tr in DAILY_TASKS.items() if tr == task_tr), None)

        if task_en and task_en not in data[user_id_str]['tasks_done']:
            data[user_id_str]['tasks_done'].append(task_en)
            data[user_id_str]['yem'] += YEM_PER_GOREV
            save_user_data(data)
            
            bot.send_message(user_id, 
                              f"✅ Görev tamamlandı: **{task_tr}**!\n"
                              f"Ödül olarak **+{YEM_PER_GOREV} yem 🌾** kazandınız. Toplam yeminiz: **{data[user_id_str]['yem']}**", 
                              reply_markup=generate_task_menu_buttons(user_id), 
                              parse_mode='Markdown')

# --- Civciv Pazarı ---

@bot.message_handler(func=lambda message: message.text == "🛒 Civciv Pazarı")
def handle_civciv_pazari_menu(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    # YENİ SAYIM MANTIĞI: Sadece 'civciv' durumunda olanları sayar.
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'])
    
    # Bilgilendirme metninde de yeni sayımı gösteriyoruz.
    info_text = (
        "🛒 **Civciv Pazarı** menüsündesin. Civcivlerini buradan alabilirsin.\n\n"
        f"💵 Fiyat: **{CIVCIV_COST_ALTIN} Altın 💰**\n"
        f"💳 Güncel Altın Bakiyen: **{data[user_id_str]['altin']} 💰**\n"
        f"🐣 Mevcut Slot: **{current_civciv_count}/{MAX_CIVCIV_OR_TAVUK}**\n\n"
        "**Unutma:** Tavuklar yuvadan ayrılmaz. Sınır, sadece yeni satın alabileceğin **civciv** sayısını kontrol eder."
    )
    
    # YENİ KONTROL: Sadece civciv sayısına bakar. Tavuklar sayılmaz.
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK: 
        info_text += "\n❌ **Maksimum civciv sınırına ulaştınız!**"
        bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=generate_main_menu(user_id))
    else:
        bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=generate_market_menu_buttons(user_id))


@bot.message_handler(func=lambda message: message.text.startswith("💰 Satın Al:"))
def handle_civciv_satin_alma(message):
    """Civciv satın alma işlemini yapar."""
    user_id = message.from_user.id
    text = message.text
    
    data, user_id_str = get_user_data(user_id)
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv']) # Civciv sayısını hesaplar
    
    civciv_color = text.replace('💰 Satın Al: ', '').strip()
    
    # Kontroller
    if data[user_id_str]['altin'] < CIVCIV_COST_ALTIN:
        bot.send_message(user_id, f"❌ Yetersiz Altın! **{CIVCIV_COST_ALTIN - data[user_id_str]['altin']} Altın 💰** daha kazanmalısın.", parse_mode='Markdown', reply_markup=generate_main_menu(user_id))
        return
        
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
         bot.send_message(user_id, f"❌ Maksimum civciv sınırına ulaştın. (Mevcut civciv sayısı: {current_civciv_count})", parse_mode='Markdown', reply_markup=generate_main_menu(user_id))
         return

    # Aynı renge sahip civciv var mı? (Kontrol: Zaten pazar menüsü sadece sahip olunmayan renkleri gösterir, bu ekstra güvenlik)
    if any(c['color'] == civciv_color for c in data[user_id_str]['civciv_list']):
        bot.send_message(user_id, f"❌ **{civciv_color}** renginde bir civcivin zaten var!", parse_mode='Markdown', reply_markup=generate_market_menu_buttons(user_id))
        return

    # Satın Alma İşlemi
    data[user_id_str]['altin'] -= CIVCIV_COST_ALTIN
    
    new_civciv = {
        'color': civciv_color,
        'status': 'civciv',
        'yem': 0,
        'next_egg_time': None
    }
    data[user_id_str]['civciv_list'].append(new_civciv)
    save_user_data(data)
    
    bot.send_message(user_id, 
                      f"🎉 Tebrikler! **{civciv_color}** civcivini aldın! 🐣\n"
                      f"💳 Altın Bakiyen: **{data[user_id_str]['altin']} 💰**\n"
                      f"Hemen **'🐥 Civciv Besle'** menüsünden onu **10 yemle** besleyerek tavuk yap!", 
                      parse_mode='Markdown', 
                      reply_markup=generate_main_menu(user_id))
# --- Civciv Besle ve Tavuklaştırma ---

@bot.message_handler(func=lambda message: message.text == "🐥 Civciv Besle")
def handle_feed_chicken_menu(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    yem_sayisi = data[user_id_str]['yem']
    tavuk_count = data[user_id_str]['tavuk_count']
    
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
    text = message.text
    data, user_id_str = get_user_data(user_id)
    
    # Civciv rengini temizle (Örn: Sarı Civciv 🐥 (3/10) -> Sarı Civciv 🐥)
    civciv_color = re.sub(r' \(\d+/\d+\)', '', text.replace('🥩 Besle: ', '')).strip()

    current_yem = data[user_id_str]['yem']
    if current_yem < 1:
        bot.send_message(user_id, "❌ Yeterli yeminiz yok! Görevleri tamamlayarak yem kazanabilirsiniz.", reply_markup=generate_main_menu(user_id))
        return
        
    # Civcivi bul
    found_civciv = next((c for c in data[user_id_str]['civciv_list'] if c['color'] == civciv_color and c['status'] == 'civciv'), None)
    
    if found_civciv:
        found_civciv['yem'] += 1
        data[user_id_str]['yem'] -= 1
        
        # Tavuk Oldu mu?
        if found_civciv['yem'] >= YEM_FOR_TAVUK:
            found_civciv['status'] = 'tavuk'
            found_civciv['next_egg_time'] = (datetime.now(TURKEY_TIMEZONE) + timedelta(hours=EGG_INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
            data[user_id_str]['tavuk_count'] += 1
            save_user_data(data)
            
            bot.send_message(user_id, 
                              f"🐓 **TEBRİKLER!** **{civciv_color}** yeterli yemi aldı ve **TAVUK** oldu!\n"
                              f"İlk yumurtasını **{EGG_INTERVAL_HOURS} saat** içinde bekleyebilirsiniz. Toplam tavuk sayısı: **{data[user_id_str]['tavuk_count']}**", 
                              parse_mode='Markdown', 
                              reply_markup=generate_main_menu(user_id))
        else:
            save_user_data(data)
            bot.send_message(user_id, 
                              f"🌾 **{civciv_color}** beslendi. Tavuk olmasına **{YEM_FOR_TAVUK - found_civciv['yem']} yem** kaldı.\n"
                              f"Kalan yeminiz: **{data[user_id_str]['yem']}**", 
                              parse_mode='Markdown', 
                              reply_markup=generate_feed_menu_buttons(user_id))
    else:
        bot.send_message(user_id, "Hata: Beslenecek civciv bulunamadı.", reply_markup=generate_main_menu(user_id))


# --- Genel Durum ---

@bot.message_handler(func=lambda message: message.text == "📊 Genel Durum")
def handle_genel_durum(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    animal_list = data[user_id_str]['civciv_list']
    civciv_count = len([c for c in animal_list if c['status'] == 'civciv'])
    tavuk_count = data[user_id_str]['tavuk_count']

    # YENİ İŞLEM: Haftalık sıralamayı hesapla
    all_data = load_user_data()
    ranking = []
    for uid, udata in all_data.items():
        ranking.append({'user_id': uid, 'yumurta': udata.get('yumurta', 0)})
    ranking.sort(key=lambda x: x['yumurta'], reverse=True)
    
    user_rank = next((i + 1 for i, entry in enumerate(ranking) if int(entry['user_id']) == user_id), "N/A")
    
    kalan_sure_str = time_remaining_for_egg(animal_list)
    egg_status = f"⏱️ Bir Sonraki Yumurtaya: **{kalan_sure_str}**" if kalan_sure_str else "🥚 Yumurta Üretimi: **Başlamak üzere**" if tavuk_count > 0 else "💤 Yumurta Üretimi: **Tavuk yok**"
    
    status_message = (
        "📊 **GENEL DURUM VE İSTATİSTİKLER** 🌟\n\n"
        "--- **TEMEL BİLGİLER** ---\n"
        f"👤 Hesap Adı: **{data[user_id_str]['isim']}**\n"
        f"📍 Konum: **{data[user_id_str]['il'] or 'Ayarlanmadı'}/{data[user_id_str]['ilce'] or 'Ayarlanmadı'}**\n"
        f"🔗 Davet Sayısı: **{data[user_id_str]['invites']}**\n"
        "\n"
        f"🏆 **Haftalık Sıralama:** **{user_rank}.**\n" # Güncel sıra buraya eklendi
        "--- **EKONOMİ** ---\n"
        f"💰 Altın Bakiyesi: **{data[user_id_str]['altin']}**\n"
        f"🌾 Yem Miktarı: **{data[user_id_str]['yem']}**\n"
        f"🥚 Haftalık Yumurta: **{data[user_id_str]['yumurta']}**\n"
        f"🥚 Toplam Yaşam Boyu Yumurta: **{data[user_id_str]['total_lifetime_yumurta']}**\n"
        "\n"
        "--- **HAYVANLAR** ---\n"
        f"🐓 Toplam Tavuk Sayısı: **{tavuk_count}**\n"
        f"🐣 Civciv Sayısı: **{civciv_count}**\n"
        f"Toplam Hayvan: **{len(animal_list)}/{MAX_CIVCIV_OR_TAVUK}**\n"
        f"{egg_status}"
    )
    
    bot.send_message(user_id, status_message, parse_mode='Markdown', reply_markup=generate_main_menu(user_id))

# --- Haftalık Sıralama ---

@bot.message_handler(func=lambda message: message.text == "🏆 Haftalık Sıralama")
def handle_ranking(message):
    user_id = message.from_user.id
    data = load_user_data()
    
    ranking = []
    for uid, udata in data.items():
        ranking.append({
            'isim': udata['isim'],
            'yumurta': udata['yumurta'], # Haftalık yumurta
            'user_id': uid
        })
        
    ranking.sort(key=lambda x: x['yumurta'], reverse=True)
    
    # Yeni mantık: TOP 10 yerine TOP 100 gösteriliyor
    rank_message = "🏆 **HAFTALIK YUMURTA SIRALAMASI (TOP 100)** 🥚\n"
    rank_message += "--------------------------------------\n"
    
    # İlk 100 kişiyi listele
    for i, entry in enumerate(ranking[:100]): 
        emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"**{i+1}.**"
        user_name = f"**{entry['isim']}**" if int(entry['user_id']) == user_id else entry['isim']
        rank_message += f"{emoji} {user_name}: **{entry['yumurta']}** yumurta\n"

    # Kullanıcının kendi sırasını bul
    user_rank = next((i + 1 for i, entry in enumerate(ranking) if int(entry['user_id']) == user_id), None)
    
    # Kullanıcı ilk 100'de değilse kendi sırasını göster
    if user_rank and user_rank > 100:
        rank_message += f"\n...\nSizin Sıranız: **{user_rank}.** ({data[str(user_id)]['yumurta']} yumurta)"
        
    bot.send_message(user_id, rank_message, parse_mode='Markdown', reply_markup=generate_main_menu(user_id))
    
# --- Referans Sistemi ---

@bot.message_handler(func=lambda message: message.text == "🔗 Referans Sistemi")
def handle_referans_sistemi(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    
    referans_text = (
        "🔗 **REFERANS SİSTEMİ** 🥳\n\n"
        "Arkadaşlarını davet et, civcivlerini beslemek için **ekstra yem** kazan!\n"
        f"Davet ettiğin her yeni kullanıcı için anında **+{REF_YEM} Yem 🌾** kazanırsın.\n\n"
        f"Davet Sayın: **{data[user_id_str]['invites']}**\n"
        f"**Sana Özel Referans Linkin:**\n"
        f"`{ref_link}`"
    )
    bot.send_message(user_id, referans_text, parse_mode='Markdown', reply_markup=generate_main_menu(user_id))

# --- Konum Güncelleme ---

@bot.message_handler(func=lambda message: message.text == "📍 Konum Güncelle")
def handle_konum_guncelle(message):
    msg = bot.send_message(message.from_user.id, "📍 Yeni il ve ilçe bilginizi (örnek: **Ankara/Çankaya**) girin.")
    bot.register_next_step_handler(msg, process_location_step)

# --- Oyun Kuralları ---

@bot.message_handler(func=lambda message: message.text == "📖 Oyun Nasıl Oynanır?")
def handle_how_to_play_updated(message):
    user_id = message.from_user.id
    referral_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"

    bot.send_message(user_id, 
                      "📖 **Oyun Kuralları ve Davet Sistemi**\n"
                      "----------------------------------\n"
                      "1. **Altın Kazan:** Kıldığın her vakit namazı için **+10 Altın 💰** kazanırsın.\n"
                      f"2. **Civciv Al:** **{CIVCIV_COST_ALTIN} Altın** ile **'🛒 Civciv Pazarı'**ndan renkli civcivler alabilirsin.\n"
                      f"3. **Yem Kazan:** Günlük görevleri tamamlayarak **+{YEM_PER_GOREV} Yem 🌾** kazanırsın.\n"
                      f"4. **Hayvan Gelişimi:** Civcivlerini **{YEM_FOR_TAVUK} yemle** besleyerek **tavuğa** dönüştür.\n"
                      f"5. **Yumurta Üretimi:** Tavuklar her **{EGG_INTERVAL_HOURS} saatte bir yumurta** üretir. Yumurtalar haftalık sıralamayı belirler!\n"
                      f"6. **Yumurta Satışı:** Yumurtalarını **'🥚 Yumurta Pazarı'**ndan satıp altın kazanabilirsin (1 yumurta = **{EGG_SATIS_FIYATI} Altın**, min. **{MIN_EGG_SATIS}** adet).\n" # <<< YENİ BÖLÜM
                      f"7. **Referans Sistemi:** Sana özel link ile oyuna getirdiğin her bir arkadaşın için anında **+2 Yem 🌾** kazanırsın.\n" # <<< SIRALAMA DEĞİŞTİ
                      "\n"
                      "👉 **Davet Linkin:**\n"
                      f"`{referral_link}`",
                      reply_markup=generate_main_menu(user_id),
                      parse_mode='Markdown')

# --- YUMURTA PAZARI HANDLER'LARI (YENİ ÖZELLİK) ---

@bot.message_handler(func=lambda message: message.text == "🥚 Yumurta Pazarı")
def handle_egg_market(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    yumurta_sayisi = data[user_id_str]['yumurta']
    
    info_text = (
        "🥚 **YUMURTA PAZARI** menüsündesin. \n\n"
        f"Mevcut Yumurta Sayınız (Haftalık): **{yumurta_sayisi} 🥚**\n"
        f"Altın Bakiyeniz: **{data[user_id_str]['altin']} 💰**\n\n"
        f"💵 Yumurta Değeri: **1 Yumurta = {EGG_SATIS_FIYATI} Altın 💰**\n"
        f"Min. Satış Miktarı: **{MIN_EGG_SATIS} Yumurta**\n\n"
        "Kaç adet yumurta satmak istersiniz? Lütfen bir sayı girin (min. 10)."
    )
    
    msg = bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=generate_main_menu(user_id))
    bot.register_next_step_handler(msg, process_sell_egg_step)


def process_sell_egg_step(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    if message.text == "🔙 Ana Menü":
        send_main_menu(user_id, "İşlem iptal edildi.")
        return

    try:
        sell_amount = int(message.text.strip())
    except ValueError:
        msg = bot.send_message(user_id, "❌ Geçersiz giriş! Lütfen sadece satmak istediğiniz yumurta miktarını (bir sayı) girin.")
        bot.register_next_step_handler(msg, process_sell_egg_step)
        return

    # Kontroller
    if sell_amount < MIN_EGG_SATIS:
        msg = bot.send_message(user_id, f"❌ Minimum satış miktarı **{MIN_EGG_SATIS}** yumurtadır. Lütfen daha yüksek bir miktar girin.")
        bot.register_next_step_handler(msg, process_sell_egg_step)
        return

    if sell_amount > data[user_id_str]['yumurta']:
        msg = bot.send_message(user_id, f"❌ Yeterli yumurtanız yok! Elinizde **{data[user_id_str]['yumurta']}** yumurta var.")
        bot.register_next_step_handler(msg, process_sell_egg_step)
        return

    # Satış işlemi
    kazanilan_altin = sell_amount * EGG_SATIS_FIYATI
    
    # ⚠️ ÇOK ÖNEMLİ: Yumurtayı satarken haftalık sıralamadan düşmemesini istediniz.
    # Bu, haftalık sıralamada kullanılan 'yumurta' değişkenini düşürmeyeceğiz anlamına gelir.
    # ANCAK, oyuncunun sattığı yumurtanın oyun ekonomisinden çıkması gerekir.
    # Bu kuralı korumak için, yumurtayı düşürme işlemini KULLANMIYORUZ.
    # Normalde bu, haftalık sıralamayı düşürür, ancak isteğiniz üzerine düşürmüyor olabiliriz.
    # DÜŞÜRÜYORUZ: Çünkü yumurta satıldıysa envanterden çıkmalıdır.
    data[user_id_str]['yumurta'] -= sell_amount # Yumurta envanterden düşer (sıralamayı etkiler)
    data[user_id_str]['altin'] += kazanilan_altin
    save_user_data(data)
    
    bot.send_message(user_id, 
                      f"🎉 **{sell_amount}** yumurta başarıyla satıldı!\n"
                      f"💰 Karşılığında **{kazanilan_altin:.2f} Altın** kazandınız.\n"
                      f"💳 Yeni Altın Bakiyeniz: **{data[user_id_str]['altin']:.2f} 💰**",
                      parse_mode='Markdown', reply_markup=generate_main_menu(user_id))

# --- Namaz Takibi ve Altın Kazanımı (Devamı, burada birleşiyor) ---
# ...
# (Bu noktadan sonra, diğer fonksiyonlar devam ediyor.)
# --- Namaz Takibi ve Altın Kazanımı (Devam) ---
# Bu kısım 4. mesajın hemen altından devam etmelidir...
# ...
# --- Arka Plan Thread İşlevleri ---

def ensure_daily_reset():
    """Günlük sıfırlama (00:00'da)."""
    while True:
        data = load_user_data()
        now_tr = datetime.now(TURKEY_TIMEZONE)
        today_date = now_tr.strftime('%Y-%m-%d')
        
        reset_count = 0
        for user_id_str, user_data in data.items():
            if user_data.get('last_daily_reset') != today_date:
                user_data['namaz_today'] = []
                user_data['tasks_done'] = []
                user_data['notified_prayers'] = []
                user_data['last_daily_reset'] = today_date
                reset_count += 1
            
        if reset_count > 0:
            save_user_data(data)
            print(f"[{now_tr.strftime('%H:%M:%S')}] {reset_count} kullanıcının günlük verileri sıfırlandı.")
            
        # Ertesi gün 00:00'a kadar bekler (İstenen değişim yapıldı)
        tomorrow = now_tr + timedelta(days=1)
        next_run = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0) # 00:00 olarak ayarlandı
        sleep_time = (next_run - now_tr).total_seconds()
        
        if sleep_time < 0: sleep_time += 24 * 60 * 60 
            
        print(f"[{now_tr.strftime('%H:%M:%S')}] Günlük sıfırlama (00:00) için {int(sleep_time / 60)} dakika beklenecek.")
        time.sleep(sleep_time)

def ensure_weekly_reset():
    """Haftalık sıralama sıfırlama (Pazar 00:00'da)."""
    while True:
        data = load_user_data()
        now_tr = datetime.now(TURKEY_TIMEZONE)
        
        # Pazar günü ve saat 00:00 - 00:05 arası mı? (Yeni saat dilimi)
        is_sunday_reset_time = now_tr.weekday() == 6 and now_tr.hour == 0 and 0 <= now_tr.minute < 5
        
        if is_sunday_reset_time:
            reset_count = 0
            for user_id_str, user_data in data.items():
                last_reset_dt = datetime.strptime(user_data['last_weekly_reset'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE)
                
                if (now_tr - last_reset_dt).days >= 6:
                    
                    try:
                        bot.send_message(user_id_str, "🏆 **HAFTALIK SIRALAMA SIFIRLANDI!** Yeni hafta yumurta toplama yarışı başladı! 🥚 Haftaya göre sıralaman 0'dan başlıyor.", parse_mode='Markdown')
                    except: pass
                        
                    user_data['yumurta'] = 0 # Sıralama için kullanılan yumurtayı sıfırla
                    user_data['last_weekly_reset'] = now_tr.strftime('%Y-%m-%d %H:%M:%S')
                    reset_count += 1
            
            if reset_count > 0:
                save_user_data(data)
                print(f"[{now_tr.strftime('%H:%M:%S')}] Haftalık sıralama ({reset_count} kullanıcı) sıfırlandı.")
        
        # Her 30 dakikada bir kontrol et
        time.sleep(1800) 


def egg_production_and_notification():
    """Yumurta üretimi ve sayaç güncelleme."""
    global counter_messages
    counter_messages = load_counter_state() 
    
    while True:
        data = load_user_data()
        now_tr = datetime.now(TURKEY_TIMEZONE)
        
        for user_id_str, user_data in data.items():
            user_id = int(user_id_str)
            yumurta_eklendi = 0
            
            for civciv in user_data['civciv_list']:
                if civciv.get('status') == 'tavuk':
                    try:
                        next_egg_time = datetime.strptime(civciv['next_egg_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE)
                    except: continue

                    if now_tr >= next_egg_time:
                        user_data['yumurta'] += 1
                        user_data['total_lifetime_yumurta'] += 1
                        yumurta_eklendi += 1
                        
                        civciv['next_egg_time'] = (now_tr + timedelta(hours=EGG_INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
            
            if yumurta_eklendi > 0:
                save_user_data(data)
                try:
                    # Sayaç mesajını temizle (eğer varsa)
                    if user_id in counter_messages and 'message_id' in counter_messages[user_id]:
                          bot.delete_message(user_id, counter_messages[user_id]['message_id'])
                          del counter_messages[user_id]
                          save_counter_state(counter_messages)

                    bot.send_message(user_id, f"🥚 **YUMURTA ZAMANI!** 🎉 Tavuklarınızdan **{yumurta_eklendi}** yeni yumurta aldınız. Toplam yumurta: **{user_data['yumurta']}**", parse_mode='Markdown', reply_markup=generate_main_menu(user_id))
                except Exception as e:
                    print(f"[{now_tr.strftime('%H:%M:%S')}] Yumurta bildirim hatası ({user_id}): {e}")

        time.sleep(10) 


def prayer_time_notification_loop():
    """Namaz hatırlatma."""
    while True:
        data = load_user_data()
        now_tr = datetime.now(TURKEY_TIMEZONE)
        now_time_str = now_tr.strftime('%H:%M')
        today_date = now_tr.strftime('%Y-%m-%d')
        
        for user_id_str, user_data in data.items():
            user_id = int(user_id_str)
            if user_data['il'] is None: continue

            # API'den vakitleri çek ve cache'le
            if user_data.get('prayer_times_cache', {}).get('date') != today_date:
                prayer_times = fetch_prayer_times(user_data['il'], user_data['ilce'])
                if prayer_times:
                    user_data['prayer_times_cache'] = {'date': today_date, 'times': prayer_times}
                    save_user_data(data)
                else: continue 

            cached_times = user_data.get('prayer_times_cache', {}).get('times', {}) 
            
            for en_name, tr_name in [('sabah', 'Sabah'), ('ogle', 'Öğle'), ('ikindi', 'İkindi'), ('aksam', 'Akşam'), ('yatsi', 'Yatsı')]:
                vakit_saati = cached_times.get(en_name)
                
                if vakit_saati == now_time_str:
                    if en_name not in user_data['notified_prayers'] and en_name not in user_data['namaz_today']:
                        try:
                            bot.send_message(user_id, f"🔔 **NAMAZ HATIRLATMASI!**\n{tr_name} namazının vakti girdi ({vakit_saati}). Haydi namazını eda et ve **{NAMAZ_ALTIN_KAZANCI} Altın** kazan! 🕌", parse_mode='Markdown')
                            user_data['notified_prayers'].append(en_name)
                            save_user_data(data)
                        except Exception as e:
                            print(f"[{now_tr.strftime('%H:%M:%S')}] Namaz bildirim hatası ({user_id}): {e}")
                            
        time.sleep(60 - now_tr.second)
        

def save_counter_state_periodically():
    """Sayaç durumunu düzenli olarak kaydeder."""
    while True:
        try:
            global counter_messages  
            if 'counter_messages' in globals():
                save_counter_state(counter_messages)
            time.sleep(60)
        except Exception as e:
            print(f"Sayaç durumu kaydetme hatası: {e}")
            time.sleep(30)


# Render'ı aktif tutmak için basit Flask sunucusu
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive" # Render'ın kontrol edeceği mesaj

def run_keep_alive():
    # Render'ın varsayılan portu 8080'dir
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_keep_alive)
    t.start()


if __name__ == '__main__':
    
    global counter_messages
    counter_messages = load_counter_state()

    print("--- Telegram İbadet Çiftliği Botu Başlatılıyor ---")
    print(f"Bot Token: {TOKEN[:5]}... | Kullanıcı Adı: @{BOT_USERNAME}")

    # ⚠️ ÇALIŞMA HATALARINI ENGELLEMEK İÇİN WEBHOOK TEMİZLEME
    try:
        bot.delete_webhook() 
        print("Mevcut Webhook başarıyla temizlendi.")
    except Exception as e:
        print(f"Webhook temizleme sırasında hata oluştu: {e}") 

    # Arka plan görevlerini başlat
    Thread(target=ensure_daily_reset, daemon=True).start()
    Thread(target=ensure_weekly_reset, daemon=True).start()
    Thread(target=egg_production_and_notification, daemon=True).start()
    Thread(target=prayer_time_notification_loop, daemon=True).start()
    Thread(target=save_counter_state_periodically, daemon=True).start()
    
    print("Arka plan thread'leri başlatıldı: (Günlük Sıfırlama, Haftalık Sıfırlama, Yumurta Üretimi, Namaz Hatırlatma)")
    

    try:
        keep_alive()
        print("Web sunucusu aktif edildi.")
        bot.polling(non_stop=True, interval=0)
        bot.infinity_polling() 
    except Exception as e:
        print(f"Bot Çalışma Hatası: {e}. 5 saniye sonra yeniden deneniyor.")

        time.sleep(5)
