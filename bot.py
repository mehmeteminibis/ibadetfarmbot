_make_request(token,  method_url,  parametreler=yük) döndür
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyası ,  satır  168, _make_request  içinde 
    json_result  =  _check_result(yöntem_adı,  sonuç)
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyası ,  satır  197, _check_result  içinde 
     ApiTelegramException(method_name,  result,  result_json) ' u yükselt
telebot.apihelper.ApiTelegramException: Telegram API'sine yapılan bir  istek  başarısız oldu . Hata kodu : 409. Açıklama: Çakışma : Webhook etkinken getUpdates yöntemi kullanılamaz ; önce webhook'u silmek için deleteWebhook kullanın .                          
"
2025-11-30  17:45:39,778 (  __init__.py:1241  MainThread)  HATA  -  TeleBot:  "İş parçacıklı yoklama  istisnası  : Telegram API'sine yapılan  bir  istek başarısız oldu . Hata kodu: 409. Açıklama: Çakışma : Webhook etkinken getUpdates yöntemi kullanılamaz ; önce webhook'u silmek için deleteWebhook kullanın "                          
2025-11-30  17:45:39,780  (__init__.py:1243  MainThread)  HATA  -  TeleBot:  "İstisna  geri izleme:
Geri izleme  (en  son  çağrı  en son):
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/__init__.py" dosyası ,  satır  1234,  __threaded_polling'de 
    yoklama_iş parçacığı.istisnaları_yükseltin()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/util.py" dosyası , 115.  satır , raise_exceptions'da   
     self.exception_info'yu yükselt
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/util.py" dosyası ,  satır  97,  çalıştırmada 
    görev(*argümanlar,  **anahtar kelimeler)
    ~~~~^^^^^^^^^^^^^^^^^
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/__init__.py" dosyası ,  satır  688, __retrieve_updates  içinde 
    güncellemeler  =  self.get_updates(offset=(self.last_update_id  +  1),
                               izin verilen_güncellemeler=izin verilen_güncellemeler,
                               zaman aşımı=zaman aşımı,  uzun_arama_zaman_aşımı=uzun_arama_zaman_aşımı)
  get_updates dosyasında  "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/__init__.py" ,  satır  660  
    json_güncellemeleri  =  apihelper.get_updates(
        self.token,  ofset=ofset,  limit=limit,  zaman aşımı=zaman aşımı,  izin verilen_güncellemeler=izin verilen_güncellemeler,
        uzun_araştırma_zaman_aşımı=uzun_araştırma_zaman_aşımı)
  get_updates dosyasındaki  "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyasının 339.  satırı   
     _make_request(token,  method_url,  parametreler=yük) döndür
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyası ,  satır  168, _make_request  içinde 
    json_result  =  _check_result(yöntem_adı,  sonuç)
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyası ,  satır  197, _check_result  içinde 
     ApiTelegramException(method_name,  result,  result_json) ' u yükselt
telebot.apihelper.ApiTelegramException: Telegram API'sine yapılan bir  istek  başarısız oldu . Hata kodu : 409. Açıklama: Çakışma : Webhook etkinken getUpdates yöntemi kullanılamaz ; önce webhook'u silmek için deleteWebhook kullanın .                          
"
2025-11-30  17:45:47,939  (__init__.py:1241  MainThread)  HATA  -  TeleBot:  "İş parçacıklı yoklama  istisnası  : Telegram API'sine yapılan  bir  istek başarısız oldu . Hata kodu: 409. Açıklama : Çakışma : Webhook etkinken getUpdates yöntemi kullanılamaz ; önce webhook'u silmek için deleteWebhook kullanın "                          
2025-11-30  17:45:47,940  (__init__.py:1243  MainThread)  HATA  -  TeleBot:  "İstisna  geri izleme:
Geri izleme  (en  son  çağrı  en son):
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/__init__.py" dosyası ,  satır  1234,  __threaded_polling'de 
    yoklama_iş parçacığı.istisnaları_yükseltin()
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/util.py" dosyası , 115.  satır , raise_exceptions'da   
     self.exception_info'yu yükselt
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/util.py" dosyası ,  satır  97,  çalıştırmada 
    görev(*argümanlar,  **anahtar kelimeler)
    ~~~~^^^^^^^^^^^^^^^^^
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/__init__.py" dosyası ,  satır  688, __retrieve_updates  içinde 
    güncellemeler  =  self.get_updates(offset=(self.last_update_id  +  1),
                               izin verilen_güncellemeler=izin verilen_güncellemeler,
                               zaman aşımı=zaman aşımı,  uzun_arama_zaman_aşımı=uzun_arama_zaman_aşımı)
  get_updates dosyasında  "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/__init__.py" ,  satır  660  
    json_güncellemeleri  =  apihelper.get_updates(
        self.token,  ofset=ofset,  limit=limit,  zaman aşımı=zaman aşımı,  izin verilen_güncellemeler=izin verilen_güncellemeler,
        uzun_araştırma_zaman_aşımı=uzun_araştırma_zaman_aşımı)
  get_updates dosyasındaki  "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyasının 339.  satırı   
     _make_request(token,  method_url,  parametreler=yük) döndür
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyası ,  satır  168, _make_request  içinde 
    json_result  =  _check_result(yöntem_adı,  sonuç)
   "/opt/render/project/src/.venv/lib/python3.13/site-packages/telebot/apihelper.py" dosyası ,  satır  197, _check_result  içinde 
     ApiTelegramException(method_name,  result,  result_json) ' u yükselt
telebot.apihelper.ApiTelegramException: Telegram API'sine yapılan bir  istek  başarısız oldu . Hata kodu : 409. Açıklama: Çakışma : Webhook etkinken getUpdates yöntemi kullanılamaz ; önce webhook'u silmek için deleteWebhook kullanın .                          
"
