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
from config_shared import *
from proxies import *

def _prepare_session_with_proxy(email, password):
    """
    دالة مشتركة: تجهيز البروكسي ثم إنشاء الجلسة المصادقة وحفظها.
    تعمل بأمان في خيط مستقل — تحل مشكلة Python closure bug.
    """
    email_lower = email.lower().strip()
    # 1) جلب/تجهيز البروكسي أولاً (تزامني داخل الخيط)
    _ensure_proxy_for_account(email_lower)
    # 2) إنشاء الجلسة مع البروكسي المجهّز
    sess = get_authenticated_session(email, password)
    if sess:
        with auth_sessions_lock:
            user_auth_sessions[email_lower] = sess
        print(f"[SESSION] جلسة جاهزة وبروكسي نشط: {email_lower}")
    else:
        print(f"[SESSION] فشل تجهيز الجلسة للحساب: {email_lower}")

def check_and_load_session_silently(chat_id):
    if chat_id not in user_data_store:
        saved_acc = cloud_get_account(chat_id)
        if saved_acc:
            settings_loaded = cloud_load_user_settings(chat_id)
            if not settings_loaded:
                notify_status[chat_id] = False
                all_notify_status[chat_id] = False
                notify_interval[chat_id] = 10
                auto_hunt_status[chat_id] = False
                hunt_mode[chat_id] = "GTE"
                auto_execute_status[chat_id] = False
                auto_execute_interval[chat_id] = 5
            if saved_acc.get('username') and saved_acc.get('password'):
                email = saved_acc['username']
                password = saved_acc['password']
                user_data_store[chat_id] = {'email': email, 'password': password}

                email_lower = email.lower().strip()
                with auth_sessions_lock:
                    cached = user_auth_sessions.get(email_lower)
                if not cached:
                    # تجهيز البروكسي والجلسة في خيط خلفي — بدون closure bug
                    threading.Thread(
                        target=_prepare_session_with_proxy,
                        args=(email, password),
                        daemon=True
                    ).start()
                return True
            return False
        return False
    if chat_id not in notify_status:
        cloud_load_user_settings(chat_id)
    return True

def safe_edit_or_send(bot, chat_id, message_id, new_text, reply_markup=None, parse_mode=None):
    try:
        bot.edit_message_text(new_text, chat_id, message_id, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            bot.send_message(chat_id, new_text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            pass

# ==========================================
# 🚨 كشف وإدارة BLOCKED و CAPTCHA
# ==========================================

def detect_page_state(html_text):
    """
    يفحص نص صفحة HTML ويُرجع:
      - 'blocked'  إذا كان الحساب محظوراً
      - 'captcha'  إذا ظهرت صفحة captcha أو تحقق
      - None       إذا كانت الصفحة عادية
    """
    if not html_text:
        return None

    # ── كشف الحظر: النص الروسي الموجود في صفحة BLOCKED ──
    blocked_signals = [
        "заблокирован",          # الحساب محظور
        "аккаунт заблокирован",  # الحساب محظور (أكثر دقة)
        "account is blocked",
        "account blocked",
    ]
    html_lower = html_text.lower()
    for sig in blocked_signals:
        if sig in html_lower:
            return "blocked"

    # ── كشف CAPTCHA: صفحة تسجيل الدخول بدون زر الخروج ──
    # صفحة CAPTCHA_PAGE تُظهر صفحة رئيسية بدون "Выход" (زر الخروج)
    # وتحتوي على "Вход" (تسجيل الدخول) مما يعني أن الجلسة انهارت
    captcha_signals = [
        "recaptcha",
        "g-recaptcha",
        "captcha",
        "i am not a robot",
        "я не робот",
        "cloudflare",
        "cf-challenge",
        "challenge-form",
    ]
    for sig in captcha_signals:
        if sig in html_lower:
            return "captcha"

    # صفحة الموقع الرئيسية بدون جلسة = captcha/انتهاء جلسة مع وجود صفحة تسجيل الدخول
    # الموقع يعيد توجيه الجلسة المنتهية إلى الصفحة الرئيسية
    if "login-box" in html_lower and "Выход" not in html_text:
        return "captcha"

    return None


def handle_blocked_account(email, chat_id_origin=None):
    """
    عند اكتشاف أن حساباً محظور:
    1. يضمن إرسال رسالة الحظر مرة واحدة فقط لكل حساب (حماية من التكرار)
    2. يحذف الحساب نهائياً من جميع القوائم والجلسات
    """
    email_lower = email.lower().strip()

    # ── حماية من التكرار: إذا كان يُعالَج الآن نتجاهل ──
    with _handling_blocked_lock:
        if email_lower in _handling_blocked:
            print(f"[BLOCKED] {email_lower} — معالجة الحظر جارية بالفعل، تجاهل التكرار")
            return
        _handling_blocked.add(email_lower)

    try:
        account_label = email_lower.split("@")[0]
        print(f"[BLOCKED] ⛔ الحساب {email_lower} محظور — جاري الحذف النهائي")

        # ── 1: إيقاف جميع المهام التلقائية للحساب المحظور ──
        acct_notify_status[email_lower] = False
        acct_all_notify_status[email_lower] = False
        acct_auto_hunt_status[email_lower] = False
        acct_auto_execute_status[email_lower] = False

        # ── إلغاء فوري لأي خيط إشعارات كلية جارٍ ──
        _cancel_all_notify_for_email(email_lower)

        # ── 2: مسح الجلسة النشطة ──
        with auth_sessions_lock:
            user_auth_sessions.pop(email_lower, None)

        # ── 3: حذف البروكسيات المرتبطة بالحساب ──
        with proxy_store_lock:
            dynamic_proxy_store.pop(email_lower, None)

        # ── 4: تحديد كل chat_ids التي تملك هذا الحساب ──
        affected_chats = []
        with active_accounts_lock:
            for cid, accounts in active_accounts.items():
                if email_lower in accounts:
                    affected_chats.append(cid)

        blocked_msg = (
            f"🚫 **تنبيه: حساب محظور**\n\n"
            f"⛔ الحساب **{account_label}** (`{email_lower}`) تعرّض للحظر من قِبَل الموقع.\n\n"
            f"📌 تم تسجيل الخروج وحذفه تلقائياً.\n"
            f"💡 للاستفسار: `support@forumok.com`"
        )

        for cid in affected_chats:
            try:
                # ── حذف الحساب نهائياً من active_accounts ──
                with active_accounts_lock:
                    if cid in active_accounts:
                        active_accounts[cid].pop(email_lower, None)

                # ── حذف الحساب نهائياً من قاعدة البيانات السحابية ──
                threading.Thread(
                    target=cloud_delete_multi_account,
                    args=(cid, email_lower),
                    daemon=True
                ).start()

                # ── تعليم الحساب كـ"مُسجَّل خروجه" ──
                with logged_out_lock:
                    if cid not in logged_out_accounts:
                        logged_out_accounts[cid] = set()
                    logged_out_accounts[cid].add(email_lower)

                # إذا كان هذا هو الحساب النشط حالياً في الواجهة → امسح بياناته
                active_email = user_data_store.get(cid, {}).get("email", "").lower().strip()
                if active_email == email_lower:
                    for store in [user_data_store, user_sessions, user_numbered_tasks,
                                  notify_status, notify_interval, auto_hunt_status, hunt_mode,
                                  last_take_time, user_notify_tasks, ignored_tasks,
                                  auto_execute_status, auto_execute_interval, all_notify_status]:
                        store.pop(cid, None)

                # ── إرسال رسالة واحدة فقط لكل chat_id ──
                try:
                    bot.send_message(cid, blocked_msg, parse_mode="Markdown")
                except Exception as e:
                    print(f"[BLOCKED] خطأ في إرسال تنبيه blocked لـ {cid}: {e}")

            except Exception as e:
                print(f"[BLOCKED] خطأ في معالجة chat_id {cid}: {e}")

    finally:
        # إزالة الحساب من مجموعة المعالجة بعد 120 ثانية (لو عاد ظهوره مجدداً)
        def _clear_handling():
            time.sleep(120)
            with _handling_blocked_lock:
                _handling_blocked.discard(email_lower)
        threading.Thread(target=_clear_handling, daemon=True).start()


def handle_captcha_detected(email, context=""):
    """
    عند اكتشاف CAPTCHA:
    يرسل رسالة خاصة إلى CAPTCHA_ALERT_CHAT_ID يُخبره بظهور تحقق للحساب.
    context: وصف المكان الذي ظهر فيه CAPTCHA (تسجيل دخول / أثناء العمل)
    """
    email_lower = email.lower().strip()
    account_label = email_lower.split("@")[0]

    print(f"[CAPTCHA] ⚠️ ظهر CAPTCHA للحساب {email_lower} — إرسال تنبيه")

    context_text = f"\n📍 **السياق:** {context}" if context else ""

    captcha_msg = (
        f"🤖 **تنبيه: CAPTCHA ظهر!**\n\n"
        f"🔐 الحساب: **{account_label}** (`{email_lower}`)\n"
        f"{context_text}\n"
        f"⚠️ يجب حل التحقق يدوياً أو تغيير البروكسي.\n\n"
        f"🔄 تم إيقاف العمل التلقائي لهذا الحساب مؤقتاً."
    )

    # إيقاف مؤقت لجميع المهام التلقائية حتى يُحَل CAPTCHA
    acct_notify_status[email_lower] = False
    acct_all_notify_status[email_lower] = False
    acct_auto_hunt_status[email_lower] = False
    acct_auto_execute_status[email_lower] = False

    # ── إلغاء فوري لأي خيط إشعارات كلية جارٍ ──
    _cancel_all_notify_for_email(email_lower)

    # مسح الجلسة المنتهية
    with auth_sessions_lock:
        user_auth_sessions.pop(email_lower, None)

    try:
        bot.send_message(CAPTCHA_ALERT_CHAT_ID, captcha_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[CAPTCHA] خطأ في إرسال تنبيه CAPTCHA: {e}")


# ==========================================
# إنشاء الجلسات مع دعم البروكسي الكامل
# ==========================================
def create_session(email=None):
    """
    إنشاء جلسة HTTP مع ربط البروكسي على مستوى الحساب بالكامل.
    - الحسابات المستثناة: بروكسيات ثابتة مع مصادقة.
    - باقي الحسابات: بروكسي ديناميكي حصري بدون مصادقة.
    """
    session = requests.Session()
    if not email:
        return session

    email_lower = email.lower().strip()

    if email_lower in EXEMPT_ACCOUNTS:
        # نظام البروكسي الثابت للحسابين المستثنيين
        fast_proxy = get_fastest_proxy_exempt(email_lower)
        if fast_proxy:
            proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{fast_proxy}"
            session.proxies = {"http": proxy_url, "https": proxy_url}
            print(f"[SESSION] {email_lower} → بروكسي ثابت: {fast_proxy}")
    else:
        # النظام الديناميكي
        proxy_addr = get_current_proxy_for_account(email_lower)
        if proxy_addr:
            session.proxies = {"http": proxy_addr, "https": proxy_addr}
            session._dynamic_proxy_email = email_lower
            session._dynamic_proxy_addr = proxy_addr
            print(f"[SESSION] {email_lower} → بروكسي ديناميكي: {proxy_addr}")

    return session

def _try_login_with_proxy(username, password, proxy_addr, email_lower):
    """محاولة تسجيل دخول واحدة مع بروكسي محدد. تُرجع session أو None أو 'CAPTCHA' أو 'BLOCKED'."""
    try:
        sess = requests.Session()
        if proxy_addr:
            sess.proxies = {"http": proxy_addr, "https": proxy_addr}
            sess._dynamic_proxy_email = email_lower
            sess._dynamic_proxy_addr = proxy_addr
        login_data = {
            "signin[username]": username,
            "signin[password]": password,
            "signin[remember]": "1",
            "signin[refer_url]": "@office_initial"
        }
        sess.get(BASE_URL, headers=HEADERS, timeout=8)
        lr = sess.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=8)
        if lr.status_code == 200:
            page_state = detect_page_state(lr.text)
            if page_state == "blocked":
                threading.Thread(
                    target=handle_blocked_account, args=(username,), daemon=True
                ).start()
                return "BLOCKED"
            if page_state == "captcha":
                threading.Thread(
                    target=handle_captcha_detected,
                    args=(username, "أثناء تسجيل الدخول"),
                    daemon=True
                ).start()
                return "CAPTCHA"
            if "Выход" in lr.text:
                return sess
    except Exception:
        pass
    return None


def get_authenticated_session(username, password, use_proxy=True):
    """
    نظام تسجيل الدخول المُحسَّن:
    1. إذا توجد جلسة محفوظة صالحة → تُستخدم مباشرة.
    2. إذا توجد بروكسيات محفوظة → يُستخدم الأسرع.
    3. إذا لم تتوجد بروكسيات (حساب جديد) → يجلب ويختبر دفعة كبيرة بالتوازي،
       يُسجَّل الدخول بأول بروكسي يعمل فوراً، ثم يكمل جمع الـ20 في الخلفية.
    """
    email_lower = username.lower().strip()

    # ── 1: جلسة محفوظة ──
    with auth_sessions_lock:
        cached_session = user_auth_sessions.get(email_lower)
    if cached_session:
        try:
            test_r = cached_session.get(BASE_URL, headers=HEADERS, timeout=8)
            page_state = detect_page_state(test_r.text)
            if page_state == "blocked":
                threading.Thread(target=handle_blocked_account, args=(username,), daemon=True).start()
                with auth_sessions_lock:
                    user_auth_sessions.pop(email_lower, None)
                return None
            if page_state == "captcha":
                threading.Thread(
                    target=handle_captcha_detected,
                    args=(username, "أثناء التحقق من الجلسة المحفوظة"),
                    daemon=True
                ).start()
                with auth_sessions_lock:
                    user_auth_sessions.pop(email_lower, None)
                return None
            if "Выход" in test_r.text:
                return cached_session
        except Exception:
            pass
        with auth_sessions_lock:
            user_auth_sessions.pop(email_lower, None)

    # ── حسابات استثنائية: بروكسي ثابت ──
    if email_lower in EXEMPT_ACCOUNTS:
        session = create_session(email=username)
        login_data = {
            "signin[username]": username,
            "signin[password]": password,
            "signin[remember]": "1",
            "signin[refer_url]": "@office_initial"
        }
        try:
            session.get(BASE_URL, headers=HEADERS, timeout=10)
            lr = session.post(LOGIN_URL, data=login_data, headers=HEADERS, timeout=10)
            if lr.status_code == 200 and "Выход" in lr.text:
                with auth_sessions_lock:
                    user_auth_sessions[email_lower] = session
                return session
        except Exception:
            pass
        return None

    # ── 2: توجد بروكسيات محفوظة → الأسرع منها ──
    with proxy_store_lock:
        store = dynamic_proxy_store.get(email_lower)
        has_proxies = store and bool(store.get("proxies"))

    if has_proxies:
        with proxy_store_lock:
            alive = [p for p in store["proxies"] if p.get("status", "active") != "dead"]
        if alive:
            alive.sort(key=lambda x: x.get("latency", 999))
            # محاولة مع الأسرع، ثم fallover للتالي
            for proxy_info in alive[:3]:
                sess = _try_login_with_proxy(username, password, proxy_info["address"], email_lower)
                if sess and sess not in ("BLOCKED", "CAPTCHA"):
                    with auth_sessions_lock:
                        user_auth_sessions[email_lower] = sess
                    return sess
                elif sess in ("BLOCKED", "CAPTCHA"):
                    return None  # تم التعامل مع الحالة داخل _try_login_with_proxy
                else:
                    # ضع هذا البروكسي كـ dead
                    proxy_info["status"] = "dead"
                    enqueue_db_save(mark_proxy_dead_in_db, proxy_info["address"])
        # كل البروكسيات المحفوظة فاشلة → احذفها وابدأ من جديد
        with proxy_store_lock:
            dynamic_proxy_store.pop(email_lower, None)

    # ── 3: حساب جديد أو بروكسيات فاشلة → أولاً من الاحتياطي، ثم الجلب ──
    print(f"[SESSION] {email_lower}: محاولة تسجيل الدخول...")

    # أولاً: جرب أخذ بروكسي من الاحتياطي (فوري بدون جلب)
    first_proxy = None
    raw_proxies = []

    with reserve_pool_lock:
        reserve_alive = [p for p in proxy_reserve_pool["proxies"] if p.get("status", "active") != "dead"]

    if reserve_alive:
        first_proxy = reserve_alive[0]
        # احذفه من الاحتياطي مؤقتاً
        with reserve_pool_lock:
            proxy_reserve_pool["proxies"] = [p for p in proxy_reserve_pool["proxies"]
                                              if p["address"] != first_proxy["address"]]
        print(f"[SESSION] {email_lower}: استخدام بروكسي من الاحتياطي: {first_proxy['address']} ({first_proxy.get('latency','?')}s)")
    else:
        # لا احتياطي — جلب ومعالجة سريعة
        print(f"[SESSION] {email_lower}: الاحتياطي فارغ — جلب بروكسيات جديدة...")
        raw_proxies = fetch_raw_proxies()
        if not raw_proxies:
            print(f"[SESSION] {email_lower}: فشل جلب البروكسيات الخام — تسجيل مباشر")
            sess = _try_login_with_proxy(username, password, None, email_lower)
            if sess and sess not in ("BLOCKED", "CAPTCHA"):
                with auth_sessions_lock:
                    user_auth_sessions[email_lower] = sess
            return sess if sess not in ("BLOCKED", "CAPTCHA") else None
        first_proxy = get_first_alive_proxy(raw_proxies, batch_size=150, max_wait=25)

    if not first_proxy:
        print(f"[SESSION] {email_lower}: لم يُعثر على بروكسي — تسجيل مباشر")
        sess = _try_login_with_proxy(username, password, None, email_lower)
        if sess and sess not in ("BLOCKED", "CAPTCHA"):
            with auth_sessions_lock:
                user_auth_sessions[email_lower] = sess
        return sess if sess not in ("BLOCKED", "CAPTCHA") else None

    # حفظ أول بروكسي مؤقتاً في المخزن
    with proxy_store_lock:
        dynamic_proxy_store[email_lower] = {
            "proxies": [first_proxy],
            "current_index": 0,
            "last_updated": time.time()
        }

    print(f"[SESSION] {email_lower}: تسجيل الدخول بأول بروكسي سريع: {first_proxy['address']} ({first_proxy.get('latency', '?')}s)")
    sess = _try_login_with_proxy(username, password, first_proxy["address"], email_lower)

    if sess and sess not in ("BLOCKED", "CAPTCHA"):
        with auth_sessions_lock:
            user_auth_sessions[email_lower] = sess
        # في الخلفية: جمع أفضل 20 بروكسي من الاحتياطي + raw_proxies
        threading.Thread(
            target=_background_fill_proxies,
            args=(email_lower, raw_proxies, first_proxy),
            daemon=True
        ).start()
        return sess

    if sess in ("BLOCKED", "CAPTCHA"):
        return None  # تم التعامل مع الحالة داخل _try_login_with_proxy

    # أول بروكسي فشل في تسجيل الدخول → جرب التاليين من الاحتياطي
    print(f"[SESSION] {email_lower}: فشل أول بروكسي في تسجيل الدخول، محاولة بالاحتياطي...")
    first_proxy["status"] = "dead"

    # جرب ثاني بروكسي من الاحتياطي
    backup_proxy = None
    with reserve_pool_lock:
        reserve_now = [p for p in proxy_reserve_pool["proxies"] if p.get("status", "active") != "dead"]
        if reserve_now:
            backup_proxy = reserve_now[0]
            proxy_reserve_pool["proxies"] = reserve_now[1:]

    if not backup_proxy and raw_proxies:
        backup_proxy = get_first_alive_proxy(
            [p for p in raw_proxies if p != first_proxy["address"]],
            batch_size=100, max_wait=20
        )

    if backup_proxy:
        with proxy_store_lock:
            dynamic_proxy_store[email_lower] = {
                "proxies": [backup_proxy],
                "current_index": 0,
                "last_updated": time.time()
            }
        sess2 = _try_login_with_proxy(username, password, backup_proxy["address"], email_lower)
        if sess2 and sess2 not in ("BLOCKED", "CAPTCHA"):
            with auth_sessions_lock:
                user_auth_sessions[email_lower] = sess2
            threading.Thread(
                target=_background_fill_proxies,
                args=(email_lower, raw_proxies, backup_proxy),
                daemon=True
            ).start()
            return sess2
        if sess2 in ("BLOCKED", "CAPTCHA"):
            return None

    # كل المحاولات فشلت
    print(f"[SESSION] {email_lower}: كل المحاولات فشلت")
    # طلب تعبئة احتياطي في الخلفية للمحاولة القادمة
    trigger_reserve_fill()
    return None

# ==========================================
# استخراج البيانات والتنفيذ التلقائي
# ==========================================
def extract_real_price_and_description(session, task_page_url):
    try:
        response = session.get(task_page_url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            desc_text = ""
            desc_div = soup.find("div", style=re.compile(r"overflow-wrap:\s*break-word"))
            if desc_div:
                desc_text = desc_div.get_text(strip=True)
            else:
                for td in soup.find_all("td", align="left"):
                    if td.find("div"):
                        desc_text = td.find("div").get_text(strip=True)
                        break

            price_val = None
            info_table = soup.find("table", id="order-info-requests")
            if info_table:
                rows = info_table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2 and "Оплата" in cells[0].get_text():
                        price_td = cells[1] if len(cells) > 1 else None
                        if price_td:
                            price_text = price_td.get_text(strip=True)
                            price_match = re.search(r"([\d\.,]+)", price_text)
                            if price_match:
                                price_val = float(price_match.group(1).replace(",", "."))
            if price_val is None:
                page_text = soup.get_text()
                pay_match = re.search(r"Оплата\s*([\d\.,]+)", page_text, re.IGNORECASE)
                if pay_match:
                    price_val = float(pay_match.group(1).replace(",", "."))

            return price_val, desc_text
    except Exception:
        pass
    return None, ""

def _fetch_task_details_unified(session, task_page_url):
    """
    ⚡ دالة موحدة: تجلب صفحة المهمة مرة واحدة فقط وتستخرج منها:
      - السعر الحقيقي
      - الوصف
      - مدة التنفيذ
    بدلاً من طلبَين منفصلَين → طلب واحد فقط لكل مهمة.
    """
    try:
        response = session.get(task_page_url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None, "", "2 часа"
        soup = BeautifulSoup(response.text, "html.parser")

        # ── استخراج الوصف ──
        desc_text = ""
        desc_div = soup.find("div", style=re.compile(r"overflow-wrap:\s*break-word"))
        if desc_div:
            desc_text = desc_div.get_text(strip=True)
        else:
            for td in soup.find_all("td", align="left"):
                if td.find("div"):
                    desc_text = td.find("div").get_text(strip=True)
                    break

        # ── استخراج السعر ──
        price_val = None
        info_table = soup.find("table", id="order-info-requests")
        if info_table:
            for row in info_table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) >= 2 and "Оплата" in cells[0].get_text():
                    price_text = cells[1].get_text(strip=True)
                    price_match = re.search(r"([\d\.,]+)", price_text)
                    if price_match:
                        price_val = float(price_match.group(1).replace(",", "."))
                        break
        if price_val is None:
            pay_match = re.search(r"Оплата\s*([\d\.,]+)", soup.get_text(), re.IGNORECASE)
            if pay_match:
                price_val = float(pay_match.group(1).replace(",", "."))

        # ── استخراج مدة التنفيذ ──
        raw_duration = "2 часа"
        for td in soup.find_all("td"):
            if "Время на выполнение" in td.get_text():
                next_td = td.find_next_sibling("td")
                if next_td:
                    raw_duration = next_td.get_text(strip=True)
                    break
        if raw_duration == "2 часа":
            time_match = re.search(r"Время на выполнение\s*(.*)", soup.get_text())
            if time_match:
                raw_duration = time_match.group(1).strip().split("\n")[0]

        return price_val, desc_text, raw_duration
    except Exception:
        return None, "", "2 часа"

def submit_task_proof_automatically(session, execute_page_url, work_url_val, proof_msg_val):
    try:
        res = session.get(execute_page_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            form = soup.find("form", action=re.compile(r"addRequest"))
            if form:
                post_action_url = f"{BASE_URL}/publisher-requests-socio/addRequest"
                if form.get('action'):
                    act = form.get('action')
                    post_action_url = act if act.startswith("http") else BASE_URL + act

                post_data = {}
                for hidden_input in form.find_all("input", type="hidden"):
                    if hidden_input.get("name"):
                        post_data[hidden_input.get("name")] = hidden_input.get("value", "")

                post_data["url[]"] = str(work_url_val) if work_url_val else ""
                post_data["msg"] = str(proof_msg_val)

                final_res = session.post(post_action_url, data=post_data, headers=HEADERS, timeout=10)
                if final_res.status_code == 200:
                    return True
    except Exception:
        pass
    return False

def get_platform_from_url(url):
    """استخراج اسم المنصة من رابط المهمة"""
    url_lower = url.lower()
    platforms = {
        "youtube": "🎥 YouTube",
        "vkontakte": "💙 VK",
        "vk": "💙 VK",
        "telegram": "✈️ Telegram",
        "instagram": "📸 Instagram",
        "tiktok": "🎵 TikTok",
        "twitter": "🐦 Twitter",
        "facebook": "👤 Facebook",
        "google": "🔍 Google",
        "yandex": "🔍 Yandex",
        "ok": "🟠 OK",
        "odnoklassniki": "🟠 OK",
        "twitch": "🟣 Twitch",
        "discord": "💬 Discord",
        "reddit": "🟥 Reddit",
    }
    for key, name in platforms.items():
        if f"/{key}/" in url_lower or f"/{key}" == url_lower[-len(key)-1:]:
            return name
    return "🌐 أخرى"

def extract_confirmed_tasks(session):
    tasks = []
    try:
        r = session.get(CONFIRMED_URL, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return tasks, "فشل تحميل الصفحة"

        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table", id="publisher-requests")
        if not table:
            return tasks, "لم يتم العثور على جدول المهام"

        rows = table.find_all("tr")
        for row in rows:
            try:
                cells = row.find_all("td")
                if len(cells) < 7:
                    continue

                time_cell = cells[1]
                time_remaining = re.sub(r'\s+', ' ', time_cell.get_text(strip=True)).strip()
                if not time_remaining:
                    time_remaining = "غير محدد"

                task_cell = cells[3]
                task_name = ""
                task_link = ""
                task_id = ""
                original_task_url = ""
                link_tag = task_cell.find("a")
                if link_tag:
                    task_name = link_tag.get_text(strip=True)
                    task_link = link_tag.get("href", "")
                    if task_link and not task_link.startswith("http"):
                        task_link = BASE_URL + task_link
                    original_task_url = task_link
                    if task_link and "?ok=1" not in task_link:
                        task_link += "?ok=1" if "?" not in task_link else "&ok=1"
                    id_match = re.search(r'/request/(\d+)/', task_link)
                    if id_match:
                        task_id = id_match.group(1)

                # استخراج المنصة من رابط المهمة الأصلي
                platform = get_platform_from_url(original_task_url) if original_task_url else "🌐 أخرى"

                price_cell = cells[5]
                price = price_cell.get_text(strip=True).replace("\xa0", " ")

                report_cell = cells[6]
                report_link = ""
                link_tag = report_cell.find("a")
                if link_tag:
                    report_link = link_tag.get("href", "")
                    if report_link and not report_link.startswith("http"):
                        report_link = BASE_URL + report_link

                if task_name:
                    tasks.append({
                        "name": task_name, "task_id": task_id,
                        "task_link": task_link, "report_link": report_link,
                        "time_remaining": time_remaining, "price": price,
                        "platform": platform, "original_url": original_task_url
                    })
            except Exception:
                continue

        return tasks, "SUCCESS"
    except Exception as e:
        return tasks, f"خطأ: {str(e)}"

def get_task_full_description(session, task_link):
    try:
        r = session.get(task_link, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        task_name = ""
        name_td = soup.find("td", string="Название")
        if name_td:
            name_link = name_td.find_next("td").find("a")
            if name_link:
                task_name = name_link.get_text(strip=True)

        description_html = ""
        description_text = ""
        what_td = soup.find("td", string="Что делать")
        if what_td:
            desc_td = what_td.find_next("td")
            if desc_td:
                desc_div = desc_td.find("div", style=re.compile(r"overflow-wrap"))
                if desc_div:
                    description_html = str(desc_div)
                    description_text = desc_div.get_text(separator="\n", strip=True)

        form_action = ""
        form = soup.find("form", attrs={"name": "message_form"})
        if form:
            form_action = form.get("action", "")

        return {
            "name": task_name,
            "description_html": description_html,
            "description_text": description_text,
            "form_action": form_action
        }
    except Exception:
        return None

def search_text_in_description(description_html, description_text, search_keyword):
    if not search_keyword or not search_keyword.strip():
        return False
    search_lower = search_keyword.strip().lower()
    if description_text and search_lower in description_text.lower():
        return True
    if description_html and search_lower in description_html.lower():
        return True
    return False

def submit_task_report(session, form_action, work_url, proof_msg):
    try:
        if not form_action.startswith("http"):
            form_action = BASE_URL + form_action
        post_data = {
            "request[status]": "completed",
            "request[url]": str(work_url) if work_url else "",
            "request[message]": str(proof_msg)
        }
        r = session.post(form_action, data=post_data, headers=HEADERS, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

# ==========================================
# 💸 نظام السحب
# ==========================================
WITHDRAWAL_URL = "https://forumok.com/billing/withdrawal"
BILLING_PROFILE_URL = "https://forumok.com/profile/billing"

def fetch_withdrawal_page(session):
    """
    جلب صفحة السحب وتحليلها.
    يُرجع dict يحتوي على:
      - status: 'ok' | 'restricted_10days' | 'error'
      - balance: float  (الرصيد المتاح)
      - wallet: str     (عنوان المحفظة الحالي)
      - pay_system: str (نظام الدفع)
      - csrf_token: str
      - user_id: str
    """
    try:
        r = session.get(WITHDRAWAL_URL, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return {"status": "error", "msg": f"فشل تحميل الصفحة ({r.status_code})"}
        soup = BeautifulSoup(r.text, "html.parser")

        # فحص قيد 10 أيام
        notification = soup.find("div", class_="notification")
        if notification and "10" in notification.get_text():
            return {"status": "restricted_10days"}

        # جلب الرصيد من الصفحة الحالية أو من صفحة البحث
        balance_val = 0.0
        page_text = soup.get_text()
        bal_match = re.search(r"Доступно:\s*([\d.,\s]+)\s*р\.", page_text)
        if bal_match:
            raw = bal_match.group(1).strip().replace(" ", "").replace(",", ".")
            try:
                balance_val = float(raw)
            except Exception:
                balance_val = 0.0

        # جلب نظام الدفع + المحفظة من نص الصفحة
        pay_system = ""
        wallet = ""
        ps_td = soup.find("td", string=re.compile(r"Платежная система", re.I))
        if ps_td:
            val_td = ps_td.find_next_sibling("td")
            if val_td:
                pay_system = val_td.get_text(strip=True)
        req_td = soup.find("td", string=re.compile(r"Реквизиты", re.I))
        if req_td:
            val_td = req_td.find_next_sibling("td")
            if val_td:
                wallet = val_td.get_text(strip=True).split("\n")[0].strip()

        # CSRF + user_id
        csrf_input = soup.find("input", {"id": "withdrawal__csrf_token"})
        csrf_token = csrf_input["value"] if csrf_input else ""
        uid_input = soup.find("input", {"id": "withdrawal_user_id"})
        user_id = uid_input["value"] if uid_input else ""

        return {
            "status": "ok",
            "balance": balance_val,
            "wallet": wallet,
            "pay_system": pay_system,
            "csrf_token": csrf_token,
            "user_id": user_id
        }
    except Exception as e:
        return {"status": "error", "msg": str(e)}

def fetch_billing_profile(session):
    """
    جلب صفحة إعدادات البنك (المحفظة + نظام الدفع).
    يُرجع dict: { pay_system, wallet, csrf_token, user_id }
    """
    try:
        r = session.get(BILLING_PROFILE_URL, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        pay_system_select = soup.find("select", {"id": "sf_guard_user_Profile_pay_system"})
        pay_system = ""
        if pay_system_select:
            selected = pay_system_select.find("option", selected=True)
            if selected:
                pay_system = selected.get_text(strip=True)

        wallet_textarea = soup.find("textarea", {"id": "sf_guard_user_Profile_pay_system_requisites"})
        wallet = wallet_textarea.get_text(strip=True) if wallet_textarea else ""

        csrf_input = soup.find("input", {"id": "sf_guard_user__csrf_token"})
        csrf_token = csrf_input["value"] if csrf_input else ""
        uid_input = soup.find("input", {"id": "sf_guard_user_id"})
        user_id = uid_input["value"] if uid_input else ""

        return {
            "pay_system": pay_system,
            "wallet": wallet,
            "csrf_token": csrf_token,
            "user_id": user_id
        }
    except Exception:
        return None

def update_billing_profile(session, pay_system_val, wallet_val, csrf_token, user_id):
    """
    تحديث عنوان المحفظة على الموقع.
    يُرجع True عند النجاح.
    """
    try:
        post_data = {
            "sf_method": "put",
            "sf_guard_user[id]": user_id,
            "sf_guard_user[_csrf_token]": csrf_token,
            "sf_guard_user[Profile][pay_system]": pay_system_val,
            "sf_guard_user[Profile][pay_system_requisites]": wallet_val
        }
        r = session.post(BILLING_PROFILE_URL, data=post_data, headers=HEADERS, timeout=12)
        return r.status_code == 200
    except Exception:
        return False

def get_withdraw_menu(balance=None, wallet=None, pay_system=None):
    """قائمة زر السحب الرئيسية — زر تعديل المحفظة يظهر دائماً"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("💸 تنفيذ سحب الآن", callback_data="withdraw_do"))
    # زر تعديل/إضافة المحفظة يظهر دائماً بغض النظر عن الرصيد أو القيد
    if wallet and wallet.strip() and wallet.strip() != "غير محدد":
        markup.add(types.InlineKeyboardButton("✏️ تعديل عنوان المحفظة", callback_data="withdraw_edit_wallet"))
    else:
        markup.add(types.InlineKeyboardButton("➕ إضافة عنوان المحفظة", callback_data="withdraw_edit_wallet"))
    markup.add(types.InlineKeyboardButton("🔄 تحديث البيانات", callback_data="withdraw_menu"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main"))
    return markup

def get_withdraw_menu_limited(wallet=None):
    """قائمة السحب عند وجود قيد (رصيد منخفض أو قيد 10 أيام) — يظهر زر تعديل المحفظة فقط"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    if wallet and wallet.strip() and wallet.strip() != "غير محدد":
        markup.add(types.InlineKeyboardButton("✏️ تعديل عنوان المحفظة", callback_data="withdraw_edit_wallet"))
    else:
        markup.add(types.InlineKeyboardButton("➕ إضافة عنوان المحفظة", callback_data="withdraw_edit_wallet"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main"))
    return markup

def execute_confirmed_tasks_manually(chat_id, creds):
    session = get_authenticated_session(creds['email'], creds['password'])
    if not session:
        return "❌ فشل تجديد الجلسة.", 0

    tasks, status = extract_confirmed_tasks(session)
    if status != "SUCCESS" or not tasks:
        return f"📋 لا توجد مهام مؤكدة." if status == "SUCCESS" else f"❌ {status}", 0

    templates = cloud_get_auto_tasks(chat_id)
    if not templates:
        return "⚠️ لا توجد البقات. أضف باقة أولاً.", 0

    executed = 0
    results = []
    for task in tasks:
        task_info = get_task_full_description(session, task['task_link'])
        if not task_info:
            continue
        for tmpl in templates:
            if search_text_in_description(task_info['description_html'], task_info['description_text'], tmpl['keyword']):
                success = submit_task_report(session, task_info['form_action'], tmpl.get('work_url', ''), tmpl.get('proof_msg', ''))
                if success:
                    executed += 1
                    results.append(f"✅ {task['name']} | 💰 {task['price']}")
                else:
                    results.append(f"❌ {task['name']} | فشل الإرسال")
                time.sleep(10)
                break

    if executed > 0:
        return f"📊 **تم تنفيذ {executed} مهمة**\n\n" + "\n".join(results[:10]), executed
    else:
        return f"⚠️ لم يتم العثور على مهام تطابق البقات.\n\n📋 البقات المتاحة:\n" + "\n".join([f"🔍 {t['keyword'][:50]}" for t in templates]), 0

# ==========================================
# ترجمة الوقت وفحص الجداول
# ==========================================
def translate_and_parse_duration(duration_text):
    total_minutes = 0
    duration_text = duration_text.strip().lower()
    try:
        number_match = re.search(r"(\d+)", duration_text)
        if not number_match:
            return 120, "2 ساعات"
        number = int(number_match.group(1))

        if "день" in duration_text or "дня" in duration_text or "дней" in duration_text:
            total_minutes = number * 24 * 60
        elif "час" in duration_text or "часа" in duration_text or "часов" in duration_text:
            total_minutes = number * 60
        elif "минут" in duration_text or "минуты" in duration_text or "минуту" in duration_text:
            total_minutes = number
        elif "неделя" in duration_text or "недели" in duration_text or "недель" in duration_text:
            total_minutes = number * 7 * 24 * 60
        else:
            total_minutes = number * 60

        if "день" in duration_text or "дня" in duration_text or "дней" in duration_text:
            translated_text = "1 يوم" if number == 1 else f"{number} أيام" if 2 <= number <= 10 else f"{number} يوم"
        elif "час" in duration_text or "часа" in duration_text or "часов" in duration_text:
            translated_text = "1 ساعة" if number == 1 else f"{number} ساعات" if 2 <= number <= 10 else f"{number} ساعة"
        elif "минут" in duration_text or "минуты" in duration_text or "минуту" in duration_text:
            translated_text = "1 دقيقة" if number == 1 else f"{number} دقائق" if 2 <= number <= 10 else f"{number} دقيقة"
        elif "неделя" in duration_text or "недели" in duration_text or "недель" in duration_text:
            translated_text = "1 أسبوع" if number == 1 else f"{number} أسابيع" if 2 <= number <= 10 else f"{number} أسبوع"
        else:
            translated_text = f"{number} ساعات"
    except Exception:
        return 120, "2 ساعات"
    return total_minutes, translated_text

def fetch_publisher_stats(session):
    stats = {"to_execute": "0", "on_check": "0", "completed": "0", "uncompleted": "0"}
    try:
        r = session.get(STATS_URL, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            page_text = soup.get_text()
            m = re.search(r"Выполнить\s+(\d+)", page_text)
            if m:
                stats["to_execute"] = m.group(1)
            m = re.search(r"На проверке\s+(\d+)", page_text)
            if m:
                stats["on_check"] = m.group(1)
            m = re.search(r"Выполнено\s+(\d+)", page_text)
            if m:
                stats["completed"] = m.group(1)
            m = re.search(r"Невыполненные\s+(\d+)", page_text)
            if m:
                stats["uncompleted"] = m.group(1)
    except Exception:
        pass
    return stats

def extract_task_duration(session, task_page_url):
    try:
        res = session.get(task_page_url, headers=HEADERS, timeout=7)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for td in soup.find_all("td"):
                if "Время на выполнение" in td.get_text():
                    next_td = td.find_next_sibling("td")
                    if next_td:
                        return next_td.get_text(strip=True)
            page_text = soup.get_text()
            time_match = re.search(r"Время на выполнение\s*(.*)", page_text)
            if time_match:
                return time_match.group(1).strip().split("\n")[0]
    except Exception:
        pass
    return "2 часа"

def get_site_data(username, password, chat_id):
    """
    ⚡ نسخة محسّنة وسريعة:
    - تقرأ كل بيانات المهام من صفحة واحدة فقط (orders-search/socio)
    - لا تفتح رابط أي مهمة على حدة أبداً (بدون _fetch_task_details_unified)
    - كل المعلومات (السعر، الوصف، المدة، نوع المهمة، القيود) تُستخرج من
      tooltip content الموجود في نفس الصفحة (نفس أسلوب get_site_data_all_tasks)
    - تطلب فقط: صفحة orders-search/socio + صفحة الإحصائيات (بالتوازي)
    - تُرجع نفس البنية القديمة (balance, stats, tasks) بنفس مفاتيح كل مهمة
      (price, task_page, duration, minutes, description, app_name,
       is_restricted, restrictions) للحفاظ على توافق كل الاستخدامات
      (view_tasks, manual_take, auto_hunt, auto_execute, take_task_via_post...)

    🚫 فرز الصلاحية (خاص بهذه الدالة فقط):
    - يتم استبعاد أي مهمة من tasks_list في الحالتين التاليتين:
        1) الصف من فئة "taken-list" (مأخوذة/منفَّذة من هذا الحساب بالفعل)
           أو "gray-list" (في القائمة الرمادية).
        2) آخر خلية في الصف (icon-send-td) لا تحتوي على
           <a><img alt="take">  → أي لا يوجد زر اصطحاب فعلي = "غير صالحة"
           لهذا الحساب (مكتملة العدد لهذا الحساب / غير مؤهل لها...).
      هذا هو فرز "صالح/غير صالح" الحقيقي كما يعرضه الموقع نفسه — وليس
      مرتبطاً بالقيود الجغرافية (country code)، التي تبقى للعرض فقط.
    - عرض المهام الكاملة (صالحة + غير صالحة معاً) يبقى محصوراً في
      get_site_data_all_tasks (إشعارات الكلية) فقط — بدون أي تغيير عليها.
    """
    import html as html_module

    session = get_authenticated_session(username, password)
    if not session:
        return None, "AUTH_FAILED"
    try:
        # ── طلب واحد للصفحة الرئيسية ──
        r = _safe_get(TARGET_URL, session=session, headers=HEADERS, timeout=12)

        # ── كشف الحظر أو CAPTCHA ──
        page_state = detect_page_state(r.text)
        if page_state == "blocked":
            threading.Thread(target=handle_blocked_account, args=(username,), daemon=True).start()
            return None, "BLOCKED"
        if page_state == "captcha":
            threading.Thread(
                target=handle_captcha_detected,
                args=(username, "أثناء جلب المهام من الموقع"),
                daemon=True
            ).start()
            return None, "CAPTCHA"

        if "Выход" not in r.text:
            return None, "SESSION_EXPIRED"

        soup = BeautifulSoup(r.text, "html.parser")
        page_text = soup.get_text(separator="\n")

        # ── الرصيد (متوفر في نفس الصفحة) ──
        balance = "0.0"
        available_match = re.search(r"Доступно:\s*([\d.,\s]+)\s*р\.", page_text)
        if available_match:
            balance = available_match.group(1).strip()

        # ── جلب الإحصائيات في خيط موازٍ (الطلب الإضافي الوحيد المتبقي) ──
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as stats_executor:
            stats_future = stats_executor.submit(fetch_publisher_stats, session)

            # ══════════════════════════════════════════════
            # تحليل جدول المهام من نفس الصفحة (بدون أي طلب إضافي)
            # ══════════════════════════════════════════════
            PLATFORM_MAP = {
                "youtube":    "YouTube",
                "telegram":   "Telegram",
                "yandex":     "Yandex",
                "google":     "Google",
                "vkontakte":  "VKontakte",
                "vk":         "VKontakte",
                "instagram":  "Instagram",
                "tiktok":     "TikTok",
                "twitter":    "Twitter",
                "facebook":   "Facebook",
                "ok":         "OK",
            }

            tasks_list = []
            tbody = soup.find("tbody", class_="td-order-search")
            rows = tbody.find_all("tr", id=re.compile(r"^tr\d+")) if tbody else []

            for row in rows:
                try:
                    # ── استبعاد المهام المأخوذة مسبقاً (taken-list) أو المخفية (gray-list) ──
                    # taken-list = هذه المهمة أُخذت/نُفِّذت بالفعل من هذا الحساب → غير صالحة لاصطحاب جديد
                    row_classes = row.get("class", []) or []
                    if "taken-list" in row_classes or "gray-list" in row_classes:
                        continue

                    cells = row.find_all("td")
                    if len(cells) < 9:
                        continue

                    # ── 🚫 فرز الصلاحية الحقيقي: زر "اصطحاب" (take) في آخر خلية ──
                    # إذا كانت آخر خلية (icon-send-td) لا تحتوي على
                    # <a><img alt="take">، فهذه المهمة "غير صالحة" لهذا
                    # الحساب (مكتملة/غير مؤهل/لا يمكن اصطحابها مباشرة) — تُستبعد.
                    # هذا هو نفس الفرز الذي يُظهره الموقع نفسه (صالح vs غير صالح).
                    action_cell = cells[-1]
                    take_link = action_cell.find("a", href=True)
                    has_take_btn = (
                        take_link is not None
                        and action_cell.find("img", alt="take") is not None
                    )
                    if not has_take_btn:
                        continue

                    # ── رابط المهمة (رابط الاصطحاب المباشر من آخر خلية) ──
                    take_href = take_link.get("href", "")
                    task_page_url = take_href if take_href.startswith("http") else BASE_URL + take_href
                    if "?ok=1" not in task_page_url:
                        task_page_url += "?ok=1" if "?" not in task_page_url else "&ok=1"

                    # ── السعر ──
                    price_raw = cells[3].get_text(strip=True).replace(",", ".").replace(" ", "")
                    try:
                        real_price = float(price_raw)
                    except ValueError:
                        continue  # بدون سعر صالح = تجاهل (مطابق لسلوك real_price is None)

                    # ── الدولة (للعرض فقط — لا تُستخدم للاستبعاد) ──
                    country_img = cells[4].find("img")
                    country_code = country_img.get("alt", "--") if country_img else "--"

                    # ── استخراج التفاصيل من tooltip content — بدون أي طلب HTTP ──
                    raw_duration = "2 часа"
                    task_desc = ""

                    info_img = cells[2].find("img", class_="cursor-help")
                    if info_img:
                        raw_content = html_module.unescape(info_img.get("content", ""))
                        mini = BeautifulSoup(raw_content, "html.parser")

                        for small in mini.find_all("small"):
                            txt = small.get_text()
                            if "Время на выполнение" in txt:
                                b = small.find("b")
                                if b:
                                    raw_duration = b.get_text(strip=True)

                        parts = []
                        for tag in mini.find_all(["p", "li"]):
                            t = tag.get_text(separator=" ", strip=True)
                            if t:
                                parts.append(t)
                        task_desc = " ".join(parts)

                    task_minutes, arabic_duration = translate_and_parse_duration(raw_duration)

                    # ── المنصة ──
                    plat_img = cells[1].find("img")
                    platform_key = plat_img.get("alt", "").lower().strip() if plat_img else ""
                    app_name = PLATFORM_MAP.get(platform_key, "منصة أخرى")
                    if app_name == "منصة أخرى":
                        # احتياط إضافي: استخراج من الرابط (مطابق للسلوك القديم)
                        for platform in ["yandex", "google", "telegram", "youtube", "vkontakte", "vk"]:
                            if platform in task_page_url.lower():
                                app_name = ("YouTube" if platform == "youtube" else
                                             "Telegram" if platform == "telegram" else
                                             "Yandex" if platform == "yandex" else
                                             "Google" if platform == "google" else "VKontakte")
                                break

                    # ── القيود الجغرافية (للعرض/الإشعارات فقط — لا تستبعد المهمة هنا) ──
                    is_restricted = "غير مقيدة"
                    restrictions_details = ""
                    task_desc_check = task_desc.lower()
                    if country_code not in ("", "--", "---"):
                        is_restricted = "مقيدة"
                        restrictions_details = country_code
                    elif ("россия" in task_desc_check or "russia" in task_desc_check
                          or "только для рф" in task_desc_check or "рф" in task_desc_check):
                        is_restricted = "مقيدة"
                        restrictions_details = "روسيا"
                    elif "гео" in task_desc_check or "страна" in task_desc_check:
                        is_restricted = "مقيدة"
                        restrictions_details = "محددة جغرافيًا"

                    tasks_list.append({
                        "price": f"{real_price:.2f}", "task_page": task_page_url,
                        "duration": arabic_duration, "minutes": task_minutes,
                        "description": task_desc, "app_name": app_name,
                        "is_restricted": is_restricted, "restrictions": restrictions_details
                    })
                except Exception:
                    continue

            # ── نتيجة الإحصائيات ──
            try:
                stats_data = stats_future.result(timeout=8)
            except Exception:
                stats_data = {"to_execute": "0", "on_check": "0", "completed": "0", "uncompleted": "0"}

        user_numbered_tasks[chat_id] = tasks_list
        return {"balance": balance, "stats": stats_data, "tasks": tasks_list}, "SUCCESS"
    except Exception:
        return None, "ERROR"


def get_site_data_all_tasks(username, password, chat_id):
    """
    📢 دالة مخصصة لإشعارات الكلية — نسخة محسّنة:
    - تقرأ كل بيانات المهام من صفحة واحدة فقط (orders-search/socio)
    - لا تفتح رابط أي مهمة على حدة أبداً
    - كل المعلومات مستخرجة من tooltip content في نفس الصفحة
    - أسرع + أأمن + لا تضغط على الحساب
    """
    import html as html_module
    session = get_authenticated_session(username, password)
    if not session:
        return None, "AUTH_FAILED"
    try:
        # ── صفحة واحدة فقط — لا روابط إضافية ──
        r = _safe_get(TARGET_URL, session=session, timeout=12)

        page_state = detect_page_state(r.text)
        if page_state == "blocked":
            threading.Thread(target=handle_blocked_account, args=(username,), daemon=True).start()
            return None, "BLOCKED"
        if page_state == "captcha":
            threading.Thread(target=handle_captcha_detected,
                             args=(username, "إشعارات الكلية"), daemon=True).start()
            return None, "CAPTCHA"
        if "Выход" not in r.text:
            return None, "SESSION_EXPIRED"

        soup = BeautifulSoup(r.text, "html.parser")

        # ── جدول المهام ──
        tbody = soup.find("tbody", class_="td-order-search")
        if not tbody:
            return {"tasks": []}, "SUCCESS"

        rows = tbody.find_all("tr", id=re.compile(r"^tr\d+"))
        if not rows:
            return {"tasks": []}, "SUCCESS"

        PLATFORM_MAP = {
            "youtube":    "YouTube",
            "telegram":   "Telegram",
            "yandex":     "Yandex",
            "google":     "Google",
            "vkontakte":  "VKontakte",
            "vk":         "VKontakte",
            "instagram":  "Instagram",
            "tiktok":     "TikTok",
            "twitter":    "Twitter",
            "facebook":   "Facebook",
            "ok":         "OK",
        }

        tasks_list = []
        for row in rows:
            try:
                cells = row.find_all("td")
                if len(cells) < 9:
                    continue

                # order_id من id الصف
                order_id = re.sub(r"\D", "", row.get("id", ""))
                if not order_id:
                    continue

                # ── المنصة ──
                plat_img = cells[1].find("img")
                platform_key = plat_img.get("alt", "").lower().strip() if plat_img else ""
                app_name = PLATFORM_MAP.get(platform_key, "منصة أخرى")

                # ── رابط الاصطحاب المباشر من خلية العنوان ──
                title_link = cells[2].find("a", href=True)
                task_title = title_link.get("title", "") if title_link else ""
                take_href = title_link.get("href", "") if title_link else ""
                take_url = (take_href if take_href.startswith("http")
                            else BASE_URL + take_href) if take_href else ""

                # ── السعر ──
                price_raw = cells[3].get_text(strip=True).replace(",", ".").replace(" ", "")
                try:
                    price_val = float(price_raw)
                except ValueError:
                    price_val = 0.0

                # ── الدولة ──
                country_img = cells[4].find("img")
                country_code = country_img.get("alt", "--") if country_img else "--"

                # ── مكان مأخوذ / مجموع ──
                taken_text = cells[8].get_text(strip=True)  # مثال: "100 / 500"

                # ── استخراج التفاصيل من tooltip content — بدون أي طلب HTTP ──
                duration_raw = "2 часа"
                description = ""
                task_type = ""
                link_in_desc = ""

                info_img = cells[2].find("img", class_="cursor-help")
                if info_img:
                    raw_content = html_module.unescape(info_img.get("content", ""))
                    mini = BeautifulSoup(raw_content, "html.parser")

                    # نوع المهمة
                    for small in mini.find_all("small"):
                        txt = small.get_text()
                        if "Тип задания" in txt:
                            b = small.find("b")
                            if b: task_type = b.get_text(strip=True)
                        elif "Время на выполнение" in txt:
                            b = small.find("b")
                            if b: duration_raw = b.get_text(strip=True)

                    # الرابط في الوصف (إن وجد)
                    link_p = mini.find("p")
                    if link_p:
                        b_tag = link_p.find("b")
                        if b_tag:
                            link_in_desc = b_tag.get_text(strip=True)

                    # نص الوصف الكامل
                    parts = []
                    for tag in mini.find_all(["p", "li"]):
                        t = tag.get_text(separator=" ", strip=True)
                        if t:
                            parts.append(t)
                    description = " ".join(parts)

                # ── ترجمة المدة ──
                task_minutes, arabic_duration = translate_and_parse_duration(duration_raw)

                # ── تحديد القيود الجغرافية من الوصف ──
                desc_lower = description.lower()
                is_restricted = "غير مقيدة"
                restrictions_details = ""
                if country_code not in ("", "--", "---"):
                    is_restricted = "مقيدة"
                    restrictions_details = country_code
                elif ("россия" in desc_lower or "russia" in desc_lower
                      or "только для рф" in desc_lower or "рф" in desc_lower):
                    is_restricted = "مقيدة"
                    restrictions_details = "روسيا"
                elif "гео" in desc_lower or "страна" in desc_lower:
                    is_restricted = "مقيدة"
                    restrictions_details = "محددة جغرافيًا"

                tasks_list.append({
                    "price":        f"{price_val:.2f}",
                    "task_page":    take_url,   # رابط الاصطحاب المباشر
                    "order_id":     order_id,
                    "title":        task_title,
                    "duration":     arabic_duration,
                    "minutes":      task_minutes,
                    "description":  description,
                    "task_type":    task_type,
                    "link_in_desc": link_in_desc,
                    "app_name":     app_name,
                    "country":      country_code,
                    "taken":        taken_text,
                    "is_restricted": is_restricted,
                    "restrictions": restrictions_details,
                })
            except Exception:
                continue

        return {"tasks": tasks_list}, "SUCCESS"
    except Exception as ex:
        print(f"[ALL-TASKS] خطأ: {ex}")
        return None, "ERROR"


def take_task_via_post(session, task_page_url):
    """
    اصطحاب مهمة مع التحقق الحقيقي من نجاح الاصطحاب.
    يتحقق من صفحة المهام المؤكدة بعد الاصطحاب للتأكد من أن المهمة موجودة فعلاً.
    """
    try:
        # ── استخراج order_id من الرابط للتحقق لاحقاً ──
        order_id_for_verify = None
        id_match = re.search(r"/order[_/](\d+)", task_page_url)
        if not id_match:
            id_match = re.search(r"/(\d+)/?$", task_page_url)
        if id_match:
            order_id_for_verify = id_match.group(1)

        response = session.get(task_page_url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return False

        soup = BeautifulSoup(response.text, "html.parser")

        # ── التحقق المبدئي: هل المهمة متاحة للاصطحاب؟ ──
        # إذا كان الرابط يُعيد توجيه لصفحة مختلفة أو يحتوي رسالة "لا توجد مهام" → مهمة وهمية
        page_text = soup.get_text()
        not_available_signals = [
            "нет заданий", "no tasks", "задание недоступно",
            "order not found", "not found", "404"
        ]
        for signal in not_available_signals:
            if signal in page_text.lower():
                print(f"[TAKE] المهمة غير متاحة: {signal}")
                return False

        form = soup.find("form", action=re.compile(r"batch|order_request"))
        if not form:
            # لا يوجد فورم = لا يوجد زر اصطحاب = المهمة غير موجودة أو مصطحبة سابقاً
            print(f"[TAKE] لا يوجد فورم اصطحاب في الصفحة: {task_page_url}")
            return False

        # ── تجهيز بيانات الفورم وإرسال طلب الاصطحاب ──
        post_action_url = f"{BASE_URL}/order_request_socio/batch"
        if form.get('action'):
            act = form.get('action')
            post_action_url = act if act.startswith("http") else BASE_URL + act

        post_data = {"batch_action": "batchConfirm"}
        for hidden_input in form.find_all("input", type="hidden"):
            if hidden_input.get("name"):
                post_data[hidden_input.get("name")] = hidden_input.get("value", "")

        account_checkboxes = form.find_all("input", class_="batch_checkbox")
        account_ids = [cb.get("value") for cb in account_checkboxes if cb.get("value")]
        if account_ids:
            post_data["ids[]"] = account_ids
        elif form.find("input", name="ids[]"):
            post_data["ids[]"] = [form.find("input", name="ids[]").get("value", "")]
        else:
            # لا يوجد ids → لا شيء يمكن اصطحابه
            print(f"[TAKE] لا يوجد ids في الفورم: {task_page_url}")
            return False

        res = session.post(post_action_url, data=post_data, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return False

        # ── التحقق الحقيقي: هل المهمة ظهرت في المهام المؤكدة؟ ──
        time.sleep(1.5)  # انتظار قصير حتى يُحدَّث السيرفر
        try:
            confirmed_r = session.get(CONFIRMED_URL, headers=HEADERS, timeout=10)
            if confirmed_r.status_code == 200:
                confirmed_soup = BeautifulSoup(confirmed_r.text, "html.parser")
                table = confirmed_soup.find("table", id="publisher-requests")
                if table:
                    rows = table.find_all("tr")
                    if rows and len(rows) > 1:
                        # ── طريقة 1: إذا عندنا order_id نتحقق منه مباشرة ──
                        if order_id_for_verify:
                            table_text = confirmed_r.text
                            if order_id_for_verify in table_text:
                                print(f"[TAKE] ✅ تحقق ناجح بـ order_id={order_id_for_verify}")
                                return True
                            # لم نجد الـ id → اصطحاب فاشل
                            print(f"[TAKE] ❌ order_id={order_id_for_verify} غير موجود في المؤكدة")
                            return False
                        else:
                            # ── طريقة 2: نتحقق من وجود صف جديد بمقارنة العدد ──
                            # إذا وصلنا هنا بدون order_id نعتمد على وجود صفوف فعلية
                            data_rows = [r for r in rows if r.find_all("td")]
                            if data_rows:
                                print(f"[TAKE] ✅ يوجد {len(data_rows)} مهمة في المؤكدة — اعتبار الاصطحاب ناجحاً")
                                return True
                            print(f"[TAKE] ❌ جدول المؤكدة فارغ بعد الاصطحاب")
                            return False
                    else:
                        print(f"[TAKE] ❌ جدول المؤكدة فارغ بعد الاصطحاب")
                        return False
                else:
                    # لا يوجد جدول مهام مؤكدة → الاصطحاب لم ينجح
                    print(f"[TAKE] ❌ لا يوجد جدول publisher-requests في صفحة المؤكدة")
                    return False
        except Exception as verify_err:
            print(f"[TAKE] تحذير: فشل التحقق من المؤكدة: {verify_err}")
            # في حالة فشل التحقق فقط → لا نُرسل إشعاراً كاذباً
            return False

    except Exception as e:
        print(f"[TAKE] خطأ عام: {e}")
        pass
    return False

