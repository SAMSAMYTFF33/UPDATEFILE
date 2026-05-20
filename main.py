import time
import requests
from bs4 import BeautifulSoup
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==========================================
# بيانات تسجيل الدخول والإعدادات
# ==========================================
USERNAME = "miricanmoroco@gmail.com"
PASSWORD = "miricanmoroco" 

BASE_URL = "https://forumok.com"
LOGIN_URL = "https://forumok.com/login"
TARGET_URL = "https://forumok.com/orders-search/socio"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": BASE_URL
}

# ==========================================
# إعدادات معرفات (IDs) تليجرام
# ==========================================
TELEGRAM_TOKEN = "8288533297:AAGMDEG1feHpX6887h1kVhmSGsL0Y6SpF04"

ID_TASKS = "7638322813"   # الحساب الخاص بالمهام (عند وجود مهمة)
ID_REPORT = "8486184645"  # الحساب الخاص بالتقرير (عند عدم وجود مهمة)

# ==========================================
# دالة إرسال الإشعارات
# ==========================================
def send_telegram_message(chat_id, message):
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(telegram_url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ خطأ أثناء الاتصال بتليجرام: {e}")

# ==========================================
# الحلقة الموحدة للفحص (تمنع التكرار والتداخل)
# ==========================================
def smart_check_loop():
    # عداد داخلي لحساب وقت التقرير (كل 15 دقيقة)
    # الفحص يتم كل 5 دقائق، إذن كل 3 دورات فحص تعادل 15 دقيقة
    loop_counter = 0

    while True:
        loop_counter += 1
        session = requests.Session()
        print(f"🔄 [بدء الفحص الدورة رقم {loop_counter}]...")
        
        try:
            session.get(BASE_URL, headers=HEADERS, timeout=15)
            login_data = {
                "signin[username]": USERNAME,
                "signin[password]": PASSWORD,
                "signin[remember]": "1",
                "signin[refer_url]": "@office_initial"
            }
            login_response = session.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=15)
            
            if login_response.status_code == 200:
                r = session.get(TARGET_URL, headers=HEADERS, timeout=15)
                
                if "Выход" in r.text:
                    soup = BeautifulSoup(r.text, "html.parser")
                    table = soup.find("table") 
                    
                    jobs_found = []
                    if table:
                        rows = table.find_all("tr")
                        for row in rows[1:]:
                            cells = row.find_all("td")
                            if len(cells) >= 8:
                                title_cell = cells[1]
                                price_cell = cells[2]
                                
                                # استخراج السعر وتدقيقه
                                price = price_cell.get_text(strip=True)
                                if not price or price == "" or "---" in price:
                                    price = "*"
                                else:
                                    # إبقاء الأرقام فقط أو الكلمة المكتوبة
                                    price = price.replace("руб.", "").strip()
                                
                                actions_cell = cells[-1] 
                                actions_text = actions_cell.get_text(strip=True)
                                has_link = actions_cell.find("a") or ("---" not in actions_text and actions_text != "")
                                
                                if has_link:
                                    jobs_found.append(price)

                    # 🌟 [حالة وجود مهام] -> يرسل إلى ID_TASKS
                    if len(jobs_found) > 0:
                        for current_price in jobs_found:
                            short_message = f"توجد مهمة واحد بسعر {current_price} روبل"
                            send_telegram_message(ID_TASKS, short_message)
                            print(f"🔥 تم إرسال إشعار بمهمة سعرها {current_price} للـ ID الخاص بالمهام.")
                    
                    # 🌟 [حالة عدم وجود مهام] -> يرسل إلى ID_REPORT كل 15 دقيقة (الدورة 1، 3، 6...) لمنع النوم
                    else:
                        print("🔍 لا توجد مهام حالياً في هذه الدورة.")
                        if loop_counter >= 3: # تعادل 15 دقيقة تماماً
                            send_telegram_message(ID_REPORT, "لا توجد أي مهمة")
                            print("💤 تم إرسال تقرير (لا توجد أي مهمة) لحماية السيرفر من النوم.")
                            loop_counter = 0 # تصفير العداد لإعادة الحساب

                else:
                    print("❌ فشل تسجيل الدخول للموقع.")
            else:
                print("❌ فشل الاتصال بالموقع.")

        except Exception as e:
            print(f"⚠️ حدث خطأ أثناء الفحص الحالي: {e}")
            
        print("💤 في انتظار الفحص القادم بعد 5 دقائق...")
        time.sleep(300) # فحص منظم وثابت كل 5 دقائق تماماً بدلاً من 3

# ==========================================
# سيرفر ويب لاستقبال طلبات Render
# ==========================================
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("السكربت يعمل بنظام الفحص الموحد الذكي!".encode("utf-8"))

def run_web_server():
    server_address = ('', 10000)
    httpd = HTTPServer(server_address, WebServerHandler)
    httpd.serve_forever()

# ==========================================
# نقطة الانطلاق
# ==========================================
if __name__ == "__main__":
    print("🚀 تم تشغيل السكريبت المحدث بنجاح...")
    
    # تشغيل حلقة الفحص الذكية في الخلفية
    t = threading.Thread(target=smart_check_loop, daemon=True)
    t.start()
    
    # تشغيل سيرفر الويب لـ Render
    run_web_server()
