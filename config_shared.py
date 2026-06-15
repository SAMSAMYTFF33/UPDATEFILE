import time
import requests
import random
from bs4 import BeautifulSoup
import threading
import re
import os
import telebot
from telebot import types
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import concurrent.futures
import uuid
# ملاحظة: لا حاجة لـ python-dotenv هنا — القيم تأتي من os.environ
# التي يضبطها main.py مباشرة قبل استدعاء هذا الملف.

# ==========================================
# إعداد Gemini AI لاستخراج عنوان البحث
# (يعمل بـ requests فقط — بدون أي مكتبة إضافية)
# ==========================================
# ==========================================
# ⏳ العد التنازلي (24 ساعة من لحظة تشغيل البوت)
# يظهر فقط في رسالة القائمة الرئيسية — لا يرسل أي إشعار
# ==========================================
BOT_START_TIME = time.time()  # يُسجَّل فور تشغيل البوت مرة واحدة

def get_countdown_text() -> str:
    """
    يحسب الوقت المتبقي من 24 ساعة منذ تشغيل البوت.
    يُرجع نصاً بالشكل [24h] أو [1h 30mini] أو [45mini] وما شابه.
    لا يسبب أي توقف أو استثناء.
    """
    try:
        elapsed = time.time() - BOT_START_TIME
        total_seconds = 24 * 3600  # 24 ساعة بالثواني
        remaining = total_seconds - elapsed

        if remaining <= 0:
            return "[0mini]"

        remaining_int = int(remaining)
        hours   = remaining_int // 3600
        minutes = (remaining_int % 3600) // 60

        if hours >= 1:
            if minutes > 0:
                return f"[{hours}h {minutes}mini]"
            else:
                return f"[{hours}h]"
        else:
            return f"[{minutes}mini]"
    except Exception:
        return "[--]"

# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

def analyze_task_with_ai(task_description: str) -> dict:
    """
    يرسل وصف المهمة إلى Gemini في طلب واحد فقط ويستخرج:
    - عنوان البحث في يوتيوب (إن وُجد)
    - اسم القناة (إن وُجد)
    - شرح المهمة بالعربية في فقرة صغيرة
    يُرجع dict: { 'search_title': str, 'channel_name': str, 'explanation': str, 'error': str }
    """
    prompt = (
        "أنت مساعد متخصص في تحليل مهام العمل الرقمي.\n"
        "المطلوب: اقرأ وصف المهمة التالي ثم أجب بهذا الشكل الثابت فقط (لا تغيّر أسماء الحقول أبداً):\n\n"
        "عنوان الفيديو: [إذا وُجد عنوان فيديو محدد في المهمة اكتبه كما هو بلغته الأصلية دون ترجمة، وإذا لم يوجد عنوان محدد فاستخرج عبارة البحث من نص المهمة كما هي بلغتها الأصلية دون ترجمة]\n"
        "اسم القناة: [اسم القناة كما هو بلغته الأصلية دون أي ترجمة، وإلا اكتب: لا يوجد]\n"
        "الشرح: [اشرح ما يجب على المستخدم فعله بالعربية في 3-5 جمل واضحة ومباشرة، بدون نقاط أو عناوين]\n\n"
        "قواعد صارمة:\n"
        "- لا تُضف أي نص خارج الحقول الثلاثة أعلاه\n"
        "- عنوان الفيديو واسم القناة يجب أن يكونا بنفس لغتهما الأصلية (روسية، إنجليزية، إلخ) — لا تترجمهما أبداً\n"
        "- عنوان الفيديو أو عبارة البحث يجب أن تُستخرج من نص المهمة مباشرة، لا تخترعها\n"
        "- الشرح فقرة نثرية واحدة بالعربية فقط\n"
        "- لا تتجاوز 5 جمل في الشرح\n\n"
        f"وصف المهمة:\n{task_description}"
    )
    result = {'search_title': '', 'channel_name': '', 'explanation': '', 'error': ''}
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        r = requests.post(url, json=payload, timeout=25)
        if r.status_code != 200:
            result['error'] = f"⚠️ خطأ من Gemini: {r.status_code}"
            return result

        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        # ── تحليل الرد سطراً سطراً ──
        lines = raw.splitlines()
        explanation_lines = []
        in_explanation = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("عنوان الفيديو:"):
                val = stripped.replace("عنوان الفيديو:", "").strip()
                if val and val != "لا يوجد":
                    result['search_title'] = val
                in_explanation = False
            elif stripped.startswith("اسم القناة:"):
                val = stripped.replace("اسم القناة:", "").strip()
                if val and val != "لا يوجد":
                    result['channel_name'] = val
                in_explanation = False
            elif stripped.startswith("الشرح:"):
                val = stripped.replace("الشرح:", "").strip()
                if val:
                    explanation_lines.append(val)
                in_explanation = True
            elif in_explanation and stripped:
                # سطور إضافية تابعة لحقل الشرح
                explanation_lines.append(stripped)

        result['explanation'] = " ".join(explanation_lines).strip()

    except Exception as e:
        result['error'] = f"❌ خطأ في AI: {str(e)[:150]}"

    return result


# ==========================================
# الإعدادات الأساسية
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ==========================================
# ⏰ إعدادات التوقيت العشوائي لإشعارات الكلية
# (مثل نظام 6.py — نهار وليل)
# ==========================================
ALL_NOTIFY_DAY_MIN_MINUTES   = 3
ALL_NOTIFY_DAY_MAX_MINUTES   = 10
ALL_NOTIFY_NIGHT_MIN_MINUTES = 20
ALL_NOTIFY_NIGHT_MAX_MINUTES = 35

MOROCCO_UTC_OFFSET = 1   # المغرب UTC+1
NIGHT_START_HOUR   = 22
NIGHT_END_HOUR     = 6

def _morocco_hour() -> int:
    from datetime import timedelta
    utc_now = datetime.now(timezone.utc)
    morocco_now = utc_now + timedelta(hours=MOROCCO_UTC_OFFSET)
    return morocco_now.hour

def _is_night_now() -> bool:
    h = _morocco_hour()
    return h >= NIGHT_START_HOUR or h < NIGHT_END_HOUR

def _all_notify_next_interval_seconds() -> int:
    """حساب الفترة العشوائية التالية لإشعارات الكلية حسب وقت اليوم"""
    if _is_night_now():
        minutes = random.randint(ALL_NOTIFY_NIGHT_MIN_MINUTES, ALL_NOTIFY_NIGHT_MAX_MINUTES)
    else:
        minutes = random.randint(ALL_NOTIFY_DAY_MIN_MINUTES, ALL_NOTIFY_DAY_MAX_MINUTES)
    extra_seconds = random.randint(0, 59)
    return minutes * 60 + extra_seconds

# مخزن آخر وقت إرسال لإشعارات الكلية لكل (chat_id, email)
# منفصل عن _bg_last_notify لأن التوقيت مختلف
# القيمة: {'last_sent': timestamp, 'next_interval': seconds}
# يضمن أن الفترة العشوائية تُحسب مرة واحدة وتُحفظ لا أن تُعاد كل 5 ثواني
_bg_last_all_notify = {}

# علامة إلغاء عالمية لإشعارات الكلية — إذا أُوقف المستخدم الإشعارات
# يرفع هذا الحدث لكل خيط إرسال نشط يخص هذا الحساب
# المفتاح: email_lower — القيمة: threading.Event()
_all_notify_cancel_events = {}
_all_notify_cancel_lock = threading.Lock()

def _get_cancel_event(email_lower):
    """جلب أو إنشاء حدث الإلغاء لحساب معين"""
    with _all_notify_cancel_lock:
        if email_lower not in _all_notify_cancel_events:
            _all_notify_cancel_events[email_lower] = threading.Event()
        return _all_notify_cancel_events[email_lower]

def _cancel_all_notify_for_email(email_lower):
    """إلغاء فوري لأي خيط إرسال جارٍ لهذا الحساب"""
    with _all_notify_cancel_lock:
        ev = _all_notify_cancel_events.get(email_lower)
        if ev:
            ev.set()
        # إنشاء حدث جديد للدورة القادمة (إعادة تهيئة)
        _all_notify_cancel_events[email_lower] = threading.Event()

def _reset_cancel_event(email_lower):
    """إعادة تهيئة حدث الإلغاء (بعد توقف خيط إرسال سابق)"""
    with _all_notify_cancel_lock:
        _all_notify_cancel_events[email_lower] = threading.Event()

# ==========================================
# 🔔 إعدادات التنبيهات الخاصة
# ==========================================
# chat_id الخاص الذي يستقبل تنبيهات CAPTCHA
# غيّره إلى chat_id المطلوب
CAPTCHA_ALERT_CHAT_ID = int(os.getenv("CAPTCHA_ALERT_CHAT_ID", "0"))  # ← من ملف .env

BASE_URL = "https://forumok.com"
LOGIN_URL = "https://forumok.com/login"
TARGET_URL = "https://forumok.com/orders-search/socio"
STATS_URL = "https://forumok.com/publisher-requests/socio/confirmed"
CONFIRMED_URL = "https://forumok.com/publisher-requests/socio/confirmed"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": BASE_URL
}

# ══ مساعد: retry تلقائي لجميع طلبات الشبكة ══
def _safe_get(url, session=None, retries=3, **kwargs):
    req = session or requests
    kwargs.setdefault("timeout", 15)
    for i in range(retries):
        try:
            return req.get(url, **kwargs)
        except requests.exceptions.RequestException:
            if i == retries - 1: raise
            time.sleep(2 * (i + 1))

def _safe_post(url, session=None, retries=3, **kwargs):
    req = session or requests
    kwargs.setdefault("timeout", 15)
    for i in range(retries):
        try:
            return req.post(url, **kwargs)
        except requests.exceptions.RequestException:
            if i == retries - 1: raise
            time.sleep(2 * (i + 1))

# ==========================================
# إعدادات البروكسيات الثابتة للحسابين المستثنيين
# ==========================================
EXEMPT_ACCOUNTS = ["france260026@gmail.com", "rossxpro26@gmail.com"]

ACCOUNT_PROXIES = {
    "france260026@gmail.com": [
        "38.154.203.95:5863", "198.105.121.200:6462", "64.137.96.74:6641",
        "209.127.138.10:5784", "38.154.185.97:6370"
    ],
    "rossxpro26@gmail.com": [
        "84.247.60.125:6095", "142.111.67.146:5611", "191.96.254.138:6185",
        "31.58.9.4:6077", "64.137.10.153:5803"
    ]
}
PROXY_USER = os.getenv("PROXY_USER")
PROXY_PASS = os.getenv("PROXY_PASS")

# ==========================================
# 🔐 روابط ومفاتيح مشروع Supabase
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

DB_API_URL = f"{SUPABASE_URL}/rest/v1/users_accounts"
DB_AUTO_TASKS_URL = f"{SUPABASE_URL}/rest/v1/auto_tasks"
DB_SETTINGS_URL = f"{SUPABASE_URL}/rest/v1/user_settings"
DB_PROXY_URL = f"{SUPABASE_URL}/rest/v1/proxy_manager"
DB_MULTI_ACCOUNTS_URL = f"{SUPABASE_URL}/rest/v1/multi_accounts"  # جدول الحسابات المتعددة السحابي

DB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

# ==========================================
# 🌐 نظام إدارة البروكسيات الذكي المتقدم
# ==========================================
PROXY_SOURCE_URL = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
PROXIES_PER_ACCOUNT = 20
PROXY_REFRESH_INTERVAL = 30 * 60  # 30 دقيقة

# ── مخزن البروكسيات المخصصة لكل حساب ──
# { email: { "proxies": [...], "current_index": 0, "last_updated": ts } }
dynamic_proxy_store = {}
proxy_store_lock = threading.Lock()
last_proxy_refresh_time = 0

# ── المخزن الاحتياطي الذكي ──
# يحتفظ دائماً بـ (عدد_حسابات_النشطة + 1) × 20 بروكسي جاهزة للتخصيص الفوري
# { "proxies": [...مرتبة حسب latency...], "last_filled": timestamp }
proxy_reserve_pool = {"proxies": [], "last_filled": 0}
reserve_pool_lock = threading.Lock()
_reserve_fill_running = False  # يمنع تشغيل أكثر من عملية تعبئة واحدة في نفس الوقت

# ══ Semaphore: يمنع تشغيل refresh + reserve بالتوازي ══
# قيمة 1 = عملية واحدة فقط تجلب وتختبر البروكسيات في نفس الوقت
_proxy_fetch_semaphore = threading.Semaphore(1)

# ══ Queue مركزي لحفظ البيانات في DB بدل خيط لكل حفظ ══
import queue as _queue_module
_db_save_queue = _queue_module.Queue()

def _db_save_worker():
    """خيط واحد دائم يعالج كل طلبات الحفظ في DB"""
    while True:
        try:
            fn, args = _db_save_queue.get(timeout=5)
            try:
                fn(*args)
            except Exception as e:
                print(f"[DB-QUEUE] خطأ في الحفظ: {e}")
            finally:
                _db_save_queue.task_done()
        except _queue_module.Empty:
            pass

# تشغيل خيط DB المركزي (يُشغَّل بعد تعريف الدوال اللازمة عند الإطلاق)
def enqueue_db_save(fn, *args):
    """إضافة عملية حفظ للقائمة بدل فتح خيط جديد"""
    _db_save_queue.put((fn, args))

def _get_active_dynamic_accounts_count():
    """عدد الحسابات الديناميكية النشطة (غير المستثناة)"""
    with proxy_store_lock:
        return len([e for e in dynamic_proxy_store if e not in EXEMPT_ACCOUNTS])

def _needed_reserve_size():
    """حجم الاحتياطي المطلوب = (حسابات + 1) × 20 — دائماً يكفي لحساب قادم جديد"""
    active = _get_active_dynamic_accounts_count()
    return (active + 1) * PROXIES_PER_ACCOUNT


# ==========================================
# متغيرات الحالة العامة
# ==========================================
user_sessions = {}
user_data_store = {}          # chat_id -> {email, password}  (الحساب النشط للعرض فقط)
user_numbered_tasks = {}
user_transient_messages = {}
user_pending_tasks = {}       # chat_id -> [confirmed tasks list]

# مخزن الجلسات المصادقة (email -> requests.Session) — الإصلاح #1
user_auth_sessions = {}
auth_sessions_lock = threading.Lock()

# ─── الحسابات المُسجَّل خروجها (جلستها منتهية) ────────────────────────────────
# { chat_id: set(email_lower, ...) }
# عند التبديل لحساب آخر لا نضيف لهذه القائمة (الجلسة تبقى)
# عند تسجيل الدخول مجدداً نحذفه من هذه القائمة
logged_out_accounts = {}   # chat_id -> set of email_lower
logged_out_lock = threading.Lock()

# ─── حماية من تكرار معالجة الحظر لنفس الحساب ───────────────────────────────
# يمنع إرسال رسالة الحظر أكثر من مرة واحدة لنفس الحساب
_handling_blocked = set()   # set of email_lower
_handling_blocked_lock = threading.Lock()

# ─── حماية من تكرار رسالة تسجيل الخروج لنفس الحساب ────────────────────────
# { (chat_id, email_lower): timestamp } — إرسال واحد كل 60 ثانية على الأقل
_logout_sent_times = {}
_logout_sent_lock = threading.Lock()

# ─── نظام الحسابات المتعددة ─────────────────────────────────────────────────
# active_accounts[chat_id][email] = {email, password}
# جميع الحسابات المحفوظة تعمل في الخلفية بغض النظر عن الحساب النشط للعرض
active_accounts = {}           # chat_id -> {email: {email, password}}
active_accounts_lock = threading.Lock()

# إعدادات مستقلة لكل حساب (مفتاحها email)
acct_notify_status = {}        # email -> bool
acct_all_notify_status = {}    # email -> bool
acct_notify_interval = {}      # email -> int (دقائق)
acct_auto_hunt_status = {}     # email -> bool
acct_hunt_mode = {}            # email -> "GT" | "GTE"
acct_auto_hunt_mode = {}       # تعيين أسرع, نفس hunt_mode
acct_auto_execute_status = {}  # email -> bool
acct_auto_execute_interval = {}# email -> int
# ─────────────────────────────────────────────────────────────────────────────

# المتغيرات القديمة (للحساب النشط - للواجهة فقط)
notify_status = {}
all_notify_status = {}
notify_interval = {}
auto_hunt_status = {}
hunt_mode = {}
last_take_time = {}
TAKE_COOLDOWN = 60

user_notify_tasks = {}
ignored_tasks = {}

auto_execute_status = {}
auto_execute_interval = {}

sent_notifications = {}

def get_email_settings(email):
    """جلب إعدادات حساب معين (email) من المخزن المستقل"""
    e = email.lower().strip()
    notify_on = acct_notify_status.get(e, False)
    all_notify_on = acct_all_notify_status.get(e, False)
    # ── حراسة صارمة: لا يعملان معاً أبداً ──
    # إذا كلاهما مُفعَّل (حالة خاطئة) → الكلية لها الأولوية
    if notify_on and all_notify_on:
        notify_on = False
        acct_notify_status[e] = False
    return {
        'notify_status': notify_on,
        'all_notify_status': all_notify_on,
        'notify_interval': acct_notify_interval.get(e, 10),
        'auto_hunt_status': acct_auto_hunt_status.get(e, False),
        'hunt_mode': acct_hunt_mode.get(e, 'GTE'),
        'auto_execute_status': acct_auto_execute_status.get(e, False),
        'auto_execute_interval': acct_auto_execute_interval.get(e, 5),
    }

def sync_chat_settings_to_email(chat_id, email):
    """نسخ إعدادات chat_id الحالية إلى مفتاح email المستقل"""
    e = email.lower().strip()
    acct_notify_status[e] = notify_status.get(chat_id, False)
    acct_all_notify_status[e] = all_notify_status.get(chat_id, False)
    acct_notify_interval[e] = notify_interval.get(chat_id, 10)
    acct_auto_hunt_status[e] = auto_hunt_status.get(chat_id, False)
    acct_hunt_mode[e] = hunt_mode.get(chat_id, 'GTE')
    acct_auto_execute_status[e] = auto_execute_status.get(chat_id, False)
    acct_auto_execute_interval[e] = auto_execute_interval.get(chat_id, 5)

def sync_email_settings_to_chat(chat_id, email):
    """نسخ إعدادات email المستقلة إلى متغيرات chat_id (للواجهة)"""
    e = email.lower().strip()
    notify_status[chat_id] = acct_notify_status.get(e, False)
    all_notify_status[chat_id] = acct_all_notify_status.get(e, False)
    notify_interval[chat_id] = acct_notify_interval.get(e, 10)
    auto_hunt_status[chat_id] = acct_auto_hunt_status.get(e, False)
    hunt_mode[chat_id] = acct_hunt_mode.get(e, 'GTE')
    auto_execute_status[chat_id] = acct_auto_execute_status.get(e, False)
    auto_execute_interval[chat_id] = acct_auto_execute_interval.get(e, 5)

def register_account_in_active(chat_id, email, password):
    """تسجيل حساب في قائمة الحسابات النشطة في الخلفية"""
    with active_accounts_lock:
        if chat_id not in active_accounts:
            active_accounts[chat_id] = {}
        active_accounts[chat_id][email.lower().strip()] = {
            'email': email, 'password': password
        }

def get_all_active_accounts_for_chat(chat_id):
    """إرجاع كل الحسابات النشطة لمستخدم معين"""
    with active_accounts_lock:
        return dict(active_accounts.get(chat_id, {}))

def load_all_saved_accounts_to_active(chat_id):
    """تحميل جميع الحسابات المحفوظة لمستخدم وتسجيلها كنشطة"""
    saved = get_saved_multi_accounts(chat_id)
    for acc in saved:
        register_account_in_active(chat_id, acc['email'], acc['password'])

# ==========================================
# ☁️ نظام الحسابات المتعددة السحابي (Supabase)
# الحسابات محفوظة في جدول multi_accounts — لا تضيع عند إعادة تشغيل VPS
# ==========================================

# كاش في الذاكرة لتجنب الطلبات المتكررة
# { chat_id: [{'email': ..., 'password': ...}, ...] }
_multi_accounts_cache = {}
_multi_accounts_cache_lock = threading.Lock()

def _generate_account_fingerprint(chat_id, email):
    """
    توليد بصمة فريدة لحساب معين.
    البصمة مرتبطة بـ chat_id + email — لا تتكرر أبداً ولا تُشارك مع أي حساب آخر.
    """
    unique_seed = f"{chat_id}:{email.strip().lower()}:{uuid.uuid4()}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_seed))

def cloud_get_account_fingerprint(chat_id, email):
    """
    جلب البصمة الموجودة للحساب من Supabase.
    إذا لم تكن موجودة يُرجع None.
    """
    try:
        email_lower = str(email).strip().lower()
        r = requests.get(
            f"{DB_MULTI_ACCOUNTS_URL}?chat_id=eq.{int(chat_id)}&email=eq.{email_lower}&select=fingerprint",
            headers=DB_HEADERS,
            timeout=10
        )
        if r.status_code == 200 and r.json():
            return r.json()[0].get('fingerprint')
    except Exception as e:
        print(f"[FINGERPRINT] خطأ في جلب البصمة: {e}")
    return None

def cloud_save_multi_account(chat_id, email, password):
    """
    حفظ حساب في جدول multi_accounts السحابي مع بصمة فريدة.
    - إذا كان الحساب جديداً: تُولَّد بصمة جديدة فريدة وتُحفظ.
    - إذا كان موجوداً مسبقاً: تُحافظ على البصمة القديمة (لا تتغير أبداً).
    """
    try:
        email_lower = str(email).strip().lower()
        cid = int(chat_id)

        # تحقق من وجود بصمة سابقة في الكاش أو السحابة
        existing_fp = None
        with _multi_accounts_cache_lock:
            if cid in _multi_accounts_cache:
                for acc in _multi_accounts_cache[cid]:
                    if acc['email'].lower() == email_lower:
                        existing_fp = acc.get('fingerprint')
                        break

        if not existing_fp:
            existing_fp = cloud_get_account_fingerprint(chat_id, email)

        # إذا لم توجد بصمة نولّد واحدة جديدة
        fingerprint = existing_fp if existing_fp else _generate_account_fingerprint(chat_id, email)

        payload = {
            "chat_id": cid,
            "email": email_lower,
            "password": str(password),
            "fingerprint": fingerprint,
            "fingerprint_created_at": datetime.now(timezone.utc).isoformat() if not existing_fp else None
        }

        # إذا كانت البصمة موجودة مسبقاً لا نرسل fingerprint_created_at مجدداً
        if existing_fp:
            del payload["fingerprint_created_at"]

        headers = {**DB_HEADERS, "Prefer": "resolution=merge-duplicates"}
        r = requests.post(DB_MULTI_ACCOUNTS_URL, json=payload, headers=headers, timeout=10)
        success = r.status_code in [200, 201]
        if success:
            # تحديث الكاش مع البصمة
            with _multi_accounts_cache_lock:
                if cid not in _multi_accounts_cache:
                    _multi_accounts_cache[cid] = []
                found = False
                for acc in _multi_accounts_cache[cid]:
                    if acc['email'].lower() == email_lower:
                        acc['password'] = password
                        acc['fingerprint'] = fingerprint
                        found = True
                        break
                if not found:
                    _multi_accounts_cache[cid].append({
                        'email': email_lower,
                        'password': password,
                        'fingerprint': fingerprint
                    })
            print(f"[FINGERPRINT] ✅ بصمة الحساب {email_lower}: {fingerprint}")
        return success
    except Exception as e:
        print(f"[MULTI-DB] خطأ في الحفظ: {e}")
        return False

def cloud_get_multi_accounts(chat_id):
    """
    جلب جميع الحسابات المحفوظة لمستخدم معين من Supabase.
    يستخدم الكاش — يُحدَّث عند الحاجة فقط.
    يشمل البصمة الخاصة بكل حساب.
    """
    cid = int(chat_id)
    # جرب الكاش أولاً
    with _multi_accounts_cache_lock:
        if cid in _multi_accounts_cache:
            return list(_multi_accounts_cache[cid])
    # جلب من السحابة
    try:
        r = requests.get(
            f"{DB_MULTI_ACCOUNTS_URL}?chat_id=eq.{cid}&order=id.asc",
            headers=DB_HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            rows = r.json()
            result = [
                {
                    'email': row['email'],
                    'password': row['password'],
                    'fingerprint': row.get('fingerprint', '')
                }
                for row in rows
            ]
            with _multi_accounts_cache_lock:
                _multi_accounts_cache[cid] = result
            return result
    except Exception as e:
        print(f"[MULTI-DB] خطأ في الجلب: {e}")
    return []

def cloud_delete_multi_account(chat_id, email):
    """حذف حساب محدد من multi_accounts (يُحذف مع بصمته نهائياً)"""
    try:
        email_lower = str(email).strip().lower()
        r = requests.delete(
            f"{DB_MULTI_ACCOUNTS_URL}?chat_id=eq.{int(chat_id)}&email=eq.{email_lower}",
            headers={**DB_HEADERS, "Prefer": "return=minimal"},
            timeout=10
        )
        # تحديث الكاش
        with _multi_accounts_cache_lock:
            cid = int(chat_id)
            if cid in _multi_accounts_cache:
                _multi_accounts_cache[cid] = [
                    a for a in _multi_accounts_cache[cid]
                    if a['email'].lower() != email_lower
                ]
        return r.status_code in [200, 204]
    except Exception as e:
        print(f"[MULTI-DB] خطأ في الحذف: {e}")
        return False

def cloud_get_fingerprint_for_account(chat_id, email):
    """
    إرجاع البصمة الخاصة بحساب معين من الكاش أو السحابة.
    هذه البصمة فريدة تماماً ولا تُشارك مع أي حساب آخر.
    """
    email_lower = str(email).strip().lower()
    cid = int(chat_id)
    # جرب الكاش أولاً
    with _multi_accounts_cache_lock:
        if cid in _multi_accounts_cache:
            for acc in _multi_accounts_cache[cid]:
                if acc['email'].lower() == email_lower:
                    fp = acc.get('fingerprint', '')
                    if fp:
                        return fp
    # جلب من السحابة
    return cloud_get_account_fingerprint(chat_id, email)

def cloud_load_all_multi_accounts():
    """
    جلب جميع الحسابات لجميع المستخدمين دفعة واحدة عند بدء التشغيل.
    يُرجع dict: { chat_id(int): [{'email':..,'password':..,'fingerprint':..}, ...] }
    """
    try:
        r = requests.get(
            f"{DB_MULTI_ACCOUNTS_URL}?order=chat_id.asc,id.asc",
            headers=DB_HEADERS,
            timeout=15
        )
        if r.status_code == 200:
            rows = r.json()
            result = {}
            for row in rows:
                cid = int(row['chat_id'])
                if cid not in result:
                    result[cid] = []
                result[cid].append({
                    'email': row['email'],
                    'password': row['password'],
                    'fingerprint': row.get('fingerprint', '')
                })
            # تحديث الكاش الكامل
            with _multi_accounts_cache_lock:
                _multi_accounts_cache.clear()
                _multi_accounts_cache.update(result)
            return result
    except Exception as e:
        print(f"[MULTI-DB] خطأ في جلب الكل: {e}")
    return {}

# ── دوال التوافق — نفس الأسماء القديمة تشير الآن للسحابة ──
def save_multi_account(chat_id, email, password):
    """واجهة توافق — تحفظ في Supabase"""
    return cloud_save_multi_account(chat_id, email, password)

def get_saved_multi_accounts(chat_id):
    """واجهة توافق — تجلب من Supabase (مع كاش)"""
    return cloud_get_multi_accounts(chat_id)

def load_multi_accounts():
    """واجهة توافق — تجلب الكل من Supabase"""
    return cloud_load_all_multi_accounts()

def delete_transient_message(bot, chat_id):
    if chat_id in user_transient_messages:
        try:
            bot.delete_message(chat_id, user_transient_messages[chat_id])
        except Exception:
            pass
        del user_transient_messages[chat_id]

# ==========================================
# 🗄️ عمليات قاعدة البيانات (Supabase)
# ==========================================
def cloud_save_account(chat_id, username, password):
    payload = {"chat_id": int(chat_id), "username": str(username), "password": str(password)}
    try:
        requests.post(DB_API_URL, json=payload, headers=DB_HEADERS, timeout=10)
    except Exception:
        pass

def cloud_get_account(chat_id):
    try:
        url = f"{DB_API_URL}?chat_id=eq.{chat_id}"
        response = requests.get(url, headers=DB_HEADERS, timeout=10)
        if response.status_code == 200 and response.json():
            return response.json()[0]
    except Exception:
        pass
    return None

def cloud_delete_account(chat_id):
    try:
        url = f"{DB_API_URL}?chat_id=eq.{chat_id}"
        payload = {"username": "", "password": ""}
        requests.patch(url, json=payload, headers=DB_HEADERS, timeout=10)
    except Exception:
        pass

def cloud_save_auto_task(chat_id, keyword, work_url, proof_msg):
    payload = {
        "chat_id": int(chat_id),
        "keyword": str(keyword),
        "work_url": str(work_url) if work_url else None,
        "proof_msg": str(proof_msg)
    }
    try:
        r = requests.post(DB_AUTO_TASKS_URL, json=payload, headers=DB_HEADERS, timeout=10)
        return r.status_code in [200, 201]
    except Exception:
        return False

def cloud_get_auto_tasks(chat_id):
    try:
        url = f"{DB_AUTO_TASKS_URL}?chat_id=eq.{int(chat_id)}&order=id.asc"
        response = requests.get(url, headers=DB_HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return []

def cloud_delete_auto_task(task_id):
    try:
        url = f"{DB_AUTO_TASKS_URL}?id=eq.{task_id}"
        requests.delete(url, headers=DB_HEADERS, timeout=10)
        return True
    except Exception:
        return False

def cloud_update_template(template_id, keyword, work_url, proof_msg):
    payload = {
        "keyword": str(keyword),
        "work_url": str(work_url) if work_url else None,
        "proof_msg": str(proof_msg)
    }
    try:
        url = f"{DB_AUTO_TASKS_URL}?id=eq.{template_id}"
        r = requests.patch(url, json=payload, headers=DB_HEADERS, timeout=10)
        return r.status_code in [200, 204]
    except Exception:
        return False

def cloud_share_templates_by_chat_id(target_chat_id, current_chat_id):
    try:
        current_templates = cloud_get_auto_tasks(current_chat_id)
        if not current_templates:
            return "EMPTY"

        existing_keywords = set()
        target_templates = cloud_get_auto_tasks(target_chat_id)
        for t in target_templates:
            existing_keywords.add(t.get('keyword', '').strip().lower())

        success_count = 0
        original_template_ids = []

        for tmpl in current_templates:
            kw = tmpl['keyword'].strip().lower()
            if kw in existing_keywords:
                continue
            payload = {
                "chat_id": int(target_chat_id),
                "keyword": str(tmpl['keyword']),
                "work_url": str(tmpl.get('work_url')) if tmpl.get('work_url') else None,
                "proof_msg": str(tmpl['proof_msg'])
            }
            r = requests.post(DB_AUTO_TASKS_URL, json=payload, headers=DB_HEADERS, timeout=10)
            if r.status_code in [200, 201]:
                success_count += 1
                existing_keywords.add(kw)
                original_template_ids.append(tmpl['id'])

        if original_template_ids:
            for template_id in original_template_ids:
                try:
                    cloud_delete_auto_task(template_id)
                except Exception:
                    pass

        if success_count == 0:
            return "ALREADY_EXISTS"

        try:
            bot.send_message(current_chat_id, f"✅ تم نقل {success_count} الباقة بنجاح إلى حساب التليجرام {target_chat_id}")
            bot.send_message(target_chat_id, f"📥 تم استلام {success_count} الباقة جديد من حساب التليجرام {current_chat_id}")
        except Exception:
            pass

        return "SUCCESS"
    except Exception as e:
        print(f"❌ خطأ في المشاركة: {e}")
        return "ERROR"

def cloud_save_user_settings(chat_id):
    email = user_data_store.get(chat_id, {}).get('email', '')
    # مزامنة إعدادات chat_id → email المستقل
    if email:
        sync_chat_settings_to_email(chat_id, email)
    payload = {
        "notify_status": bool(notify_status.get(chat_id, False)),
        "notify_interval": int(notify_interval.get(chat_id, 10)),
        "auto_hunt_status": bool(auto_hunt_status.get(chat_id, False)),
        "hunt_mode": str(hunt_mode.get(chat_id, "GTE")),
        "auto_execute_status": bool(auto_execute_status.get(chat_id, False)),
        "auto_execute_interval": int(auto_execute_interval.get(chat_id, 5)),
        "all_notify_status": bool(all_notify_status.get(chat_id, False))
    }
    try:
        url = f"{DB_API_URL}?chat_id=eq.{chat_id}"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        response = requests.patch(url, json=payload, headers=headers, timeout=10)
        return response.status_code in [200, 204]
    except Exception:
        return False

def cloud_load_user_settings(chat_id):
    try:
        url = f"{DB_API_URL}?chat_id=eq.{chat_id}&select=notify_status,notify_interval,auto_hunt_status,hunt_mode,auto_execute_status,auto_execute_interval,all_notify_status"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200 and response.json():
            settings = response.json()[0]
            notify_status[chat_id] = settings.get('notify_status', False)
            all_notify_status[chat_id] = settings.get('all_notify_status', False)
            notify_interval[chat_id] = settings.get('notify_interval', 10)
            auto_hunt_status[chat_id] = settings.get('auto_hunt_status', False)
            hunt_mode[chat_id] = settings.get('hunt_mode', 'GTE')
            auto_execute_status[chat_id] = settings.get('auto_execute_status', False)
            auto_execute_interval[chat_id] = settings.get('auto_execute_interval', 5)
            # مزامنة الإعدادات للحساب النشط الحالي
            email = user_data_store.get(chat_id, {}).get('email', '')
            if email:
                sync_chat_settings_to_email(chat_id, email)
            return True
    except Exception:
        pass
    return False

