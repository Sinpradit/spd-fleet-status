# -*- coding: utf-8 -*-
"""ไฟล์น้ำมันดึงไม่ได้ (Google ตอบ 500/หมดเวลา) → ใช้งานจากรอบก่อน ไม่ล้มทั้งรอบ + fuel_ok=false
และ CALENDAR_ID มาจาก secret (ไม่มี = ข้ามการอ่านปฏิทินแบบไม่ล้ม) · รัน: python pipeline/test_fuel_fallback.py (ไม่ยิงเน็ต)"""
import json
import os
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402

run._osrm_fail = 99
time.sleep = lambda s: None
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def no_net(*a, **k):
    raise AssertionError("ห้ามยิงเน็ตในเทสต์")


urllib.request.urlopen = no_net

# ---------- 1) prev_fuel: งานจาก job_key รอบก่อน ----------
PREV = {"generated_at": "2026-11-25T13:30:00+07:00", "categories": [{"key": "working", "groups": [
    {"key": "flatbed", "trucks": [
        {"number": "1300", "category": "working", "job_key": "กระชับมิตร อุบลธัญกิจ-กระชับมิตร-|23 พย 69",
         "lat": 14.84, "lon": 105.11, "province": "อุบลราชธานี", "district": "เดชอุดม",
         "updated": "2026-11-25 13:25:00", "heading": 90},
        {"number": "2187", "category": "working", "job_key": "ชัยวัฒนา-|25 พย 69",
         "lat": 15.27, "lon": 104.63, "province": "อุบลราชธานี", "district": "เขื่องใน",
         "updated": "2026-11-25 13:25:00", "heading": 90},
        {"number": "3606", "category": "find_outbound", "job_key": None,
         "lat": 15.10, "lon": 104.57, "province": "ศรีสะเกษ", "district": "กันทรารมย์",
         "updated": "2026-11-25 13:25:00", "heading": 90}]}]}]}
pf = run.prev_fuel(PREV)
check("prev_fuel แยกเส้นทาง/วันที่จาก job_key",
      pf.get("1300") == {"route": "กระชับมิตร อุบลธัญกิจ-กระชับมิตร-", "date": "23 พย 69"}, pf.get("1300"))
check("prev_fuel ข้ามคันที่ไม่มีงาน", "3606" not in pf and len(pf) == 2, pf)
check("prev_fuel รอบก่อนว่าง = ไม่มีงาน (ไม่ล้ม)", run.prev_fuel({}) == {})

# ---------- 2) CALENDAR_ID จาก secret ----------
run.CALENDAR_ID = ""
try:
    run.fetch_calendar_jobs("{}", None)
    check("ไม่มี CALENDAR_ID = แจ้งชัด ไม่ยิงปฏิทินด้วย id ว่าง", False, "no exception")
except RuntimeError as e:
    check("ไม่มี CALENDAR_ID = แจ้งชัด ไม่ยิงปฏิทินด้วย id ว่าง", "CALENDAR_ID" in str(e), e)
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py"), encoding="utf-8").read()
check("ไม่มีอีเมลในโค้ด (repo public)", "@gmail.com" not in src)

# ---------- 3) main() ทั้งรอบ ตอนไฟล์น้ำมันดึงไม่ได้ ----------
work = tempfile.mkdtemp()
os.chdir(work)
with open("fleet-status.json", "w", encoding="utf-8") as f:
    json.dump(PREV, f, ensure_ascii=False)
os.environ.update(DTC_TOKEN="x", GDRIVE_SA_KEY="{}", GITHUB_EVENT_NAME="schedule")
RT = [{"truck_name": f"70-{t['number']}", "lat": t["lat"], "lon": t["lon"], "province_th": t["province"],
       "district_th": t["district"], "heading": 90, "gps_speed": 0, "status_name_th": "รถจอด",
       "time": "2026-11-25 13:40:00"} for t in run._iter_trucks(PREV)]


def fuel_500(svc):
    raise RuntimeError("HttpError 500 when requesting .../export (Internal Error)")


run._dtc_down = False
run.pull_dtc = lambda token: ([], RT)
run.fetch_pois = lambda token: {}
run.fetch_history = lambda *a, **k: []
run.drive_service = lambda sa: None
run.download_fuel = fuel_500
run.fetch_master = lambda svc: (["1300", "2187", "3606"], {"1300": "เอ็ม2", "2187": "เทน", "3606": "คอม"})
run.fetch_gps2 = lambda svc, now: {}
run.load_manual_groups = lambda *a, **k: {}
run.fetch_calendar_jobs = lambda sa, now: []
try:
    run.main()
    check("main ไม่ล้มตอนไฟล์น้ำมันดึงไม่ได้", True)
except BaseException as e:   # noqa: BLE001
    check("main ไม่ล้มตอนไฟล์น้ำมันดึงไม่ได้", False, repr(e))
doc = json.load(open("fleet-status.json", encoding="utf-8"))
m = {t["number"]: t for t in run._iter_trucks(doc)}
check("fuel_ok = false", doc.get("fuel_ok") is False, doc.get("fuel_ok"))
check("งานของ 1300 ยังอยู่ (จากรอบก่อน)", m["1300"].get("job_key") == PREV["categories"][0]["groups"][0]["trucks"][0]["job_key"],
      m["1300"].get("job_key"))
check("1300 ยังฝั่งกำลังไป (ลงงานแล้วยังไม่ออก)", m["1300"]["category"] == "working" and m["1300"].get("leg") == "out",
      (m["1300"]["category"], m["1300"].get("reason")))
check("คันที่ไม่มีงานยังไม่มีงาน", not m["3606"].get("job_key"), m["3606"].get("job_key"))

print("\nALL PASS" if not fails else f"\n{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
