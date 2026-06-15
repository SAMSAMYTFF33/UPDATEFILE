"""
core.py - يُرفع على GitHub
لا يحتوي على أي توكن
"""
import requests, json, re, time, threading, logging
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# BOT_TOKEN و bot يأتيان من main.py تلقائياً
log = logging.getLogger(__name__)

# ============================================================
BASE_URL   = "https://aviso.bz"
TASKS_URL  = "https://aviso.bz/tasks"
AJAX_URL   = "https://aviso.bz/ajax/load_pages.php"
TASK_URL   = "https://aviso.bz/task-read"
GOTASK_URL = "https://aviso.bz/go/gotask.php"

FOLLOW_TYPES = {"telegram", "youtube", "vk", "социальные", "подписк"}
MIN_PRICE = 2.0
MAX_PRICE = 8.0
AUTO_REFRESH_INTERVAL = 38 * 60
TASK_LOOP_INTERVAL    = 3 * 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": TASKS_URL,
}

# ============================================================
# بيانات المستخدمين
# ============================================================
user_data: dict = {}
user_data_lock  = threading.Lock()

def get_user(chat_id: int) -> dict:
    with user_data_lock:
        if chat_id not in user_data:
            user_data[chat_id] = {
                "state": "idle",
                "session": None,
                "cookies_source": None,
                "user_id": None,
                "username": None,
                "running": False,
                "last_refresh": 0.0,
                "lock": threading.Lock(),
            }
        return user_data[chat_id]

# ============================================================
# كوكيز وجلسة
# ============================================================

def cookies_from_json(text):
    try:
        data = json.loads(text)
        if isinstance(data, list) and data and "name" in data[0]:
            return data
    except:
        pass
    return None

def cookies_from_url(url):
    try:
        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com","raw.githubusercontent.com").replace("/blob/","/")
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return cookies_from_json(r.text)
    except:
        return None

def load_cookies(source):
    if source.startswith("http"):
        return cookies_from_url(source)
    return cookies_from_json(source)

def build_session(cookies):
    import requests as req
    s = req.Session()
    for c in cookies:
        s.cookies.set(c["name"], c["value"],
                      domain=c.get("domain","aviso.bz").lstrip("."),
                      path=c.get("path","/"))
    return s

def validate_session(session):
    try:
        r = session.get(BASE_URL, headers=HEADERS, timeout=15)
        m = re.search(r"var\s+id_user\s*=\s*['\"](\d+)['\"]", r.text)
        if m:
            uid = m.group(1)
            un  = re.search(r'id="user-block-info-username"[^>]*>([^<]+)<', r.text)
            return True, uid, (un.group(1).strip() if un else uid)
        if "/logout" in r.text:
            return True, "unknown", "unknown"
        return False, None, None
    except:
        return False, None, None

# ============================================================
# جلب المهام
# ============================================================

def extract_tasks(html, page=1):
    tasks = []
    for m in re.finditer(
        r'<tr[^>]+id="(?:earn-task\s+)?block-task(\d+)"[^>]*>(.*?)</tr>',
        html, re.DOTALL | re.IGNORECASE
    ):
        tid, block = m.group(1), m.group(2)
        task = {"id": tid, "page": page, "title": None, "price": None, "task_type": None}
        t = re.search(r'href="/task-read\?adv=' + tid + r'"[^>]*><span>([^<]+)</span>', block)
        if t: task["title"] = t.group(1).strip()
        p = re.search(r'color:#9d0000[^>]*>(\d+)&nbsp;руб\.(?:&nbsp;(\d+)&nbsp;коп)?', block)
        if p:
            task["price"] = int(p.group(1)) + (int(p.group(2)) if p.group(2) else 0) / 100
        tp = re.search(r'<span class="serfinfotext">№\s*\d+\s*-\s*([^<]+)', block)
        if tp: task["task_type"] = tp.group(1).strip()
        tasks.append(task)
    return tasks

def fetch_all_tasks(session, max_tasks=100):
    try:
        r = session.get(TASKS_URL, headers=HEADERS, timeout=15)
        if r.status_code != 200: return []
        html1 = r.text
    except:
        return []

    csrf = re.search(r'name="csrf-token"\s+content="([^"]+)"', html1)
    csrf_token = csrf.group(1) if csrf else None
    all_tasks  = extract_tasks(html1, 1)

    page, empty = 2, 0
    while len(all_tasks) < max_tasks and empty < 2:
        try:
            payload = {"func":"tasks","numPages":"30","numClosed":"9999","page":str(page)}
            h = {**HEADERS,
                 "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
                 "X-Requested-With":"XMLHttpRequest"}
            if csrf_token: h["X-CSRF-Token"] = csrf_token
            resp = session.post(AJAX_URL, data=payload, headers=h, timeout=15)
            tasks = extract_tasks(resp.text, page) if resp.status_code == 200 else []
            if tasks: all_tasks.extend(tasks); empty = 0
            else: empty += 1
        except:
            empty += 1
        page += 1
        time.sleep(0.4)
    return all_tasks

def filter_tasks(tasks):
    return [t for t in tasks
            if t.get("price") and MIN_PRICE <= t["price"] <= MAX_PRICE
            and any(f in (t.get("task_type") or "").lower() for f in FOLLOW_TYPES)]

# ============================================================
# تنفيذ المهمة
# ============================================================

def get_task_hash(session, tid):
    try:
        r = session.get(f"{TASK_URL}?adv={tid}", headers=HEADERS, timeout=15)
        m = re.search(r'<input[^>]+name="hash"[^>]+value="([a-f0-9]{32})"', r.text)
        if m: return m.group(1)
        m = re.search(r"var\s+HashTask\s*=\s*['\"]([a-f0-9]{32})['\"]", r.text)
        if m: return m.group(1)
    except:
        pass
    return None

def start_task(session, tid, h):
    try:
        r = session.post(GOTASK_URL,
                        data={"adv": tid, "hash": h},
                        headers={**HEADERS,"Content-Type":"application/x-www-form-urlencoded"},
                        allow_redirects=True, timeout=15)
        return r.status_code in (200, 302) and "error" not in r.url.lower()
    except:
        return False

# ============================================================
# لوحة المفاتيح
# ============================================================

def main_keyboard(chat_id):
    u  = get_user(chat_id)
    kb = InlineKeyboardMarkup(row_width=2)
    if u.get("running"):
        kb.add(InlineKeyboardButton("⏹ إيقاف 🔴", callback_data="stop"))
    else:
        kb.add(InlineKeyboardButton("▶️ تشغيل 🟢", callback_data="start"))
    kb.add(
        InlineKeyboardButton("📊 الحالة",       callback_data="status"),
        InlineKeyboardButton("🔄 تجديد الجلسة", callback_data="refresh"),
    )
    kb.add(InlineKeyboardButton("📋 جلب المهام الآن",  callback_data="fetch_tasks"))
    kb.add(
        InlineKeyboardButton("🔑 تغيير الكوكيز", callback_data="change_cookies"),
        InlineKeyboardButton("❌ تسجيل الخروج",  callback_data="logout"),
    )
    return kb

# ============================================================
# Daemons
# ============================================================

def _refresh_loop(chat_id):
    while True:
        time.sleep(AUTO_REFRESH_INTERVAL)
        u = get_user(chat_id)
        if u["state"] != "logged_in": break
        with u["lock"]:
            src = u.get("cookies_source")
        cookies = load_cookies(src) if src else None
        if not cookies:
            bot.send_message(chat_id, "❌ فشل تجديد الجلسة!")
            u["state"] = "awaiting_cookies"
            break
        s = build_session(cookies)
        ok, uid, un = validate_session(s)
        if ok:
            with u["lock"]:
                u["session"] = s
                u["last_refresh"] = time.time()
            bot.send_message(chat_id, "🔄 تم تجديد الجلسة!")
        else:
            bot.send_message(chat_id, "❌ الجلسة انتهت! أرسل الكوكيز مجدداً.")
            u["state"] = "awaiting_cookies"
            break

def _task_loop(chat_id):
    while True:
        time.sleep(TASK_LOOP_INTERVAL)
        u = get_user(chat_id)
        if not u.get("running") or u["state"] != "logged_in": break
        session = u.get("session")
        if not session: break

        all_tasks = fetch_all_tasks(session)
        follow    = filter_tasks(all_tasks)
        if not follow:
            bot.send_message(chat_id,
                f"⚠️ لا مهام متابعة ({MIN_PRICE}-{MAX_PRICE} руб)\n"
                f"فحصت {len(all_tasks)} مهمة")
            continue

        t = follow[0]
        tid   = t["id"]
        h     = get_task_hash(session, tid)
        if not h:
            bot.send_message(chat_id, f"❌ لا hash للمهمة #{tid}")
            continue
        if start_task(session, tid, h):
            bot.send_message(chat_id,
                f"✅ تم تنفيذ المهمة!\n"
                f"🆔 {tid} | 💰 {t.get('price',0):.2f} руб\n"
                f"📌 {(t.get('title') or '')[:40]}")
        else:
            bot.send_message(chat_id, f"❌ فشل تنفيذ #{tid}")

# ============================================================
# Handlers
# ============================================================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    u = get_user(message.chat.id)
    if u["state"] == "logged_in":
        bot.send_message(message.chat.id,
            f"👋 مرحباً {u.get('username')}!\nأنت مسجل الدخول.",
            reply_markup=main_keyboard(message.chat.id))
        return
    u["state"] = "awaiting_cookies"
    bot.send_message(message.chat.id,
        "🤖 *Aviso Bot*\n\nأرسل:\n"
        "• رابط GitHub لملف cookies.json\n"
        "• أو نص JSON مباشرة",
        parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_msg(message):
    chat_id = message.chat.id
    u    = get_user(chat_id)
    text = (message.text or "").strip()

    if u["state"] == "idle":
        bot.send_message(chat_id, "أرسل /start للبدء.")
        return
    if u["state"] == "logged_in":
        bot.send_message(chat_id, "استخدم الأزرار للتحكم.",
                         reply_markup=main_keyboard(chat_id))
        return

    # awaiting_cookies
    if not (text.startswith("http") or text.startswith("[") or text.startswith("{")):
        bot.send_message(chat_id, "⚠️ أرسل رابط GitHub أو نص JSON للكوكيز.")
        return

    msg = bot.send_message(chat_id, "⏳ جاري التحقق...")
    cookies = load_cookies(text)
    if not cookies:
        bot.edit_message_text("❌ فشل تحليل الكوكيز!", chat_id, msg.message_id)
        return
    s = build_session(cookies)
    bot.edit_message_text("⏳ التحقق من الجلسة...", chat_id, msg.message_id)
    ok, uid, un = validate_session(s)
    if not ok:
        bot.edit_message_text("❌ الكوكيز منتهية أو خاطئة!", chat_id, msg.message_id)
        return

    with u["lock"]:
        u.update({"state":"logged_in","session":s,"cookies_source":text,
                  "user_id":uid,"username":un,"last_refresh":time.time(),"running":False})

    threading.Thread(target=_refresh_loop, args=(chat_id,), daemon=True).start()
    bot.edit_message_text(
        f"✅ تم تسجيل الدخول!\n👤 {un} | 🆔 {uid}",
        chat_id, msg.message_id, reply_markup=main_keyboard(chat_id))

@bot.callback_query_handler(func=lambda c: True)
def handle_cb(call):
    chat_id = call.message.chat.id
    u = get_user(chat_id)
    if u["state"] != "logged_in":
        bot.answer_callback_query(call.id, "⚠️ سجّل الدخول أولاً!")
        return

    d = call.data
    if d == "start":
        u["running"] = True
        threading.Thread(target=_task_loop, args=(chat_id,), daemon=True).start()
        bot.answer_callback_query(call.id, "✅ تشغيل")
        bot.edit_message_text("🟢 البوت يعمل!\nيجلب مهمة كل 3 دقائق.",
                              chat_id, call.message.message_id,
                              reply_markup=main_keyboard(chat_id))
    elif d == "stop":
        u["running"] = False
        bot.answer_callback_query(call.id, "⏹ إيقاف")
        bot.edit_message_text("🔴 متوقف.", chat_id, call.message.message_id,
                              reply_markup=main_keyboard(chat_id))
    elif d == "status":
        last = datetime.fromtimestamp(u["last_refresh"]).strftime("%H:%M:%S") if u["last_refresh"] else "—"
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            f"📊 الحالة\n👤 {u.get('username')} | 🆔 {u.get('user_id')}\n"
            f"🔄 آخر تجديد: {last}\n"
            f"🎛️ {'🟢 يعمل' if u.get('running') else '🔴 متوقف'}",
            chat_id, call.message.message_id, reply_markup=main_keyboard(chat_id))
    elif d == "refresh":
        bot.answer_callback_query(call.id, "⏳")
        src = u.get("cookies_source")
        cookies = load_cookies(src) if src else None
        if not cookies:
            bot.send_message(chat_id, "❌ فشل! أرسل الكوكيز من جديد.")
            u["state"] = "awaiting_cookies"
            return
        s = build_session(cookies)
        ok, uid, un = validate_session(s)
        if ok:
            with u["lock"]:
                u["session"] = s
                u["last_refresh"] = time.time()
            bot.send_message(chat_id, "✅ تم تجديد الجلسة!")
        else:
            bot.send_message(chat_id, "❌ انتهت الجلسة!")
            u["state"] = "awaiting_cookies"
    elif d == "fetch_tasks":
        bot.answer_callback_query(call.id, "⏳")
        all_t  = fetch_all_tasks(u["session"])
        follow = filter_tasks(all_t)
        lines  = [f"📋 المهام: {len(all_t)} | متابعة: {len(follow)}\n"]
        for i, t in enumerate(follow[:8], 1):
            lines.append(f"{i}. #{t['id']} {(t.get('title') or '')[:30]} | {t.get('price',0):.2f}р")
        bot.send_message(chat_id, "\n".join(lines) or "⚠️ لا مهام")
    elif d == "change_cookies":
        u["state"] = "awaiting_cookies"
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "📁 أرسل الكوكيز الجديدة:")
    elif d == "logout":
        u.update({"running":False,"state":"idle","session":None,
                  "cookies_source":None,"user_id":None,"username":None})
        bot.answer_callback_query(call.id, "👋")
        bot.edit_message_text("👋 تم الخروج. /start للبدء.",
                              chat_id, call.message.message_id)