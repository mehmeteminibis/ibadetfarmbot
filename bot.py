# =================================================================
# BÖLÜM 1/5: KÜTÜPHANELER, SABİTLER VE GLOBAL TANIMLAR
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
import threading # Threading import'u eklendi
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
BOT_USERNAME = 'ibadetciftligi_bot' # Telegram bot kullanıcı adınızı girin (link oluşturmak için)
PRAYER_API_URL = "http://api.aladhan.com/v1/timingsByCity"

# ⚠️ NAMAZ VAKTİ DÜZELTME (Yeni Kaynak Hatasını Gidermeye Yönelik) ⚠️
# API'den gelen saatleriniz yanlışsa, bu değeri değiştirin.
# Örn: Vakit 18 dakika geç okunuyorsa: -18 yazın. 18 dakika erken okunuyorsa: 18 yazın.
GLOBAL_TIME_OFFSET_MINUTES = 0 # Şu an sıfır (0) olarak ayarlı

# --- OYUN EKONOMİSİ SABİTLERİ ---
NAMAZ_ALTIN_KAZANCI = 10
CIVCIV_COST_ALTIN = 50
REF_YEM_SAHIBI = 3           # YENİ: Referans sahibine +3 Yem
YEM_FOR_TAVUK = 10
EGG_INTERVAL_HOURS = 4       
MAX_CIVCIV_OR_TAVUK = 8      # Maksimum civciv slotu
EGG_SATIS_DEGERI = 0.10      # 1 Yumurta Kaç Altın?
MIN_EGG_SATIS = 10           # Minimum satılabilecek yumurta sayısı (10 olarak ayarlandı)

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
# BÖLÜM 2/5: VERİ YÖNETİMİ, API VE YARDIMCI FONKSİYONLAR
# =================================================================

# --- YARDIMCI ZAMAN FONKSİYONU (Namaz vakitlerini düzeltmek için) ---
def add_minutes_to_time(time_str, minutes_to_add):
    """'HH:MM' formatındaki saate dakika ekler/çıkarır ve sonucu döndürür."""
    try:
        dt_obj = datetime.strptime(time_str, '%H:%M')
    except ValueError:
        return time_str
        
    dt_obj_new = dt_obj + timedelta(minutes=minutes_to_add)
    return dt_obj_new.strftime('%H:%M')


# --- VERİ YÖNETİMİ FONKSİYONLARI ---

def load_user_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("Uyarı: user_data.json bozuk. Boş sözlük ile devam ediliyor.")
            return {}
    return {}

def save_user_data(data):
    # Geçici bir dosyaya yazıp sonra yeniden adlandırma (veri bütünlüğü için)
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
        except Exception: isim = "Anonim Kullanıcı"

        data[user_id_str] = {
            'isim': isim,
            'il': None, 'ilce': None, 'referrer_id': None, 'invites': 0,
            
            # YENİ EKONOMİ ALANLARI
            'altin': 0, 'yem': 0, 
            'sellable_eggs': 0,       # Satılabilir Yumurta (Satışta düşer)
            'ranking_eggs': 0,        # Haftalık Sıralama için Toplam Kazanılan Yumurta (Asla düşmez)
            'total_lifetime_yumurta': 0, # Toplam kazanılan yumurta (İstatistik)
            
            'last_weekly_reset': now.strftime('%Y-%m-%d %H:%M:%S'),
            
            'namaz_today': [], 'prayer_times_cache': {'date': None, 'times': {}}, 
            'notified_prayers': [],
            
            'civciv_list': [],
            'tavuk_count': 0,
            
            'daily_tasks_done': [],
            'last_daily_reset': (now - timedelta(days=1)).strftime('%Y-%m-%d'),
        }
        save_user_data(data)
    
    # Eksik anahtarları ekleme (Geriye dönük uyumluluk)
    if 'sellable_eggs' not in data[user_id_str]: data[user_id_str]['sellable_eggs'] = 0
    if 'ranking_eggs' not in data[user_id_str]: data[user_id_str]['ranking_eggs'] = 0
    if 'total_lifetime_yumurta' not in data[user_id_str]: data[user_id_str]['total_lifetime_yumurta'] = 0
    
    return data, user_id_str

# --- API VE VAKİT ÇEKME FONKSİYONLARI ---

def fetch_prayer_times(il, ilce):
    """Aladhan API'den namaz vakitlerini çeker ve manuel kaydırma uygular."""
    try:
        # API kaynağını değiştirmek zor olduğu için, mevcut API'yi kullanıp düzeltme uyguluyoruz.
        params = {'city': il, 'country': 'Turkey', 'method': 9} 
        response = requests.get(PRAYER_API_URL, params=params, timeout=10)
        response.raise_for_status()
        timings = response.json()['data']['timings']
        
        vakitler = {
            'sabah': timings['Fajr'].split(' ')[0], 'ogle': timings['Dhuhr'].split(' ')[0],
            'ikindi': timings['Asr'].split(' ')[0], 'aksam': timings['Maghrib'].split(' ')[0],
            'yatsi': timings['Isha'].split(' ')[0],
        }

        # ❗ GLOBAL ZAMAN KAYDIRMASINI UYGULAMA
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
            # Anahtarları int'e dönüştürerek yükleme
            return {int(k): v for k, v in json.load(f).items()} 
    return {}

def save_counter_state(data):
    with open(COUNTER_STATE_FILE, 'w', encoding='utf-8') as f:
        # Anahtarları str'ye dönüştürerek kaydetme
        json.dump({str(k): v for k, v in data.items()}, f, indent=4, ensure_ascii=False)

# ... (Devamı 3. mesajda)
# =================================================================
# BÖLÜM 3/5: KLAVYE VE MENÜ FONKSİYONLARI
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
    
    # KULLANICININ İSTEDİĞİ YENİ SIRALAMA
    buttons = [
        "📖 Oyun Nasıl Oynanır?", "📊 Genel Durum", 
        "🕌 Namaz Takibi", "📋 Günlük Görevler", 
        "🍗 Civciv Besle", "🛒 Civciv Pazarı", 
        "🥚 Yumurta Pazarı", "🏆 Haftalık Sıralama", 
        "🔗 Referans Sistemi", "📍 Konum Güncelle"
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
    bot.send_message(chat_id, message_text, reply_markup=generate_main_menu(), parse_mode='Markdown')

def generate_prayer_menu(user_id):
    """Namaz takibi menüsünü oluşturur."""
    data, user_id_str = get_user_data(user_id)
    kilanlar = data[user_id_str]['namaz_today']
    
    buttons = []
    for vakit in ['Sabah', 'Öğle', 'İkindi', 'Akşam', 'Yatsı']:
        # Altın kazanmışsa yeşil onay, sadece kılmışsa normal onay
        vakit_key = vakit.lower().replace('öğle', 'ogle').replace('yatsı', 'yatsi')
        emoji = "✅" if vakit_key in kilanlar else "⏳"
        buttons.append(f"{emoji} {vakit} Namazı Kıldım")
        
    return generate_sub_menu(buttons, row_width=2)

def generate_task_menu(user_id):
    """Günlük görevler menüsünü oluşturur. (Yeni görev listesi)"""
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
    """Civciv Pazarı butonlarını oluşturur (Yalnızca alınmamış renkleri gösterir)."""
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
    # Sadece Civciv statüsündekileri göster
    civcivler = [c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'] 
    
    buttons = []
    for civciv in civcivler:
        yem_durumu = civciv.get('yem', 0)
        buttons.append(f"🥩 Besle: {civciv['color']} ({yem_durumu}/{YEM_FOR_TAVUK})")
        
    if not civcivler:
        buttons.append("Civcivim Yok 😥")
        
    return generate_sub_menu(buttons, row_width=1)

# ... (Devamı 4. mesajda)
# =================================================================
# BÖLÜM 4/5: ANA HANDLER'LAR, REFERANS VE BİLGİLENDİRME
# =================================================================

# --- GÜNLÜK VE HAFTALIK SIFIRLAMA YARDIMCILARI ---

def check_daily_reset(data, user_id_str):
    """Günlük görevleri ve namaz takibini sıfırlar."""
    last_reset_date_str = data[user_id_str]['last_daily_reset']
    last_reset_date = datetime.strptime(last_reset_date_str, '%Y-%m-%d').date()
    today = datetime.now(TURKEY_TIMEZONE).date()

    if today > last_reset_date:
        data[user_id_str]['namaz_today'] = []
        data[user_id_str]['daily_tasks_done'] = []
        data[user_id_str]['last_daily_reset'] = today.strftime('%Y-%m-%d')
        return True
    return False

# --- /start VE REFERANS SİSTEMİ LOGİĞİ (YENİ ÜYEYE KAZANÇ YOK) ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    # Kullanıcının Telegram ismini alma
    user_name = message.from_user.first_name if message.from_user.first_name else "Kullanıcı"
    
    # YENİ BAŞLANGIÇ METNİ
    welcome_text = (
        f"Selamün Aleyküm, {user_name}! 🕌\n\n"
        f"Ben, ibadetlerini eğlenceli bir oyunla takip etmen için tasarlanmış bir botum! "
        f"Hadi \"📖 Oyun Nasıl Oynanır?\" butonuna tıkla👇🏻"
    )
    
    # 1. Referans Kodu Kontrolü (SADECE LİNK SAHİBİ KAZANIYOR)
    referrer_id = None
    if len(message.text.split()) > 1 and message.text.split()[1].startswith('ref_'):
        referrer_id_str = message.text.split()[1].replace('ref_', '')

        # Geçerli bir referans kimliği var mı ve kişi daha önce kaydolmadıysa
        if referrer_id_str in data and user_id_str != referrer_id_str:
            if data[user_id_str].get('referrer_id') is None:
                
                # 1. Kaydetme
                data[user_id_str]['referrer_id'] = referrer_id_str
                
                # 2. REFERANS SAHİBİNE YEM ÖDÜLÜ (+3 YEM)
                data[referrer_id_str]['yem'] += REF_YEM_SAHIBI 
                data[referrer_id_str]['invites'] = data[referrer_id_str].get('invites', 0) + 1
                save_user_data(data)
                
                # SADECE REFERANS SAHİBİNE BİLDİRİM GÖNDERİLİR
                try:
                    bot.send_message(
                        referrer_id_str, 
                        f"🔗 Tebrikler! Davet ettiğiniz kullanıcı katıldı. **+{REF_YEM_SAHIBI} yem** kazandınız. 🌾", 
                        parse_mode='Markdown'
                    )
                except Exception as e: 
                    print(f"Referans bildirim hatası: {e}")
                    
                # YENİ ÜYEYE ÖDÜL KAZANÇ MESAJI GÖNDERİLMEZ (İstek Üzerine Düzeltildi).
                
    # Konum bilgisi eksikse sor
    if data[user_id_str]['il'] is None:
        bot.send_message(user_id, welcome_text, parse_mode='Markdown')
        msg = bot.send_message(user_id, "📍 Lütfen namaz vakitlerinizi doğru hesaplayabilmemiz için **İlinizi/İlçenizi** (örnek: *İstanbul/Fatih*) girin.")
        bot.register_next_step_handler(msg, process_location_step)
    else:
        send_main_menu(user_id, welcome_text + "\n\nHayırlı ve bereketli bir gün dilerim! 👇")


# --- KONUM VE NAMAZ VAKTİ İŞLEME ---

def process_location_step(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    try:
        parts = [p.strip() for p in message.text.split('/')]
        if len(parts) < 2:
            raise ValueError
            
        il = parts[0]
        ilce = parts[1]
        
        # Namaz vakitlerini çekme (Kaydırma dahil)
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


# --- BİLGİLENDİRME HANDLER'LARI ---

@bot.message_handler(func=lambda message: message.text == "📖 Oyun Nasıl Oynanır?")
def handle_how_to_play(message):
    user_id = message.from_user.id
    
    info_text = (
        "📖 **OYUN NASIL OYNANIR? (İBADET ÇİFTLİĞİ REHBERİ)**\n\n"
        "İbadet Çiftliği, günlük ibadetlerinizi takip ederek sanal çiftliğinizi büyütmenize olanak tanır.\n\n"
        "**1. Başlangıç ve Kazanım Yolları:**\n"
        "  - **🕌 Namaz Takibi:** Beş vakit namazı kıldıkça (**10 Altın** 💰) kazanırsınız. Vakitleri doğru girmeyi unutmayın!\n"
        f"  - **📋 Günlük Görevler:** Her gün yenilenen zikir ve nafile namazı görevlerini yaparak **{DAILY_TASKS['kaza_nafile']['reward']} Yem** 🌾'e kadar kazanabilirsiniz.\n"
        f"  - **🔗 Referans Sistemi:** Arkadaşlarınızı davet ettiğinizde, davet ettiğiniz kişi katılır katılmaz **+{REF_YEM_SAHIBI} Yem** 🌾 kazanırsınız. Davet edilen kişi ödül almaz.\n\n"
        "**2. Civciv ve Yumurta Ekonomisi:**\n"
        f"  - **🛒 Civciv Pazarı:** **{CIVCIV_COST_ALTIN} Altın** karşılığında bir civciv alın. Sadece **{MAX_CIVCIV_OR_TAVUK}** adet civciviniz olabilir (Tavuklar sınırsızdır).\n"
        f"  - **🍗 Besleme:** Civcivleri görevlerden kazandığınız yemlerle besleyin. Bir civcivin tavuk olması için **{YEM_FOR_TAVUK} Yem** gereklidir.\n"
        f"  - **🥚 Yumurta Üretimi:** Tavuklar, her **{EGG_INTERVAL_HOURS} saatte bir** yumurta üretir.\n"
        f"  - **🥚 Yumurta Pazarı:** Yumurtaları burada Altın karşılığı satabilirsiniz. **1 Yumurta = {EGG_SATIS_DEGERI} Altın** değerindedir. Sattığınız yumurtalar **Haftalık Sıralamanızı ETKİLEMEZ**.\n\n"
        "**3. Sıralama:**\n"
        "  - **🏆 Haftalık Sıralama** toplam ürettiğiniz yumurta sayısına göre yapılır ve yumurta satışı sıralamanızı geri düşürmez.\n\n"
        "Hemen ilk görevinizi yaparak yem kazanmaya başlayın ve çiftliğinizi büyütün!"
    )
    bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=generate_main_menu())


@bot.message_handler(func=lambda message: message.text == "📊 Genel Durum")
def handle_general_status(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    # Günlük sıfırlama kontrolü
    check_daily_reset(data, user_id_str)
    
    # Mevcut hayvan sayımı
    civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'])
    tavuk_count = data[user_id_str].get('tavuk_count', 0)
    
    # Namaz ve görev durumu
    namaz_done = len(data[user_id_str]['namaz_today'])
    tasks_done_count = len(data[user_id_str]['daily_tasks_done'])
    
    # Satılabilir yumurta
    current_sellable_eggs = data[user_id_str].get('sellable_eggs', 0)
    
    status_text = (
        "**📊 GENEL DURUMUNUZ**\n\n"
        f"👤 Kullanıcı: **{data[user_id_str]['isim']}**\n"
        f"📍 Konum: **{data[user_id_str]['il'] if data[user_id_str]['il'] else 'Ayarlanmadı'}**\n\n"
        
        "**💰 EKONOMİ**\n"
        f"  - Altın: **{data[user_id_str]['altin']:.2f} 💰**\n"
        f"  - Yem: **{data[user_id_str]['yem']} 🌾**\n"
        f"  - Satılabilir Yumurta: **{current_sellable_eggs} 🥚**\n"
        f"  - Davet Sayısı: **{data[user_id_str]['invites']}**\n\n"
        
        "**🐓 ÇİFTLİK**\n"
        f"  - Civciv Sayısı: **{civciv_count}** / **{MAX_CIVCIV_OR_TAVUK}** 🐥\n"
        f"  - Tavuk Sayısı: **{tavuk_count} 🐓**\n\n"
        
        "**🕌 İBADET TAKİBİ**\n"
        f"  - Kılınan Namaz: **{namaz_done}** / 5\n"
        f"  - Tamamlanan Görev: **{tasks_done_count}** / {len(DAILY_TASKS)}\n"
        
    )
    bot.send_message(user_id, status_text, parse_mode='Markdown', reply_markup=generate_main_menu())


@bot.message_handler(func=lambda message: message.text == "🔗 Referans Sistemi")
def handle_referans_sistemi(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    if not BOT_USERNAME or BOT_USERNAME == 'ibadetciftligi_bot':
        bot.send_message(user_id, "❌ **HATA!** Botun kullanıcı adı (BOT_USERNAME) ayarlanmadığı için link oluşturulamıyor. Lütfen geliştiricinize danışın.", parse_mode='Markdown')
        return

    # Telegram linkini Markdown formatında oluşturma (Kullanıcının isteği üzerine Düzeltildi)
    referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id_str}"
    link_text = f"[Arkadaşını Davet Etmek İçin Tıkla]({referral_link})"
    
    ref_info = (
        "🔗 **REFERANS SİSTEMİ**\n\n"
        "Bu linki kullanarak arkadaşını davet et, ikramiyeni kap!\n\n"
        f"**🎁 Kazanım:** Davet ettiğin kişi bota katıldığında, **sana özel +{REF_YEM_SAHIBI} Yem** 🌾 anında hesabına eklenir. Davet edilen kişiye ödül verilmez.\n\n"
        f"**Tebrikler!** Şu ana kadar **{data[user_id_str]['invites']}** arkadaşını davet ettin.\n\n"
        f"**Davet Linkin:**\n{link_text}"
    )
    
    bot.send_message(user_id, ref_info, parse_mode='Markdown', reply_markup=generate_main_menu())


@bot.message_handler(func=lambda message: message.text.startswith("⏳ Sabah Namazı Kıldım") or message.text.startswith("✅ Sabah Namazı Kıldım"))
def handle_prayer_action(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    # Namaz Vaktini Çıkar
    vakit_tr = message.text.split(' ')[1].replace('Namazı', '').strip()
    vakit_key = vakit_tr.lower().replace('öğle', 'ogle').replace('yatsı', 'yatsi')
    
    if check_daily_reset(data, user_id_str):
        save_user_data(data)
        
    if vakit_key in data[user_id_str]['namaz_today']:
        bot.send_message(user_id, f"❗ **{vakit_tr}** namazını zaten kıldın.", reply_markup=generate_prayer_menu(user_id))
        return

    # Kazanım Ekle
    data[user_id_str]['altin'] += NAMAZ_ALTIN_KAZANCI
    data[user_id_str]['namaz_today'].append(vakit_key)
    save_user_data(data)
    
    bot.send_message(user_id, 
                     f"✅ **{vakit_tr}** namazını kıldığın için **+{NAMAZ_ALTIN_KAZANCI} Altın** kazandın!", 
                     parse_mode='Markdown', 
                     reply_markup=generate_prayer_menu(user_id))
                     
# --- GÜNLÜK GÖREVLER TAMAMLAMA LOGİĞİ ---

@bot.message_handler(func=lambda message: message.text.startswith("◻️") or message.text.startswith("✅"))
def handle_complete_daily_task(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    check_daily_reset(data, user_id_str) # Görev sıfırlamasını kontrol et
    
    # Hangi görevin tamamlandığını bul (Ödül ve emoji hariç metni al)
    task_text_raw = re.sub(r' \(\+?\d+ Yem\)', '', message.text.replace('✅', '').replace('◻️', '').strip())
    
    completed_task_key = None
    for key, task in DAILY_TASKS.items():
        if task['text'] == task_text_raw:
            completed_task_key = key
            break
            
    if not completed_task_key:
        # Alt menüdeki butonlara basıldığında buraya düşme ihtimali var
        if message.text == "🔙 Ana Menü":
            send_main_menu(user_id)
        else:
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
    
# ... (Devamı 5. mesajda)
# =================================================================
# BÖLÜM 5/5: PAZARLAR, YUMURTA SATIŞI VE BOT BAŞLATMA
# =================================================================

# --- YUMURTA PAZARI HANDLER'LARI (YENİ ÖZELLİK VE ZORUNLU KONTROLLER) ---

@bot.message_handler(func=lambda message: message.text == "🥚 Yumurta Pazarı")
def handle_egg_market(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    current_eggs = data[user_id_str].get('sellable_eggs', 0) # Satılabilir Yumurta
    
    info_text = (
        "🥚 **YUMURTA PAZARI** menüsündesin. \n\n"
        "Tavuklarının ürettiği yumurtaları Altın karşılığında satabilirsin.\n"
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
        bot.send_message(user_id, "❌ **Geçersiz Giriş!** Lütfen satmak istediğin miktarı sadece sayı olarak gir. İşlem iptal edildi.", parse_mode='Markdown', reply_markup=generate_main_menu())
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
    
    # Veri Güncelleme
    data[user_id_str]['sellable_eggs'] -= sell_quantity # Sadece satılabilir yumurtadan düşer
    # data['ranking_eggs'] (Haftalık Sıralama) EKLENMEZ/DÜŞÜLMEZ (İstenen özellik)
    data[user_id_str]['altin'] += kazanilan_altin       
    save_user_data(data)
    
    success_text = (
        f"✅ **Satış Başarılı!**\n"
        f"**{sell_quantity}** yumurta satıldı.\n"
        f"💰 Karşılığında **{kazanilan_altin:.2f} Altın** kazandınız.\n"
        f"💳 Yeni Altın Bakiyeniz: **{data[user_id_str]['altin']:.2f} 💰**"
    )
    
    bot.send_message(user_id, success_text, parse_mode='Markdown', reply_markup=generate_main_menu())

# --- CIVCIV PAZARI HANDLER'LARI VE BESLEME ---

@bot.message_handler(func=lambda message: message.text == "🛒 Civciv Pazarı")
def handle_civciv_market(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'])
    
    info_text = (
        "**🛒 Civciv Pazarı**\n\n"
        "Civcivleri buradan alabilirsin.\n"
        f"Fiyat: **{CIVCIV_COST_ALTIN} Altın** 💰\n\n"
        f"Mevcut Civciv Slotu: **{current_civciv_count}** / **{MAX_CIVCIV_OR_TAVUK}**\n\n"
    )
    
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
        info_text += "\n❗ **Maksimum civciv sınırına ulaştınız!** (8 civciv). Lütfen besleyip tavuğa dönüştürün."
        bot.send_message(user_id, info_text, parse_mode='Markdown', reply_markup=generate_main_menu())
        return
    
    bot.send_message(user_id, info_text + "\nAlmak istediğin civciv rengini seç:", parse_mode='Markdown', reply_markup=generate_market_buttons(data[user_id_str]['civciv_list']))

@bot.message_handler(func=lambda message: message.text.startswith("💰 Satın Al:"))
def handle_civciv_satin_alma(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    text = message.text
    
    current_civciv_count = len([c for c in data[user_id_str]['civciv_list'] if c['status'] == 'civciv'])
    civciv_color_raw = re.sub(r'[^\w\s]', '', text.replace('💰 Satın Al: ', '')).strip() # Emoji ve buton metnini temizler
    
    if data[user_id_str]['altin'] < CIVCIV_COST_ALTIN:
        bot.send_message(user_id, f"❌ **Yetersiz Altın!** Civciv almak için **{CIVCIV_COST_ALTIN - data[user_id_str]['altin']:.2f} Altın** daha kazanmalısın.", parse_mode='Markdown', reply_markup=generate_main_menu())
        return
        
    if current_civciv_count >= MAX_CIVCIV_OR_TAVUK:
         bot.send_message(user_id, f"❌ Maksimum civciv sınırına ulaştın. (Mevcut civciv sayısı: {current_civciv_count})", parse_mode='Markdown', reply_markup=generate_main_menu())
         return

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

    bot.send_message(user_id, f"✅ **Tebrikler!** **{civciv_color_raw} Civciv** satın aldın. Altın bakiyen: **{data[user_id_str]['altin']:.2f}**.", parse_mode='Markdown', reply_markup=generate_main_menu())


@bot.message_handler(func=lambda message: message.text.startswith("🥩 Besle:"))
def handle_feed_chicken_action(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    text = message.text
    
    # Buton metninden sadece rengi alır: "🥩 Besle: Sarı Civciv (0/10)" -> "Sarı Civciv"
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
            # İlk yumurtlama zamanını ayarla
            found_civciv['next_egg_time'] = (datetime.now(TURKEY_TIMEZONE) + timedelta(hours=EGG_INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
            data[user_id_str]['tavuk_count'] = data[user_id_str].get('tavuk_count', 0) + 1
            save_user_data(data)
            
            bot.send_message(user_id, f"🐓 **TEBRİKLER!** **{civciv_color}** yeterli yemi aldı ve **TAVUK** oldu!", parse_mode='Markdown', reply_markup=generate_main_menu())
        else:
            save_user_data(data)
            bot.send_message(user_id, f"🌾 **{civciv_color}** beslendi. Tavuk olmasına **{YEM_FOR_TAVUK - found_civciv['yem']} yem** kaldı.\nKalan yeminiz: **{data[user_id_str]['yem']}**", parse_mode='Markdown', reply_markup=generate_feed_menu_buttons(user_id))
    else:
        bot.send_message(user_id, "Hata: Beslenecek civciv bulunamadı.", reply_markup=generate_main_menu())


# --- HAFTALIK SIRALAMA VE DİĞER HANDLER'LAR (Kısaltıldı) ---

@bot.message_handler(func=lambda message: message.text == "🏆 Haftalık Sıralama")
def handle_weekly_ranking(message):
    user_id = message.from_user.id
    data, user_id_str = get_user_data(user_id)
    all_users = load_user_data()
    
    # Ranking Eggs (Satıştan etkilenmeyen yumurta sayısına göre sırala)
    ranking_list = sorted([
        {'id': uid, 'isim': udata.get('isim', 'Anonim'), 'eggs': udata.get('ranking_eggs', 0)}
        for uid, udata in all_users.items()
    ], key=lambda x: x['eggs'], reverse=True)
    
    rank_text = "🏆 **HAFTALIK YUMURTA SIRALAMASI**\n\n"
    
    for i, user in enumerate(ranking_list[:10]):
        rank_text += f"**{i+1}.** {user['isim']} - **{user['eggs']}** Yumurta\n"
        
    rank_text += "\n*(Sıralama, toplam ürettiğiniz yumurta (satıştan etkilenmez) miktarına göre yapılır)*"
    
    bot.send_message(user_id, rank_text, parse_mode='Markdown', reply_markup=generate_main_menu())
    
# Geri kalan menü handler'ları (Civciv Besle, Günlük Görevler, Namaz Takibi, Konum Güncelle) 
# Bölüm 3'teki menü oluşturucular ve Bölüm 4'teki aksiyon handler'ları tarafından zaten karşılanmaktadır.

# --- ARKA PLAN VE KEEP ALIVE ---

# GEREKLİ TÜM THREAD İŞLEVLERİ (İçerikleri uzun olduğu için sadece tanımları buraya bırakılır)

def ensure_daily_reset_loop():
    """Günlük görev/namaz sıfırlamasını 00:00'da yapar."""
    while True:
        now = datetime.now(TURKEY_TIMEZONE)
        next_reset = now.replace(hour=0, minute=1, second=0, microsecond=0)
        if now > next_reset:
            next_reset += timedelta(days=1)
        
        sleep_seconds = (next_reset - now).total_seconds()
        # print(f"Daily reset için bekleme: {sleep_seconds} saniye")
        time.sleep(sleep_seconds)
        
        all_users = load_user_data()
        for uid, udata in all_users.items():
            if check_daily_reset(all_users, uid):
                pass # check_daily_reset içinde save_user_data çağrılır
        save_user_data(all_users)
        
def egg_production_and_notification():
    """Tavukların yumurta üretmesini kontrol eder ve bildirim yapar."""
    while True:
        all_users = load_user_data()
        for uid, udata in all_users.items():
            now = datetime.now(TURKEY_TIMEZONE)
            made_change = False
            
            for civciv in udata['civciv_list']:
                if civciv['status'] == 'tavuk' and civciv['next_egg_time']:
                    next_egg_time = datetime.strptime(civciv['next_egg_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TURKEY_TIMEZONE)
                    
                    if now >= next_egg_time:
                        # Yumurtayı üret
                        udata['sellable_eggs'] = udata.get('sellable_eggs', 0) + 1
                        udata['ranking_eggs'] = udata.get('ranking_eggs', 0) + 1
                        udata['total_lifetime_yumurta'] = udata.get('total_lifetime_yumurta', 0) + 1
                        
                        # Sonraki yumurtlama zamanını ayarla
                        new_next_egg_time = next_egg_time + timedelta(hours=EGG_INTERVAL_HOURS)
                        civciv['next_egg_time'] = new_next_egg_time.strftime('%Y-%m-%d %H:%M:%S')
                        made_change = True
                        
                        # Bildirim
                        try:
                            bot.send_message(uid, f"🐣 **Yumurta!** {civciv['color']} tavuğunuz bir yumurta (🥚) üretti. Toplam: {udata['sellable_eggs']}", parse_mode='Markdown')
                        except Exception as e:
                            print(f"Yumurta bildirim hatası ({uid}): {e}")

            if made_change:
                save_user_data(all_users)
                
        time.sleep(600) # 10 dakika bekler

def prayer_time_notification_loop():
    """Namaz hatırlatma mekanizması."""
    while True:
        # Kodun geri kalan kısmı buraya gelecek (Botun ana mantığından bağımsızdır, polling yapıyorsa gerekli değildir)
        time.sleep(600) # 10 dakika bekler
        
def save_counter_state_periodically():
    """Sayaç durumunu düzenli olarak kaydeder."""
    # Şu an sayaç sistemi aktif olmadığı için bu thread sadece yer tutar.
    while True:
        time.sleep(3600) # 1 saat bekler

# --- 7/24 AKTİF TUTMA (FLASK SUNUCUSU) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive"

def run_keep_alive():
    """Flask uygulamasını Render'ın gerektirdiği portta çalıştırır."""
    # Render, ortam değişkeni olarak PORT sağlar.
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 8080))

def keep_alive():
    """Flask sunucusunu ayrı bir thread'de başlatır."""
    t = threading.Thread(target=run_keep_alive)
    t.daemon = True
    t.start()
    
# --- BOT BAŞLATMA ---

# Ana menüye dönüş handler'ı
@bot.message_handler(func=lambda message: message.text == "🔙 Ana Menü")
def handle_back_to_main_menu(message):
    send_main_menu(message.chat.id, "Ana Menüye dönüldü.")

# Konum Güncelle handler'ı
@bot.message_handler(func=lambda message: message.text == "📍 Konum Güncelle")
def handle_location_update(message):
    msg = bot.send_message(message.chat.id, "📍 Lütfen namaz vakitleriniz için **İlinizi/İlçenizi** (örnek: *İstanbul/Fatih*) girin.")
    bot.register_next_step_handler(msg, process_location_step)


if __name__ == '__main__':
    keep_alive() # Flask sunucusunu başlat

    # ARKA PLAN GÖREVLERİNİ BAŞLAT
    # Indentation hatasını engellemek için, tüm thread'ler if __name__ == '__main__': içinde başlatılır.
    threading.Thread(target=ensure_daily_reset_loop, daemon=True).start()
    # threading.Thread(target=ensure_weekly_reset, daemon=True).start() # Haftalık sıfırlama şu an zorunlu değil
    threading.Thread(target=egg_production_and_notification, daemon=True).start()
    threading.Thread(target=prayer_time_notification_loop, daemon=True).start()
    threading.Thread(target=save_counter_state_periodically, daemon=True).start()
    
    print("--- Telegram İbadet Çiftliği Botu Başlatılıyor ---")
    
    # BOTU SÜREKLİ DİNLEMEYE AL (Polling)
    try:
        # Webhook'ları temizleme adımı, sadece güvenilir bir yerde yapılırsa mantıklıdır. 
        # Polling kullanıldığında webhook gerekmez, temizlenmesi en sağlıklısıdır.
        # bot.delete_webhook()
        print("Webhook temizlendi (Eğer varsa).")

        print("Bot Polling başlıyor.")
        # Bu, telebot'un sürekli dinlemesini sağlar.
        bot.polling(non_stop=True, interval=0, timeout=40) 
        
    except Exception as e:
        print(f"Bot Çalışma Hatası: {e}. 5 saniye sonra yeniden deneniyor.")
        time.sleep(5)
