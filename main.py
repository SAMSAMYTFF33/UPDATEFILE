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
# إعدادات إشعارات تليجرام الخاصة بك
# ==========================================
TELEGRAM_TOKEN = "8288533297:AAGMDEG1feHpX6887h1kVhmSGsL0Y6SpF04"
TELEGRAM_CHAT_ID = "7638322813"

# ==========================================
# دالة إرسال الإشعارات
# ==========================================
def send_notification(title, price, link):
    """
    تقوم هذه الدالة بطباعة الإشعار وإرساله إلى تليجرام
    """
    print(f"\n🔔 [إشعار]: {title}")
    print(f"💰 السعر: {price} روبل")
    print(f"🔗 الرابط: {link}\n")
    
    # صياغة نص الرسالة لتليجرام
    message = (
        f"🔔 *إشعار من السكريبت!*\n\n"
        f"📌 *الموضوع:* {title}\n"
        f"💰 *السعر:* {price} روبل\n\n"
        f"🔗 [اضغط هنا لفتح الرابط]({link})"
    )
    
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    
    try:
        response = requests.post(telegram_url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ تم إرسال الإشعار بنجاح إلى تليجرام.")
        else:
            print(f"⚠️ فشل إرسال الإشعار لتليجرام: {response.text}")
    except Exception as e:
        print(f"⚠️ خطأ أثناء الاتصال بتليجرام: {e}")

# ==========================================
# الدالة الرئيسية لفحص المهام
# ==========================================
def check_for_orders():
    session = requests.Session()
    try:
        print("🔄 جاري فتح الصفحة الرئيسية...")
        session.get(BASE_URL, headers=HEADERS, timeout=15)
        
        print("🔐 جاري تسجيل الدخول...")
        login_data = {
            "signin[username]": USERNAME,
            "signin[password]": PASSWORD,
            "signin[remember]": "1",
            "signin[refer_url]": "@office_initial"
        }
        login_response = session.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=15)
        
        if login_response.status_code != 200:
            print("❌ فشل الاتصال بالموقع أثناء تسجيل الدخول.")
            return

        print("📥 جاري فحص صفحة المهام...")
        r = session.get(TARGET_URL, headers=HEADERS, timeout=15)
        
        if "Выход" not in r.text:
            print("❌ فشل تسجيل الدخول. تأكد من صحة الحساب.")
            return

        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table") 
        
        if not table:
            print("⚠️ لم يتم العثور على جدول المهام حالياً.")
            return
            
        rows = table.find_all("tr")
        available_jobs_count = 0
        
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 8:
                title_cell = cells[1]
                title = title_cell.get_text(strip=True)
                price = cells[2].get_text(strip=True)
                
                actions_cell = cells[-1] 
                actions_text = actions_cell.get_text(strip=True)
                has_link = actions_cell.find("a") or ("---" not in actions_text and actions_text != "")
                
                if has_link:
                    available_jobs_count += 1
                    job_link = BASE_URL
                    link_tag = title_cell.find("a")
                    if link_tag and link_tag.has_attr("href"):
                        job_link = BASE_URL + link_tag["href"]
                    
                    send_notification(f"مهمة متاحة للعمل فوراً: {title}", price, job_link)
                    
        if available_jobs_count == 0:
            print("🔍 تم الفحص: لا توجد مهام متاحة حالياً.")
        else:
            print(f"✅ إجمالي المهام المتاحة: {available_jobs_count}")

    except Exception as e:
        print(f"⚠️ حدث خطأ أثناء الفحص: {e}")

# ==========================================
# حلقة الفحص المستمرة
# ==========================================
def background_loop():
    # إرسال رسالة تجريبية فوراً عند بدء تشغيل السيرفر للتأكد من التليجرام
    print("📢 جاري إرسال رسالة التجربة إلى تليجرام...")
    send_notification("السكريبت تم تشغيله بنجاح على Render! 🚀", "0.00", "https://render.com")
    
    while True:
        check_for_orders()
        print("-" * 50)
        print("💤 في انتظار التحديث القادم بعد 3 دقائق...")
        time.sleep(180)

# ==========================================
# سيرفر ويب وهمي لإرضاء منصة Render
# ==========================================
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("السكريبت يعمل في الخلفية بنجاح!".encode("utf-8"))

def run_web_server():
    server_address = ('', 10000) # بورت 10000 هو الافتراضي في Render
    httpd = HTTPServer(server_address, WebServerHandler)
    print("🌐 تم تشغيل سيرفر الويب الوهمي للبقاء أونلاين...")
    httpd.serve_forever()

# ==========================================
# نقطة انطلاق البرنامج
# ==========================================
if __name__ == "__main__":
    print("🚀 تم بدء تشغيل السكريبت بالكامل...")
    
    # تشغيل حلقة الفحص في خلفية منفصلة
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()
    
    # تشغيل سيرفر الويب في الواجهة الأساسية ليستجيب لـ Render
    run_web_server()
