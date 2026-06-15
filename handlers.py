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
from site_actions import *

# ==========================================
# 🔥 الواجهات الرسومية
# ==========================================
def get_auth_menu(chat_id=None):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if chat_id:
        saved_accounts = get_saved_multi_accounts(chat_id)
        for i, acc in enumerate(saved_accounts, 1):
            email = acc['email']
            label = email.split('@')[0]
            markup.add(types.InlineKeyboardButton(f"⚡ الدخول المباشر: الحساب {i} ({label})", callback_data=f"switch_acc_{i-1}"))
    markup.add(types.InlineKeyboardButton("🔐 تسجيل الدخول بحساب جديد", callback_data="login_start"))
    return markup

def get_main_menu_text() -> str:
    """نص رسالة القائمة الرئيسية مع العد التنازلي"""
    countdown = get_countdown_text()
    return f"🏠 **القائمة الرئيسية**  {countdown}\nــــــــــــــــــ"

def get_main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)

    user_label = "غير محدد"
    if chat_id in user_data_store:
        email = user_data_store[chat_id].get('email', '')
        if "@" in email:
            user_label = email.split('@')[0]

    markup.add(types.InlineKeyboardButton(f"👤 الحساب الحالي: {user_label} 🔄", callback_data="switch_account_menu"))

    btn1 = types.InlineKeyboardButton("📋 عرض المهام المتاحة وتحديثها", callback_data="view_tasks")
    btn2 = types.InlineKeyboardButton("🎯 تصيد المهام (إشعارات/اصطحاب)", callback_data="hunt_menu")
    btn3 = types.InlineKeyboardButton("✅ تنفيذ المهام (البقات والأتمتة)", callback_data="exec_menu")
    btn4 = types.InlineKeyboardButton("🌐 حالة البروكسي الحالي", callback_data="proxy_status")
    btn_withdraw = types.InlineKeyboardButton("💸 سحب الرصيد", callback_data="withdraw_menu")
    btn5 = types.InlineKeyboardButton("🚪 تسجيل الخروج من الحساب الحالي", callback_data="logout")

    markup.add(btn1, btn2, btn3, btn4, btn_withdraw, btn5)
    return markup

def get_switch_account_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    saved_accounts = get_saved_multi_accounts(chat_id)
    current_email = user_data_store.get(chat_id, {}).get('email', '').lower().strip()
    # الحسابات المُسجَّل خروجها لهذا المستخدم
    with logged_out_lock:
        lo_set = set(logged_out_accounts.get(chat_id, set()))
    for i, acc in enumerate(saved_accounts, 1):
        email = acc['email']
        label = email.split('@')[0]
        e = email.lower().strip()
        is_logged_out = e in lo_set
        is_active_display = (e == current_email)

        if is_active_display:
            # الحساب النشط حالياً في الواجهة
            status_icon = "✅"
        elif is_logged_out:
            # جلسته منتهية (تسجيل خروج حقيقي)
            status_icon = "💤"
        else:
            # حساب نشط في الخلفية (تبديل فقط)
            hunt_on = acct_auto_hunt_status.get(e, False)
            status_icon = "⚡" if hunt_on else "🔘"

        markup.add(types.InlineKeyboardButton(
            f"{status_icon} الحساب {i}: {label}",
            callback_data=f"switch_acc_{i-1}"
        ))
        # ملاحظة: أزرار البصمة مخفية من القائمة لكن وظيفتها محفوظة (show_fp_{i-1})
    markup.add(types.InlineKeyboardButton("➕ إضافة حساب جديد", callback_data="add_new_account"))
    markup.add(types.InlineKeyboardButton("🗑️ حذف حساب", callback_data="delete_account_start"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main"))
    return markup

def get_hunting_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("🔔 إشعارات دورية", callback_data="notif_menu")
    btn2 = types.InlineKeyboardButton("⚡ اصطحاب للعمل", callback_data="take_work_menu")
    btn3 = types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main")
    markup.add(btn1, btn2)
    markup.add(btn3)
    return markup

def get_notifications_config_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    is_active = notify_status.get(chat_id, False)
    status_icon = "🟢" if is_active else "🔴"
    is_all_active = all_notify_status.get(chat_id, False)
    all_status_icon = "🟢" if is_all_active else "🔴"

    btn1 = types.InlineKeyboardButton("⚙️ تخصيص فترة التنبيه", callback_data="custom_notify")
    btn2 = types.InlineKeyboardButton(f"إشعارات دورية {status_icon}", callback_data="toggle_notify")
    btn_all = types.InlineKeyboardButton(f"إشعارات كلية {all_status_icon}", callback_data="toggle_all_notify")
    btn3 = types.InlineKeyboardButton("15 دقيقة", callback_data="set_notify_15")
    btn4 = types.InlineKeyboardButton("10 دقائق", callback_data="set_notify_10")
    btn5 = types.InlineKeyboardButton("🔙 رجوع", callback_data="back_hunt")

    markup.add(btn1, btn2)
    markup.add(btn_all)
    markup.add(btn3, btn4)
    markup.add(btn5)
    return markup

def get_take_work_menu(chat_id, email=""):
    markup = types.InlineKeyboardMarkup(row_width=1)
    current_mode = hunt_mode.get(chat_id, "GTE")
    is_active = auto_hunt_status.get(chat_id, False)
    icon_gt = "🟢" if (is_active and current_mode == "GT") else "🔴"
    icon_gte = "🟢" if (is_active and current_mode == "GTE") else "🔴"
    btn1 = types.InlineKeyboardButton(f"تفعيل > 2 ساعات قطعاً {icon_gt}", callback_data="toggle_gt")
    btn2 = types.InlineKeyboardButton(f"تفعيل >= 2 ساعات {icon_gte}", callback_data="toggle_gte")
    markup.add(btn1, btn2)
    btn3 = types.InlineKeyboardButton("👆 اصطحاب يدوي", callback_data="manual_take")
    btn4 = types.InlineKeyboardButton("🔙 رجوع", callback_data="back_hunt")
    markup.add(btn3, btn4)
    return markup

def get_task_execution_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    is_active = auto_execute_status.get(chat_id, False)
    if is_active:
        status_text = "🟢 تشغيل"
        status_callback = "exec_auto_off"
    else:
        status_text = "🔴 إيقاف"
        status_callback = "exec_auto_on"
    btn_status = types.InlineKeyboardButton(status_text, callback_data=status_callback)
    btn_add = types.InlineKeyboardButton("➕ إضافة الباقة", callback_data="exec_add_template")
    btn_browse = types.InlineKeyboardButton("📂 البقات", callback_data="exec_browse_templates")
    btn_share = types.InlineKeyboardButton("📧 مشاركة", callback_data="exec_share_by_chat_id")
    btn_manual = types.InlineKeyboardButton("⚡ تنفيذ يدوي", callback_data="exec_manual_now")
    current_interval = auto_execute_interval.get(chat_id, 5)
    btn_interval = types.InlineKeyboardButton(f"⏱️ {current_interval} دقيقة", callback_data="exec_set_interval")
    btn_back = types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main")
    markup.add(btn_status, btn_add, btn_browse)
    markup.add(btn_share, btn_manual, btn_interval)
    markup.add(btn_back)
    return markup

def get_templates_browse_menu(chat_id):
    templates = cloud_get_auto_tasks(chat_id)
    if not templates:
        return None
    markup = types.InlineKeyboardMarkup(row_width=1)
    for tmpl in templates:
        short_keyword = tmpl['keyword'][:30] + "..." if len(tmpl['keyword']) > 30 else tmpl['keyword']
        markup.add(types.InlineKeyboardButton(f"📌 {short_keyword}", callback_data=f"exec_view_{tmpl['id']}"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="exec_back_to_main"))
    return markup

def get_template_edit_menu(template_id, keyword, work_url, proof_msg):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✏️ تعديل كلمة البحث", callback_data=f"exec_edit_keyword_{template_id}"),
        types.InlineKeyboardButton("🔗 تعديل رابط العمل", callback_data=f"exec_edit_url_{template_id}")
    )
    markup.add(
        types.InlineKeyboardButton("📝 تعديل نص الإثبات", callback_data=f"exec_edit_proof_{template_id}"),
        types.InlineKeyboardButton("🗑️ حذف الباقة", callback_data=f"exec_delete_{template_id}")
    )
    markup.add(types.InlineKeyboardButton("🔙 رجوع للقوائم", callback_data="exec_browse_templates"))
    return markup


# ==========================================
# 🔄 الخيط الخلفي الرئيسي (متعدد الحسابات)
# ==========================================
# مخازن الحالة الداخلية للخيط — مفتاحها (chat_id, email)
_bg_last_notify = {}
_bg_last_hunt = {}
_bg_last_exec = {}
_bg_last_take = {}   # (chat_id, email) -> timestamp

def _send_all_notify_for_account(chat_id, email, password, settings, cancel_event):
    """
    إرسال إشعارات الكلية في خيط منفصل حتى لا يُجمّد الخيط الخلفي الرئيسي.
    يُستدعى فقط عند حلول موعد الإشعار.

    cancel_event: threading.Event — إذا رُفع يتوقف الإرسال فوراً
    (يُرفع عند إيقاف إشعارات الكلية من الواجهة أو من أي مكان آخر)
    """
    e = email.lower().strip()
    try:
        # ── فحص الإلغاء قبل البدء ──
        if cancel_event.is_set():
            print(f"[ALL-NOTIFY] إلغاء قبل البدء لـ {e}")
            return

        all_data, all_status = get_site_data_all_tasks(email, password, chat_id)

        # ── فحص الإلغاء بعد جلب البيانات ──
        if cancel_event.is_set():
            print(f"[ALL-NOTIFY] إلغاء بعد جلب البيانات لـ {e}")
            return

        if all_status == "SUCCESS" and all_data and all_data.get('tasks'):
            user_ignored = ignored_tasks.get(chat_id, [])

            sn_key = f"all_{chat_id}_{e}"
            if sn_key not in sent_notifications:
                sent_notifications[sn_key] = set()

            new_tasks = [
                t for t in all_data['tasks']
                if t['task_page'] not in user_ignored
                and t['task_page'] not in sent_notifications[sn_key]
            ]

            if new_tasks:
                for t in new_tasks:
                    sent_notifications[sn_key].add(t['task_page'])

                acc_tag = f"👤 الحساب: {e.split('@')[0]}"
                period_label = "☀️ نهار" if not _is_night_now() else "🌙 ليل"

                # التأخير بين الإشعارات: فترة التنبيه ÷ عدد المهام
                # حد أدنى 5 ثوان، أقصى 60 ثانية — لا 2 ثوان أبداً
                user_interval_secs = settings.get('notify_interval', 10) * 60
                inter_msg_delay = max(5, min(60, user_interval_secs // max(len(new_tasks), 1)))

                for t in new_tasks:
                    # ── فحص الإلغاء قبل كل رسالة ──
                    if cancel_event.is_set():
                        print(f"[ALL-NOTIFY] إلغاء أثناء الإرسال لـ {e} — توقف فوري")
                        return

                    # ── فحص مزدوج: حدث الإلغاء + قيمة الإعداد الفعلية ──
                    current_settings = get_email_settings(email)
                    if not current_settings['all_notify_status']:
                        print(f"[ALL-NOTIFY] توقف الإرسال لـ {e} — تم إيقاف إشعارات الكلية")
                        return

                    task_title = t.get('description', '').split('\n')[0][:50].strip() or "مهمة تفاعلية"

                    msg = f"📢 **إشعار كلي** — {period_label}\n{acc_tag}\n\n"
                    msg += f"📌 **المهمة:** {task_title}\n"
                    msg += f"💰 **السعر:** {t['price']} روبل\n"
                    msg += f"📱 **المنصة:** {t.get('app_name', 'منصة أخرى')}\n"
                    msg += f"⏱️ **المدة:** {t.get('duration', 'غير محدد')}\n"
                    msg += f"🔒 **الحالة:** {t.get('is_restricted', 'غير مقيدة')}\n"
                    if t.get('is_restricted') == "مقيدة" and t.get('restrictions'):
                        msg += f"🌍 **القيود:** {t['restrictions']}\n"
                    msg += f"\n🔗 `{t['task_page']}`\n"
                    msg += "━━━━━━━━━━━━━━━━"

                    try:
                        bot.send_message(chat_id, msg, parse_mode="Markdown")
                    except Exception:
                        try:
                            bot.send_message(chat_id, msg.replace("**", "").replace("`", ""))
                        except Exception:
                            pass

                    # انتظار مع دعم الإلغاء الفوري
                    cancel_event.wait(timeout=inter_msg_delay)
                    if cancel_event.is_set():
                        print(f"[ALL-NOTIFY] إلغاء خلال الانتظار بين الرسائل لـ {e}")
                        return

    except Exception as ex:
        print(f"[ALL-NOTIFY] خطأ في إرسال إشعارات الكلية لـ {e}: {ex}")


def _bg_process_one_account(chat_id, email, password, current_time, _all_notify_threads=None):
    """
    معالجة حساب واحد في الخيط الخلفي:
    - إشعارات + اصطحاب تلقائي + تنفيذ دوري
    - يعمل بغض النظر عن الحساب النشط في الواجهة
    - محاط بحماية كاملة ضد الانهيار
    """
    try:
        _bg_process_one_account_inner(chat_id, email, password, current_time, _all_notify_threads)
    except Exception as _bg_acc_err:
        print(f"[BG-ACC] خطأ في حساب {email}: {_bg_acc_err}")

def _bg_process_one_account_inner(chat_id, email, password, current_time, _all_notify_threads=None):
    key = (chat_id, email)
    e = email.lower().strip()
    settings = get_email_settings(email)

    # ══════════════════════════════════════════════════════════
    # 📢 إشعارات الكلية — منطق مستقل بتوقيت عشوائي (نهار/ليل)
    # يجلب جميع المهام (صالحة + غير صالحة) ويرسل إشعاراً لكل
    # مهمة لم يُرسل عنها إشعار من قبل. لا يصطحب أبداً.
    # ══════════════════════════════════════════════════════════
    if settings['all_notify_status']:
        # ── تهيئة مدخل الحالة لهذا الحساب ──
        if key not in _bg_last_all_notify:
            # أول تشغيل: تأجيل عشوائي بدلاً من الإرسال الفوري
            first_interval = _all_notify_next_interval_seconds()
            _bg_last_all_notify[key] = {
                'last_sent': current_time - random.randint(0, first_interval // 2),
                'next_interval': first_interval
            }

        state = _bg_last_all_notify[key]
        elapsed = current_time - state['last_sent']
        due_interval = state['next_interval']

        if elapsed >= due_interval:
            # التحقق من عدم وجود خيط إرسال نشط لهذا الحساب
            notify_thread_key = (chat_id, e, 'all_notify')
            existing_thread = (_all_notify_threads or {}).get(notify_thread_key)

            if existing_thread and existing_thread.is_alive():
                # خيط سابق لا يزال يُرسل — تخطي هذه الدورة بدون تحديث last_sent
                pass
            else:
                # ── تنظيف الخيوط الميتة من القاموس ──
                if _all_notify_threads is not None:
                    dead_keys = [k for k, t in _all_notify_threads.items() if not t.is_alive()]
                    for dk in dead_keys:
                        del _all_notify_threads[dk]

                # تحديث وقت الإرسال والفترة القادمة قبل إطلاق الخيط
                state['last_sent'] = current_time
                state['next_interval'] = _all_notify_next_interval_seconds()  # فترة جديدة عشوائية للدورة القادمة

                # جلب حدث الإلغاء الخاص بهذا الحساب
                cancel_ev = _get_cancel_event(e)

                # إرسال الإشعارات في خيط منفصل
                t = threading.Thread(
                    target=_send_all_notify_for_account,
                    args=(chat_id, email, password, settings, cancel_ev),
                    daemon=True
                )
                if _all_notify_threads is not None:
                    _all_notify_threads[notify_thread_key] = t
                t.start()

    else:
        # إشعارات الكلية مُوقفة — احذف حالة الفترة حتى تبدأ من جديد عند إعادة التفعيل
        if key in _bg_last_all_notify:
            del _bg_last_all_notify[key]

    # ══════════════════════════════════════════════════════════
    # 🔔 الإشعارات الدورية العادية (notify_status) — منطق أصلي
    # تعمل فقط إذا كانت all_notify_status مُوقفة
    # ══════════════════════════════════════════════════════════
    if settings['notify_status'] and not settings['all_notify_status']:
        interval_secs = settings['notify_interval'] * 60
        if current_time - _bg_last_notify.get(key, 0) >= interval_secs:
            _bg_last_notify[key] = current_time
            data, status = get_site_data(email, password, chat_id)
            if status == "SUCCESS" and data and data['tasks']:
                user_ignored = ignored_tasks.get(chat_id, [])

                sn_key = f"{chat_id}_{e}"
                if sn_key not in sent_notifications:
                    sent_notifications[sn_key] = set()

                filtered_tasks = [t for t in data['tasks'] if t['task_page'] not in user_ignored]
                if filtered_tasks:
                    user_notify_tasks[chat_id] = filtered_tasks[:5]
                    acc_tag = f"\n👤 الحساب: {e.split('@')[0]}"
                    msg = f"📢 مهام جديدة متوفرة{acc_tag}:\n\n"
                    for idx, t in enumerate(filtered_tasks[:5], start=1):
                        msg += f"🔢 {idx} ➖ {t['price']} RUB | {t['duration']}\n"
                    inline_markup = types.InlineKeyboardMarkup()
                    inline_markup.add(types.InlineKeyboardButton(
                        text="🔕 تجاهل مهمة من القائمة", callback_data="ign_task"
                    ))
                    try:
                        bot.send_message(chat_id, msg, reply_markup=inline_markup)
                    except Exception:
                        pass

    # ── الاصطحاب التلقائي ──
    if settings['auto_hunt_status']:
        last_take = _bg_last_take.get(key, 0)
        if current_time - last_take >= TAKE_COOLDOWN:
            hunt_interval = 120
            if current_time - _bg_last_hunt.get(key, 0) >= hunt_interval:
                _bg_last_hunt[key] = current_time
                data, status = get_site_data(email, password, chat_id)
                if status == "SUCCESS" and data and data['tasks']:
                    mode = settings['hunt_mode']
                    for target_task in data['tasks']:
                        task_minutes = target_task.get('minutes', 120)
                        should_take = (mode == "GT" and task_minutes > 120) or (mode == "GTE" and task_minutes >= 120)
                        if should_take:
                            session = get_authenticated_session(email, password)
                            if session:
                                success = take_task_via_post(session, target_task['task_page'])
                                if success:
                                    _bg_last_take[key] = time.time()
                                    acc_tag = f"\n👤 الحساب: {e.split('@')[0]}"
                                    try:
                                        bot.send_message(
                                            chat_id,
                                            f"⚡ تم اصطحاب مهمة تلقائياً!{acc_tag}\n"
                                            f"💰 السعر: {target_task['price']} RUB\n"
                                            f"⏱️ الوقت: {target_task['duration']}"
                                        )
                                    except Exception:
                                        pass

                                    if settings['auto_execute_status']:
                                        saved_templates = cloud_get_auto_tasks(chat_id)
                                        task_desc_lower = target_task.get('description', '').lower()
                                        task_url_str = target_task['task_page'].lower()
                                        for tmpl in saved_templates:
                                            kw = tmpl['keyword'].lower()
                                            if kw in task_desc_lower or kw in task_url_str:
                                                order_id_match = re.search(r"/(\d+)/", target_task['task_page'])
                                                if order_id_match:
                                                    ord_id = order_id_match.group(1)
                                                    execute_page_url = f"https://forumok.com/publisher-requests-socio/addRequest/order_id/{ord_id}?ok=1"
                                                    if submit_task_proof_automatically(session, execute_page_url, tmpl.get('work_url'), tmpl.get('proof_msg')):
                                                        try:
                                                            bot.send_message(chat_id, f"✅ تم إرسال التقرير بنجاح للمهمة المصطادة.")
                                                        except Exception:
                                                            pass
                                                break
                            break

    # ── التنفيذ الدوري ──
    if settings['auto_execute_status']:
        exec_interval_secs = settings['auto_execute_interval'] * 60
        if current_time - _bg_last_exec.get(key, 0) >= exec_interval_secs:
            _bg_last_exec[key] = current_time
            session = get_authenticated_session(email, password)
            if session:
                tasks, status = extract_confirmed_tasks(session)
                if status == "SUCCESS" and tasks:
                    templates = cloud_get_auto_tasks(chat_id)
                    if templates:
                        for task in tasks:
                            task_info = get_task_full_description(session, task['task_link'])
                            if task_info:
                                for tmpl in templates:
                                    if search_text_in_description(task_info['description_html'], task_info['description_text'], tmpl['keyword']):
                                        success = submit_task_report(session, task_info['form_action'], tmpl.get('work_url', ''), tmpl.get('proof_msg', ''))
                                        if success:
                                            acc_tag = f"\n👤 الحساب: {e.split('@')[0]}"
                                            try:
                                                bot.send_message(chat_id, f"🤖 [عمل دوري]: تم تنفيذ {task['name']}{acc_tag} | 💰 {task['price']}")
                                            except Exception:
                                                pass
                                        time.sleep(random.randint(30, 120))
                                        break


def global_background_worker():
    last_proxy_check = 0
    last_reserve_check = 0
    last_thread_cleanup = 0
    RESERVE_CHECK_INTERVAL = 5 * 60  # فحص الاحتياطي كل 5 دقائق
    THREAD_CLEANUP_INTERVAL = 10 * 60  # تنظيف الخيوط الميتة كل 10 دقائق
    consecutive_errors = 0
    # مجموعة تتبع الخيوط النشطة لإرسال إشعارات الكلية لكل (chat_id, email)
    _all_notify_threads = {}

    while True:
        try:
            consecutive_errors = 0
            current_time = time.time()

            # ── تحديث البروكسيات الديناميكية كل 30 دقيقة ──
            if current_time - last_proxy_check >= PROXY_REFRESH_INTERVAL:
                last_proxy_check = current_time
                print("[BG] بدء تحديث البروكسيات الديناميكية...")
                threading.Thread(target=refresh_dynamic_proxies, daemon=True).start()

            # ── فحص صحة الاحتياطي كل 5 دقائق ──
            if current_time - last_reserve_check >= RESERVE_CHECK_INTERVAL:
                last_reserve_check = current_time
                needed = _needed_reserve_size()
                with reserve_pool_lock:
                    reserve_count = len([p for p in proxy_reserve_pool["proxies"]
                                         if p.get("status", "active") != "dead"])
                if reserve_count < needed:
                    print(f"[BG] الاحتياطي منخفض ({reserve_count}/{needed}) — تعبئة...")
                    trigger_reserve_fill()

            # ── تنظيف دوري لخيوط _all_notify_threads الميتة (حماية من تسرب الذاكرة) ──
            if current_time - last_thread_cleanup >= THREAD_CLEANUP_INTERVAL:
                last_thread_cleanup = current_time
                dead_keys = [k for k, t in list(_all_notify_threads.items()) if not t.is_alive()]
                for dk in dead_keys:
                    del _all_notify_threads[dk]
                if dead_keys:
                    print(f"[BG] تم تنظيف {len(dead_keys)} خيط منتهٍ من _all_notify_threads")

            # ── المرور على جميع chat_ids وجميع حساباتهم النشطة ──
            with active_accounts_lock:
                snapshot = {cid: dict(accs) for cid, accs in active_accounts.items()}

            for chat_id, accounts in snapshot.items():
                for email_key, creds in accounts.items():
                    try:
                        _bg_process_one_account(chat_id, creds['email'], creds['password'], current_time, _all_notify_threads)
                    except Exception as ex:
                        print(f"[BG] خطأ في معالجة {email_key}: {ex}")

        except Exception as e:
            consecutive_errors += 1
            print(f"[BG] خطأ عام (#{consecutive_errors}): {e}")
            sleep_time = min(60, 5 * consecutive_errors)
            time.sleep(sleep_time)
            continue
        time.sleep(5)

# ==========================================
# 📞 معالجة الضغطات (Callbacks)
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_all_inline_callbacks(call):
    try:
        _handle_callback_inner(call)
    except Exception as _cb_err:
        print(f"[CALLBACK] خطأ غير متوقع: {_cb_err}")
        try:
            bot.answer_callback_query(call.id, "⚠️ حدث خطأ، حاول مرة أخرى.")
        except Exception:
            pass

def _handle_callback_inner(call):
    chat_id = call.message.chat.id
    data = call.data
    message_id = call.message.message_id

    if chat_id in user_sessions:
        step = user_sessions[chat_id].get('step', '')
        waiting_steps = [
            'WAITING_EMAIL', 'WAITING_PASSWORD',
            'WAITING_CUSTOM_INTERVAL', 'EXEC_SET_INTERVAL',
            'WAIT_IGN_NUM',
            'EXEC_ADD_KEYWORD', 'EXEC_ADD_URL', 'EXEC_ADD_PROOF',
            'EXEC_EDIT_KEYWORD', 'EXEC_EDIT_URL', 'EXEC_EDIT_PROOF',
            'EXEC_WAIT_SHARE_CHAT_ID',
            'WITHDRAW_WAIT_AMOUNT', 'WITHDRAW_EDIT_WALLET',
            'MANUAL_EXEC_FILL', 'MANUAL_EXEC_PROOF',
            'MANUAL_EXEC_NOW_FIELD1', 'MANUAL_EXEC_NOW_FIELD2',
            'MANUAL_EXEC_CUSTOM_URL', 'MANUAL_EXEC_CUSTOM_WORK_URL', 'MANUAL_EXEC_CUSTOM_PROOF',
            'WAITING_DELETE_ACCOUNT'
        ]
        if step in waiting_steps:
            del user_sessions[chat_id]

    elif data.startswith("show_fp_"):
        bot.answer_callback_query(call.id)
        idx = int(data.replace("show_fp_", ""))
        saved_accounts = get_saved_multi_accounts(chat_id)
        if 0 <= idx < len(saved_accounts):
            acc = saved_accounts[idx]
            fp = acc.get('fingerprint') or cloud_get_fingerprint_for_account(chat_id, acc['email'])
            label = acc['email'].split('@')[0]
            if fp:
                fp_msg = (
                    f"🔑 **بصمة الحساب: {label}**\n\n"
                    f"`{fp}`\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ هذه البصمة فريدة لهذا الحساب فقط\n"
                    f"🔒 لا تُشارك مع أي حساب آخر أبداً\n"
                    f"💾 محفوظة بشكل دائم في السحابة"
                )
            else:
                fp_msg = f"⚠️ لا توجد بصمة للحساب {label}، سجّل خروجاً ثم دخولاً مجدداً لإنشائها."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="switch_account_menu"))
            bot.send_message(chat_id, fp_msg, parse_mode="Markdown", reply_markup=markup)
        return

    elif data == "switch_account_menu":
        bot.answer_callback_query(call.id)
        msg_text = "🔄 **إدارة الحسابات**\nاختر حساباً للتبديل إليه أو قم بإضافة حساب جديد:\nــــــــــــــــــ"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_switch_account_menu(chat_id))
        return

    elif data == "add_new_account":
        bot.answer_callback_query(call.id)
        delete_transient_message(bot, chat_id)
        msg = bot.send_message(chat_id, "📥 أدخل البريد الإلكتروني للحساب الجديد:")
        user_transient_messages[chat_id] = msg.message_id
        user_sessions[chat_id] = {'step': 'WAITING_EMAIL'}
        return

    elif data == "delete_account_start":
        bot.answer_callback_query(call.id)
        saved_accounts = get_saved_multi_accounts(chat_id)
        if not saved_accounts:
            bot.answer_callback_query(call.id, "⚠️ لا توجد حسابات محفوظة.", show_alert=True)
            return
        # بناء قائمة الحسابات مرقمة
        lines = ["🗑️ **حذف حساب من القائمة**\n\nأرسل **رقم الحساب** الذي تريد حذفه:\n"]
        for i, acc in enumerate(saved_accounts, 1):
            label = acc['email'].split('@')[0]
            lines.append(f"  {i}. {label}")
        lines.append("\nأو أرسل **إلغاء** للرجوع بدون حذف.")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="switch_account_menu"))
        delete_transient_message(bot, chat_id)
        msg = bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown", reply_markup=markup)
        user_transient_messages[chat_id] = msg.message_id
        user_sessions[chat_id] = {'step': 'WAITING_DELETE_ACCOUNT'}
        return

    elif data.startswith("switch_acc_"):
        idx = int(data.replace("switch_acc_", ""))
        saved_accounts = get_saved_multi_accounts(chat_id)
        if 0 <= idx < len(saved_accounts):
            acc = saved_accounts[idx]
            new_email_lower = acc['email'].lower().strip()

            # ── حفظ إعدادات الحساب الحالي قبل التبديل ──
            old_email = user_data_store.get(chat_id, {}).get('email', '')
            if old_email:
                sync_chat_settings_to_email(chat_id, old_email)

            # حفظ بيانات الحساب الجديد كحساب نشط للعرض
            user_data_store[chat_id] = {'email': acc['email'], 'password': acc['password']}
            cloud_save_account(chat_id, acc['email'], acc['password'])

            # ── تسجيل الحساب الجديد في نظام الحسابات النشطة (إذا لم يكن مسجلاً) ──
            register_account_in_active(chat_id, acc['email'], acc['password'])

            # ── إذا كان الحساب المُبدَّل إليه مُعلَّماً كـ"مُسجَّل خروجه"، فامسح العلامة
            # لأن التبديل إليه يعني أننا سنعيد استخدامه (وستُعاد الجلسة تلقائياً)
            with logged_out_lock:
                if chat_id in logged_out_accounts:
                    logged_out_accounts[chat_id].discard(new_email_lower)

            # ── تحميل إعدادات الحساب الجديد ──
            # أولاً: جرب من المخزن المستقل (email-level)
            e_settings = get_email_settings(acc['email'])
            if e_settings['notify_status'] or e_settings['auto_hunt_status'] or e_settings['auto_execute_status']:
                # الحساب له إعدادات محفوظة → حمّلها للواجهة
                sync_email_settings_to_chat(chat_id, acc['email'])
            else:
                # حمّل من السحابة (الإعدادات الخاصة بـ chat_id)
                cloud_load_user_settings(chat_id)
                sync_chat_settings_to_email(chat_id, acc['email'])

            # التحقق من وجود جلسة صالحة مخزنة للحساب المُبدَّل إليه
            with auth_sessions_lock:
                cached = user_auth_sessions.get(new_email_lower)

            if not cached:
                # لا توجد جلسة مخزنة → نجهّز البروكسي والجلسة في الخلفية فوراً
                threading.Thread(
                    target=_prepare_session_with_proxy,
                    args=(acc['email'], acc['password']),
                    daemon=True
                ).start()
            # إذا كانت الجلسة موجودة فستُستخدم مباشرة عند أي طلب قادم

            bot.answer_callback_query(call.id)
            safe_edit_or_send(bot, chat_id, message_id, get_main_menu_text(), reply_markup=get_main_menu(chat_id))
        else:
            bot.answer_callback_query(call.id, "⚠️ حدث خطأ أثناء التبديل.", show_alert=True)
        return

    elif data == "login_start":
        bot.answer_callback_query(call.id)
        delete_transient_message(bot, chat_id)
        msg = bot.send_message(chat_id, "📥 أدخل البريد الإلكتروني:")
        user_transient_messages[chat_id] = msg.message_id
        user_sessions[chat_id] = {'step': 'WAITING_EMAIL'}
        return

    elif data == "proxy_status":
        bot.answer_callback_query(call.id)
        creds = user_data_store.get(chat_id)
        if not creds:
            safe_edit_or_send(bot, chat_id, message_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return
        email = creds.get('email', '')
        proxy_text = build_proxy_status_text(email)

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 تحديث", callback_data="proxy_status"))
        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))

        safe_edit_or_send(bot, chat_id, message_id, proxy_text, reply_markup=markup)
        return

    elif data == "view_tasks":
        bot.answer_callback_query(call.id)
        if not check_and_load_session_silently(chat_id):
            safe_edit_or_send(bot, chat_id, message_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return

        # ⚡ رد فوري + تشغيل الجلب في خيط خلفي حتى لا يتجمد البوت
        safe_edit_or_send(bot, chat_id, message_id, "⏳ جارٍ جلب المهام...")

        def _do_view_tasks():
            creds = user_data_store.get(chat_id)
            if not creds:
                return
            result, status = get_site_data(creds['email'], creds['password'], chat_id)
            if status == "SUCCESS":
                msg = f"💰 **الرصيد:** `{result['balance']}` RUB\n\n📌 **المهام المتوفرة:**\n"
                if result['tasks']:
                    for i, t in enumerate(result['tasks'][:10], start=1):
                        msg += f"🔢 {i} ➖ {t['price']} RUB | {t['duration']}\n"
                else:
                    msg += "🟢 لا توجد مهام حالياً.\n"
                msg += f"\n📊 **الإحصائيات:**\n🟡 قيد التنفيذ: {result['stats']['to_execute']}\n🔵 قيد المراجعة: {result['stats']['on_check']}"
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔄 تحديث", callback_data="view_tasks"))
                markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
                safe_edit_or_send(bot, chat_id, message_id, msg, reply_markup=markup)
            else:
                err_markup = types.InlineKeyboardMarkup()
                err_markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
                safe_edit_or_send(bot, chat_id, message_id, "⚠️ فشل جلب البيانات. حاول مجدداً.", reply_markup=err_markup)

        threading.Thread(target=_do_view_tasks, daemon=True).start()
        return

    elif data == "hunt_menu":
        bot.answer_callback_query(call.id)
        if not check_and_load_session_silently(chat_id):
            safe_edit_or_send(bot, chat_id, message_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return
        safe_edit_or_send(bot, chat_id, message_id, "🎯 **تصيد المهام**\nــــــــــــــــــ", reply_markup=get_hunting_menu())
        return

    elif data == "exec_menu":
        bot.answer_callback_query(call.id)
        if not check_and_load_session_silently(chat_id):
            safe_edit_or_send(bot, chat_id, message_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return
        msg = "⚙️ **لوحة تحكم تنفيذ المهام**\nاختر أحد الخيارات أدناه:\nــــــــــــــــــ"
        safe_edit_or_send(bot, chat_id, message_id, msg, reply_markup=get_task_execution_menu(chat_id))
        return

    elif data == "logout":
        bot.answer_callback_query(call.id)
        creds = user_data_store.get(chat_id, {})
        email_to_logout = creds.get('email', '').lower().strip()

        # ── تسجيل خروج حقيقي: مسح الجلسة النشطة ──
        if email_to_logout:
            # مسح الجلسة المصادقة من الذاكرة
            with auth_sessions_lock:
                user_auth_sessions.pop(email_to_logout, None)
            # إيقاف جميع المهام التلقائية لهذا الحساب
            e = email_to_logout
            acct_notify_status[e] = False
            acct_all_notify_status[e] = False
            acct_auto_hunt_status[e] = False
            acct_auto_execute_status[e] = False
            # ── إلغاء فوري لأي خيط إشعارات كلية جارٍ ──
            _cancel_all_notify_for_email(e)
            # تعليم الحساب كـ "مُسجَّل خروجه" في الذاكرة
            with logged_out_lock:
                if chat_id not in logged_out_accounts:
                    logged_out_accounts[chat_id] = set()
                logged_out_accounts[chat_id].add(email_to_logout)

        # ── مسح بيانات الجلسة الخاصة بـ chat_id (الواجهة) فقط ──
        # لا نحذف الحساب من multi_accounts حتى يبقى في قائمة الحسابات المحفوظة
        for store in [user_data_store, user_sessions, user_numbered_tasks,
                      notify_status, notify_interval, auto_hunt_status, hunt_mode,
                      last_take_time, user_notify_tasks, ignored_tasks,
                      auto_execute_status, auto_execute_interval, all_notify_status]:
            store.pop(chat_id, None)

        safe_edit_or_send(
            bot, chat_id, message_id,
            "🚪 **تم تسجيل الخروج بنجاح**\n\n"
            "💤 جلستك الحالية انتهت.\n"
            "يمكنك تسجيل الدخول مجدداً من قائمة الحسابات المحفوظة:",
            reply_markup=get_auth_menu(chat_id)
        )
        return

    elif data == "back_main":
        bot.answer_callback_query(call.id)
        if not check_and_load_session_silently(chat_id):
            safe_edit_or_send(bot, chat_id, message_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return
        safe_edit_or_send(bot, chat_id, message_id, get_main_menu_text(), reply_markup=get_main_menu(chat_id))
        return

    elif data == "notif_menu":
        bot.answer_callback_query(call.id)
        if not check_and_load_session_silently(chat_id):
            safe_edit_or_send(bot, chat_id, message_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return
        current_interval = notify_interval.get(chat_id, 10)
        is_active = notify_status.get(chat_id, False)
        status_text = "🟢 مفعلة" if is_active else "🔴 متوقفة"
        msg_text = f"🔔 **الإشعارات الدورية: {status_text}**\n⏱️ الفترة الحالية: {current_interval} دقائق\n\nاختر فترة التنبيه أو اضغط تخصيص:"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_notifications_config_menu(chat_id))
        return

    elif data == "take_work_menu":
        bot.answer_callback_query(call.id)
        if not check_and_load_session_silently(chat_id):
            safe_edit_or_send(bot, chat_id, message_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return
        creds = user_data_store.get(chat_id, {})
        email = creds.get('email', '')
        safe_edit_or_send(bot, chat_id, message_id, "⚡ **خيارات اصطحاب المهام**\nــــــــــــــــــ", reply_markup=get_take_work_menu(chat_id, email))
        return

    elif data == "back_hunt":
        bot.answer_callback_query(call.id)
        safe_edit_or_send(bot, chat_id, message_id, "🎯 **تصيد المهام**\nــــــــــــــــــ", reply_markup=get_hunting_menu())
        return

    elif data == "toggle_notify":
        bot.answer_callback_query(call.id)
        current = notify_status.get(chat_id, False)
        new_state = not current
        notify_status[chat_id] = new_state
        # ── القاعدة الصارمة: لا يعملان معاً أبداً ──
        # عند تشغيل الدورية → أوقف الكلية فوراً في كل مكان
        # عند إيقاف الدورية → الكلية تبقى كما هي (المستخدم يتحكم بها)
        if new_state:
            all_notify_status[chat_id] = False
        creds_t = user_data_store.get(chat_id, {})
        if creds_t.get('email'):
            e_t = creds_t['email'].lower().strip()
            acct_notify_status[e_t] = new_state
            if new_state:
                acct_all_notify_status[e_t] = False
                # ── إيقاف فوري لأي خيط إشعارات كلية جارٍ ──
                _cancel_all_notify_for_email(e_t)
                # حذف حالة الفترة
                from_key_to_del = [(cid, em) for (cid, em) in list(_bg_last_all_notify.keys())
                                   if em.lower().strip() == e_t and cid == chat_id]
                for k in from_key_to_del:
                    _bg_last_all_notify.pop(k, None)
        cloud_save_user_settings(chat_id)
        current_interval = notify_interval.get(chat_id, 10)
        msg_text = f"🔔 **إعدادات الإشعارات:**\n⏱️ الفترة الحالية: {current_interval} دقائق\n\nاختر من الخيارات أدناه:"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_notifications_config_menu(chat_id))
        return

    elif data == "toggle_all_notify":
        bot.answer_callback_query(call.id)
        current = all_notify_status.get(chat_id, False)
        new_state = not current
        all_notify_status[chat_id] = new_state
        # ── القاعدة الصارمة: لا يعملان معاً أبداً ──
        # عند تشغيل الكلية → أوقف الدورية فوراً في كل مكان
        # عند إيقاف الكلية → الدورية تبقى كما هي (المستخدم يتحكم بها)
        if new_state:
            notify_status[chat_id] = False
        creds_t = user_data_store.get(chat_id, {})
        if creds_t.get('email'):
            e_t = creds_t['email'].lower().strip()
            acct_all_notify_status[e_t] = new_state
            if new_state:
                acct_notify_status[e_t] = False
            else:
                # ── إيقاف فوري لأي خيط إرسال جارٍ ──
                _cancel_all_notify_for_email(e_t)
                # حذف حالة الفترة حتى تبدأ من جديد عند إعادة التفعيل
                from_key_to_del = [(cid, em) for (cid, em) in list(_bg_last_all_notify.keys())
                                   if em.lower().strip() == e_t and cid == chat_id]
                for k in from_key_to_del:
                    _bg_last_all_notify.pop(k, None)
        cloud_save_user_settings(chat_id)
        current_interval = notify_interval.get(chat_id, 10)
        msg_text = f"🔔 **إعدادات الإشعارات:**\n⏱️ الفترة الحالية: {current_interval} دقائق\n\nاختر من الخيارات أدناه:"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_notifications_config_menu(chat_id))
        return

    elif data == "set_notify_10":
        # تفعيل الدورية 10 دق → إيقاف الكلية فوراً
        notify_interval[chat_id] = 10
        notify_status[chat_id] = True
        all_notify_status[chat_id] = False
        creds_t = user_data_store.get(chat_id, {})
        if creds_t.get('email'):
            e_t = creds_t['email'].lower().strip()
            acct_notify_status[e_t] = True
            acct_all_notify_status[e_t] = False
            acct_notify_interval[e_t] = 10
            # ── إيقاف فوري لأي خيط إشعارات كلية جارٍ ──
            _cancel_all_notify_for_email(e_t)
            from_key_to_del = [(cid, em) for (cid, em) in list(_bg_last_all_notify.keys())
                               if em.lower().strip() == e_t and cid == chat_id]
            for k in from_key_to_del:
                _bg_last_all_notify.pop(k, None)
        cloud_save_user_settings(chat_id)
        bot.answer_callback_query(call.id, "✅ تم الضبط إلى 10 دقائق")
        msg_text = f"🔔 **الإشعارات الدورية: 🟢 مفعلة**\n⏱️ الفترة الحالية: 10 دقائق\n\nاختر فترة التنبيه أو اضغط تخصيص:"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_notifications_config_menu(chat_id))
        return

    elif data == "set_notify_15":
        # تفعيل الدورية 15 دق → إيقاف الكلية فوراً
        notify_interval[chat_id] = 15
        notify_status[chat_id] = True
        all_notify_status[chat_id] = False
        creds_t = user_data_store.get(chat_id, {})
        if creds_t.get('email'):
            e_t = creds_t['email'].lower().strip()
            acct_notify_status[e_t] = True
            acct_all_notify_status[e_t] = False
            acct_notify_interval[e_t] = 15
            # ── إيقاء فوري لأي خيط إشعارات كلية جارٍ ──
            _cancel_all_notify_for_email(e_t)
            from_key_to_del = [(cid, em) for (cid, em) in list(_bg_last_all_notify.keys())
                               if em.lower().strip() == e_t and cid == chat_id]
            for k in from_key_to_del:
                _bg_last_all_notify.pop(k, None)
        cloud_save_user_settings(chat_id)
        bot.answer_callback_query(call.id, "✅ تم الضبط إلى 15 دقيقة")
        msg_text = f"🔔 **الإشعارات الدورية: 🟢 مفعلة**\n⏱️ الفترة الحالية: 15 دقيقة\n\nاختر فترة التنبيه أو اضغط تخصيص:"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_notifications_config_menu(chat_id))
        return

    elif data == "custom_notify":
        bot.answer_callback_query(call.id)
        user_sessions[chat_id] = {'step': 'WAITING_CUSTOM_INTERVAL'}
        msg_text = "📥 **أدخل فترة التنبيه بالدقائق**\n(من 3 إلى 120 دقيقة)\n\nاكتب الرقم وأرسله في الشات مباشرة:"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_notifications_config_menu(chat_id))
        return

    elif data == "toggle_gt":
        bot.answer_callback_query(call.id)
        creds = user_data_store.get(chat_id, {})
        current_active = auto_hunt_status.get(chat_id, False)
        current_mode = hunt_mode.get(chat_id, "")
        if current_active and current_mode == "GT":
            auto_hunt_status[chat_id] = False
            status_msg = "🔴 تم إيقاف تصيد (أكبر من ساعتين)"
        else:
            auto_hunt_status[chat_id] = True
            hunt_mode[chat_id] = "GT"
            status_msg = "✅ تم تفعيل تصيد (أكبر من ساعتين)"
        cloud_save_user_settings(chat_id)
        # مزامنة للخيط الخلفي
        if creds.get('email'):
            sync_chat_settings_to_email(chat_id, creds['email'])
        full_msg = f"⚡ **اصطحاب العمل**\n{status_msg}\nــــــــــــــــــ"
        safe_edit_or_send(bot, chat_id, message_id, full_msg, reply_markup=get_take_work_menu(chat_id, creds.get('email', '')))
        return

    elif data == "toggle_gte":
        bot.answer_callback_query(call.id)
        creds = user_data_store.get(chat_id, {})
        current_active = auto_hunt_status.get(chat_id, False)
        current_mode = hunt_mode.get(chat_id, "")
        if current_active and current_mode == "GTE":
            auto_hunt_status[chat_id] = False
            status_msg = "🔴 تم إيقاف تصيد (ساعتين فما فوق)"
        else:
            auto_hunt_status[chat_id] = True
            hunt_mode[chat_id] = "GTE"
            status_msg = "✅ تم تفعيل تصيد (ساعتين فما فوق)"
        cloud_save_user_settings(chat_id)
        # مزامنة للخيط الخلفي
        if creds.get('email'):
            sync_chat_settings_to_email(chat_id, creds['email'])
        full_msg = f"⚡ **اصطحاب العمل**\n{status_msg}\nــــــــــــــــــ"
        safe_edit_or_send(bot, chat_id, message_id, full_msg, reply_markup=get_take_work_menu(chat_id, creds.get('email', '')))
        return

    elif data == "manual_take":
        bot.answer_callback_query(call.id)
        if not check_and_load_session_silently(chat_id):
            bot.send_message(chat_id, "⚠️ يرجى تسجيل الدخول أولاً.", reply_markup=get_auth_menu(chat_id))
            return
        creds = user_data_store[chat_id]
        result, status = get_site_data(creds['email'], creds['password'], chat_id)
        if status == "SUCCESS":
            if not result['tasks']:
                full_msg = "⚡ **اصطحاب العمل**\n📋 لا توجد مهام متوفرة حالياً.\nــــــــــــــــــ"
                safe_edit_or_send(bot, chat_id, message_id, full_msg, reply_markup=get_take_work_menu(chat_id, creds.get('email', '')))
            else:
                lines = ["📌 **قائمة المهام للاصطحاب اليدوي:**\n"]
                for i, task in enumerate(result['tasks'], start=1):
                    lines.append(f"🔢 {i} - السعر: {task['price']} RUB | المدة: {task['duration']}")
                bot.send_message(chat_id, "\n".join(lines))
        else:
            bot.send_message(chat_id, "⚠️ تعذر تحميل المهام اليدوية.")
        return

    elif data == "exec_auto_on":
        auto_execute_status[chat_id] = True
        cloud_save_user_settings(chat_id)
        bot.answer_callback_query(call.id, "🟢 تم تشغيل التنفيذ التلقائي")
        msg = "⚙️ **لوحة تحكم تنفيذ المهام**\n🟢 تم تشغيل التنفيذ التلقائي\nــــــــــــــــــ"
        safe_edit_or_send(bot, chat_id, message_id, msg, reply_markup=get_task_execution_menu(chat_id))
        return

    elif data == "exec_auto_off":
        auto_execute_status[chat_id] = False
        cloud_save_user_settings(chat_id)
        bot.answer_callback_query(call.id, "🔴 تم إيقاف التنفيذ التلقائي")
        msg = "⚙️ **لوحة تحكم تنفيذ المهام**\n🔴 تم إيقاف التنفيذ التلقائي\nــــــــــــــــــ"
        safe_edit_or_send(bot, chat_id, message_id, msg, reply_markup=get_task_execution_menu(chat_id))
        return

    elif data == "exec_add_template":
        if chat_id in user_sessions:
            bot.answer_callback_query(call.id, "⚠️ يرجى إكمال العملية السابقة أولاً.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        user_sessions[chat_id] = {'step': 'EXEC_ADD_KEYWORD'}
        bot.send_message(chat_id, "📝 **إضافة باقة جديدة**\n\n🔍 **الخطوة 1/3:** أدخل جزء من وصف المهمة للبحث عنه (كلمة مفتاحية):")
        return

    elif data == "exec_browse_templates":
        bot.answer_callback_query(call.id)
        templates = cloud_get_auto_tasks(chat_id)
        if not templates:
            msg_text = "📂 لا توجد البقات محفوظة لهذا الحساب حالياً.\n\nاضغط على '➕ إضافة الباقة' بالأسفل للبدء."
            safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_task_execution_menu(chat_id))
            return

        msg = f"📂 **البقاتك المحفوظة:** ({len(templates)} باقة)\n\n"
        for i, tmpl in enumerate(templates, 1):
            msg += f"**{i}.** 🔍 {tmpl['keyword'][:80]}\n"
            msg += f"   🔗 الحقل 1: {tmpl.get('work_url', '-')[:50]}\n"
            msg += f"   📝 الحقل 2: {tmpl.get('proof_msg', '-')[:50]}\n\n"

        markup = get_templates_browse_menu(chat_id)
        if markup:
            bot.send_message(chat_id, msg, reply_markup=markup)
        else:
            bot.send_message(chat_id, msg)
        return

    elif data.startswith("exec_view_"):
        template_id = data.replace("exec_view_", "")
        templates = cloud_get_auto_tasks(chat_id)
        template = next((t for t in templates if str(t['id']) == template_id), None)

        if not template:
            bot.answer_callback_query(call.id, "⚠️ الباقة غير موجودة")
            return

        bot.answer_callback_query(call.id)
        msg = (
            f"🔧 الباقة المحددة:\n\n"
            f"🔍 كلمة البحث:\n{template['keyword'][:200]}\n\n"
            f"🔗 رابط العمل (الحقل 1):\n{template.get('work_url', 'فارغ')[:200]}\n\n"
            f"📝 نص الإثبات (الحقل 2):\n{template.get('proof_msg', 'فارغ')[:200]}"
        )
        bot.send_message(chat_id, msg, reply_markup=get_template_edit_menu(template_id, template['keyword'], template.get('work_url', ''), template.get('proof_msg', '')))
        return

    elif data.startswith("exec_edit_keyword_"):
        template_id = data.replace("exec_edit_keyword_", "")
        templates = cloud_get_auto_tasks(chat_id)
        template = next((t for t in templates if str(t['id']) == template_id), None)
        if not template:
            bot.answer_callback_query(call.id, "⚠️ الباقة غير موجودة")
            return
        bot.answer_callback_query(call.id)
        if chat_id in user_sessions:
            bot.send_message(chat_id, "⚠️ يرجى إكمال العملية السابقة أولاً.")
            return
        user_sessions[chat_id] = {'step': 'EXEC_EDIT_KEYWORD', 'edit_id': template_id, 'old_template': template}
        bot.send_message(chat_id, f"✏️ تعديل كلمة البحث\n\nالقيمة الحالية:\n{template['keyword'][:200]}\n\nأدخل القيمة الجديدة:")
        return

    elif data.startswith("exec_edit_url_"):
        template_id = data.replace("exec_edit_url_", "")
        templates = cloud_get_auto_tasks(chat_id)
        template = next((t for t in templates if str(t['id']) == template_id), None)
        if not template:
            bot.answer_callback_query(call.id, "⚠️ الباقة غير موجودة")
            return
        bot.answer_callback_query(call.id)
        if chat_id in user_sessions:
            bot.send_message(chat_id, "⚠️ يرجى إكمال العملية السابقة أولاً.")
            return
        user_sessions[chat_id] = {'step': 'EXEC_EDIT_URL', 'edit_id': template_id, 'old_template': template}
        bot.send_message(chat_id, f"✏️ تعديل رابط العمل (الحقل 1)\n\nالقيمة الحالية:\n{template.get('work_url', 'فارغ')[:200]}\n\nأدخل القيمة الجديدة (أو `-` لتركه فارغاً):")
        return

    elif data.startswith("exec_edit_proof_"):
        template_id = data.replace("exec_edit_proof_", "")
        templates = cloud_get_auto_tasks(chat_id)
        template = next((t for t in templates if str(t['id']) == template_id), None)
        if not template:
            bot.answer_callback_query(call.id, "⚠️ الباقة غير موجودة")
            return
        bot.answer_callback_query(call.id)
        if chat_id in user_sessions:
            bot.send_message(chat_id, "⚠️ يرجى إكمال العملية السابقة أولاً.")
            return
        user_sessions[chat_id] = {'step': 'EXEC_EDIT_PROOF', 'edit_id': template_id, 'old_template': template}
        bot.send_message(chat_id, f"✏️ تعديل نص الإثبات (الحقل 2)\n\nالقيمة الحالية:\n{template.get('proof_msg', 'فارغ')[:200]}\n\nأدخل القيمة الجديدة:")
        return

    elif data.startswith("exec_delete_"):
        template_id = data.replace("exec_delete_", "")
        templates = cloud_get_auto_tasks(chat_id)
        template = next((t for t in templates if str(t['id']) == template_id), None)
        if not template:
            bot.answer_callback_query(call.id, "⚠️ الباقة غير موجودة")
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ نعم، احذف", callback_data=f"exec_confirm_delete_{template_id}"),
            types.InlineKeyboardButton("❌ إلغاء", callback_data=f"exec_view_{template_id}")
        )
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, f"⚠️ هل أنت متأكد من حذف الباقة؟\n\n{template['keyword'][:100]}", reply_markup=markup)
        return

    elif data.startswith("exec_confirm_delete_"):
        template_id = data.replace("exec_confirm_delete_", "")
        if cloud_delete_auto_task(template_id):
            bot.answer_callback_query(call.id, "✅ تم حذف الباقة بنجاح")
            safe_edit_or_send(bot, chat_id, message_id, "🗑️ تم حذف الباقة.", reply_markup=get_task_execution_menu(chat_id))
        else:
            bot.answer_callback_query(call.id, "❌ فشل الحذف")
        return

    elif data == "exec_manual_now":
        creds = user_data_store.get(chat_id)
        if not creds:
            bot.answer_callback_query(call.id, "⚠️ يرجى تسجيل الدخول أولاً.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "⏳ جاري جلب المهام قيد التنفيذ...")

        def _fetch_pending_tasks():
            try:
                session = get_authenticated_session(creds['email'], creds['password'])
                if not session:
                    safe_edit_or_send(bot, chat_id, message_id, "❌ فشل تجديد الجلسة.", reply_markup=get_task_execution_menu(chat_id))
                    return
                tasks, status = extract_confirmed_tasks(session)
                if status != "SUCCESS":
                    safe_edit_or_send(bot, chat_id, message_id, f"❌ {status}", reply_markup=get_task_execution_menu(chat_id))
                    return
                if not tasks:
                    markup = types.InlineKeyboardMarkup(row_width=1)
                    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="exec_back_to_main"))
                    safe_edit_or_send(bot, chat_id, message_id,
                        "📋 **لا توجد مهام قيد التنفيذ حالياً.**",
                        reply_markup=markup)
                    return
                user_pending_tasks[chat_id] = tasks
                markup = types.InlineKeyboardMarkup(row_width=1)
                for i, task in enumerate(tasks[:15]):
                    btn_text = f"{task['platform']} | 💰 {task['price']} | ⏱ {task['time_remaining'][:20]}"
                    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"manual_exec_task_{i}"))
                markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="exec_back_to_main"))
                msg_text = f"⚡ **المهام قيد التنفيذ ({len(tasks)} مهمة)**\n\nاختر مهمة:\nــــــــــــــــــ"
                safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=markup)
            except Exception as e:
                safe_edit_or_send(bot, chat_id, message_id, f"❌ خطأ: {e}", reply_markup=get_task_execution_menu(chat_id))

        threading.Thread(target=_fetch_pending_tasks, daemon=True).start()
        return

    elif data.startswith("manual_exec_task_"):
        idx_t = int(data.replace("manual_exec_task_", ""))
        tasks = user_pending_tasks.get(chat_id, [])
        if not tasks or idx_t >= len(tasks):
            bot.answer_callback_query(call.id, "⚠️ المهمة غير متوفرة.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "⏳ جاري جلب وصف المهمة...")
        task = tasks[idx_t]
        creds = user_data_store.get(chat_id)
        if not creds:
            bot.answer_callback_query(call.id, "⚠️ يرجى تسجيل الدخول أولاً.", show_alert=True)
            return

        def _fetch_task_description(t, idx):
            wait_msg = None
            try:
                wait_msg = bot.send_message(chat_id, "⏳ جاري جلب وصف المهمة...")
                session = get_authenticated_session(creds['email'], creds['password'])
                task_link = t.get('original_url', t['task_link'])
                description_text = ""
                task_type_text = ""
                task_title = t.get('name', '')
                youtube_search_title = ""   # عنوان البحث في يوتيوب
                youtube_channel_name = ""   # اسم القناة

                if session:
                    try:
                        r = session.get(task_link, headers=HEADERS, timeout=10)
                        if r.status_code == 200:
                            from bs4 import BeautifulSoup as _BS
                            soup = _BS(r.text, "html.parser")

                            # استخراج العنوان (اسم الطلب)
                            name_td = soup.find("td", string="Название")
                            if name_td:
                                name_link = name_td.find_next("td").find("a")
                                if name_link:
                                    task_title = name_link.get_text(strip=True)

                            # استخراج نوع المهمة
                            type_td = soup.find("td", string=re.compile(r"Тип задания", re.I))
                            if type_td:
                                type_val = type_td.find_next_sibling("td")
                                if type_val:
                                    task_type_text = type_val.get_text(strip=True)

                            # استخراج الوصف "ما يجب فعله" + عنوان البحث + اسم القناة
                            what_td = soup.find("td", string="Что делать")
                            if what_td:
                                desc_td = what_td.find_next("td")
                                if desc_td:
                                    desc_div = desc_td.find("div", style=re.compile(r"overflow-wrap"))
                                    target_el = desc_div if desc_div else desc_td
                                    description_text = target_el.get_text(separator="\n", strip=True)

                                    # ── استخراج عنوان البحث في يوتيوب ──
                                    # البنية: فقرة تحتوي "поиске" ثم <strong> يليها مباشرة
                                    for p_tag in target_el.find_all("p"):
                                        p_text = p_tag.get_text()
                                        if "поиске" in p_text or "поиск" in p_text:
                                            strong_tags = p_tag.find_all("strong")
                                            for st in strong_tags:
                                                candidate = st.get_text(strip=True)
                                                if len(candidate) > 5:
                                                    youtube_search_title = candidate
                                                    break
                                            # إذا لم نجد <strong> نبحث في الفقرة التالية
                                            if not youtube_search_title:
                                                next_p = p_tag.find_next_sibling("p")
                                                if next_p:
                                                    st = next_p.find("strong")
                                                    if st:
                                                        youtube_search_title = st.get_text(strip=True)
                                            break

                                    # إذا لم نجد بالفقرات، نبحث في كل النص عن أول <strong> بعد "поиске"
                                    if not youtube_search_title:
                                        full_html = str(target_el)
                                        idx_search = full_html.lower().find("поиске")
                                        if idx_search == -1:
                                            idx_search = full_html.lower().find("поиск")
                                        if idx_search != -1:
                                            chunk = full_html[idx_search:]
                                            tmp_soup = _BS(chunk, "html.parser")
                                            st = tmp_soup.find("strong")
                                            if st:
                                                candidate = st.get_text(strip=True)
                                                if len(candidate) > 5:
                                                    youtube_search_title = candidate

                                    # ── استخراج اسم القناة ──
                                    # البنية: "от канала" ثم <strong> أو <span> مباشرة
                                    full_html = str(target_el)
                                    for kw in ["от канала", "канала"]:
                                        idx_ch = full_html.lower().find(kw)
                                        if idx_ch != -1:
                                            chunk = full_html[idx_ch:]
                                            tmp_soup = _BS(chunk, "html.parser")

                                            # أولاً: ابحث في <span> المميّز بلون خلفية (أصفر غالباً = اسم القناة)
                                            candidate = ""
                                            for span in tmp_soup.find_all("span"):
                                                style = span.get("style", "")
                                                if "background-color" in style:
                                                    txt = span.get_text(strip=True)
                                                    txt = txt.strip().rstrip("-").strip()
                                                    if len(txt) > 1:
                                                        candidate = txt
                                                        break

                                            # ثانياً: إذا لم يُجدِ، ابحث في <strong> لكن تأكد أنه ليس كلمة تحذير
                                            if not candidate:
                                                st = tmp_soup.find("strong")
                                                if st:
                                                    txt = st.get_text(strip=True).strip().rstrip("-").strip()
                                                    # تجاهل كلمات التحذير الروسية الشائعة
                                                    ignore_words = ["ВНИМАНИЕ", "ОБЯЗАТЕЛЬНО", "ВАЖНО", "СТРОГО", "НОВОЕ"]
                                                    if len(txt) > 1 and not any(w in txt.upper() for w in ignore_words):
                                                        candidate = txt

                                            if candidate:
                                                youtube_channel_name = candidate
                                                break

                    except Exception:
                        pass

                try:
                    bot.delete_message(chat_id, wait_msg.message_id)
                except Exception:
                    pass

                # ── رسالة المعلومات الأساسية (مع Markdown) ──
                msg_lines = ["📋 *تنفيذ المهمة*\n"]
                msg_lines.append(f"🌐 المنصة: {t['platform']}")
                msg_lines.append(f"💰 السعر: {t['price']}")
                msg_lines.append(f"⏱ الوقت: {t['time_remaining']}")
                if task_title:
                    msg_lines.append(f"\n📌 *اسم المهمة:* {task_title}")
                if task_type_text:
                    msg_lines.append(f"🏷 *نوع المهمة:* {task_type_text}")

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🤖 عنوان البحث (AI)", callback_data=f"ai_extract_yt_{idx}"),
                    types.InlineKeyboardButton("⚡ تنفيذ الآن (إرسال الروابط)", callback_data=f"manual_exec_now_{idx}"),
                    types.InlineKeyboardButton("🔙 رجوع", callback_data="exec_manual_now")
                )

                bot.send_message(chat_id, "\n".join(msg_lines), parse_mode="Markdown")

                                # ── رسالة عنوان البحث (تنسيق MarkdownV2 - قابلة للنسخ بالكامل بنقرة واحدة) ──
                if youtube_search_title:
                    # هروب الرموز الخاصة بـ MarkdownV2 لحماية النص من الأخطاء والانهيار
                    escaped_title = (
                        str(youtube_search_title)
                        .replace('\\', '\\\\')
                        .replace('_', '\\_')
                        .replace('*', '\\*')
                        .replace('[', '\\[')
                        .replace(']', '\\]')
                        .replace('(', '\\(')
                        .replace(')', '\\)')
                        .replace('~', '\\~')
                        .replace('`', '\\`')
                        .replace('>', '\\>')
                        .replace('#', '\\#')
                        .replace('+', '\\+')
                        .replace('-', '\\-')
                        .replace('=', '\\=')
                        .replace('|', '\\|')
                        .replace('{', '\\{')
                        .replace('}', '\\}')
                        .replace('.', '\\.')
                        .replace('!', '\\!')
                    )
                    
                    bot.send_message(
                        chat_id,
                        f"🔍 عنوان البحث في يوتيوب \\(اضغط للنسخ\\):\n\n`{escaped_title}`",
                        parse_mode="MarkdownV2"
                    )


                # ── رسالة اسم القناة (بدون Markdown - قابلة للنسخ) ──
                if youtube_channel_name:
                    bot.send_message(
                        chat_id,
                        f"📺 اسم القناة (انسخه):\n\n{youtube_channel_name}"
                    )

                # ── رسالة الوصف الكامل ──
                if description_text:
                    max_desc = 2000
                    desc_display = description_text[:max_desc]
                    if len(description_text) > max_desc:
                        desc_display += "\n…[مقتطع]"
                    bot.send_message(
                        chat_id,
                        f"📝 ما يجب فعله:\n\n{desc_display}"
                    )
                else:
                    bot.send_message(chat_id, "⚠️ لم يتم العثور على وصف تفصيلي للمهمة.")

                # ── رسالة الأزرار ──
                bot.send_message(chat_id, "━━━━━━━━━━━━━━━━━━━━\n     https://imgbb.com      اختر الإجراء:", reply_markup=markup)

            except Exception as e:
                if wait_msg:
                    try:
                        bot.delete_message(chat_id, wait_msg.message_id)
                    except Exception:
                        pass
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="exec_manual_now"))
                bot.send_message(chat_id, f"❌ خطأ أثناء جلب وصف المهمة: {e}", reply_markup=markup)

        threading.Thread(target=_fetch_task_description, args=(task, idx_t), daemon=True).start()
        return

    elif data.startswith("ai_extract_yt_"):
        # ── زر "🤖 عنوان البحث (AI)" — يستخرج عنوان البحث + اسم القناة + شرح المهمة في طلب واحد ──
        idx_t = int(data.replace("ai_extract_yt_", ""))
        tasks = user_pending_tasks.get(chat_id, [])
        if not tasks or idx_t >= len(tasks):
            bot.answer_callback_query(call.id, "⚠️ المهمة غير متوفرة.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "⏳ AI يحلل المهمة...")

        task = tasks[idx_t]
        creds = user_data_store.get(chat_id)
        if not creds:
            bot.answer_callback_query(call.id, "⚠️ يرجى تسجيل الدخول أولاً.", show_alert=True)
            return

        def _do_ai_extract(t, idx):
            wait_msg = None
            try:
                wait_msg = bot.send_message(chat_id, "🤖 AI يقرأ المهمة ويحللها...")

                # ── جلب وصف المهمة من الموقع ──
                session = get_authenticated_session(creds['email'], creds['password'])
                task_link = t.get('original_url', t['task_link'])
                description_text = ""

                if session:
                    try:
                        r = session.get(task_link, headers=HEADERS, timeout=10)
                        if r.status_code == 200:
                            from bs4 import BeautifulSoup as _BS
                            soup = _BS(r.text, "html.parser")
                            what_td = soup.find("td", string="Что делать")
                            if what_td:
                                desc_td = what_td.find_next("td")
                                if desc_td:
                                    desc_div = desc_td.find("div", style=re.compile(r"overflow-wrap"))
                                    target_el = desc_div if desc_div else desc_td
                                    description_text = target_el.get_text(separator="\n", strip=True)
                    except Exception:
                        pass

                try:
                    bot.delete_message(chat_id, wait_msg.message_id)
                except Exception:
                    pass

                if not description_text:
                    bot.send_message(chat_id, "⚠️ لم يُعثر على وصف للمهمة لإرساله إلى AI.")
                    return

                # ── طلب واحد فقط لـ Gemini يعيد الثلاثة معاً ──
                ai = analyze_task_with_ai(description_text)

                if ai['error']:
                    bot.send_message(chat_id, ai['error'])
                    return

                # ── عنوان البحث (قابل للنسخ) ──
                if ai['search_title']:
                    bot.send_message(
                        chat_id,
                        f"🎬 عنوان الفيديو \\(اضغط للنسخ\\):\n\n`{ai['search_title']}`",
                        parse_mode="MarkdownV2"
                    )

                # ── اسم القناة (قابل للنسخ) ──
                if ai['channel_name']:
                    bot.send_message(
                        chat_id,
                        f"📺 اسم القناة \\(اضغط للنسخ\\):\n\n`{ai['channel_name']}`",
                        parse_mode="MarkdownV2"
                    )

                # ── شرح المهمة مع تقسيم تلقائي إذا كان طويلاً ──
                if ai['explanation']:
                    MAX_CHUNK = 4000
                    full_text = f"📖 شرح المهمة:\n\n{ai['explanation']}"
                    if len(full_text) <= MAX_CHUNK:
                        bot.send_message(chat_id, full_text)
                    else:
                        remaining = full_text
                        first = True
                        while remaining:
                            if len(remaining) <= MAX_CHUNK:
                                bot.send_message(chat_id, remaining)
                                break
                            cut = remaining[:MAX_CHUNK].rfind('\n')
                            if cut == -1:
                                cut = MAX_CHUNK
                            bot.send_message(chat_id, remaining[:cut])
                            remaining = remaining[cut:].lstrip('\n')
                            if not first:
                                time.sleep(0.5)
                            first = False

                # إذا لم يجد AI أي شيء مفيد
                if not ai['search_title'] and not ai['channel_name'] and not ai['explanation']:
                    bot.send_message(chat_id, "⚠️ لم يتمكن AI من استخراج معلومات من هذه المهمة.")

                # ── أزرار الإجراءات ──
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("⚡ تنفيذ الآن", callback_data=f"manual_exec_now_{idx}"),
                    types.InlineKeyboardButton("🔙 رجوع", callback_data="exec_manual_now")
                )
                bot.send_message(chat_id, "اختر الإجراء:", reply_markup=markup)

            except Exception as e:
                if wait_msg:
                    try:
                        bot.delete_message(chat_id, wait_msg.message_id)
                    except Exception:
                        pass
                bot.send_message(chat_id, f"❌ خطأ في AI: {e}")

        threading.Thread(target=_do_ai_extract, args=(task, idx_t), daemon=True).start()
        return

    elif data.startswith("manual_exec_fill_"):
        idx_t = int(data.replace("manual_exec_fill_", ""))
        tasks = user_pending_tasks.get(chat_id, [])
        if not tasks or idx_t >= len(tasks):
            bot.answer_callback_query(call.id, "⚠️ المهمة غير متوفرة.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        task = tasks[idx_t]
        user_sessions[chat_id] = {'step': 'MANUAL_EXEC_FILL', 'selected_task': task}
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"),
            types.InlineKeyboardButton("🔙 رجوع", callback_data=f"manual_exec_task_{idx_t}")
        )
        msg = (
            f"📎 **الحقل 1 — رابط العمل**\n\n"
            f"أرسل رابط عملك الآن:\n"
            f"(أو أرسل `-` إذا لم يكن مطلوباً)"
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        return

    elif data.startswith("manual_exec_now_"):
        idx_t = int(data.replace("manual_exec_now_", ""))
        tasks = user_pending_tasks.get(chat_id, [])
        if not tasks or idx_t >= len(tasks):
            bot.answer_callback_query(call.id, "⚠️ المهمة غير متوفرة.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        task = tasks[idx_t]
        user_sessions[chat_id] = {'step': 'MANUAL_EXEC_NOW_FIELD1', 'selected_task': task, 'task_idx': idx_t}
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"),
            types.InlineKeyboardButton("🔙 رجوع", callback_data=f"manual_exec_task_{idx_t}")
        )
        msg = (
            f"⚡ **تنفيذ الآن**\n\n"
            f"🌐 المنصة: {task['platform']}\n"
            f"💰 السعر: {task['price']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📎 **أرسل رابط العمل (الحقل 1):**\n"
            f"(أو أرسل `-` إذا لم يكن مطلوباً)"
        )
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)
        return

    elif data == "manual_exec_custom":
        bot.answer_callback_query(call.id)
        user_sessions[chat_id] = {'step': 'MANUAL_EXEC_CUSTOM_URL'}
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"))
        bot.send_message(chat_id,
            "✍️ **تنفيذ مهمة برابط يدوي**\n\n"
            "أرسل رابط المهمة (مثال):\n"
            "`https://forumok.com/create-request/1588396/youtube/7b8229d2`",
            parse_mode="Markdown", reply_markup=markup)
        return

    elif data == "manual_exec_cancel":
        bot.answer_callback_query(call.id)
        if chat_id in user_sessions:
            step = user_sessions[chat_id].get('step', '')
            if 'MANUAL_EXEC' in step:
                del user_sessions[chat_id]
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        safe_edit_or_send(bot, chat_id, message_id,
            "⚙️ **لوحة تحكم تنفيذ المهام**\nــــــــــــــــــ",
            reply_markup=get_task_execution_menu(chat_id))
        return

    elif data == "exec_set_interval":
        if chat_id in user_sessions:
            bot.answer_callback_query(call.id, "⚠️ يرجى إكمال العملية السابقة أولاً.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        user_sessions[chat_id] = {'step': 'EXEC_SET_INTERVAL'}
        bot.send_message(chat_id, "⏱️ أدخل الفترة الزمنية للتنفيذ الدوري بالدقائق (من 1 إلى 80 دقيقة):")
        return

    elif data == "exec_share_by_chat_id":
        bot.answer_callback_query(call.id)
        if chat_id in user_sessions:
            bot.answer_callback_query(call.id, "⚠️ يرجى إكمال العملية السابقة أولاً.", show_alert=True)
            return
        user_sessions[chat_id] = {'step': 'EXEC_WAIT_SHARE_CHAT_ID'}
        msg_text = "📧 **مشاركة البقات مع حساب تليجرام آخر**\n\nاكتب chat_id الخاص بحساب التليجرام الذي تريد إرسال البقات إليه:"
        safe_edit_or_send(bot, chat_id, message_id, msg_text, reply_markup=get_task_execution_menu(chat_id))
        return

    elif data == "exec_back_to_main":
        bot.answer_callback_query(call.id)
        msg = "⚙️ **لوحة تحكم تنفيذ المهام**\nــــــــــــــــــ"
        safe_edit_or_send(bot, chat_id, message_id, msg, reply_markup=get_task_execution_menu(chat_id))
        return

    elif data == "ign_task":
        if chat_id not in user_notify_tasks or not user_notify_tasks[chat_id]:
            bot.answer_callback_query(call.id, "⚠️ لا توجد مهام حالياً لتجاهلها.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        user_sessions[chat_id] = {'step': 'WAIT_IGN_NUM'}
        bot.send_message(chat_id, "🔢 أدخل رقم المهمة لتجاهلها:")
        return

    elif data.startswith("ign_specific_"):
        bot.answer_callback_query(call.id)
        parts = data.split("_", 3)
        if len(parts) >= 4:
            task_identifier = parts[3]
            if chat_id in user_notify_tasks:
                for task in user_notify_tasks[chat_id]:
                    if task['task_page'][:50] == task_identifier:
                        if chat_id not in ignored_tasks:
                            ignored_tasks[chat_id] = []
                        if task['task_page'] not in ignored_tasks[chat_id]:
                            ignored_tasks[chat_id].append(task['task_page'])
                        bot.answer_callback_query(call.id, "✅ تم تجاهل المهمة بنجاح")
                        try:
                            bot.delete_message(chat_id, message_id)
                        except Exception:
                            pass
                        return
        bot.answer_callback_query(call.id, "⚠️ لم يتم العثور على المهمة", show_alert=True)
        return

    # ==========================================
    # 💸 معالجات زر السحب
    # ==========================================
    elif data == "withdraw_menu":
        creds = user_data_store.get(chat_id)
        if not creds:
            bot.answer_callback_query(call.id, "⚠️ يرجى تسجيل الدخول أولاً.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "⏳ جاري جلب بيانات السحب...")

        def _do_fetch_withdraw():
            try:
                session = get_authenticated_session(creds['email'], creds['password'])
                if not session:
                    safe_edit_or_send(bot, chat_id, message_id, "❌ فشل تجديد الجلسة.", reply_markup=get_main_menu(chat_id))
                    return
                info = fetch_withdrawal_page(session)

                if info["status"] == "restricted_10days":
                    # جلب بيانات المحفظة لعرض زر التعديل
                    wallet_r = info.get("wallet", "")
                    if not wallet_r:
                        # محاولة جلب من صفحة الإعدادات
                        try:
                            profile = fetch_billing_profile(session)
                            if profile:
                                wallet_r = profile.get("wallet", "")
                        except Exception:
                            pass
                    msg = (
                        "🔒 **السحب مقيد مؤقتاً**\n\n"
                        "⏳ مسموح بطلب سحب واحد فقط كل **10 أيام**.\n"
                        "يرجى الانتظار حتى انتهاء فترة القيد."
                    )
                    safe_edit_or_send(bot, chat_id, message_id, msg,
                        reply_markup=get_withdraw_menu_limited(wallet_r))
                    return

                if info["status"] == "error":
                    safe_edit_or_send(bot, chat_id, message_id,
                        f"❌ خطأ: {info.get('msg', 'غير معروف')}",
                        reply_markup=get_main_menu(chat_id))
                    return

                balance = info.get("balance", 0.0)
                wallet = info.get("wallet", "غير محدد")
                pay_system = info.get("pay_system", "غير محدد")

                # فحص الحد الأدنى 300 روبل
                if balance < 300:
                    msg = (
                        f"⚠️ **لا يمكن السحب**\n\n"
                        f"💰 رصيدك الحالي: **{balance:.2f} روبل**\n"
                        f"📌 الحد الأدنى للسحب: **300 روبل**\n\n"
                        f"أكمل المهام لزيادة رصيدك."
                    )
                    safe_edit_or_send(bot, chat_id, message_id, msg,
                        reply_markup=get_withdraw_menu_limited(wallet))
                    return

                msg = (
                    f"💸 **سحب الرصيد**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 الرصيد المتاح: **{balance:.2f} روبل**\n"
                    f"🏦 نظام الدفع: {pay_system}\n"
                    f"📬 عنوان المحفظة: `{wallet}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                safe_edit_or_send(bot, chat_id, message_id, msg,
                    reply_markup=get_withdraw_menu(balance, wallet, pay_system))
            except Exception as e:
                safe_edit_or_send(bot, chat_id, message_id, f"❌ خطأ غير متوقع: {e}",
                    reply_markup=get_main_menu(chat_id))

        threading.Thread(target=_do_fetch_withdraw, daemon=True).start()
        return

    elif data == "withdraw_do":
        creds = user_data_store.get(chat_id)
        if not creds:
            bot.answer_callback_query(call.id, "⚠️ يرجى تسجيل الدخول أولاً.", show_alert=True)
            return
        # طلب مبلغ السحب
        if chat_id in user_sessions:
            bot.answer_callback_query(call.id, "⚠️ يرجى إكمال العملية السابقة أولاً.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        user_sessions[chat_id] = {'step': 'WITHDRAW_WAIT_AMOUNT'}
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="withdraw_cancel"))
        bot.send_message(chat_id,
            "💸 **أدخل مبلغ السحب بالروبل** (الحد الأدنى 300):\n"
            "أو أرسل `كل` لسحب كامل الرصيد:",
            parse_mode="Markdown", reply_markup=markup)
        return

    elif data == "withdraw_edit_wallet":
        creds = user_data_store.get(chat_id)
        if not creds:
            bot.answer_callback_query(call.id, "⚠️ يرجى تسجيل الدخول أولاً.", show_alert=True)
            return
        if chat_id in user_sessions:
            bot.answer_callback_query(call.id, "⚠️ يرجى إكمال العملية السابقة أولاً.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "⏳ جاري جلب بيانات المحفظة...")

        def _do_fetch_billing():
            try:
                session = get_authenticated_session(creds['email'], creds['password'])
                if not session:
                    bot.send_message(chat_id, "❌ فشل تجديد الجلسة.")
                    return
                profile = fetch_billing_profile(session)
                if not profile:
                    bot.send_message(chat_id, "❌ فشل جلب بيانات المحفظة.")
                    return
                user_sessions[chat_id] = {
                    'step': 'WITHDRAW_EDIT_WALLET',
                    'billing_profile': profile
                }
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="withdraw_cancel"))
                bot.send_message(chat_id,
                    f"✏️ **تعديل عنوان المحفظة**\n\n"
                    f"🏦 نظام الدفع الحالي: {profile['pay_system']}\n"
                    f"📬 العنوان الحالي: `{profile['wallet']}`\n\n"
                    f"أرسل العنوان الجديد:",
                    parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                bot.send_message(chat_id, f"❌ خطأ: {e}")

        threading.Thread(target=_do_fetch_billing, daemon=True).start()
        return

    elif data == "withdraw_cancel":
        bot.answer_callback_query(call.id)
        if chat_id in user_sessions:
            step = user_sessions[chat_id].get('step', '')
            if step in ('WITHDRAW_WAIT_AMOUNT', 'WITHDRAW_EDIT_WALLET'):
                del user_sessions[chat_id]
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        try:
            bot.send_message(chat_id, get_main_menu_text(),
                parse_mode="Markdown", reply_markup=get_main_menu(chat_id))
        except Exception:
            pass
        return

# ==========================================
# 📨 معالجة الرسائل
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_bot_logic(message):
    try:
        _handle_message_inner(message)
    except Exception as _msg_err:
        print(f"[MESSAGE] خطأ غير متوقع: {_msg_err}")
        try:
            bot.send_message(message.chat.id, "⚠️ حدث خطأ، حاول مجدداً.")
        except Exception:
            pass

def _handle_message_inner(message):
    chat_id = message.chat.id
    text = message.text.strip() if message.text else ""

    if text.lower() not in ["/start", "start"]:
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

    if text.lower() in ["/start", "start"]:
        remove_keyboard = types.ReplyKeyboardRemove()
        if check_and_load_session_silently(chat_id):
            bot.send_message(chat_id, "مرحباً بك في لوحة التحكم الرئيسية ⚙️", reply_markup=remove_keyboard)
            bot.send_message(chat_id, get_main_menu_text(), reply_markup=get_main_menu(chat_id))
        else:
            bot.send_message(chat_id, "مرحباً بك في البوت.", reply_markup=remove_keyboard)
            bot.send_message(chat_id, "⚙️ يرجى تسجيل الدخول للبدء أو اختيار حسابك المحفوظ:", reply_markup=get_auth_menu(chat_id))
        return

    if chat_id in user_sessions:
        step = user_sessions[chat_id]['step']

        if step == 'WAITING_EMAIL':
            delete_transient_message(bot, chat_id)
            user_sessions[chat_id]['email'] = text
            user_sessions[chat_id]['step'] = 'WAITING_PASSWORD'
            msg = bot.send_message(chat_id, "🔐 أدخل كلمة المرور:")
            user_transient_messages[chat_id] = msg.message_id
            return

        elif step == 'WAITING_PASSWORD':
            delete_transient_message(bot, chat_id)
            email = user_sessions[chat_id]['email']
            password = text
            del user_sessions[chat_id]

            email_lower = email.lower().strip()

            # رسالة انتظار مناسبة
            with proxy_store_lock:
                has_proxies = (
                    email_lower not in EXEMPT_ACCOUNTS and
                    email_lower in dynamic_proxy_store and
                    bool(dynamic_proxy_store[email_lower].get("proxies"))
                )
            if email_lower in EXEMPT_ACCOUNTS:
                status_msg = bot.send_message(chat_id, "⏳ جاري التحقق من الحساب...")
            elif has_proxies:
                status_msg = bot.send_message(chat_id, "⚡ جاري تسجيل الدخول بأسرع بروكسي متاح...")
            else:
                status_msg = bot.send_message(
                    chat_id,
                    "🌐 جاري جلب البروكسيات واختبارها...\n"
                    "⏳ سيتم تسجيل الدخول بأول بروكسي سريع يُعثر عليه\n"
                    "📦 ثم يكمل تجهيز أفضل 20 بروكسي في الخلفية"
                )

            # تسجيل الدخول — يعثر على أول بروكسي سريع ثم يُسجَّل فوراً
            session = get_authenticated_session(email, password)

            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                pass

            if session:
                user_data_store[chat_id] = {'email': email, 'password': password}
                cloud_save_account(chat_id, email, password)
                save_multi_account(chat_id, email, password)
                cloud_load_user_settings(chat_id)

                # ── تسجيل الحساب في نظام الحسابات النشطة المتعددة ──
                register_account_in_active(chat_id, email, password)
                sync_chat_settings_to_email(chat_id, email)

                # حفظ الجلسة في المخزن العام (قد تكون محفوظة بالفعل من get_authenticated_session)
                with auth_sessions_lock:
                    user_auth_sessions[email_lower] = session

                # ── مسح علامة "مُسجَّل خروجه" عند إعادة الدخول ──
                with logged_out_lock:
                    if chat_id in logged_out_accounts:
                        logged_out_accounts[chat_id].discard(email_lower)

                remove_keyboard = types.ReplyKeyboardRemove()
                bot.send_message(chat_id, "✅", reply_markup=remove_keyboard)

                welcome_msg = "🎉 **تم تسجيل الدخول بنجاح!**"
                if email_lower in EXEMPT_ACCOUNTS:
                    welcome_msg += "\n🔵 تم تفعيل البروكسي الثابت المخصص."
                else:
                    with proxy_store_lock:
                        proxy_count = len(dynamic_proxy_store.get(email_lower, {}).get("proxies", []))
                    if proxy_count >= PROXIES_PER_ACCOUNT:
                        welcome_msg += f"\n🌐 تم تفعيل {proxy_count} بروكسي ديناميكي."
                    else:
                        welcome_msg += f"\n⚡ تم تسجيل الدخول بأسرع بروكسي.\n📦 جاري تجهيز أفضل {PROXIES_PER_ACCOUNT} بروكسي في الخلفية..."
                welcome_msg += "\n\nــــــــــــــــــ"

                bot.send_message(chat_id, welcome_msg, parse_mode="Markdown", reply_markup=get_main_menu(chat_id))
            else:
                bot.send_message(chat_id, "❌ فشل تسجيل الدخول، تأكد من بياناتك.", reply_markup=get_auth_menu(chat_id))
            return

        elif step == 'WAITING_DELETE_ACCOUNT':
            delete_transient_message(bot, chat_id)
            # السماح بكتابة "إلغاء" أو "الغاء" للخروج بدون حذف
            if text.strip().lower() in ['إلغاء', 'الغاء', 'cancel', 'لا']:
                del user_sessions[chat_id]
                bot.send_message(chat_id, "↩️ تم الإلغاء.",
                    reply_markup=get_switch_account_menu(chat_id))
                return
            if not text.strip().isdigit():
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="switch_account_menu"))
                bot.send_message(chat_id, "⚠️ أرسل رقم الحساب فقط، أو أرسل **إلغاء** للرجوع:",
                    parse_mode="Markdown", reply_markup=markup)
                return
            idx = int(text.strip()) - 1
            saved_accounts = get_saved_multi_accounts(chat_id)
            if idx < 0 or idx >= len(saved_accounts):
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="switch_account_menu"))
                bot.send_message(chat_id,
                    f"⚠️ الرقم غير موجود. أدخل رقماً بين 1 و {len(saved_accounts)}، أو أرسل **إلغاء**:",
                    parse_mode="Markdown", reply_markup=markup)
                return

            del user_sessions[chat_id]
            acc_to_delete = saved_accounts[idx]
            email_del = acc_to_delete['email'].lower().strip()
            label_del = email_del.split('@')[0]

            # ── حذف من الذاكرة ──
            with active_accounts_lock:
                if chat_id in active_accounts:
                    active_accounts[chat_id].pop(email_del, None)

            # ── حذف من السحابة ──
            threading.Thread(
                target=cloud_delete_multi_account,
                args=(chat_id, email_del),
                daemon=True
            ).start()

            # ── إزالة الجلسة والبروكسي ──
            with auth_sessions_lock:
                user_auth_sessions.pop(email_del, None)
            with proxy_store_lock:
                dynamic_proxy_store.pop(email_del, None)

            # ── إذا كان الحساب المحذوف هو الحساب النشط، امسح الواجهة ──
            active_email = user_data_store.get(chat_id, {}).get('email', '').lower().strip()
            if active_email == email_del:
                for store in [user_data_store, user_sessions, user_numbered_tasks,
                              notify_status, notify_interval, auto_hunt_status, hunt_mode,
                              last_take_time, user_notify_tasks, ignored_tasks,
                              auto_execute_status, auto_execute_interval, all_notify_status]:
                    store.pop(chat_id, None)

            bot.send_message(chat_id,
                f"✅ **تم حذف الحساب {label_del} نهائياً**\n\n"
                f"🗑️ تم حذفه من القائمة وجميع الجلسات.",
                parse_mode="Markdown",
                reply_markup=get_switch_account_menu(chat_id))
            return

        elif step == 'WAITING_CUSTOM_INTERVAL':
            if text.isdigit():
                minutes = int(text)
                if 3 <= minutes <= 120:
                    notify_interval[chat_id] = minutes
                    notify_status[chat_id] = True
                    # ── إيقاف إشعارات الكلية فوراً — لا يعملان معاً أبداً ──
                    all_notify_status[chat_id] = False
                    creds_ci = user_data_store.get(chat_id, {})
                    if creds_ci.get('email'):
                        e_ci = creds_ci['email'].lower().strip()
                        acct_notify_status[e_ci] = True
                        acct_all_notify_status[e_ci] = False
                        acct_notify_interval[e_ci] = minutes
                    cloud_save_user_settings(chat_id)
                    del user_sessions[chat_id]
                    bot.send_message(chat_id, f"✅ تم ضبط فترة التنبيه إلى {minutes} دقيقة.")
                else:
                    bot.send_message(chat_id, "⚠️ يرجى إدخال قيمة بين 3 و 120 دقيقة:")
            else:
                bot.send_message(chat_id, "❌ الرجاء إدخال أرقام فقط (مثال: 25):")
            return

        elif step == 'EXEC_SET_INTERVAL':
            if text.isdigit():
                minutes = int(text)
                if 1 <= minutes <= 80:
                    auto_execute_interval[chat_id] = minutes
                    cloud_save_user_settings(chat_id)
                    del user_sessions[chat_id]
                    bot.send_message(chat_id, f"✅ تم ضبط الفترة الدورية إلى {minutes} دقيقة.")
                else:
                    bot.send_message(chat_id, "⚠️ يرجى إدخال قيمة بين 1 و 80 دقيقة:")
            else:
                bot.send_message(chat_id, "❌ الرجاء إدخال أرقام فقط (مثال: 10):")
            return

        elif step == 'WAIT_IGN_NUM':
            if text.isdigit():
                idx = int(text) - 1
                if chat_id in user_notify_tasks and 0 <= idx < len(user_notify_tasks[chat_id]):
                    task_url = user_notify_tasks[chat_id][idx]['task_page']
                    if chat_id not in ignored_tasks:
                        ignored_tasks[chat_id] = []
                    if task_url not in ignored_tasks[chat_id]:
                        ignored_tasks[chat_id].append(task_url)
                    del user_sessions[chat_id]
                    bot.send_message(chat_id, "✅ تم تجاهل المهمة.")
                else:
                    bot.send_message(chat_id, "⚠️ الرقم غير موجود بالقائمة:")
            else:
                bot.send_message(chat_id, "❌ أدخل رقم صحيح فقط:")
            return

        elif step == 'EXEC_ADD_KEYWORD':
            user_sessions[chat_id]['keyword'] = text
            user_sessions[chat_id]['step'] = 'EXEC_ADD_URL'
            bot.send_message(chat_id, "🔗 **الخطوة 2/3:** أدخل رابط العمل للحقل الأول (أو أرسل `-` إذا لم يوجد):")
            return

        elif step == 'EXEC_ADD_URL':
            work_url_val = "" if text in ["-", "لا يوجد", "لايوجد"] else text
            user_sessions[chat_id]['work_url'] = work_url_val
            user_sessions[chat_id]['step'] = 'EXEC_ADD_PROOF'
            bot.send_message(chat_id, "📝 **الخطوة 3/3:** أدخل نص التقرير والإثبات للحقل الثاني:")
            return

        elif step == 'EXEC_ADD_PROOF':
            keyword = user_sessions[chat_id]['keyword']
            work_url = user_sessions[chat_id]['work_url']
            proof_msg = text
            del user_sessions[chat_id]
            if cloud_save_auto_task(chat_id, keyword, work_url, proof_msg):
                bot.send_message(chat_id, "✅ **تم حفظ الباقة بنجاح!**")
            else:
                bot.send_message(chat_id, "❌ فشل حفظ الباقة.")
            return

        elif step == 'EXEC_EDIT_KEYWORD':
            template_id = user_sessions[chat_id]['edit_id']
            new_keyword = text
            old_data = user_sessions[chat_id].get('old_template', {})
            del user_sessions[chat_id]
            if cloud_update_template(template_id, new_keyword, old_data.get('work_url', ''), old_data.get('proof_msg', '')):
                bot.send_message(chat_id, "✅ تم تحديث كلمة البحث.")
            else:
                bot.send_message(chat_id, "❌ فشل التحديث.")
            return

        elif step == 'EXEC_EDIT_URL':
            template_id = user_sessions[chat_id]['edit_id']
            new_url = "" if text in ["-", "لا يوجد", "لايوجد"] else text
            old_data = user_sessions[chat_id].get('old_template', {})
            del user_sessions[chat_id]
            if cloud_update_template(template_id, old_data.get('keyword', ''), new_url, old_data.get('proof_msg', '')):
                bot.send_message(chat_id, "✅ تم تحديث رابط العمل.")
            else:
                bot.send_message(chat_id, "❌ فشل التحديث.")
            return

        elif step == 'EXEC_EDIT_PROOF':
            template_id = user_sessions[chat_id]['edit_id']
            new_proof = text
            old_data = user_sessions[chat_id].get('old_template', {})
            del user_sessions[chat_id]
            if cloud_update_template(template_id, old_data.get('keyword', ''), old_data.get('work_url', ''), new_proof):
                bot.send_message(chat_id, "✅ تم تحديث نص الإثبات.")
            else:
                bot.send_message(chat_id, "❌ فشل التحديث.")
            return

        elif step == 'EXEC_WAIT_SHARE_CHAT_ID':
            target_chat_id_text = text.strip()
            del user_sessions[chat_id]
            if not target_chat_id_text.isdigit() and not (target_chat_id_text.startswith('-') and target_chat_id_text[1:].isdigit()):
                bot.send_message(chat_id, "❌ الرجاء إدخال chat_id رقمي صحيح.")
                return
            target_chat_id = int(target_chat_id_text)
            status_msg = bot.send_message(chat_id, f"⏳ جاري نقل البقات إلى حساب التليجرام: {target_chat_id}...")
            result = cloud_share_templates_by_chat_id(target_chat_id, current_chat_id=chat_id)
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                pass
            if result == "SUCCESS":
                bot.send_message(chat_id, f"✅ تم نقل البقات إلى حساب التليجرام {target_chat_id} بنجاح.")
            elif result == "ALREADY_EXISTS":
                bot.send_message(chat_id, "ℹ️ جميع البقات موجودة مسبقاً لدى هذا الحساب، لم يتم إضافة جديد.")
            elif result == "EMPTY":
                bot.send_message(chat_id, "⚠️ لا توجد البقات محفوظة لنقلها!")
            else:
                bot.send_message(chat_id, "❌ حدث خطأ غير متوقع.")
            return

        elif step == 'WITHDRAW_WAIT_AMOUNT':
            creds = user_data_store.get(chat_id, {})
            amount_text = text.strip()
            del user_sessions[chat_id]
            if not creds:
                bot.send_message(chat_id, "⚠️ يرجى تسجيل الدخول أولاً.")
                return

            # سحب كامل الرصيد أو مبلغ محدد
            withdraw_all = amount_text in ["كل", "الكل", "all", "ALL"]
            if not withdraw_all:
                try:
                    amount_val = float(amount_text.replace(",", "."))
                    if amount_val < 300:
                        bot.send_message(chat_id, "❌ الحد الأدنى للسحب هو 300 روبل.")
                        return
                except ValueError:
                    bot.send_message(chat_id, "❌ أدخل رقماً صحيحاً أو كلمة 'كل' لسحب كامل الرصيد.")
                    return
            else:
                amount_val = None

            wait_msg = bot.send_message(chat_id, "⏳ جاري تنفيذ طلب السحب...")

            def _do_withdraw(a_val, a_all):
                try:
                    session = get_authenticated_session(creds['email'], creds['password'])
                    if not session:
                        try:
                            bot.delete_message(chat_id, wait_msg.message_id)
                        except Exception:
                            pass
                        bot.send_message(chat_id, "❌ فشل تجديد الجلسة.")
                        return

                    info = fetch_withdrawal_page(session)

                    if info["status"] == "restricted_10days":
                        try:
                            bot.delete_message(chat_id, wait_msg.message_id)
                        except Exception:
                            pass
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
                        bot.send_message(chat_id,
                            "🔒 **السحب مقيد مؤقتاً**\n\n"
                            "⏳ مسموح بطلب سحب واحد فقط كل **10 أيام**.",
                            parse_mode="Markdown", reply_markup=markup)
                        return

                    if info["status"] != "ok":
                        try:
                            bot.delete_message(chat_id, wait_msg.message_id)
                        except Exception:
                            pass
                        bot.send_message(chat_id, f"❌ فشل جلب بيانات السحب: {info.get('msg', '')}")
                        return

                    balance = info.get("balance", 0.0)
                    if balance < 300:
                        try:
                            bot.delete_message(chat_id, wait_msg.message_id)
                        except Exception:
                            pass
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
                        bot.send_message(chat_id,
                            f"⚠️ رصيدك {balance:.2f} روبل — أقل من الحد الأدنى 300 روبل.",
                            reply_markup=markup)
                        return

                    # تحديد المبلغ النهائي
                    final_amount = balance if a_all else min(a_val, balance)

                    post_data = {
                        "withdrawal[user_id]": info.get("user_id", ""),
                        "withdrawal[_csrf_token]": info.get("csrf_token", ""),
                        "withdrawal[amount]": str(final_amount)
                    }
                    r = session.post(WITHDRAWAL_URL, data=post_data, headers=HEADERS, timeout=12)
                    try:
                        bot.delete_message(chat_id, wait_msg.message_id)
                    except Exception:
                        pass

                    if r.status_code == 200:
                        # فحص صفحة النتيجة
                        soup_r = BeautifulSoup(r.text, "html.parser")
                        notif = soup_r.find("div", class_="notification")
                        if notif and "10" in notif.get_text():
                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
                            bot.send_message(chat_id,
                                "🔒 **السحب مقيد — مسموح بسحب واحد كل 10 أيام**.",
                                parse_mode="Markdown", reply_markup=markup)
                        else:
                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="back_main"))
                            bot.send_message(chat_id,
                                f"✅ **تم إرسال طلب السحب بنجاح!**\n\n"
                                f"💰 المبلغ: **{final_amount:.2f} روبل**\n"
                                f"📬 إلى: `{info.get('wallet', '')}`\n"
                                f"⏱ المدة المتوقعة: 2-5 أيام عمل",
                                parse_mode="Markdown", reply_markup=markup)
                    else:
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
                        bot.send_message(chat_id,
                            f"❌ فشل طلب السحب (كود: {r.status_code}).",
                            reply_markup=markup)
                except Exception as e:
                    try:
                        bot.delete_message(chat_id, wait_msg.message_id)
                    except Exception:
                        pass
                    bot.send_message(chat_id, f"❌ خطأ غير متوقع: {e}")

            threading.Thread(target=_do_withdraw, args=(amount_val, withdraw_all), daemon=True).start()
            return

        elif step == 'MANUAL_EXEC_FILL':
            # الحقل 1: رابط العمل — يجب أن يكون URL صالح أو "-"
            if text not in ["-", "لا يوجد", "لايوجد"]:
                if not re.match(r'^https?://', text.strip()):
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"))
                    bot.send_message(chat_id,
                        "⚠️ **رابط غير صالح!**\n\n"
                        "الحقل الأول يجب أن يكون رابط URL صالحاً يبدأ بـ `http://` أو `https://`\n\n"
                        "📎 **أعد إرسال رابط العمل:**\n(أو أرسل `-` إذا لم يكن مطلوباً)",
                        parse_mode="Markdown", reply_markup=markup)
                    return
            work_url_val = "" if text in ["-", "لا يوجد", "لايوجد"] else text
            user_sessions[chat_id]['work_url'] = work_url_val
            user_sessions[chat_id]['step'] = 'MANUAL_EXEC_PROOF'
            task_idx = user_sessions[chat_id].get('task_idx', '')
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"),
            )
            bot.send_message(chat_id,
                "📝 **الحقل 2 — رابط الإثبات:**\n(رابط إثبات التنفيذ أو وصف)",
                parse_mode="Markdown", reply_markup=markup)
            return

        elif step == 'MANUAL_EXEC_NOW_FIELD1':
            # "تنفيذ الآن" — الحقل 1
            # السماح بـ "-" أو رابط URL صالح فقط
            if text not in ["-", "لا يوجد", "لايوجد"]:
                if not re.match(r'^https?://', text.strip()):
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"))
                    bot.send_message(chat_id,
                        "⚠️ **رابط غير صالح!**\n\n"
                        "الحقل الأول يجب أن يكون رابط URL صالحاً يبدأ بـ `http://` أو `https://`\n\n"
                        "📎 **أعد إرسال رابط العمل:**\n(أو أرسل `-` إذا لم يكن مطلوباً)",
                        parse_mode="Markdown", reply_markup=markup)
                    return
            work_url_val = "" if text in ["-", "لا يوجد", "لايوجد"] else text
            user_sessions[chat_id]['work_url'] = work_url_val
            user_sessions[chat_id]['step'] = 'MANUAL_EXEC_NOW_FIELD2'
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"))
            bot.send_message(chat_id,
                "📝 **الحقل 2 — رابط الإثبات:**\n(رابط إثبات التنفيذ أو وصف)",
                parse_mode="Markdown", reply_markup=markup)
            return

        elif step == 'MANUAL_EXEC_NOW_FIELD2':
            # "تنفيذ الآن" — الحقل 2 — تنفيذ فوري
            task = user_sessions[chat_id].get('selected_task', {})
            work_url = user_sessions[chat_id].get('work_url', '')
            proof_msg = text
            del user_sessions[chat_id]

            creds = user_data_store.get(chat_id)
            if not creds:
                bot.send_message(chat_id, "⚠️ يرجى تسجيل الدخول أولاً.")
                return

            wait_msg = bot.send_message(chat_id, "⏳ جاري إرسال التقرير...")

            def _do_now_exec(t, wu, pm):
                try:
                    session = get_authenticated_session(creds['email'], creds['password'])
                    if not session:
                        try: bot.delete_message(chat_id, wait_msg.message_id)
                        except: pass
                        bot.send_message(chat_id, "❌ فشل تجديد الجلسة.")
                        return
                    task_info = get_task_full_description(session, t['task_link'])
                    success = False
                    if task_info and task_info.get('form_action'):
                        success = submit_task_report(session, task_info['form_action'], wu, pm)
                    if not success:
                        task_id_val = t.get('task_id', '')
                        if task_id_val:
                            execute_page_url = f"https://forumok.com/publisher-requests-socio/addRequest/order_id/{task_id_val}?ok=1"
                            success = submit_task_proof_automatically(session, execute_page_url, wu, pm)
                    try: bot.delete_message(chat_id, wait_msg.message_id)
                    except: pass
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="exec_back_to_main"))
                    if success:
                        bot.send_message(chat_id,
                            f"✅ **تم تنفيذ المهمة بنجاح!**\n\n"
                            f"🌐 المنصة: {t['platform']}\n"
                            f"💰 السعر: {t['price']}",
                            parse_mode="Markdown", reply_markup=markup)
                    else:
                        bot.send_message(chat_id, "❌ فشل إرسال التقرير. تحقق من الروابط.", reply_markup=markup)
                except Exception as e:
                    try: bot.delete_message(chat_id, wait_msg.message_id)
                    except: pass
                    bot.send_message(chat_id, f"❌ خطأ: {e}")

            threading.Thread(target=_do_now_exec, args=(task, work_url, proof_msg), daemon=True).start()
            return

        elif step == 'MANUAL_EXEC_PROOF':
            # الحقل 2: رابط الإثبات
            task = user_sessions[chat_id].get('selected_task', {})
            work_url = user_sessions[chat_id].get('work_url', '')
            proof_msg = text
            del user_sessions[chat_id]

            creds = user_data_store.get(chat_id)
            if not creds:
                bot.send_message(chat_id, "⚠️ يرجى تسجيل الدخول أولاً.")
                return

            wait_msg = bot.send_message(chat_id, "⏳ جاري إرسال التقرير...")

            def _do_manual_exec(t, wu, pm):
                try:
                    session = get_authenticated_session(creds['email'], creds['password'])
                    if not session:
                        try: bot.delete_message(chat_id, wait_msg.message_id)
                        except: pass
                        bot.send_message(chat_id, "❌ فشل تجديد الجلسة.")
                        return
                    task_info = get_task_full_description(session, t['task_link'])
                    success = False
                    if task_info and task_info.get('form_action'):
                        success = submit_task_report(session, task_info['form_action'], wu, pm)
                    if not success:
                        # fallback: try addRequest directly
                        task_id_val = t.get('task_id', '')
                        if task_id_val:
                            execute_page_url = f"https://forumok.com/publisher-requests-socio/addRequest/order_id/{task_id_val}?ok=1"
                            success = submit_task_proof_automatically(session, execute_page_url, wu, pm)
                    try: bot.delete_message(chat_id, wait_msg.message_id)
                    except: pass
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="exec_back_to_main"))
                    if success:
                        bot.send_message(chat_id,
                            f"✅ **تم تنفيذ المهمة بنجاح!**\n\n"
                            f"🌐 المنصة: {t['platform']}\n"
                            f"💰 السعر: {t['price']}",
                            parse_mode="Markdown", reply_markup=markup)
                    else:
                        bot.send_message(chat_id, "❌ فشل إرسال التقرير. تحقق من الروابط.", reply_markup=markup)
                except Exception as e:
                    try: bot.delete_message(chat_id, wait_msg.message_id)
                    except: pass
                    bot.send_message(chat_id, f"❌ خطأ: {e}")

            threading.Thread(target=_do_manual_exec, args=(task, work_url, proof_msg), daemon=True).start()
            return

        elif step == 'MANUAL_EXEC_CUSTOM_URL':
            # رابط المهمة اليدوي
            if not text.startswith("http"):
                bot.send_message(chat_id, "❌ يرجى إرسال رابط صحيح يبدأ بـ http")
                return
            user_sessions[chat_id]['custom_task_url'] = text
            user_sessions[chat_id]['step'] = 'MANUAL_EXEC_CUSTOM_WORK_URL'
            # استخراج المنصة من الرابط
            platform = get_platform_from_url(text)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"))
            bot.send_message(chat_id,
                f"✅ رابط المهمة: `{text[:80]}`\n🌐 المنصة: {platform}\n\n"
                f"📎 **أرسل رابط العمل (الحقل 1):**\n(أو `-` إذا لم يوجد)",
                parse_mode="Markdown", reply_markup=markup)
            return

        elif step == 'MANUAL_EXEC_CUSTOM_WORK_URL':
            work_url_val = "" if text in ["-", "لا يوجد", "لايوجد"] else text
            user_sessions[chat_id]['work_url'] = work_url_val
            user_sessions[chat_id]['step'] = 'MANUAL_EXEC_CUSTOM_PROOF'
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="manual_exec_cancel"))
            bot.send_message(chat_id,
                "📝 **أرسل رابط الإثبات (الحقل 2):**",
                parse_mode="Markdown", reply_markup=markup)
            return

        elif step == 'MANUAL_EXEC_CUSTOM_PROOF':
            custom_url = user_sessions[chat_id].get('custom_task_url', '')
            work_url = user_sessions[chat_id].get('work_url', '')
            proof_msg = text
            del user_sessions[chat_id]

            creds = user_data_store.get(chat_id)
            if not creds:
                bot.send_message(chat_id, "⚠️ يرجى تسجيل الدخول أولاً.")
                return

            wait_msg = bot.send_message(chat_id, "⏳ جاري تنفيذ المهمة...")

            def _do_custom_exec(curl, wu, pm):
                try:
                    session = get_authenticated_session(creds['email'], creds['password'])
                    if not session:
                        try: bot.delete_message(chat_id, wait_msg.message_id)
                        except: pass
                        bot.send_message(chat_id, "❌ فشل تجديد الجلسة.")
                        return
                    # normalize url
                    task_url = curl
                    if "?ok=1" not in task_url:
                        task_url += "?ok=1" if "?" not in task_url else "&ok=1"
                    task_info = get_task_full_description(session, task_url)
                    success = False
                    if task_info and task_info.get('form_action'):
                        success = submit_task_report(session, task_info['form_action'], wu, pm)
                    if not success:
                        id_match = re.search(r'/(\d+)/', curl)
                        if id_match:
                            execute_page_url = f"https://forumok.com/publisher-requests-socio/addRequest/order_id/{id_match.group(1)}?ok=1"
                            success = submit_task_proof_automatically(session, execute_page_url, wu, pm)
                    try: bot.delete_message(chat_id, wait_msg.message_id)
                    except: pass
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="exec_back_to_main"))
                    platform = get_platform_from_url(curl)
                    if success:
                        bot.send_message(chat_id,
                            f"✅ **تم تنفيذ المهمة بنجاح!**\n🌐 المنصة: {platform}",
                            parse_mode="Markdown", reply_markup=markup)
                    else:
                        bot.send_message(chat_id, "❌ فشل إرسال التقرير. تحقق من الروابط.", reply_markup=markup)
                except Exception as e:
                    try: bot.delete_message(chat_id, wait_msg.message_id)
                    except: pass
                    bot.send_message(chat_id, f"❌ خطأ: {e}")

            threading.Thread(target=_do_custom_exec, args=(custom_url, work_url, proof_msg), daemon=True).start()
            return

        elif step == 'WITHDRAW_EDIT_WALLET':
            creds = user_data_store.get(chat_id, {})
            new_wallet = text.strip()
            profile = user_sessions[chat_id].get('billing_profile', {})
            del user_sessions[chat_id]
            if not creds:
                bot.send_message(chat_id, "⚠️ يرجى تسجيل الدخول أولاً.")
                return
            if not new_wallet:
                bot.send_message(chat_id, "❌ العنوان لا يمكن أن يكون فارغاً.")
                return

            wait_msg = bot.send_message(chat_id, "⏳ جاري تحديث عنوان المحفظة...")

            def _do_update_wallet(wlt, prof):
                try:
                    session = get_authenticated_session(creds['email'], creds['password'])
                    if not session:
                        try:
                            bot.delete_message(chat_id, wait_msg.message_id)
                        except Exception:
                            pass
                        bot.send_message(chat_id, "❌ فشل تجديد الجلسة.")
                        return
                    # جلب أحدث CSRF إذا لزم
                    csrf = prof.get("csrf_token", "")
                    uid = prof.get("user_id", "")
                    pay_sys = prof.get("pay_system", "webmoney")
                    # تحديد قيمة pay_system
                    pay_sys_val = "webmoney"
                    if "toncoin" in pay_sys.lower() or "telegram" in pay_sys.lower():
                        pay_sys_val = "toncoin"
                    elif "card" in pay_sys.lower() or "карта" in pay_sys.lower():
                        pay_sys_val = "card"

                    success = update_billing_profile(session, pay_sys_val, wlt, csrf, uid)
                    try:
                        bot.delete_message(chat_id, wait_msg.message_id)
                    except Exception:
                        pass
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("💸 فتح قائمة السحب", callback_data="withdraw_menu"))
                    markup.add(types.InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main"))
                    if success:
                        bot.send_message(chat_id,
                            f"✅ **تم تحديث عنوان المحفظة بنجاح!**\n\n"
                            f"📬 العنوان الجديد: `{wlt}`",
                            parse_mode="Markdown", reply_markup=markup)
                    else:
                        bot.send_message(chat_id, "❌ فشل تحديث عنوان المحفظة.", reply_markup=markup)
                except Exception as e:
                    try:
                        bot.delete_message(chat_id, wait_msg.message_id)
                    except Exception:
                        pass
                    bot.send_message(chat_id, f"❌ خطأ: {e}")

            threading.Thread(target=_do_update_wallet, args=(new_wallet, profile), daemon=True).start()
            return

    if "@" in text and not check_and_load_session_silently(chat_id):
        delete_transient_message(bot, chat_id)
        user_sessions[chat_id] = {'step': 'WAITING_PASSWORD', 'email': text}
        msg = bot.send_message(chat_id, "🔐 أدخل كلمة المرور:")
        user_transient_messages[chat_id] = msg.message_id
        return

    if text.isdigit():
        if chat_id not in user_numbered_tasks or not user_numbered_tasks[chat_id]:
            bot.send_message(chat_id, "⚠️ اضغط على زر 'اصطحاب يدوي' أولاً لاستدعاء القائمة:")
            return
        index = int(text) - 1
        if 0 <= index < len(user_numbered_tasks[chat_id]):
            creds = user_data_store.get(chat_id)
            if not creds:
                bot.send_message(chat_id, "⚠️ يرجى تسجيل الدخول أولاً.")
                return
            selected_task = user_numbered_tasks[chat_id][index]

            session = get_authenticated_session(creds['email'], creds['password'])
            if session:
                last_take = last_take_time.get(chat_id, 0)
                if time.time() - last_take < TAKE_COOLDOWN:
                    remaining = int(TAKE_COOLDOWN - (time.time() - last_take))
                    bot.send_message(chat_id, f"⏳ انتظر {remaining} ثانية قبل المحاولة القادمة:")
                    return

                success = take_task_via_post(session, selected_task['task_page'])
                if success:
                    last_take_time[chat_id] = time.time()
                    bot.send_message(chat_id, f"✅ تم اصطحاب المهمة {text}\n💰 السعر: {selected_task['price']} RUB\n⏱️ الوقت: {selected_task['duration']}")

                    if auto_execute_status.get(chat_id, False):
                        saved_templates = cloud_get_auto_tasks(chat_id)
                        task_desc_lower = selected_task.get('description', '').lower()
                        task_url_str = selected_task['task_page'].lower()
                        for tmpl in saved_templates:
                            kw = tmpl['keyword'].lower()
                            if kw in task_desc_lower or kw in task_url_str:
                                order_id_match = re.search(r"/(\d+)/", selected_task['task_page'])
                                if order_id_match:
                                    ord_id = order_id_match.group(1)
                                    execute_page_url = f"https://forumok.com/publisher-requests-socio/addRequest/order_id/{ord_id}?ok=1"
                                    if submit_task_proof_automatically(session, execute_page_url, tmpl.get('work_url'), tmpl.get('proof_msg')):
                                        bot.send_message(chat_id, "✅ تم إرسال تقرير الإثبات تلقائياً بنجاح.")
                                break
                else:
                    bot.send_message(chat_id, f"❌ فشل اصطحاب المهمة {text}")
        else:
            bot.send_message(chat_id, "❌ رقم غير صحيح.")

