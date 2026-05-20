import time
import requests
from bs4 import BeautifulSoup
import threading
import telebot
from telebot import types
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==========================================
# الإعدادات الأساسية
# ==========================================
TELEGRAM_TOKEN = "8288533297:AAGMDEG1feHpX6887h1kVhmSGsL0Y6SpF04"
bot = telebot.TeleBot(TELEGRAM_TOKEN)

BASE_URL = "https://forumok.com"
LOGIN_URL = "https://forumok.com/login"
TARGET_URL = "https://forumok.com/orders-search/socio"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": BASE_URL
}

# ذاكرة مؤقتة لتخزين بيانات المستخدمين وجلساتهم أثناء استخدام البوت
user_sessions = {}
user_data_store = {}

# ==========================================
# دالة الاتصال بالموقع وجلب البيانات
# ==========================================
def fetch_site_data(username, password):
    session = requests.Session()
    try:
        session.get(BASE_URL, headers=HEADERS, timeout=10)
        login_data = {
            "signin[username]": username,
            "signin[password]": password,
            "signin[remember]": "1",
            "signin[refer_url]": "@office_initial"
        }
        login_response = session.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=10)
        
        if login_response.status_code != 200:
            return None, "❌ خطأ في الاتصال بالموقع أثناء تسجيل الدخول."

        r = session.get(TARGET_URL, headers=HEADERS, timeout=10)
        if "Выход" not in r.text:
            return None, "❌ فشل تسجيل الدخول. تأكد من صحة الإيميل وكلمة المرور."

        soup = BeautifulSoup(r.text, "html.parser")
        
        # 💰 استخراج الرصيد (روبل)
        balance = "*"
        balance_tag = soup.find("span", {"class": "balance"}) or soup.find(text=lambda t: "руб" in t)
        if balance_tag:
            balance = balance_tag.get_text(strip=True).replace("руб.", "").strip()

        # 📋 حساب عدد المهام
        tasks_count = 0
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) >= 8:
                    actions_cell = cells[-1]
                    actions_text = actions_cell.get_text(strip=True)
                    has_link = actions_cell.find("a") or ("---" not in actions_text and actions_text != "")
                    if has_link:
                        tasks_count += 1

        return {"balance": balance, "tasks": tasks_count}, "SUCCESS"

    except Exception as e:
        return None, f"⚠️ حدث خطأ أثناء الاتصال: {str(e)}"

# ==========================================
# لوحات الأزرار تفاعلية (Keyboards)
# ==========================================
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add(types.KeyboardButton("1️⃣ تسجيل دخول"))
    return markup

def get_logged_in_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_refresh = types.KeyboardButton("4️⃣ تحديث البيانات")
    btn_logout = types.KeyboardButton("3️⃣ تسجيل خروج")
    markup.add(btn_refresh, btn_logout)
    return markup

# ==========================================
# استقبال الأوامر والرسائل (تليجرام)
# ==========================================

# عند إرسال /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if chat_id in user_data_store:
        bot.send_message(chat_id, "👋 أنت مسجل الدخول بالفعل بالخلفية!", reply_markup=get_logged_in_menu())
    else:
        bot.send_message(chat_id, "📌 أهلاً بك في بوت صائد المهام. اختر من القائمة أدناه للبدء:", reply_markup=get_main_menu())

# معالجة النصوص والأزرار
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    chat_id = message.chat.id
    text = message.text

    # الضغط على زر تسجيل الدخول
    if text == "1️⃣ تسجيل دخول" or text == "1":
        bot.send_message(chat_id, "📬 قم بكتابة اسم المستخدم أو الـ Gmail الخاص بك:")
        user_sessions[chat_id] = {'step': 'WAITING_EMAIL'}
        
    # الضغط على زر تسجيل الخروج
    elif text == "3️⃣ تسجيل خروج" or text == "3":
        if chat_id in user_data_store:
            del user_data_store[chat_id]
        if chat_id in user_sessions:
            del user_sessions[chat_id]
        bot.send_message(chat_id, "🔒 تم تسجيل الخروج بنجاح وحذف بيانات الجلسة.", reply_markup=get_main_menu())

    # الضغط على زر تحديث البيانات
    elif text == "4️⃣ تحديث البيانات" or text == "4":
        if chat_id not in user_data_store:
            bot.send_message(chat_id, "⚠️ لم تقم بتسجيل الدخول بعد!", reply_markup=get_main_menu())
            return
        
        bot.send_message(chat_id, "🔄 جاري تحديث وفحص البيانات الحالية من الموقع...")
        creds = user_data_store[chat_id]
        data, status = fetch_site_data(creds['email'], creds['password'])
        
        if status == "SUCCESS":
            msg = f"📊 *تحديث البيانات الحالية:*\n\n💰 رصيد الروبل لديك: `{data['balance']}` روبل\n📋 عدد المهام المتوفرة: `{data['tasks']}`"
            bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=get_logged_in_menu())
        else:
            bot.send_message(chat_id, status, reply_markup=get_logged_in_menu())

    # معالجة خطوات إدخال البيانات (الـ Steps)
    elif chat_id in user_sessions:
        current_step = user_sessions[chat_id]['step']
        
        # استقبال الإيميل
        if current_step == 'WAITING_EMAIL':
            user_sessions[chat_id]['email'] = text
            user_sessions[chat_id]['step'] = 'WAITING_PASSWORD'
            bot.send_message(chat_id, "🔐 ممتاز، الآن أرسل كلمة المرور الخاصة بحسابك:")
            
        # استقبال الباسورد والبدء في الفحص والتشغيل
        elif current_step == 'WAITING_PASSWORD':
            email = user_sessions[chat_id]['email']
            password = text
            bot.send_message(chat_id, "⏳ جاري تسجيل الدخول وفحص الحساب، يرجى الانتظار...")
            
            data, status = fetch_site_data(email, password)
            
            if status == "SUCCESS":
                # حفظ البيانات للتمكن من التحديث لاحقاً عبر زر (4)
                user_data_store[chat_id] = {'email': email, 'password': password}
                del user_sessions[chat_id]
                
                success_msg = f"✅ تم تسجيل الدخول بنجاح!\n\n💰 رصيد الروبل الحالي: `{data['balance']}` روبل\n📋 عدد المهام المتوفرة الآن: `{data['tasks']}`"
                bot.send_message(chat_id, success_msg, parse_mode="Markdown", reply_markup=get_logged_in_menu())
            else:
                # في حال الفشل نتيح له المحاولة مجدداً
                del user_sessions[chat_id]
                bot.send_message(chat_id, f"{status}\n\nجرّب الضغط على زر تسجيل الدخول مرة أخرى.", reply_markup=get_main_menu())
    else:
        bot.send_message(chat_id, "يرجى استخدام الأزرار المتوفرة في القائمة بالأسفل.", reply_markup=get_main_menu())

# ==========================================
# تشغيل السيرفر لـ Render في الخلفية لمنع النوم
# ==========================================
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("البوت التفاعلي يعمل أونلاين بنجاح!".encode("utf-8"))

def run_web_server():
    server_address = ('', 10000)
    httpd = HTTPServer(server_address, WebServerHandler)
    httpd.serve_forever()

# ==========================================
# انطلاق البوت
# ==========================================
if __name__ == "__main__":
    print("🚀 جاري بدء تشغيل البوت التفاعلي المطور...")
    
    # تشغيل سيرفر الويب الخاص بـ Render في Thread منفصل
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # تشغيل استقبال رسائل تليجرام بشكل مستمر (Polling)
    # ملاحظة: Polling المستمر يرسل ويستقبل إشارات بشكل دائم مما يضمن بقاء سيرفر Render نشطاً
    bot.infinity_polling()
