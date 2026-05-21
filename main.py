 
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
            return None, "❌ خطأ في الاتصال بالسيرفر الرئيسي أثناء تسجيل الدخول."

        r = session.get(TARGET_URL, headers=HEADERS, timeout=12)
        if "Выход" not in r.text:
            return None, "❌ فشل التحقق من الهوية. يرجى التأكد من صحة اسم المستخدم وكلمة المرور."

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

                    # تخطي صف العداد والإحصائيات الكلية للموقع لتجنب الأخطاء في العد
                    if "Всего" in price or "найдено" in price or "Найдено" in price:
                        continue 

                    if price and "---" not in price:
                        price = price.replace("руб.", "").replace("руб", "").strip()

                        actions_cell = cells[-1]
                        actions_text = actions_cell.get_text(strip=True)
                        has_link = actions_cell.find("a") or ("---" not in actions_text and actions_text != "")

                        if has_link:
                            tasks_prices.append(price)

        return {"balance": balance, "tasks": tasks_prices}, "SUCCESS"

    except Exception as e:
        return None, f"⚠️ حدث خطأ غير متوقع أثناء الاتصال بالخادم: {str(e)}"

# ==========================================
# تصميم قوائم الأزرار (Keyboards) بأسلوب رسمي
# ==========================================
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add(types.KeyboardButton("🔐 تسجيل الدخول إلى النظام"))
    return markup

def get_logged_in_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_refresh = types.KeyboardButton("🔄 تحديث البيانات الحالية")
    btn_logout = types.KeyboardButton("🚪 إنهاء الجلسة (تسجيل الخروج)")
    markup.add(btn_refresh, btn_logout)
    return markup

# ==========================================
# استقبال الأوامر والرسائل التفاعلية
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if chat_id in user_data_store:
        bot.send_message(chat_id, "ℹ️ النظام نشط بالفعل، وجلستكم الحالية لا تزال قائمة.", reply_markup=get_logged_in_menu())
    else:
        welcome_text = (
            "مرحباً بك في النظام المؤتمت لإدارة ومراقبة المهام.\n\n"
            "يرجى استخدام قائمة الخيارات المتاحة أدناه لبدء الاستخدام:"
        )
        bot.send_message(chat_id, welcome_text, reply_markup=get_main_menu())

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    chat_id = message.chat.id
    text = message.text

    if text == "🔐 تسجيل الدخول إلى النظام":
        bot.send_message(chat_id, "يرجى إدخال اسم المستخدم أو البريد الإلكتروني المسجل:")
        user_sessions[chat_id] = {'step': 'WAITING_EMAIL'}

    elif text == "🚪 إنهاء الجلسة (تسجيل الخروج)":
        if chat_id in user_data_store:
            del user_data_store[chat_id]
        if chat_id in user_sessions:
            del user_sessions[chat_id]
        bot.send_message(chat_id, "🔒 تم إنهاء الجلسة بنجاح، وحذف بيانات الاعتماد المؤقتة بأمان.", reply_markup=get_main_menu())

    elif text == "🔄 تحديث البيانات الحالية":
        if chat_id not in user_data_store:
            bot.send_message(chat_id, "⚠️ تنبيه: لم يتم العثور على جلسة نشطة. يرجى تسجيل الدخول أولاً.", reply_markup=get_main_menu())
            return

        bot.send_message(chat_id, "🔄 جاري فحص الخادم وتحديث البيانات، يرجى الانتظار...")
        creds = user_data_store[chat_id]
        data, status = fetch_site_data(creds['email'], creds['password'])

        if status == "SUCCESS":
            total_tasks = len(data['tasks'])
            bot.send_message(chat_id, f"💰 الرصيد الحالي المتاح: `{data['balance']}` روبل", parse_mode="Markdown")

            if total_tasks == 0:
                bot.send_message(chat_id, "📋 لا توجد أي مهام متاحة في الوقت الحالي.", reply_markup=get_logged_in_menu())
            else:
                bot.send_message(chat_id, f"📊 تم رصد {total_tasks} من المهام النشطة:")
                for price in data['tasks']:
                    # تم التأكيد هنا على إرسال النص فقط دون أي روابط أو معرفات للمهمة
                    bot.send_message(chat_id, f"🔹 مهمة متاحة بقيمة: {price} روبل", reply_markup=get_logged_in_menu())
        else:
            bot.send_message(chat_id, status, reply_markup=get_logged_in_menu())

    elif chat_id in user_sessions:
        current_step = user_sessions[chat_id]['step']

        if current_step == 'WAITING_EMAIL':
            user_sessions[chat_id]['email'] = text
            user_sessions[chat_id]['step'] = 'WAITING_PASSWORD'
            bot.send_message(chat_id, "🔐 تم الحفظ. يرجى إدخال كلمة المرور الخاصة بحسابكم:")

        elif current_step == 'WAITING_PASSWORD':
            email = user_sessions[chat_id]['email']
            password = text
            bot.send_message(chat_id, "⏳ جاري التحقق من الهوية ومزامنة البيانات مع السيرفر الرئيسي...")

            data, status = fetch_site_data(email, password)

            if status == "SUCCESS":
                user_data_store[chat_id] = {'email': email, 'password': password}
                del user_sessions[chat_id]

                total_tasks = len(data['tasks'])
                bot.send_message(chat_id, f"✅ تم مصادقة الحساب بنجاح!\n💰 الرصيد الحالي المتاح: `{data['balance']}` روبل", parse_mode="Markdown")

                if total_tasks == 0:
                    bot.send_message(chat_id, "📋 لا توجد أي مهام متاحة في الوقت الحالي.", reply_markup=get_logged_in_menu())
                else:
                    bot.send_message(chat_id, f"📊 تم رصد {total_tasks} من المهام النشطة:")
                    for price in data['tasks']:
                        # يرسل السعر فقط التزاماً بطلبك بعدم عرض الروابط
                        bot.send_message(chat_id, f"🔹 مهمة متاحة بقيمة: {price} روبل", reply_markup=get_logged_in_menu())
            else:
                del user_sessions[chat_id]
                bot.send_message(chat_id, f"{status}\n\nيرجى المحاولة مجدداً عن طريق الضغط على زر تسجيل الدخول.", reply_markup=get_main_menu())
    else:
        bot.send_message(chat_id, "⚠️ أمر غير معروف. يرجى استخدام لوحة التحكم المظهرة أسفل الشاشة.", reply_markup=get_main_menu())

# ==========================================
# سيرفر ويب لاستقبال اتصالات التوفر (Uptime)
# ==========================================
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("النظام البرمجي المؤتمت يعمل بكفاءة عالية (متصل)".encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server_address = ('', port) 
    httpd = HTTPServer(server_address, WebServerHandler)
    print(f"🌍 سيرفر الويب يعمل الآن على المنفذ: {port}")
    httpd.serve_forever()

# ==========================================
# نقطة انطلاق البوت
# ==========================================
if __name__ == "__main__":
    print("🚀 جاري بدء تشغيل النظام المؤتمت بالكامل...")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    bot.infinity_polling()