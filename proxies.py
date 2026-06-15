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

# ==========================================
# دوال جلب ومعالجة البروكسيات الديناميكية
# ==========================================

def fetch_raw_proxies():
    """جلب قائمة البروكسيات الخام من المصدر"""
    try:
        r = requests.get(PROXY_SOURCE_URL, timeout=20)
        if r.status_code == 200:
            lines = r.text.strip().split("\n")
            proxies = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # تنسيق: protocol://ip:port أو ip:port
                if "://" in line:
                    proxies.append(line)
                else:
                    proxies.append(f"http://{line}")
            print(f"[PROXY] تم جلب {len(proxies)} بروكسي خام")
            return proxies
    except Exception as e:
        print(f"[PROXY] خطأ في جلب البروكسيات: {e}")
    return []

def test_single_proxy(proxy_url):
    """اختبار بروكسي واحد وقياس سرعة الاستجابة مع جلب الدولة والمدينة"""
    try:
        start = time.time()
        r = requests.get(
            "http://ip-api.com/json/?fields=status,country,countryCode,city,regionName,isp,query",
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        latency = round(time.time() - start, 3)
        if r.status_code == 200:
            try:
                data = r.json()
                # ip-api يُرجع IP الحقيقي للبروكسي تلقائياً (query = الـ IP الخارجي)
                ip = data.get("query", "").strip()
                if data.get("status") == "success":
                    country = data.get("country", "Unknown")
                    country_code = data.get("countryCode", "??")
                    city = data.get("city", "")
                    region = data.get("regionName", "")
                    isp = data.get("isp", "")
                else:
                    country, country_code, city, region, isp = "Unknown", "??", "", "", ""
            except Exception:
                ip, country, country_code, city, region, isp = "", "Unknown", "??", "", "", ""
            return {
                "address": proxy_url,
                "latency": latency,
                "ip": ip,
                "country": country,
                "country_code": country_code,
                "city": city,
                "region": region,
                "isp": isp,
                "alive": True
            }
    except Exception:
        pass
    return {"address": proxy_url, "latency": 999.0, "ip": "", "country": "Unknown", "country_code": "??", "city": "", "region": "", "isp": "", "alive": False}

def test_proxies_batch(proxy_list, max_workers=15):
    """اختبار مجموعة بروكسيات بالتوازي"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(test_single_proxy, p): p for p in proxy_list}
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result["alive"]:
                    results.append(result)
            except Exception:
                pass
    # ترتيب حسب السرعة
    results.sort(key=lambda x: x["latency"])
    return results

# ==========================================
# 🧠 نظام المخزن الاحتياطي الذكي
# ==========================================

def _fill_reserve_pool_worker():
    """
    ملء المخزن الاحتياطي في الخلفية.
    يجلب ويختبر بروكسيات كافية ليحتفظ بـ (حسابات+1)×20 جاهزة.
    يُشغَّل تلقائياً عند:
      - بدء التشغيل
      - تسجيل دخول ناجح (لتعويض ما استُهلك)
      - انخفاض الاحتياطي تحت الحد
    """
    global _reserve_fill_running
    # منع التزامن مع refresh_dynamic_proxies
    if not _proxy_fetch_semaphore.acquire(blocking=False):
        print("[RESERVE] عملية جلب أخرى جارية، تم تخطي هذه الدورة")
        return
    with reserve_pool_lock:
        if _reserve_fill_running:
            _proxy_fetch_semaphore.release()
            return
        _reserve_fill_running = True

    try:
        needed = _needed_reserve_size()
        with reserve_pool_lock:
            current_alive = [p for p in proxy_reserve_pool["proxies"] if p.get("status", "active") != "dead"]

        if len(current_alive) >= needed:
            print(f"[RESERVE] الاحتياطي كافٍ: {len(current_alive)}/{needed}")
            with reserve_pool_lock:
                proxy_reserve_pool["proxies"] = current_alive
            return

        deficit = needed - len(current_alive)
        print(f"[RESERVE] الاحتياطي يحتاج {deficit} بروكسي إضافي (المستهدف: {needed})")

        raw_proxies = fetch_raw_proxies()
        if not raw_proxies:
            print("[RESERVE] فشل جلب البروكسيات الخام")
            return

        # استبعاد البروكسيات المستخدمة مسبقاً
        with proxy_store_lock:
            used_addresses = set()
            for store in dynamic_proxy_store.values():
                for p in store.get("proxies", []):
                    used_addresses.add(p["address"])
        with reserve_pool_lock:
            for p in proxy_reserve_pool["proxies"]:
                used_addresses.add(p["address"])

        candidates = [p for p in raw_proxies if p not in used_addresses]
        sample_size = min(len(candidates), deficit * 8)
        if sample_size < deficit:
            # إذا المرشحون قليلون نوسع العينة
            sample_size = min(len(raw_proxies), needed * 6)
            candidates = raw_proxies

        sample = random.sample(candidates, sample_size)
        print(f"[RESERVE] اختبار {sample_size} بروكسي لتعبئة الاحتياطي...")
        new_alive = test_proxies_batch(sample, max_workers=15)

        # دمج مع الموجود وإزالة المكرر
        with reserve_pool_lock:
            combined = current_alive + new_alive
            seen = set()
            unique = []
            for p in combined:
                if p["address"] not in seen:
                    seen.add(p["address"])
                    unique.append(p)
            unique.sort(key=lambda x: x["latency"])
            proxy_reserve_pool["proxies"] = unique
            proxy_reserve_pool["last_filled"] = time.time()
            total = len(unique)

        print(f"[RESERVE] الاحتياطي جاهز: {total} بروكسي (مستهدف: {needed})")

    except Exception as e:
        print(f"[RESERVE] خطأ في ملء الاحتياطي: {e}")
    finally:
        with reserve_pool_lock:
            _reserve_fill_running = False
        _proxy_fetch_semaphore.release()


def trigger_reserve_fill():
    """تشغيل ملء الاحتياطي في خيط خلفي منفصل"""
    threading.Thread(target=_fill_reserve_pool_worker, daemon=True).start()


def _take_from_reserve(count=20):
    """
    أخذ 'count' بروكسي من الاحتياطي للتخصيص لحساب جديد.
    يُرجع قائمة البروكسيات ويحذفها من الاحتياطي.
    بعد الأخذ يطلق تعبئة الاحتياطي تلقائياً في الخلفية.
    """
    with reserve_pool_lock:
        alive = [p for p in proxy_reserve_pool["proxies"] if p.get("status", "active") != "dead"]
        taken = alive[:count]
        proxy_reserve_pool["proxies"] = alive[count:]

    if taken:
        print(f"[RESERVE] تم أخذ {len(taken)} بروكسي من الاحتياطي (متبقٍ: {len(proxy_reserve_pool['proxies'])})")

    # دائماً أعد تعبئة الاحتياطي بعد الأخذ منه
    trigger_reserve_fill()
    return taken


def fair_distribute_proxies(alive_proxies, accounts):
    """
    التوزيع العادل للبروكسيات على الحسابات.
    
    المنطق:
    - أفضل البروكسيات (السريعة جداً) تُوزَّع بالتناوب على جميع الحسابات
      حتى لو كانت قليلة — لا حساب واحد يستأثر بها.
    - بعد توزيع الأفضل، تُكمَّل الـ20 لكل حساب بأسرع المتبقيات.
    
    مثال: 3 حسابات، 6 بروكسيات ممتازة:
      حساب1 يأخذ: #1, #4, ...
      حساب2 يأخذ: #2, #5, ...
      حساب3 يأخذ: #3, #6, ...
    ثم تُكمَّل الـ20 بالبروكسيات التالية ترتيباً.
    
    يُرجع: { email: [قائمة_بروكسيات] }
    """
    if not accounts or not alive_proxies:
        return {}

    n = len(accounts)
    result = {email: [] for email in accounts}

    # المرحلة 1: توزيع بالتناوب (round-robin) للبروكسيات الأسرع
    # نعتبر "ممتازة" أي بروكسي latency <= 1.5 ثانية
    fast_proxies = [p for p in alive_proxies if p.get("latency", 999) <= 1.5]
    slow_proxies = [p for p in alive_proxies if p.get("latency", 999) > 1.5]

    # توزيع السريعة بالتناوب
    for i, proxy in enumerate(fast_proxies):
        email = accounts[i % n]
        if len(result[email]) < PROXIES_PER_ACCOUNT:
            result[email].append(proxy)

    # المرحلة 2: إكمال الـ20 لكل حساب من البروكسيات المتوسطة/البطيئة
    slow_idx = 0
    for email in accounts:
        while len(result[email]) < PROXIES_PER_ACCOUNT and slow_idx < len(slow_proxies):
            result[email].append(slow_proxies[slow_idx])
            slow_idx += 1

    return result


def get_proxy_country(ip):
    """جلب دولة البروكسي (مجاناً)"""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=country,countryCode", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return data.get("country", "Unknown"), data.get("countryCode", "??")
    except Exception:
        pass
    return "Unknown", "??"

def latency_to_speed_label(latency):
    """تحويل زمن الاستجابة إلى تصنيف نصي"""
    if latency <= 1.0:
        return "🟢 سريع"
    elif latency <= 3.0:
        return "🟡 متوسط"
    else:
        return "🔴 بطيء"

def save_proxies_to_db(proxies_data, assigned_to):
    """حفظ البروكسيات في قاعدة البيانات"""
    try:
        # حذف البروكسيات القديمة لهذا الحساب أولاً
        del_headers = {**DB_HEADERS, "Prefer": "return=minimal"}
        requests.delete(
            f"{DB_PROXY_URL}?assigned_to=eq.{assigned_to}",
            headers=del_headers,
            timeout=10
        )
        # إضافة البروكسيات الجديدة
        for p in proxies_data:
            payload = {
                "proxy_address": p["address"],
                "protocol": p["address"].split("://")[0] if "://" in p["address"] else "http",
                "latency": p.get("latency", 999.0),
                "stability_score": p.get("stability", 80),
                "status": "active",
                "assigned_to": assigned_to,
                "last_checked": datetime.now(timezone.utc).isoformat()
            }
            try:
                requests.post(DB_PROXY_URL, json=payload, headers=DB_HEADERS, timeout=5)
            except Exception:
                pass
    except Exception as e:
        print(f"[PROXY DB] خطأ في الحفظ: {e}")

def load_proxies_from_db(assigned_to):
    """تحميل البروكسيات من قاعدة البيانات لحساب معين"""
    try:
        r = requests.get(
            f"{DB_PROXY_URL}?assigned_to=eq.{assigned_to}&status=eq.active&order=latency.asc",
            headers=DB_HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

def mark_proxy_dead_in_db(proxy_address):
    """تحديث حالة البروكسي إلى dead في قاعدة البيانات"""
    try:
        requests.patch(
            f"{DB_PROXY_URL}?proxy_address=eq.{requests.utils.quote(proxy_address)}",
            json={"status": "dead"},
            headers={**DB_HEADERS, "Prefer": "return=minimal"},
            timeout=5
        )
    except Exception:
        pass

def refresh_dynamic_proxies():
    """
    العملية الرئيسية: جلب واختبار وتوزيع البروكسيات بالعدل على الحسابات الديناميكية.
    يتم استدعاء هذه الدالة كل 30 دقيقة من الخيط الخلفي.

    الجديد:
    ────────────────────────────────────────
    1. التوزيع العادل: أسرع البروكسيات تُوزَّع بالتناوب (round-robin) لا لحساب واحد.
    2. بعد الانتهاء يُعبَّأ المخزن الاحتياطي تلقائياً لتجهيز الحساب القادم.
    3. Semaphore يمنع التشغيل المتزامن مع reserve_fill.
    ────────────────────────────────────────
    """
    global last_proxy_refresh_time

    # منع التزامن مع _fill_reserve_pool_worker
    if not _proxy_fetch_semaphore.acquire(blocking=False):
        print("[PROXY] عملية جلب أخرى جارية، تأجيل refresh...")
        last_proxy_refresh_time = time.time()
        return

    # تحديد الحسابات الديناميكية (غير المستثناة) من جميع المصادر
    all_dynamic = set()
    for cid in user_data_store:
        em = user_data_store[cid].get("email", "").lower().strip()
        if em and em not in EXEMPT_ACCOUNTS:
            all_dynamic.add(em)
    # أضف أيضاً الحسابات المسجلة في active_accounts
    with active_accounts_lock:
        for accs in active_accounts.values():
            for em in accs:
                if em and em not in EXEMPT_ACCOUNTS:
                    all_dynamic.add(em.lower().strip())

    dynamic_accounts = list(all_dynamic)

    if not dynamic_accounts:
        print("[PROXY] لا توجد حسابات ديناميكية نشطة — تعبئة الاحتياطي فقط")
        last_proxy_refresh_time = time.time()
        trigger_reserve_fill()
        return

    # المطلوب = حسابات × 20 + احتياطي لحساب قادم
    needed_for_accounts = len(dynamic_accounts) * PROXIES_PER_ACCOUNT
    needed_total = needed_for_accounts + PROXIES_PER_ACCOUNT  # +20 للاحتياطي
    print(f"[PROXY] الحسابات: {len(dynamic_accounts)} | المطلوب: {needed_total} بروكسي")

    # جلب البروكسيات الخام
    raw_proxies = fetch_raw_proxies()
    if not raw_proxies:
        print("[PROXY] فشل جلب البروكسيات الخام")
        last_proxy_refresh_time = time.time()
        return

    # اختبار عينة (×4 بدل ×7 لتقليل ضغط الخيوط)
    sample_size = min(len(raw_proxies), needed_total * 4)
    sample = random.sample(raw_proxies, sample_size)

    print(f"[PROXY] اختبار {sample_size} بروكسي...")
    alive_proxies = test_proxies_batch(sample, max_workers=15)
    print(f"[PROXY] {len(alive_proxies)} بروكسي يعمل")

    # إذا لم يكفِ، نجلب دفعة إضافية
    if len(alive_proxies) < needed_total:
        remaining = [p for p in raw_proxies if p not in sample]
        if remaining:
            extra_size = min(len(remaining), needed_total * 4)
            extra = random.sample(remaining, extra_size)
            extra_alive = test_proxies_batch(extra, max_workers=15)
            alive_proxies.extend(extra_alive)
            # إزالة مكررات + إعادة ترتيب
            seen = set()
            unique = []
            for p in alive_proxies:
                if p["address"] not in seen:
                    seen.add(p["address"])
                    unique.append(p)
            unique.sort(key=lambda x: x["latency"])
            alive_proxies = unique

    # ── التوزيع العادل على الحسابات ──
    distribution = fair_distribute_proxies(alive_proxies[:needed_for_accounts], dynamic_accounts)

    with proxy_store_lock:
        for email, account_proxies in distribution.items():
            if not account_proxies:
                continue
            # إضافة stability score
            for i, p in enumerate(account_proxies):
                p["stability"] = max(50, 100 - i * 2)

            dynamic_proxy_store[email] = {
                "proxies": account_proxies,
                "current_index": 0,
                "last_updated": time.time()
            }
            enqueue_db_save(save_proxies_to_db, account_proxies, email)
            fast = sum(1 for p in account_proxies if p.get("latency", 9) <= 1.5)
            print(f"[PROXY] {email}: {len(account_proxies)} بروكسي ({fast} سريع جداً)")

    last_proxy_refresh_time = time.time()
    print("[PROXY] اكتمل تحديث البروكسيات الديناميكية بالتوزيع العادل")
    _proxy_fetch_semaphore.release()

    # ── تعبئة الاحتياطي من البروكسيات المتبقية فوراً ──
    used_in_distribution = set()
    for proxies_list in distribution.values():
        for p in proxies_list:
            used_in_distribution.add(p["address"])
    leftover = [p for p in alive_proxies if p["address"] not in used_in_distribution]
    if leftover:
        with reserve_pool_lock:
            existing = proxy_reserve_pool.get("proxies", [])
            combined = existing + leftover
            seen2 = set()
            unique2 = []
            for p in combined:
                if p["address"] not in seen2:
                    seen2.add(p["address"])
                    unique2.append(p)
            unique2.sort(key=lambda x: x["latency"])
            proxy_reserve_pool["proxies"] = unique2
            proxy_reserve_pool["last_filled"] = time.time()
        print(f"[RESERVE] تم تحديث الاحتياطي: {len(unique2)} بروكسي")
    else:
        # طلب تعبئة من المصدر في الخلفية
        trigger_reserve_fill()

def get_current_proxy_for_account(email):
    """
    إرجاع البروكسي الحالي النشط للحساب الديناميكي.
    في حالة الفشل، يتم التبديل تلقائياً للاحتياطي.
    """
    email_lower = email.lower().strip()

    if email_lower in EXEMPT_ACCOUNTS:
        return None  # الحسابات المستثناة تدار بنظام منفصل

    with proxy_store_lock:
        store = dynamic_proxy_store.get(email_lower)
        if not store or not store["proxies"]:
            return None

        idx = store.get("current_index", 0)
        proxies = store["proxies"]

        # إيجاد أول بروكسي نشط
        for i in range(len(proxies)):
            actual_idx = (idx + i) % len(proxies)
            p = proxies[actual_idx]
            if p.get("status", "active") != "dead":
                store["current_index"] = actual_idx
                return p["address"]

    return None

def failover_proxy_for_account(email, failed_address):
    """
    عند فشل البروكسي الحالي: تحديد الفاشل وتفعيل الاحتياطي فوراً.
    """
    email_lower = email.lower().strip()

    with proxy_store_lock:
        store = dynamic_proxy_store.get(email_lower)
        if not store:
            return None

        proxies = store["proxies"]
        # تحديد البروكسي الفاشل
        for p in proxies:
            if p["address"] == failed_address:
                p["status"] = "dead"
                break

        # التبديل للتالي
        current_idx = store.get("current_index", 0)
        for i in range(1, len(proxies) + 1):
            next_idx = (current_idx + i) % len(proxies)
            if proxies[next_idx].get("status", "active") != "dead":
                store["current_index"] = next_idx
                new_proxy = proxies[next_idx]["address"]
                print(f"[PROXY] Failover لـ {email}: {failed_address} → {new_proxy}")
                # تحديث DB في الخلفية
                enqueue_db_save(mark_proxy_dead_in_db, failed_address)
                return new_proxy

    return None

def get_proxy_info_for_display(email):
    """
    إرجاع معلومات البروكسي الحالي للعرض في الواجهة.
    """
    email_lower = email.lower().strip()

    if email_lower in EXEMPT_ACCOUNTS:
        # معلومات الحساب المستثنى
        proxies = ACCOUNT_PROXIES.get(email_lower, [])
        if proxies:
            return {
                "address": proxies[0],
                "ip": proxies[0].split(":")[0],
                "country": "Static",
                "speed": "🔵 ثابت",
                "type": "static"
            }
        return None

    with proxy_store_lock:
        store = dynamic_proxy_store.get(email_lower)
        if not store or not store["proxies"]:
            return None

        idx = store.get("current_index", 0)
        proxies = store["proxies"]

        for i in range(len(proxies)):
            actual_idx = (idx + i) % len(proxies)
            p = proxies[actual_idx]
            if p.get("status", "active") != "dead":
                addr = p["address"]
                ip = p.get("ip", addr.split("://")[-1].split(":")[0])
                latency = p.get("latency", 999.0)
                speed = latency_to_speed_label(latency)

                # استخراج العنوان بدون البروتوكول
                display_addr = addr.replace("http://", "").replace("https://", "").replace("socks5://", "")

                return {
                    "address": display_addr,
                    "ip": ip,
                    "country": p.get("country", "Unknown"),
                    "country_code": p.get("country_code", "??"),
                    "city": p.get("city", ""),
                    "region": p.get("region", ""),
                    "isp": p.get("isp", ""),
                    "speed": speed,
                    "latency": latency,
                    "type": "dynamic"
                }
    return None


# ==========================================
# دوال البروكسي للحسابات المستثناة (ثابتة)
# ==========================================
def get_fastest_proxy_exempt(email):
    """أسرع بروكسي للحسابات المستثناة (5 بروكسيات ثابتة)"""
    proxies = ACCOUNT_PROXIES.get(email.lower().strip())
    if not proxies:
        return None
    fastest_proxy = None
    best_response_time = float('inf')
    for prx in proxies:
        try:
            proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{prx}"
            start_time = time.time()
            r = requests.head(BASE_URL, headers=HEADERS, proxies={"http": proxy_url, "https": proxy_url}, timeout=3)
            elapsed = time.time() - start_time
            if elapsed < best_response_time:
                best_response_time = elapsed
                fastest_proxy = prx
        except Exception:
            continue
    if not fastest_proxy:
        fastest_proxy = random.choice(proxies)
    return fastest_proxy

def get_first_alive_proxy(raw_proxies, batch_size=100, max_wait=25):
    """
    يختبر البروكسيات دفعة واحدة بالتوازي ويُرجع أول بروكسي يعمل فور وجوده.
    max_wait: الحد الأقصى للانتظار بالثواني.
    يُرجع dict البروكسي الأسرع أو None.
    """
    sample = random.sample(raw_proxies, min(len(raw_proxies), batch_size))
    first_result = [None]
    found_event = threading.Event()

    def _test(proxy_url):
        if found_event.is_set():
            return
        result = test_single_proxy(proxy_url)
        if result["alive"] and not found_event.is_set():
            first_result[0] = result
            found_event.set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(_test, p) for p in sample]
        found_event.wait(timeout=max_wait)
        # إلغاء الخيوط المتبقية بأسرع وقت
        for f in futures:
            f.cancel()

    return first_result[0]


def _background_fill_proxies(email_lower, raw_proxies, first_proxy):
    """
    يعمل في الخلفية بعد تسجيل الدخول:
    1. يأخذ من المخزن الاحتياطي أولاً (سريع جداً).
    2. إن لم يكفِ يختبر من raw_proxies.
    3. يضمن أن first_proxy في المقدمة.
    4. بعد الانتهاء يطلق تعبئة الاحتياطي من جديد.
    """
    try:
        # 1. أخذ ما يكفي من الاحتياطي أولاً
        reserve_taken = _take_from_reserve(PROXIES_PER_ACCOUNT)
        alive = list(reserve_taken)

        # 2. إذا لم يكفِ الاحتياطي، اختبر من raw_proxies
        if len(alive) < PROXIES_PER_ACCOUNT and raw_proxies:
            # استبعد ما أخذناه من الاحتياطي
            reserve_addrs = {p["address"] for p in alive}
            candidates = [p for p in raw_proxies if p not in reserve_addrs]
            needed_extra = (PROXIES_PER_ACCOUNT - len(alive)) * 8
            sample_size = min(len(candidates), needed_extra)
            if sample_size > 0:
                sample = random.sample(candidates, sample_size)
                print(f"[PROXY-BG] {email_lower}: اختبار {sample_size} إضافي (الاحتياطي غير كافٍ)...")
                extra_alive = test_proxies_batch(sample, max_workers=15)
                alive.extend(extra_alive)

        # 3. تأكد من أن first_proxy في المقدمة
        if first_proxy:
            addr = first_proxy["address"]
            alive = [p for p in alive if p["address"] != addr]
            alive.insert(0, first_proxy)

        # 4. فرز حسب السرعة وأخذ أفضل 20
        alive.sort(key=lambda x: x["latency"])
        account_proxies = alive[:PROXIES_PER_ACCOUNT]
        for i, p in enumerate(account_proxies):
            p["stability"] = max(50, 100 - i * 2)

        with proxy_store_lock:
            dynamic_proxy_store[email_lower] = {
                "proxies": account_proxies,
                "current_index": 0,
                "last_updated": time.time()
            }
        enqueue_db_save(save_proxies_to_db, account_proxies, email_lower)
        fast = sum(1 for p in account_proxies if p.get("latency", 9) <= 1.5)
        print(f"[PROXY-BG] {email_lower}: {len(account_proxies)} بروكسي جاهز ({fast} سريع جداً)")

        # 5. تعبئة الاحتياطي في الخلفية لتجهيز الحساب القادم
        trigger_reserve_fill()

    except Exception as e:
        print(f"[PROXY-BG] خطأ: {e}")


def _ensure_proxy_for_account(email_lower, blocking=False, timeout=30):
    """
    للاستخدام الخلفي الدوري فقط (تحديث كل 30 دقيقة).
    لتسجيل الدخول استخدم: get_first_alive_proxy + _background_fill_proxies
    """
    if email_lower in EXEMPT_ACCOUNTS:
        return
    with proxy_store_lock:
        already_has = email_lower in dynamic_proxy_store and bool(dynamic_proxy_store[email_lower].get("proxies"))
    if already_has:
        return

    print(f"[PROXY] _ensure (دوري) للحساب: {email_lower}")

    def _do_fetch():
        try:
            raw_proxies = fetch_raw_proxies()
            if not raw_proxies:
                return
            first = get_first_alive_proxy(raw_proxies, batch_size=100, max_wait=20)
            if first:
                with proxy_store_lock:
                    dynamic_proxy_store[email_lower] = {
                        "proxies": [first],
                        "current_index": 0,
                        "last_updated": time.time()
                    }
            _background_fill_proxies(email_lower, raw_proxies, first)
        except Exception as e:
            print(f"[PROXY] خطأ في _ensure: {e}")

    t = threading.Thread(target=_do_fetch, daemon=True)
    t.start()
    if blocking:
        t.join(timeout=timeout)


def build_proxy_status_text(email):
    """بناء نص معلومات البروكسي للعرض في الواجهة"""
    info = get_proxy_info_for_display(email)
    if not info:
        return "🌐 البروكسي: غير متصل\n"

    # بناء سطر الدولة مع العلم إن وُجد
    country_code = info.get("country_code", "")
    country_name = info.get("country", "Unknown")
    flag = ""
    if country_code and country_code != "??":
        # تحويل رمز الدولة إلى إيموجي علم
        try:
            flag = "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in country_code.upper()) + " "
        except Exception:
            flag = ""
    country_display = f"{flag}{country_name}" if country_name != "Unknown" else "غير محدد"

    city = info.get("city", "")
    region = info.get("region", "")
    isp = info.get("isp", "")

    location_parts = [p for p in [city, region] if p]
    location_display = "، ".join(location_parts) if location_parts else "غير محدد"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🌐 **معلومات البروكسي الحالي**",
        f"📡 العنوان: `{info['address']}`",
        f"🖥️ عنوان IP: `{info['ip']}`",
        f"🗺️ الدولة: {country_display}",
        f"🏙️ المدينة: {location_display}",
    ]
    if isp:
        lines.append(f"🏢 المزود: {isp}")
    if info.get("latency") and info["latency"] < 900:
        lines.append(f"📶 زمن الاستجابة: {info['latency']}s")
    lines.append(f"⚡ الحالة: {info['speed']}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

