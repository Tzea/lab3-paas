"""Tao tai de kiem tra auto-scaling cua Render (chi dung thu vien chuan).

Cach dung:  python loadtest.py https://TEN-APP.onrender.com [so_luong] [so_giay]
Mac dinh:   40 luong, chay 600 giay (10 phut), moi request ton ~300 ms CPU tren server.
"""
import json
import sys
import threading
import time
import urllib.request
from collections import Counter

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

BASE = sys.argv[1].rstrip("/")
THREADS = int(sys.argv[2]) if len(sys.argv) > 2 else 40
DURATION = int(sys.argv[3]) if len(sys.argv) > 3 else 600
URL = f"{BASE}/stress?ms=300"

instances = Counter()
errors = Counter()
lock = threading.Lock()
stop_at = time.time() + DURATION


def worker():
    while time.time() < stop_at:
        try:
            with urllib.request.urlopen(URL, timeout=30) as resp:
                data = json.loads(resp.read())
            with lock:
                instances[data.get("instance", "?")] += 1
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors[type(exc).__name__] += 1


def reporter():
    start = time.time()
    while time.time() < stop_at:
        time.sleep(10)
        with lock:
            total = sum(instances.values())
            print(f"[{int(time.time() - start):>3}s] request thanh cong: {total:>5} | "
                  f"so instance da phuc vu: {len(instances)} | loi: {sum(errors.values())}")


print(f"Tao tai toi {URL} voi {THREADS} luong trong {DURATION} giay...")
threads = [threading.Thread(target=worker, daemon=True) for _ in range(THREADS)]
for t in threads:
    t.start()
threading.Thread(target=reporter, daemon=True).start()
for t in threads:
    t.join()

print("\n===== KET QUA =====")
print(f"Tong request thanh cong: {sum(instances.values())}")
print(f"So instance khac nhau da phuc vu: {len(instances)}")
for inst, n in instances.most_common():
    print(f"  ...{inst[-12:]}: {n} request")
if errors:
    print(f"Loi: {dict(errors)}")
