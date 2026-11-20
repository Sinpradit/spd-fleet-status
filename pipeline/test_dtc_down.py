# -*- coding: utf-8 -*-
"""DTC ล่ม: pipeline ต้องไม่ล้มทั้งรอบ — ส่วนอื่นอัปเดตต่อ, รถ DTC ใช้ตำแหน่งล่าสุด + ป้าย "GPS ขาด"
รัน: python pipeline/test_dtc_down.py   (ไม่ยิงเน็ตจริง — แทนที่ urlopen/Drive ด้วยของปลอม)"""
import json
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run    # noqa: E402
import trips  # noqa: E402

run._osrm_fail = 99            # ปิด OSRM (ใช้ระยะทางตรง ไม่ยิงเน็ต)
time.sleep = lambda s: None    # ไม่รอจริงระหว่างลองซ้ำ
REAL_URLOPEN = urllib.request.urlopen
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


# ---------- 1) ตัดวงจร DTC: ค้าง 2 ครั้ง = เลิกเรียกทั้งรอบ ----------
calls = []


def hang(req, timeout=None, context=None):
    calls.append(req.full_url)
    raise TimeoutError("The read operation timed out")


def reset(req, timeout=None, context=None):
    calls.append(req.full_url)
    raise ConnectionResetError(104, "Connection reset by peer")


urllib.request.urlopen = hang
run._dtc_down = False
try:
    run.dtc_post("/getVehicleMaster", {})
    check("timeout ต้อง raise", False, "no exception")
except TimeoutError:
    check("timeout ต้อง raise", True)
check("ค้าง 2 ครั้งแล้วเลิก (ไม่ลองครบ 4)", len(calls) == 2, f"calls={len(calls)}")
check("ตัดวงจรแล้ว", not run.dtc_available())
calls.clear()
check("POI ตอบว่างทันที ไม่เรียก DTC", run.fetch_pois("t") == {} and not calls, f"calls={calls}")
check("ประวัติตอบว่างทันที", run.fetch_history("t", "g", "a", "b") == [] and not calls)

urllib.request.urlopen = reset
run._dtc_down = False
calls.clear()
try:
    run.dtc_post("/x", {})
except ConnectionResetError:
    pass
check("หลุดชั่วคราว (reset) ยังลองครบ 4", len(calls) == 4, f"calls={len(calls)}")
check("reset ไม่ตัดวงจร", run.dtc_available())
urllib.request.urlopen = REAL_URLOPEN

# ---------- ข้อมูลรอบก่อน (ก่อน DTC ล่ม) ----------
NOW = datetime.now(timezone(timedelta(hours=7)))
TODAY_TH = run.thai_today(NOW)
PREV = {"generated_at": "2026-11-18T14:35:02+07:00", "categories": [
    {"key": "working", "groups": [
        {"key": "flatbed", "trucks": [
            {"number": "3637", "group": "flatbed", "group_src": "dtc", "category": "working",
             "province": "ศรีสะเกษ", "district": "เมืองศรีสะเกษ", "lat": 15.10, "lon": 104.33,
             "heading": 270, "updated": "2026-11-18 14:31:05",
             "at_station": "เจียเม้ง ศรีสะเกษ", "reason": "x"},
            {"number": "4100", "group": "flatbed", "group_src": "code", "category": "working",
             "province": "สระบุรี", "district": None, "lat": 14.50, "lon": 100.90,
             "heading": 90, "updated": "2026-11-18 14:30:00", "reason": "x · GPS เจ้าที่ 2"}]},
        {"key": "dump", "trucks": [
            {"number": "4200", "group": "dump", "group_src": "dtc", "category": "working",
             "province": "ศรีสะเกษ", "district": "กันทรารมย์", "lat": 15.12, "lon": 104.56,
             "heading": 90, "updated": "2026-11-18 14:29:00", "reason": "x"}]}]},
    {"key": "parked", "groups": [
        {"key": "pen", "trucks": [
            {"number": "1268", "group": "pen", "group_src": "dtc", "category": "parked",
             "province": "ศรีสะเกษ", "district": "เมืองศรีสะเกษ", "lat": 15.11, "lon": 104.32,
             "updated": "2026-11-18 14:00:00", "at_station": "สินประดิษฐ์"}]}]}]}
FUEL = {"3637": {"route": "เจียเม้ง-นนทบุรี-", "date": TODAY_TH},          # งานใหม่ลงหลัง DTC ล่ม
        "4100": {"route": "เจียเม้ง-นนทบุรี-ไทซิง-เมืองวัสดุ", "date": "1 พย 69"},
        "4200": {"route": "ทอย ชัยวัฒนา-เจียเม้ง (60)", "date": TODAY_TH}}
ROSTER = ["1268", "3637", "4100", "4200"]
DRIVERS = {"3637": "สอ", "4100": "เล่", "4200": "ตั้ม"}           # 1268 ไม่มีคนขับ = รถจอด
# เวลา GPS2 อิงนาฬิกาจริง (main ใช้เวลาจริง + ตรวจ GPS ขาดเมื่อตำแหน่งเก่าเกิน 1 ชม.) → ของสด 10 นาที
GPS2_TIME = (NOW - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
GPS2 = {"4100": {"truck_name": "70-4100", "lat": 14.60, "lon": 101.00, "gps_speed": 60,
                 "heading": 90, "time": GPS2_TIME, "province_th": "สระบุรี",
                 "district_th": None, "status_name_th": "รถวิ่ง", "_gps2": True,
                 "_fuel": 80, "_stale": False}}


def by_num(trucks):
    return {t["number"]: t for t in trucks}


# ---------- 2) classify ด้วยตำแหน่งค้างจากรอบก่อน ----------
run._dtc_down = True
rt = run.stale_realtime(PREV)
pois = run.stale_pois(PREV)
t = by_num(run.classify([], rt, FUEL, {TODAY_TH}, set(), pois, roster=ROSTER,
                        drivers=DRIVERS, gps2=GPS2, prev_pos={}, future_dates=set(),
                        manual_groups={}))
a = t["3637"]
check("3637 ใช้งานใหม่จากไฟล์น้ำมัน", (a.get("job_key") or "").startswith("เจียเม้ง-นนทบุรี-"), a.get("job_key"))
check("3637 ป้าย GPS ขาด + เวลา", "GPS ขาด (ตำแหน่งล่าสุด 14:31)" in a["reason"], a["reason"])
check("3637 ตำแหน่งเดิม", (a["lat"], a["lon"]) == (15.10, 104.33))
check("3637 สถานีเดิม", a.get("at_station") == "เจียเม้ง ศรีสะเกษ", a.get("at_station"))
check("3637 ไม่มี ETA", a.get("eta_hours") is None and "อีก ~" not in a["reason"], a["reason"])
check("3637 stale", a.get("stale") is True)
b = t["4100"]
check("4100 (GPS เจ้าที่ 2) ใช้ของสด", (b["lat"], b["lon"]) == (14.60, 101.00) and not b.get("stale"), b)
check("4100 ไม่ติดป้าย GPS ขาด", "GPS ขาด" not in b["reason"] and "GPS เจ้าที่ 2" in b["reason"], b["reason"])
c = t["4200"]
check("4200 คงกลุ่มจาก DTC (ดั้ม)", (c["group"], c["group_src"]) == ("dump", "dtc"), (c["group"], c["group_src"]))
d = t["1268"]
check("1268 รถจอด + ป้าย GPS ขาด", d["category"] == "parked" and "GPS ขาด" in d["reason"], d["reason"])

# ---------- 3) main() ทั้งรอบตอน DTC ล่ม (ไม่ยิงเน็ต) ----------
work = tempfile.mkdtemp()
os.chdir(work)
with open("fleet-status.json", "w", encoding="utf-8") as f:
    json.dump(PREV, f, ensure_ascii=False)
OLD_TRACKS = {"3637": [[15.0, 104.0, "08:00", 50, None]]}
with open("tracks.json", "w", encoding="utf-8") as f:
    json.dump({"date": NOW.strftime("%Y-%m-%d"), "tracks": OLD_TRACKS}, f)
with open("gps2-history.jsonl", "w", encoding="utf-8") as f:
    f.write(json.dumps({"num": "4100", "time": NOW.strftime("%Y-%m-%d 17:20:00"), "lat": 14.6,
                        "lon": 101.0, "speed": 60, "fuel": 80}) + "\n")
os.environ.update(DTC_TOKEN="x", GDRIVE_SA_KEY="{}", GITHUB_EVENT_NAME="schedule")


def dtc_hangs(token):
    raise TimeoutError("The read operation timed out")


run._dtc_down = False
run.pull_dtc = dtc_hangs
run.drive_service = lambda sa: None
run.download_fuel = lambda svc: None
run.parse_fuel = lambda buf: FUEL
run.fetch_master = lambda svc: (ROSTER, DRIVERS)
run.fetch_gps2 = lambda svc, now: GPS2
run.load_manual_groups = lambda *a, **k: {}
run.fetch_calendar_jobs = lambda sa, now: []
try:
    run.main()
    check("main ไม่ล้มตอน DTC ล่ม", True)
except BaseException as e:   # noqa: BLE001
    check("main ไม่ล้มตอน DTC ล่ม", False, repr(e))
with open("fleet-status.json", encoding="utf-8") as f:
    doc = json.load(f)
check("dtc_ok = false", doc.get("dtc_ok") is False, doc.get("dtc_ok"))
check("dtc_last_ok = รอบสุดท้ายที่ DTC ปกติ", doc.get("dtc_last_ok") == PREV["generated_at"], doc.get("dtc_last_ok"))
m = by_num(run._iter_trucks(doc))
check("ผลรอบใหม่: 3637 ป้าย GPS ขาด", "GPS ขาด" in m["3637"]["reason"], m["3637"]["reason"])
check("ผลรอบใหม่: 4100 ตำแหน่งสด", m["4100"]["lat"] == 14.60, m["4100"])
check("ผลรอบใหม่: ตำแหน่งค้าง = gps_lost, GPS2 สด = ไม่ติด",
      m["3637"].get("gps_lost") is True and m["4100"].get("gps_lost") is False,
      (m["3637"].get("gps_lost"), m["4100"].get("gps_lost")))
with open("tracks.json", encoding="utf-8") as f:
    tr = json.load(f)
check("เส้นทางวันนี้ของรถ DTC คงเดิม", tr["tracks"].get("3637") == OLD_TRACKS["3637"], tr["tracks"].get("3637"))
check("เส้นทางรถเจ้าที่ 2 อัปเดตจากของสด", tr["tracks"].get("4100", [[None]])[0][0] == 14.6, tr["tracks"].get("4100"))
rt_nums = []
if os.path.exists("route-track.jsonl"):
    with open("route-track.jsonl", encoding="utf-8") as f:
        rt_nums = [json.loads(x)["n"] for x in f if x.strip()]
check("สถิติเส้นทาง: ไม่เก็บตำแหน่งค้างของรถ DTC", "3637" not in rt_nums, rt_nums)
check("สถิติเส้นทาง: รถเจ้าที่ 2 (ของสด) ยังเก็บ", "4100" in rt_nums, rt_nums)
# DTC กลับมาในรอบถัดไป: dtc_last_ok ต้องขยับเป็นเวลาปัจจุบัน — (ครอบโดยตรรกะเดียวกัน ไม่ต้องยิงเน็ต)

# ---------- 4) trips: DTC ล่ม → ไม่ล้ม ไม่เขียนทับ trips.json ----------
run._dtc_down = True
try:
    trips.main()
    check("trips ไม่ล้มตอน DTC ล่ม", True)
except BaseException as e:   # noqa: BLE001
    check("trips ไม่ล้มตอน DTC ล่ม", False, repr(e))
check("trips ไม่เขียน trips.json ทับ", not os.path.exists("trips.json"))

print("\nALL PASS" if not fails else f"\n{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
