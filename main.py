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

# ==========================================
# 🔗 تحميل الملفات المرتبطة من GitHub تلقائياً
# (يكفي رفع هذا الملف فقط على الاستضافة — وهو يجلب باقي
#  الملفات من المستودع عند كل تشغيل)
# ==========================================
GITHUB_USER   = "SAMSAMYTFF33"
GITHUB_REPO   = "UPDATEFILE"
GITHUB_BRANCH = "main"
_GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/"
_REQUIRED_MODULES = ["config_shared.py", "proxies.py", "site_actions.py", "handlers.py"]
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

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

from config_shared import *
from proxies import *
from site_actions import *
from handlers import *

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
