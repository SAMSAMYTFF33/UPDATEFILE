مشكلة كود يضهر مهمة  واحد هده ولكن هي لا توجد 


import time
import requests
from bs4 import BeautifulSoup
import threading
import re
import os  # تم إضافة مكتبة os لقراءة الـ Port من Render
import telebot
from telebot import types
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==========================================
# الإعدادات الأساسية وتوكن البوت الخاص بك
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

# ذاكرة السيرفر لتخزين الحالات المؤقتة للمستخدمين وجلساتهم
user_sessions = {}
user_data_store = {}

# ==========================================
# دالة الاتصال بالموقع وفحص البيانات بدقة
# ==========================================
def fetch_site_data(username, password):
    session = requests.Session()
    try:
        session.get(BASE_URL, headers=HEADERS, timeout=12)
        login_data = {
            "signin[username]": username,
            "signin[password]": password,
            "signin[remember]": "1",
            "signin[refer_url]": "@office_initial"
        }
        login_response = session.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=12)

        if login_response.status_code != 200:
            return None, "❌ خطأ في الاتصال بالموقع أثناء تسجيل الدخول."

        r = session.get(TARGET_URL, headers=HEADERS, timeout=12)
        if "Выход" not in r.text:
            return None, "❌ فشل تسجيل الدخول. تأكد من صحة الإيميل وكلمة المرور."

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()

        page_text = soup.get_text(separator="\n")

        balance = "0.0"
        available_match = re.search(r"Доступно:\s*([\d.,\s]+)\s*р\.", page_text)
        if available_match:
            balance = available_match.group(1).strip()
        else:
            available_match_alt = re.search(r"Доступно:\s*([^\n]+)", page_text)
            if available_match_alt:
                balance = available_match_alt.group(1).replace("р.", "").strip()

        tasks_prices = []
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) >= 3:
                    price_cell = cells[2]
                    price = price_cell.get_text(strip=True)

                    if price and "---" not in price:
                        price = price.replace("руб.", "").replace("руб", "").strip()

                        actions_cell = cells[-1]
                        actions_text = actions_cell.get_text(strip=True)
                        has_link = actions_cell.find("a") or ("---" not in actions_text and actions_text != "")

                        if has_link:
                            tasks_prices.append(price)

        return {"balance": balance, "tasks": tasks_prices}, "SUCCESS"

    except Exception as e:
        return None, f"⚠️ حدث خطأ أثناء الاتصال بالموقع: {str(e)}"

# ==========================================
# تصميم قوائم الأزرار (Keyboards)
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
# استقبال الأوامر والرسائل التفاعلية
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if chat_id in user_data_store:
        bot.send_message(chat_id, "👋 أنت مسجل الدخول بالفعل وبشكل نشط بالخلفية!", reply_markup=get_logged_in_menu())
    else:
        bot.send_message(chat_id, "📌 أهلاً بك في بوت صائد المهام التفاعلي.\nإليك الخيارات المتاحة بالأسفل:", reply_markup=get_main_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    chat_id = message.chat.id
    text = message.text

    if text == "1️⃣ تسجيل دخول" or text == "1":
        bot.send_message(chat_id, "📬 قم بكتابة اسم المستخدم أو الـ Gmail الخاص بك للموقع:")
        user_sessions[chat_id] = {'step': 'WAITING_EMAIL'}

    elif text == "3️⃣ تسجيل خروج" or text == "3":
        if chat_id in user_data_store:
            del user_data_store[chat_id]
        if chat_id in user_sessions:
            del user_sessions[chat_id]
        bot.send_message(chat_id, "🔒 تم تسجيل الخروج بنجاح وحذف بيانات جلستك المؤقتة.", reply_markup=get_main_menu())

    elif text == "4️⃣ تحديث البيانات" or text == "4":
        if chat_id not in user_data_store:
            bot.send_message(chat_id, "⚠️ عذراً، لم تقم بتسجيل الدخول بعد!", reply_markup=get_main_menu())
            return

        bot.send_message(chat_id, "🔄 جاري فحص الموقع وتحديث البيانات الآن...")
        creds = user_data_store[chat_id]
        data, status = fetch_site_data(creds['email'], creds['password'])

        if status == "SUCCESS":
            total_tasks = len(data['tasks'])
            bot.send_message(chat_id, f"💰 رصيد الروبل الحالي المتاح لديك: `{data['balance']}` روبل", parse_mode="Markdown")

            if total_tasks == 0:
                bot.send_message(chat_id, "📋 لا توجد أي مهمة متاحة حالياً.", reply_markup=get_logged_in_menu())
            else:
                bot.send_message(chat_id, f"📊 تم العثور على {total_tasks} من المهام المتاحة:")
                for price in data['tasks']:
                    bot.send_message(chat_id, f"🔹 توجد مهمة متاحة بسعر: {price} روبل", reply_markup=get_logged_in_menu())
        else:
            bot.send_message(chat_id, status, reply_markup=get_logged_in_menu())

    elif chat_id in user_sessions:
        current_step = user_sessions[chat_id]['step']

        if current_step == 'WAITING_EMAIL':
            user_sessions[chat_id]['email'] = text
            user_sessions[chat_id]['step'] = 'WAITING_PASSWORD'
            bot.send_message(chat_id, "🔐 ممتاز، الآن أرسل كلمة المرور (Password) الخاصة بحسابك:")

        elif current_step == 'WAITING_PASSWORD':
            email = user_sessions[chat_id]['email']
            password = text
            bot.send_message(chat_id, "⏳ جاري فحص الحساب ومحاولة تسجيل الدخول للموقع...")

            data, status = fetch_site_data(email, password)

            if status == "SUCCESS":
                user_data_store[chat_id] = {'email': email, 'password': password}
                del user_sessions[chat_id]

                total_tasks = len(data['tasks'])
                bot.send_message(chat_id, f"✅ تم تسجيل الدخول بنجاح!\n💰 رصيد الروبل المتاح لديك: `{data['balance']}` روبل", parse_mode="Markdown")

                if total_tasks == 0:
                    bot.send_message(chat_id, "📋 لا توجد أي مهمة متاحة حالياً.", reply_markup=get_logged_in_menu())
                else:
                    bot.send_message(chat_id, f"📊 تم العثور على {total_tasks} من المهام المتاحة:")
                    for price in data['tasks']:
                        bot.send_message(chat_id, f"🔹 توجد مهمة متاحة بسعر: {price} روبل", reply_markup=get_logged_in_menu())
            else:
                del user_sessions[chat_id]
                bot.send_message(chat_id, f"{status}\n\nجرّب الضغط على زر تسجيل الدخول مجدداً.", reply_markup=get_main_menu())
    else:
        bot.send_message(chat_id, "يرجى استخدام قائمة الأزرار الظاهرة في الأسفل للتحكم بالبوت.", reply_markup=get_main_menu())

# ==========================================
# سيرفر ويب مطور لاستقبال اتصالات Render و UptimeRobot
# ==========================================
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("البوت التفاعلي المطور أونلاين 24 ساعة!".encode("utf-8"))

    # إضافة دالة do_HEAD لحل مشكلة طلبات الفحص والتنبيهات
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

def run_web_server():
    # قراءة المنفذ من بيئة Render تلقائياً، وإذا لم يجده يستعمل 10000 كاحتياطي
    port = int(os.environ.get("PORT", 10000))
    server_address = ('', port) 
    httpd = HTTPServer(server_address, WebServerHandler)
    print(f"🌍 سيرفر الويب يعمل الآن على المنفذ: {port}")
    httpd.serve_forever()

# ==========================================
# نقطة انطلاق البوت
# ==========================================
if __name__ == "__main__":
    print("🚀 جاري بدء تشغيل البوت التفاعلي بالكامل...")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    bot.infinity_polling()

هل انت متأكد انه سيعمل وانه لديه علاقة مع رابط سابق