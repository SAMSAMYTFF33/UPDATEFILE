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
from cryptography.fernet import Fernet

# ==========================================
# 🔐 البيانات الحساسة — مشفّرة بـ Fernet
# هذا الملف فقط (main_local.py) يبقى محلياً
# على الاستضافة ولا يُرفع إلى GitHub أبداً.
# ⚠️ إذا جدّدت أي مفتاح، شفّره من جديد بنفس _KEY وضعه هنا.
# ==========================================

# مفتاح التشفير
_KEY = b"Yatw_mc_j5ozxfkKmwoo786tIVVy65rXhq69tnSpBHs="

# البيانات الحساسة المشفّرة
_ENC_TELEGRAM_TOKEN        = "gAAAAABqMT5hYe0JDiRpI6ktgrUf95PEV7D54OSZ2uyAYCkmV4EXjDGoA7tL3laKIGbTwpB51jH1jpRqy06MRpgbUVL1_iMOD0DCDfy8ovz-wVklIU9RZZC6HbBYIY7utznc9lSjrqfy"
_ENC_GEMINI_API_KEY        = "gAAAAABqMT5hM4rijHUkAjisR1iSvf5CNBz2IT8KUggDNF8kNKia8v2lHWSJ7c2qUG1gnI3iWndB_FY-MLivPqcxfQvaSzRE0PBP7PCX78O-zRjkAO11yaG79R-lKbvtQKMShNOmBFkNTpn7NH55TzriOYfh_Nc8lw=="
_ENC_CAPTCHA_ALERT_CHAT_ID = "gAAAAABqMT5hNmcfflMAg4RmjI45TDgT_pog1eRYcRzfUUxrp398VT6QVHOyXkEFCwW5H-sbsoSWKNdHkMrtwkzO0iWKAdstmw=="
_ENC_PROXY_USER            = "gAAAAABqMT5hb8_NGbFWCRfGlKezVEldvPwkhZC69xFcmsDRwnntJeqhH8bca-vbsohVBq3S6EXkEa_Xl-EPbDpr62AEKh1jjQ=="
_ENC_PROXY_PASS            = "gAAAAABqMT5hFh6i1hn437pWFZYKuUK28yhuRqGiEiVbKV6Kg2IJo3Pv4jsQMU2_UlYnCzC9ILnGIftEmVSzkxxjCEPd1865Rw=="
_ENC_SUPABASE_URL          = "gAAAAABqMT5hwEtE9bZ9_qkkZsaz3N9vHVlIP86Enka8eDv0Xa2dFcNljh9x4nJXSZqbbLCohvBKHlv43KARP7QD0x-xZHFzi-sFh7CVrRiiNWuwk3-8CmiZMz2gnCm1ZW7IdJK7F0IE"
_ENC_SUPABASE_KEY          = "gAAAAABqMT5hPfHHnmQmQZ2b7-T0tieqnYDpktsLz4cCiFi6QzKZNNNzP7RkebWXyu9g8q7bUEgAsYvA-FsG3ZmVm4xT9pq_d70W2LZIYqig28ZwCGXvHHc1Z9I8wfnQrMN6U1qP7F6G"

# فك التشفير وتحميل المتغيرات البيئية
_f = Fernet(_KEY)
os.environ["TELEGRAM_TOKEN"]        = _f.decrypt(_ENC_TELEGRAM_TOKEN.encode()).decode()
os.environ["GEMINI_API_KEY"]        = _f.decrypt(_ENC_GEMINI_API_KEY.encode()).decode()
os.environ["CAPTCHA_ALERT_CHAT_ID"] = _f.decrypt(_ENC_CAPTCHA_ALERT_CHAT_ID.encode()).decode()
os.environ["PROXY_USER"]            = _f.decrypt(_ENC_PROXY_USER.encode()).decode()
os.environ["PROXY_PASS"]            = _f.decrypt(_ENC_PROXY_PASS.encode()).decode()
os.environ["SUPABASE_URL"]          = _f.decrypt(_ENC_SUPABASE_URL.encode()).decode()
os.environ["SUPABASE_KEY"]          = _f.decrypt(_ENC_SUPABASE_KEY.encode()).decode()
del _f, _KEY  # حذف المفتاح من الذاكرة بعد الاستخدام

# ==========================================
# 🔗 تحميل الملفات المرتبطة من GitHub تلقائياً
# (يكفي رفع هذا الملف فقط على الاستضافة — وهو يجلب باقي
#  الملفات من المستودع عند كل تشغيل)
# ==========================================
GITHUB_USER   = "SAMSAMYTFF33"
GITHUB_REPO   = "UPDATEFILE"
GITHUB_BRANCH = "main"
_GITHUB_RAW_BASE  = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/"
_GITHUB_API_TREE  = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/git/trees/{GITHUB_BRANCH}?recursive=1"
_THIS_DIR         = os.path.dirname(os.path.abspath(__file__))

# ── الملفات الثابتة كاحتياط إذا فشل GitHub API ──
_FALLBACK_MODULES = ["config_shared.py", "proxies.py", "site_actions.py", "handlers.py"]

# ── الملفات المحمية التي لا تُحمَّل أبداً من GitHub ──
_EXCLUDED_FILES   = {"main_local.py", "main.py"}

def _fetch_github_file_list() -> list:
    """
    يجلب قائمة ملفات .py الموجودة في جذر المستودع عبر GitHub Trees API.
    - يكتشف الملفات الجديدة تلقائياً دون الحاجة لتعديل أي قائمة
    - يستبعد الملفات المحمية (_EXCLUDED_FILES)
    - يعود إلى _FALLBACK_MODULES عند فشل الاتصال
    """
    try:
        resp = requests.get(
            _GITHUB_API_TREE,
            timeout=15,
            headers={"Accept": "application/vnd.github+json"}
        )
        if resp.status_code != 200:
            print(f"⚠️ GitHub API: HTTP {resp.status_code} — استخدام القائمة الاحتياطية")
            return list(_FALLBACK_MODULES)

        tree = resp.json().get("tree", [])
        files = [
            item["path"]
            for item in tree
            if item["type"] == "blob"
            and item["path"].endswith(".py")
            and "/" not in item["path"]
            and item["path"] not in _EXCLUDED_FILES
        ]

        if not files:
            print("⚠️ GitHub API: لا توجد ملفات .py — استخدام القائمة الاحتياطية")
            return list(_FALLBACK_MODULES)

        print(f"📋 GitHub API: تم اكتشاف {len(files)} ملف: {files}")
        return files

    except Exception as e:
        print(f"⚠️ خطأ في GitHub API: {e} — استخدام القائمة الاحتياطية")
        return list(_FALLBACK_MODULES)

# ── جلب القائمة الديناميكية عند بدء التشغيل ──
_REQUIRED_MODULES = _fetch_github_file_list()

def _download_dependencies():
    for _fname in _REQUIRED_MODULES:
        _local_path = os.path.join(_THIS_DIR, _fname)
        try:
            _resp = requests.get(_GITHUB_RAW_BASE + _fname, timeout=20)
            if _resp.status_code == 200:
                with open(_local_path, "w", encoding="utf-8") as _f:
                    _f.write(_resp.text)
                print(f"✅ تم تحميل {_fname} من GitHub")
            else:
                print(f"⚠️ فشل تحميل {_fname} (HTTP {_resp.status_code}) — سيُستخدم النسخة المحلية إن وُجدت")
        except Exception as _e:
            print(f"⚠️ خطأ في تحميل {_fname}: {_e} — سيُستخدم النسخة المحلية إن وُجدت")

_download_dependencies()

# ==========================================
# 🔄 دالة التحديث التلقائي — main_local.py فقط (لا تُرفع على GitHub)
# يتم تفعيلها عند إرسال المفتاح "BOT2026" من أي مستخدم
# ==========================================
UPDATE_SECRET_KEY = "BOT2026"

def _md5_of_text(text: str) -> str:
    """حساب MD5 لنص معين (بعد توحيد نهايات الأسطر)"""
    import hashlib
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()

def _md5_of_file(path: str) -> str:
    """حساب MD5 لملف محلي — يُعيد سلسلة فارغة إذا لم يوجد الملف"""
    import hashlib
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return _md5_of_text(content)
    except Exception:
        return ""

def perform_self_update(chat_id=None):
    """
    يقارن كل ملف محلي مع نسخته على GitHub عبر MD5.
    - إذا تطابقا  → يتخطاه (لا تعديل)
    - إذا اختلفا  → يحدّثه ويحتفظ بنسخة .bak
    - إذا لم يوجد محلياً → يحمّله مباشرة

    يُعيد (True, رسالة_ملخص) أو (False, رسالة_خطأ)
    """
    import hashlib

    updated   = []   # ملفات تم تحديثها
    skipped   = []   # ملفات لم تتغير
    failed    = []   # ملفات فشل تحميلها
    not_found = []   # ملفات غير موجودة محلياً وتم تحميلها

    def _tg(text):
        if chat_id:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_TOKEN', '')}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                    timeout=10
                )
            except Exception:
                pass

    # ── جلب القائمة الحديثة من GitHub قبل المقارنة (يكتشف الملفات الجديدة) ──
    current_modules = _fetch_github_file_list()
    _tg(f"🔍 *جاري فحص {len(current_modules)} ملف ومقارنتها مع GitHub...*")

    for fname in current_modules:
        local_path  = os.path.join(_THIS_DIR, fname)
        github_url  = _GITHUB_RAW_BASE + fname

        try:
            # ── 1: جلب المحتوى من GitHub ──
            resp = requests.get(github_url, timeout=20)
            if resp.status_code != 200:
                failed.append(f"⚠️ `{fname}` — HTTP {resp.status_code}")
                print(f"[UPDATE] ⚠️ {fname} — HTTP {resp.status_code}")
                continue

            github_content  = resp.text
            github_md5      = _md5_of_text(github_content)

            # ── 2: حساب MD5 المحلي ──
            local_md5       = _md5_of_file(local_path)
            file_exists     = os.path.exists(local_path)

            # ── 3: المقارنة ──
            if file_exists and local_md5 == github_md5:
                # لا يوجد تغيير — تخطّ
                skipped.append(f"🟰 `{fname}`")
                print(f"[UPDATE] 🟰 {fname} — لا تغيير (MD5 متطابق)")
                continue

            # ── 4: يوجد تغيير أو ملف جديد → احتفظ بنسخة احتياطية ثم اكتب ──
            if file_exists:
                backup_path = local_path + ".bak"
                try:
                    with open(local_path, "r", encoding="utf-8") as _f:
                        old_content = _f.read()
                    with open(backup_path, "w", encoding="utf-8") as _f:
                        _f.write(old_content)
                except Exception as bak_err:
                    print(f"[UPDATE] تحذير: فشل حفظ نسخة .bak لـ {fname}: {bak_err}")

            with open(local_path, "w", encoding="utf-8") as wf:
                wf.write(github_content)

            if file_exists:
                updated.append(f"✅ `{fname}` — تم التحديث")
                print(f"[UPDATE] ✅ {fname} — محدَّث (MD5 مختلف)")
            else:
                not_found.append(f"🆕 `{fname}` — تم تحميله (لم يكن موجوداً)")
                print(f"[UPDATE] 🆕 {fname} — ملف جديد تم تحميله")

        except Exception as e:
            failed.append(f"❌ `{fname}`: {e}")
            print(f"[UPDATE] ❌ {fname}: {e}")

    # ── 5: بناء الرسالة النهائية ──
    lines = []

    if updated:
        lines.append("*📦 ملفات تم تحديثها:*")
        lines.extend(updated)

    if not_found:
        lines.append("\n*🆕 ملفات جديدة تم تحميلها:*")
        lines.extend(not_found)

    if skipped:
        lines.append("\n*🟰 ملفات بدون تغيير:*")
        lines.extend(skipped)

    if failed:
        lines.append("\n*⚠️ ملفات فشلت:*")
        lines.extend(failed)

    total_changed = len(updated) + len(not_found)
    all_ok        = len(failed) == 0

    if total_changed == 0 and all_ok:
        header = "✅ *جميع الملفات محدَّثة بالفعل — لا يوجد أي تغيير.*"
    elif all_ok:
        header = f"✅ *اكتمل التحديث بنجاح!* ({total_changed} ملف تم تحديثه)\n⚠️ أعد تشغيل البوت لتطبيق التغييرات."
    else:
        header = f"⚠️ *اكتمل التحديث مع بعض الأخطاء* ({total_changed} ملف تم تحديثه)"

    summary = header + "\n\n" + "\n".join(lines)
    # لا نُرسِل هنا — الإرسال يتم في _run_update فقط لتجنب التكرار
    return all_ok, summary


def handle_update_key(message):
    """
    يُستدعى من handler الرسائل النصية.
    يتحقق إذا كان النص هو مفتاح التحديث ويُنفّذ العملية.
    يُعيد True إذا عالج الرسالة، False إذا لم تكن مفتاح التحديث.
    """
    if not hasattr(message, 'text') or not message.text:
        return False
    if message.text.strip() != UPDATE_SECRET_KEY:
        return False

    chat_id = message.chat.id

    # ── إرسال رسالة "جاري التحديث" فورًا ──
    try:
        from telebot import types as _types
        wait_msg = None
        try:
            wait_msg = bot.send_message(chat_id, "🔄 *جاري تحديث الملفات من GitHub، يرجى الانتظار...*", parse_mode="Markdown")
        except Exception:
            pass

        # ── تشغيل التحديث في خيط منفصل لعدم تجميد البوت ──
        def _run_update():
            ok, msg = perform_self_update(chat_id=None)  # بدون إرسال داخلي
            # حذف رسالة "جاري التحديث..."
            try:
                if wait_msg:
                    bot.delete_message(chat_id, wait_msg.message_id)
            except Exception:
                pass
            # إرسال النتيجة النهائية مرة واحدة فقط
            try:
                bot.send_message(chat_id, msg, parse_mode="Markdown")
            except Exception as send_err:
                print(f"[UPDATE] فشل إرسال النتيجة: {send_err}")

        def _run_update_and_repatch():
            _run_update()
            # ── إعادة تطبيق الـ patch بعد التحديث لضمان استمرار البوت ──
            try:
                import importlib
                import handlers as _hmod
                importlib.reload(_hmod)
                _hmod._handle_message_inner = _patched_handle_message_inner
                print("[UPDATE] ✅ تم إعادة تطبيق patch بعد التحديث")
            except Exception as patch_err:
                print(f"[UPDATE] ⚠️ فشل إعادة الـ patch: {patch_err}")

        threading.Thread(target=_run_update_and_repatch, daemon=True).start()

    except Exception as e:
        try:
            bot.send_message(chat_id, f"❌ خطأ أثناء التحديث: {e}")
        except Exception:
            pass

    return True

# ==========================================

from config_shared import *
from proxies import *
from site_actions import *
from handlers import *

# ==========================================
# 🔌 حقن مفتاح التحديث في معالج الرسائل
# نحتفظ بالدالة الأصلية ونلفّها — بدون تعديل handlers.py
# ==========================================
_original_handle_message_inner = _handle_message_inner  # الدالة الأصلية من handlers.py

def _patched_handle_message_inner(message):
    """
    نسخة ملفوفة من _handle_message_inner:
    - إذا كانت الرسالة "BOT2026"  → تحديث تلقائي ثم توقف
    - في غير ذلك               → المسار الطبيعي كالمعتاد
    """
    if handle_update_key(message):
        return
    _original_handle_message_inner(message)

# ── استبدال المرجع داخل وحدة handlers حتى يستخدمها handle_bot_logic ──
import handlers as _handlers_module
_handlers_module._handle_message_inner = _patched_handle_message_inner
# ==========================================

# ==========================================
# 🖥️ السيرفر المساعد
# ==========================================
class KeepAliveServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bot Running".encode("utf-8"))

    def log_message(self, format, *args):
        pass

def run_uptime_server():
    port = int(os.environ.get("PORT", 10000))
    httpd = HTTPServer(('', port), KeepAliveServer)
    httpd.serve_forever()

def preload_all_user_settings():
    """
    تحميل بيانات جميع المستخدمين من السحابة عند بدء التشغيل.
    - يقرأ الحسابات الرئيسية من users_accounts
    - يقرأ الحسابات المتعددة من multi_accounts (السحابي — لا تضيع عند إعادة التشغيل)
    - يجهّز البروكسي والجلسة لكل حساب في الخلفية
    """
    try:
        # ── 1: تحميل الحسابات الرئيسية من users_accounts ──
        response = requests.get(DB_API_URL, headers=DB_HEADERS, timeout=10)
        if response.status_code == 200:
            all_accounts = response.json()
            accounts_to_prepare = []
            for account in all_accounts:
                chat_id = account['chat_id']
                if account.get('username') and account.get('password'):
                    user_data_store[chat_id] = {
                        'email': account['username'],
                        'password': account['password']
                    }
                    accounts_to_prepare.append((account['username'], account['password']))
                notify_status[chat_id] = account.get('notify_status', False)
                notify_interval[chat_id] = account.get('notify_interval', 10)
                auto_hunt_status[chat_id] = account.get('auto_hunt_status', False)
                all_notify_status[chat_id] = account.get('all_notify_status', False)
                hunt_mode[chat_id] = account.get('hunt_mode', 'GTE')
                auto_execute_status[chat_id] = account.get('auto_execute_status', False)
                auto_execute_interval[chat_id] = account.get('auto_execute_interval', 5)
                print(f"✅ {chat_id}: إشعارات={notify_status[chat_id]}, اصطحاب={auto_hunt_status[chat_id]}")

            print(f"🎉 تم تحميل {len(all_accounts)} مستخدم من users_accounts")

        # ── 2: تحميل الحسابات المتعددة من multi_accounts (السحابي) ──
        print("☁️ جلب الحسابات المتعددة من Supabase...")
        all_multi = cloud_load_all_multi_accounts()  # يملأ الكاش أيضاً
        total_multi = sum(len(v) for v in all_multi.values())
        print(f"📦 تم جلب {total_multi} حساب متعدد لـ {len(all_multi)} مستخدم")

        # ── 3: تسجيل جميع الحسابات في active_accounts ──
        seen_emails = set()
        for cid, saved_list in all_multi.items():
            for acc in saved_list:
                register_account_in_active(cid, acc['email'], acc['password'])
                e = acc['email'].lower().strip()
                # مزامنة إعدادات الحساب الرئيسي
                if user_data_store.get(cid, {}).get('email', '').lower() == e:
                    sync_chat_settings_to_email(cid, acc['email'])
                else:
                    acct_notify_status.setdefault(e, False)
                    acct_all_notify_status.setdefault(e, False)
                    acct_notify_interval.setdefault(e, 10)
                    acct_auto_hunt_status.setdefault(e, False)
                    acct_hunt_mode.setdefault(e, 'GTE')
                    acct_auto_execute_status.setdefault(e, False)
                    acct_auto_execute_interval.setdefault(e, 5)

        print(f"🔄 الحسابات النشطة: {sum(len(v) for v in active_accounts.values())} حساب")

        # ── 4: تجهيز الجلسات في الخلفية بتأخير تدريجي ──
        # التأخير يوزع الضغط على الخادم بدل إطلاق كل الخيوط دفعة واحدة
        all_accounts_to_prepare = []
        accounts_to_prepare_set = {e.lower() for e, _ in accounts_to_prepare}
        all_accounts_to_prepare.extend(accounts_to_prepare)

        for cid, saved_list in all_multi.items():
            for acc in saved_list:
                e_lower = acc['email'].lower()
                if e_lower not in accounts_to_prepare_set:
                    accounts_to_prepare_set.add(e_lower)
                    all_accounts_to_prepare.append((acc['email'], acc['password']))

        def _staggered_prepare(accounts_list):
            """تجهيز الجلسات بتأخير 3 ثواني بين كل حساب"""
            for i, (email, password) in enumerate(accounts_list):
                if i > 0:
                    time.sleep(3)  # 3 ثواني بين كل حساب
                threading.Thread(
                    target=_prepare_session_with_proxy,
                    args=(email, password),
                    daemon=True
                ).start()

        threading.Thread(target=_staggered_prepare, args=(all_accounts_to_prepare,), daemon=True).start()

    except Exception as e:
        print(f"❌ خطأ في التحميل: {e}")

# ==========================================
# ==========================================
# 📢 إشعار التوقف والاسترداد
# ==========================================
import traceback
import sys

OWNER_CHAT_ID = CAPTCHA_ALERT_CHAT_ID  # يُرسل الإشعار لنفس chat_id المضبوط أعلى

def send_crash_alert(reason: str):
    """إرسال رسالة تيليغرام عند توقف البوت"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = (
        f"🚨 *توقف البوت* 🚨\n"
        f"🕐 الوقت: `{now}`\n"
        f"❌ السبب:\n```\n{reason[:3000]}\n```"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": OWNER_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception as e:
        print(f"[ALERT] فشل إرسال إشعار التوقف: {e}")

def send_restart_alert():
    """إشعار عند إعادة التشغيل الناجحة"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = f"✅ *البوت يعمل مجدداً*\n🕐 وقت الاسترداد: `{now}`"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": OWNER_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception:
        pass

def watchdog_thread():
    """مراقب الخيوط — يُعيد تشغيل global_background_worker إذا مات"""
    global t_worker
    while True:
        time.sleep(60)
        if not t_worker.is_alive():
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"[WATCHDOG] {now} — background_worker مات، إعادة تشغيل...")
            send_crash_alert("background_worker توقف بشكل غير متوقع — تمت إعادة تشغيله تلقائياً")
            t_worker = threading.Thread(target=global_background_worker, daemon=True)
            t_worker.start()

# ==========================================
# 🚀 نقطة الانطلاق
# ==========================================
if __name__ == "__main__":
    print("🚀 تشغيل نظام إدارة البروكسيات المتكامل...")

    # ── خيط DB المركزي (يعالج كل طلبات الحفظ بدل خيط لكل عملية) ──
    _db_worker_thread2 = threading.Thread(target=_db_save_worker, daemon=True)
    _db_worker_thread2.start()

    # خيط التشغيل الخلفي
    t_worker = threading.Thread(target=global_background_worker, daemon=True)
    t_worker.start()

    # خيط السيرفر المساعد
    t_server = threading.Thread(target=run_uptime_server, daemon=True)
    t_server.start()

    # خيط المراقب
    t_watchdog = threading.Thread(target=watchdog_thread, daemon=True)
    t_watchdog.start()

    # تحميل بيانات المستخدمين
    preload_all_user_settings()

    # تحميل البروكسيات للحسابات النشطة فور التشغيل
    print("🌐 بدء تحميل البروكسيات الديناميكية للحسابات النشطة...")
    threading.Thread(target=refresh_dynamic_proxies, daemon=True).start()

    # تعبئة المخزن الاحتياطي الذكي فور التشغيل
    print("🧠 بدء تعبئة المخزن الاحتياطي للحسابات القادمة...")
    threading.Thread(target=_fill_reserve_pool_worker, daemon=True).start()

    print("✅ البوت يعمل الآن...")
    consecutive_errors = 0

    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                restart_on_change=False,
                none_stop=True,
                interval=0,
                allowed_updates=None
            )
            # إذا خرج infinity_polling بدون استثناء
            consecutive_errors = 0

        except KeyboardInterrupt:
            send_crash_alert("تم إيقاف البوت يدوياً (KeyboardInterrupt)")
            sys.exit(0)

        except Exception as _poll_err:
            consecutive_errors += 1
            error_details = traceback.format_exc()
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"[POLLING] {now_str} — خطأ #{consecutive_errors}: {_poll_err}")

            # إرسال إشعار تيليغرام بالخطأ
            send_crash_alert(f"خطأ في infinity_polling (#{consecutive_errors}):\n{error_details}")

            # انتظار تصاعدي حتى 60 ثانية
            wait_time = min(5 * consecutive_errors, 60)
            print(f"[POLLING] إعادة المحاولة خلال {wait_time} ثانية...")
            time.sleep(wait_time)

            # إشعار عند الاسترداد الناجح