import socket, requests, subprocess, sys

print("=" * 40)

# 1. DNS
try:
    ip = socket.gethostbyname("api.telegram.org")
    print(f"✅ DNS : {ip}")
except Exception as e:
    print(f"❌ DNS : {e}")

# 2. TCP Port 443
try:
    s = socket.create_connection(("api.telegram.org", 443), timeout=5)
    s.close()
    print("✅ TCP 443 : متاح")
except Exception as e:
    print(f"❌ TCP 443 : {e}")

# 3. HTTPS
try:
    r = requests.get("https://api.telegram.org", timeout=5)
    print(f"✅ HTTPS : {r.status_code}")
except Exception as e:
    print(f"❌ HTTPS : {e}")

# 4. Google (للمقارنة)
try:
    r = requests.get("https://google.com", timeout=5)
    print(f"✅ Google : {r.status_code}")
except Exception as e:
    print(f"❌ Google : {e}")

print("=" * 40)