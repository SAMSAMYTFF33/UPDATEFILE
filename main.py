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
# إعدادات معرفات (IDs) تليجرام الجديدة ⚙️
# ==========================================
TELEGRAM_TOKEN = "8288533297:AAGMDEG1feHpX6887h1kVhmSGsL0Y6SpF04"

# الـ ID المخصص لإشعارات المهام الفورية (كل 5 دقائق)
ID_TASKS = "7638322813"

# الـ ID المخصص لتقارير عدم وجود مهام وبقاء السيرفر أونلاين (كل 15 دقيقة)
ID_REPORT = "8486184645"

# ==========================================
# دالة إرسال الإشعارات العامة
# ==========================================
def send_telegram_message(chat_id, message):
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(telegram_url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"✅ تم إرسال الرسالة بنجاح إلى الـ ID: {chat_id}")
        else:
            print(f"⚠️ فشل إرسال الرسالة للـ ID ({chat_id}): {response.text}")
    except Exception as e:
        print(f"⚠️ خطأ أثناء الاتصال بتليجرام للـ ID ({chat_id}): {e}")

# ==========================================
# الدالة الأساسية لفحص وجلب البيانات من الموقع
# ==========================================
def fetch_orders():
    session = requests.Session()
    try:
        session.get(BASE_URL, headers=HEADERS, timeout=15)
        login_data = {
            "signin[username]": USERNAME,
            "signin[password]": PASSWORD,
            "signin[remember]": "1",
            "signin[refer_url]": "@office_initial"
        }
        login_response = session.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=15)
        
        if login_response.status_code != 200:
            return "ERROR_AUTH", "خطأ في الاتصال بالموقع أثناء تسجيل الدخول."

        r = session.get(TARGET_URL, headers=HEADERS, timeout=15)
        if "Выход" not in r.text:
            return "ERROR_AUTH", "فشل تسجيل الدخول. تأكد من صحة حساب الموقع."

        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table") 
        if not table:
            return "NO_TABLE", "تم تسجيل الدخول، ولكن لم يتم العثور على جدول المهام حالياً."
            
        rows = table.find_all("tr")
        jobs_found = []
        
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
                    job_link = BASE_URL
                    link_tag = title_cell.find("a")
                    if link_tag and link_tag.has_attr("href"):
                        job_link = BASE_URL + link_tag["href"]
                    jobs_found.append({"title": title, "price": price, "link": job_link})
                    
        return "SUCCESS", jobs_found

    except Exception as e:
        return "ERROR_CONN", f"حدث خطأ أثناء الاتصال: {str(e)}"

# ==========================================
# ⏱ الحلقة الأولى: فحص المهام وإرسالها فوراً (كل 5 دقائق)
# ==========================================
def fast_check_loop():
    while True:
        print("🔍 [حلقة الـ 5 دقائق]: جاري فحص المهام المتاحة...")
        status, result = fetch_orders()
        
        if status == "SUCCESS" and len(result) > 0:
            print(f"🔥 تم العثور على {len(result)} مهام! جاري إرسالها للـ ID: {ID_TASKS}")
            for job in result:
                job_message = (
                    f"🔔 *مهمة جديدة متاحة للعمل فوراً!*\n\n"
                    f"📌 *العنوان:* {job['title']}\n"
                    f"💰 *السعر:* {job['price']} روبل\n\n"
                    f"🔗 [اضغط هنا لفتح المهمة مباشرة]({job['link']})"
                )
                send_telegram_message(ID_TASKS, job_message)
        else:
            print("🔍 [حلقة الـ 5 دقائق]: لا توجد مهام حالياً (لن يتم إرسال إزعاج).")
            
        time.sleep(300) # فحص كل 5 دقائق تماماً

# ==========================================
# ⏱ الحلقة الثانية: تقرير عدم الوجود لمنع توقف السيرفر (كل 15 دقيقة)
# ==========================================
def keep_alive_report_loop():
    while True:
        print("💤 [حلقة الـ 15 دقيقة]: جاري إرسال تقرير الحالة وحماية السيرفر من النوم...")
        status, result = fetch_orders()
        
        if status == "SUCCESS" and len(result) == 0:
            report_msg = "🔍 *تقرير الفحص الدوري (كل 15 دقيقة):*\nلا توجد أي مهام متاحة حالياً في الجدول، السيرفر يعمل بشكل ممتاز وبانتظار الصيد! ⚙️"
            send_telegram_message(ID_REPORT, report_msg)
        elif status != "SUCCESS":
            # إرسال تقرير في حال وجود مشكلة في الموقع أو الحساب
            send_telegram_message(ID_REPORT, f"⚠️ *تنبيه من السيرفر:*\n{result}")
        else:
            print("💤 [حلقة الـ 15 دقيقة]: توجد مهام بالفعل، حلقة الـ 5 دقائق تولت إرسالها.")
            
        time.sleep(900) # إرسال تقرير كل 15 دقيقة تماماً (تمنع الـ Spin down في Render)

# ==========================================
# سيرفر ويب وهمي لاستقبال اتصالات الويب من Render
# ==========================================
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("السكربت يعمل بنظام الحلقات الذكية (5 دقائق للمهام / 15 دقيقة للتقارير)!".encode("utf-8"))

def run_web_server():
    server_address = ('', 10000)
    httpd = HTTPServer(server_address, WebServerHandler)
    print("🌐 تم تشغيل سيرفر الويب الأساسي بنجاح...")
    httpd.serve_forever()

# ==========================================
# نقطة انطلاق البرنامج الأساسية
# ==========================================
if __name__ == "__main__":
    print("🚀 تم بدء تشغيل السكريبت المطور بالكامل...")
    
    # رسالة ترحيبية أولية للحسابين للتأكد من جاهزيتهما
    send_telegram_message(ID_TASKS, "🚀 تم تفعيل قناة استقبال صيد المهام الفورية بنجاح (الفحص كل 5 دقائق)!")
    send_telegram_message(ID_REPORT, "⚙️ تم تفعيل قناة التقارير الدورية وحماية السيرفر بنجاح (التقرير كل 15 دقيقة)!")
    
    # تشغيل حلقة الفحص السريع (5 دقائق) في الخلفية
    t1 = threading.Thread(target=fast_check_loop, daemon=True)
    t1.start()
    
    # تشغيل حلقة التقارير والحماية (15 دقيقة) في الخلفية
    t2 = threading.Thread(target=keep_alive_report_loop, daemon=True)
    t2.start()
    
    # تشغيل السيرفر الرئيسي لـ Render
    run_web_server()
