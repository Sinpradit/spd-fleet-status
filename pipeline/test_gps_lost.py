# -*- coding: utf-8 -*-
"""ป้าย "GPS ขาด": กล่อง GPS ไม่ส่งตำแหน่งใหม่เกิน GPS_LOST_H (เช่น 3066 ใช้ไฟสำรอง ค้างโคราช 25+ ชม.)
→ gps_lost/stale = true, ไม่มี ETA, ไม่อัปเดตความจำเที่ยวด้วยตำแหน่งค้าง · รถจอดไม่มีคนขับไม่ติด (กล่องหลับเอง)
รัน: python pipeline/test_gps_lost.py   (ออฟไลน์ ไม่ยิงเน็ต)"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402

run._osrm_fail = 99
C = run.PROV_CENTROIDS
HOME = run.BASE_LATLON
POIS = {run._norm(run.HOME_POI): {"name": run.HOME_POI, "lat": HOME[0], "lon": HOME[1],
                                   "radius": 300, "poly": None}}
NOW = datetime(2026, 11, 20, 14, 0, tzinfo=timezone(timedelta(hours=7)))
TODAY = "20 พย 69"
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def one(time, *, prov="นครราชสีมา", route="ชัยวัฒนา-สมุทรสาคร-", driver="ทดสอบ", extra=None,
        trips=None, now=NOW, date=TODAY):
    pos = C[prov]
    rec = {"truck_name": "70-9999", "province_th": prov, "district_th": "อ.", "lat": pos[0],
           "lon": pos[1], "heading": 270, "gps_speed": 0, "status_name_th": "รถจอด",
           "time": time, **(extra or {})}
    return run.classify([], [rec], {"9999": {"route": route, "date": date}}, {TODAY}, set(), POIS,
                        roster=["9999"], drivers={"9999": driver}, gps2=None,
                        prev_pos={"9999": pos}, future_dates=set(), manual_groups={},
                        prev_trips=trips or {}, history={}, now=now)[0]


# 1) 3066: ตำแหน่งล่าสุดเมื่อวาน 13:21 (25 ชม.) → GPS ขาด + วันที่ · ไม่มี ETA
t = one("2026-11-19 13:21:38")
check("ค้าง 25 ชม. = gps_lost + stale", t["gps_lost"] is True and t["stale"] is True, (t["gps_lost"], t["stale"]))
check("ป้ายบอกวันที่+เวลา (ข้ามวัน)", t["reason"].endswith("GPS ขาด (ตำแหน่งล่าสุด 19 พ.ย. 13:21)"), t["reason"])
check("GPS ขาด = ไม่บอก ETA", t["eta_hours"] is None and "อีก ~" not in t["reason"], (t["eta_hours"], t["reason"]))
check("หมวดยังคงตามตำแหน่งล่าสุด (ไม่ใช่จอด)", t["category"] in ("working", "find_return", "find_outbound"), t["category"])

# 2) ตำแหน่งสด 5 นาที = ปกติ มี ETA
t = one("2026-11-20 13:55:00")
check("สด 5 นาที = ไม่ติดป้าย", t["gps_lost"] is False and "GPS ขาด" not in t["reason"], t["reason"])
check("สด = มี ETA ตามเดิม", t["eta_hours"] is not None, t["eta_hours"])

# 3) เส้นแบ่ง 1 ชม.
check("59 นาที = ยังปกติ", one("2026-11-20 13:01:00")["gps_lost"] is False)
t = one("2026-11-20 12:58:00")
check("62 นาที = GPS ขาด (วันเดียวกันโชว์แค่เวลา)",
      t["gps_lost"] is True and t["reason"].endswith("GPS ขาด (ตำแหน่งล่าสุด 12:58)"), t["reason"])

# 4) รถจอดไม่มีคนขับ กล่องหลับ 22 ชม. (1286) = ไม่ติดป้าย
t = one("2026-11-19 16:00:00", driver="")
check("จอดไม่มีคนขับ กล่องหลับ = ไม่ติดป้าย",
      t["category"] == "parked" and t["gps_lost"] is False and "GPS ขาด" not in t["reason"], t["reason"])
t = one("2026-11-20 13:10:00", driver="", extra={"_stale": True, "_dtc_stale": True})
check("จอดไม่มีคนขับ ตอน DTC ล่ม = ติดป้าย (แบบเดิม)", t["gps_lost"] is True and "GPS ขาด" in t["reason"], t["reason"])

# 5) GPS เจ้าที่ 2 ข้อมูลเก่า 2 ชม. → ป้ายเดียว ไม่ซ้ำ "(ข้อมูลเมื่อ ..)"
t = one("2026-11-20 12:00:00", extra={"_gps2": True, "_stale": True})
check("GPS2 เก่า = GPS ขาด", t["gps_lost"] is True and "GPS เจ้าที่ 2" in t["reason"], t["reason"])
check("GPS2 ไม่ขึ้นเวลาซ้ำสองที่", "ข้อมูลเมื่อ" not in t["reason"] and t["reason"].count("12:00") == 1, t["reason"])

# 6) ตำแหน่งค้างอยู่ในจังหวัดปลายทาง → ไม่ตั้ง "ถึงแล้ว" จากตำแหน่งค้าง
R = "ชัยวัฒนา-สมุทรสาคร-ไทซิง-เมืองวัสดุ"
K = run.trip_key(run.route_waypoints(R), TODAY)
t = one("2026-11-19 13:21:38", prov="สมุทรสาคร", route=R,
        trips={"9999": {"key": K, "max_km": 380, "reached": False, "seen": True}})
check("ตำแหน่งค้างไม่อัปเดตความจำเที่ยว", t["trip"]["reached"] is False and t["trip"]["max_km"] == 380, t["trip"])

# 7) ไม่ส่ง now (เทสต์/เล่นซ้ำเก่า) = ไม่ตรวจอายุตำแหน่ง (เข้ากันได้ย้อนหลัง)
t = one("2026-11-19 13:21:38", now=None)
check("ไม่มี now = ไม่ตรวจ GPS ขาด", t["gps_lost"] is False and "GPS ขาด" not in t["reason"], t["reason"])

# 8) เวลาอ่านไม่ได้ = ไม่เดา
check("เวลาอ่านไม่ได้ = ไม่ติดป้าย", one("ไม่ทราบ")["gps_lost"] is False)

print("\nALL PASS" if not fails else f"\n{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
