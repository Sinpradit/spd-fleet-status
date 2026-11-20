# -*- coding: utf-8 -*-
"""ไป/กลับต้องไม่สลับไปมา: จำต่อเที่ยวว่าถึงปลายทาง/วกกลับแล้วหรือยัง (จอด/เข็มทิศแกว่งไม่สลับ)
รัน: python pipeline/test_trip_memory.py   (ออฟไลน์ ไม่ยิงเน็ต)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402

run._osrm_fail = 99
C = run.PROV_CENTROIDS
HOME = run.BASE_LATLON
POIS = {run._norm(run.HOME_POI): {"name": run.HOME_POI, "lat": HOME[0], "lon": HOME[1],
                                   "radius": 300, "poly": None}}
TODAY = "20 พย 69"
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def one(prov, pos, route, *, prev=None, heading=90, trips=None, history=None, date=TODAY,
        num="9999", extra=None, future=None):
    rec = {"truck_name": f"70-{num}", "province_th": prov, "district_th": "อ.",
           "lat": pos[0], "lon": pos[1], "heading": heading, "gps_speed": 0,
           "status_name_th": "รถจอด", "time": "2026-11-20 12:00:00", **(extra or {})}
    out = run.classify([], [rec], {num: {"route": route, "date": date}}, {TODAY}, set(), POIS,
                       roster=[num], drivers={num: "ทดสอบ"}, gps2=None,
                       prev_pos={num: prev or pos}, future_dates=future or set(), manual_groups={},
                       prev_trips=trips or {}, history=history or {})
    return out[0]


R_SUP = "เจียเม้ง-สุพรรณบุรี-บกด หนองแค-แก่งคอย-ศิริมหาชัย อำนาจ"   # ขาไปสุพรรณ (8) กลับรับของสระบุรี
KEY = run.trip_key(run.route_waypoints(R_SUP), TODAY)
SAR = C["สระบุรี"]                                                     # สระบุรี (4) อยู่ระหว่างทาง ไป/กลับ

# 1) ขาไปจอดพักที่สระบุรี หัวรถชี้ตะวันออก — เดิมเดา "ขนกลับ" (ไม่ขยับ) → ต้องยังไปส่ง
t = one("สระบุรี", SAR, R_SUP, heading=90,
        trips={"9999": {"key": KEY, "max_km": 380, "reached": False, "seen": True}})
check("ขาไปจอดพัก = ยังไปส่ง", t["leg"] == "out" and "กำลังไปส่ง" in t["reason"], t["reason"])

# 2) ขากลับจอดรับของที่หนองแค หัวรถชี้ตะวันตก — เดิม head_out → "ไปส่ง" → ต้องขนกลับ (3001)
t = one("สระบุรี", SAR, R_SUP, heading=225,
        trips={"9999": {"key": KEY, "max_km": 496, "reached": True, "seen": True}})
check("ขากลับจอดรับของ = ขนกลับ (ไม่สนเข็มทิศ)", t["leg"] == "back", t["reason"])

# 3) เข้าจังหวัดปลายทาง = จำว่าถึงแล้ว
t = one("สุพรรณบุรี", C["สุพรรณบุรี"], R_SUP,
        trips={"9999": {"key": KEY, "max_km": 420, "reached": False, "seen": True}})
check("ถึงจังหวัดปลายทาง → reached", t["trip"]["reached"] is True, t["trip"])

# 4) ตั้งความจำจากประวัติจุด GPS (ยังไม่มีในรอบก่อน — เช่น เพิ่งเปิดใช้)
hist = {"9999": [("2026-11-19 08:00:00", "เจียเม้ง-สุพรรณบุรี-", 14.95, 102.2),
                 ("2026-11-19 14:00:00", "เจียเม้ง-สุพรรณบุรี-", 14.47, 100.12)]}
t = one("สระบุรี", SAR, R_SUP, heading=225, history=hist, date="19 พย 69")
check("ประวัติเคยถึงสุพรรณ → ขนกลับตั้งแต่รอบแรก", t["leg"] == "back" and t["trip"]["reached"], (t["reason"], t["trip"]))
old = [("2026-11-10 08:00:00", "เจียเม้ง-สุพรรณบุรี-", 14.47, 100.12)]       # งานเก่าก่อนวันลงงาน
t = one("สระบุรี", SAR, R_SUP, heading=225, history={"9999": old}, date="19 พย 69")
check("ประวัติก่อนวันลงงานไม่นับ", not t["trip"]["reached"], t["trip"])

# 5) วกกลับเกิน 25 กม. จากจุดไกลสุด (ปลายทางไม่รู้จังหวัด) = กลับแล้ว
R_UNK = "ชัยวัฒนา-โรงงานไม่รู้จัก-เมืองวัสดุ"
KU = run.trip_key(run.route_waypoints(R_UNK), TODAY)
t = one("สระบุรี", SAR, R_UNK, trips={"9999": {"key": KU, "max_km": 470, "reached": False, "seen": True}})
check("วกกลับ 40+ กม. = ขนกลับ", t["leg"] == "back" and t["trip"]["reached"], (t["reason"], t["trip"]))
t = one("สระบุรี", SAR, R_UNK, trips={"9999": {"key": KU, "max_km": 390, "reached": False, "seen": True}})
check("ยังไม่วกกลับ = ไปส่ง", t["leg"] == "out", t["reason"])

# 6) กลับถึงโซนบ้านหลังส่งของ (งานวันนี้ หัวรถชี้ออก) — เดิมเป็น "เพิ่งออกงาน" → ต้องว่างรับงานไป
SSK = C["ศรีสะเกษ"]
t = one("ศรีสะเกษ", SSK, R_SUP, heading=270,
        trips={"9999": {"key": KEY, "max_km": 496, "reached": True, "seen": True}})
check("กลับถึงบ้านแล้ว = หางานไป", t["category"] == "find_outbound", t["reason"])
t = one("ศรีสะเกษ", SSK, R_SUP, heading=270, prev=(15.2, 104.9))
check("งานใหม่ออกจากบ้าน (ยังไม่เคยถึง) = เพิ่งออกงาน", t["leg"] == "out" and "เพิ่งออกงาน" in t["reason"], t["reason"])

# 7) งานขาเดียว ส่งแล้ววิ่งกลับเปล่า = หางานกลับ + ETA กลับบ้าน (ไม่ใช่ "ถึงปลายทางแล้ว")
R_ONE = "เจียเม้ง-สุพรรณบุรี-"
K1 = run.trip_key(run.route_waypoints(R_ONE), TODAY)
t = one("สระบุรี", SAR, R_ONE, trips={"9999": {"key": K1, "max_km": 496, "reached": True, "seen": True}})
check("ส่งแล้ววิ่งกลับเปล่า = หางานกลับ", t["category"] == "find_return", t["reason"])
check("ETA กลับบ้าน (ไม่ใช่ 0)", (t.get("eta_hours") or 0) > 0 and "ถึงบ้าน" in t["reason"], (t.get("eta_hours"), t["reason"]))
t = one("สระบุรี", SAR, R_ONE, trips={"9999": {"key": K1, "max_km": 380, "reached": False, "seen": True}})
check("งานขาเดียว ยังไม่ถึง = ไปส่ง", t["leg"] == "out", t["reason"])

# 8) ลงงานใหม่ (ลายนิ้วมือเปลี่ยน) = เริ่มความจำใหม่
t = one("สระบุรี", SAR, R_SUP, date="21 พย 69",
        trips={"9999": {"key": KEY, "max_km": 496, "reached": True, "seen": True}})
check("งานใหม่ไม่เอาความจำงานเก่า", not t["trip"]["reached"], t["trip"])

# 9) ยังไม่มีความจำ + จอดนิ่ง = แบบเดิม (ขนกลับไว้ก่อน)
t = one("สระบุรี", SAR, R_SUP, heading=90)
check("ไม่มีความจำ + จอดนิ่ง = ขนกลับแบบเดิม", t["leg"] == "back" and not t["trip"]["seen"], t["trip"])

# 10) ทอยในโซนบ้าน (อำนาจเจริญ) หัวรถชี้ออก — เดิมสลับ หาไป/หากลับ ตามเข็มทิศ
t = one("อำนาจเจริญ", C["อำนาจเจริญ"], "ทอย หัวตะพาน-ชัยวัฒนา", heading=270)
check("ทอยโซนบ้าน = หางานไปเสมอ", t["category"] == "find_outbound", t["reason"])

# 11) จังหวัดที่เดิมไม่มีในตาราง (อ่างทอง) ระหว่างไปสุพรรณ = ยังไปส่ง ไม่ใช่ "เลยจุดนับ"
t = one("อ่างทอง", C["อ่างทอง"], R_ONE, trips={"9999": {"key": K1, "max_km": 430, "reached": False, "seen": True}})
check("ผ่านอ่างทองไปสุพรรณ = ไปส่ง", t["leg"] == "out", t["reason"])

# 12) ปลายทางไม่มีในตารางชื่อ แต่ตรงกับสถานีใน DTC → รู้จังหวัดจากพิกัดสถานี (ไม่ตกโซนเดา)
POIS["โรงงานใหม่ใน dtc"] = {"name": "โรงงานใหม่ใน DTC", "lat": SAR[0] + 0.05, "lon": SAR[1],
                             "radius": 200, "poly": None}
t = one("สระบุรี", SAR, "เจียเม้ง-โรงงานใหม่ใน DTC-")
check("สถานี DTC บอกจังหวัดปลายทาง → ถึงแล้ว (ไม่ใช่ประเมินจากโซน)",
      t["category"] == "find_return" and "ประเมินจากโซน" not in t["reason"], t["reason"])
t = one("บุรีรัมย์", C["บุรีรัมย์"], "เจียเม้ง-โรงงานใหม่ใน DTC-", prev=(14.95, 103.6))
check("สถานี DTC: ยังไม่ถึงจังหวัดปลายทาง = ไปส่ง", t["leg"] == "out" and "ยังไม่ถึง" in t["reason"], t["reason"])
del POIS["โรงงานใหม่ใน dtc"]

# 13) แก้คำสะกดปลายทางในไฟล์ (ยูนิวเอร์แซล → ยูนิเวอร์แซล) = เที่ยวเดิม ประวัติยังใช้ได้ (3070)
hist = {"9999": [("2026-11-19 11:00:00", "ชัยวัฒนา-ยูนิวเอร์แซล-ไทซิง-เมืองวัสดุ", 13.55, 100.27)]}
t = one("ฉะเชิงเทรา", C["ฉะเชิงเทรา"], "ชัยวัฒนา-ยูนิเวอร์แซล-ไทซิง-เมืองวัสดุ", heading=270,
        history=hist, date="19 พย 69")
check("แก้คำสะกด ยังจำว่าส่งที่สมุทรสาครแล้ว = ขนกลับ", t["leg"] == "back" and t["trip"]["reached"], (t["reason"], t["trip"]))

# 14) DTC ล่ม (ตำแหน่งค้าง) = คงความจำ ไม่เอาตำแหน่งค้างมาอัปเดต
t = one("สุพรรณบุรี", C["สุพรรณบุรี"], R_SUP, extra={"_stale": True, "_dtc_stale": True},
        trips={"9999": {"key": KEY, "max_km": 380, "reached": False, "seen": True}})
check("ตำแหน่งค้างไม่ตั้ง reached", t["trip"]["reached"] is False and t["trip"]["max_km"] == 380, t["trip"])

# 15) ลงแค่ชื่อลูกค้าขาไป "ชัยวัฒนา-" (ยังไม่ลงปลายทาง) = ฝั่งกำลังไป (2592/3604 20 พย)
#     เดิม: จุดเดียวถูกถือเป็นปลายทาง + ลูกค้าเป็นสถานี DTC ในโซนบ้าน → "ถึงปลายทางแล้ว รอรับงานกลับ"
UBN = C["อุบลราชธานี"]
CUST = {"name": "ชัยวัฒนา เขื่องใน", "lat": UBN[0], "lon": UBN[1], "radius": 300, "poly": None}
POIS[run._norm(CUST["name"])] = CUST
t = one("อุบลราชธานี", UBN, "ชัยวัฒนา-")
check("ลงแค่ลูกค้า จอดที่ลูกค้า = ระหว่างงานไป (ไม่ใช่หางานกลับ)",
      t["category"] == "working" and t["leg"] == "out" and "ยังไม่ลงปลายทาง" in t["reason"], t["reason"])
check("ยังไม่ลงปลายทาง = ไม่เดา ETA / ไม่ตั้งความจำเที่ยว", t.get("eta_hours") is None and t["trip"] is None,
      (t.get("eta_hours"), t["trip"]))
t = one("ศรีสะเกษ", SSK, "ชัยวัฒนา-", prev=(15.2, 104.9), heading=60)
check("ลงแค่ลูกค้า กำลังวิ่งไปรับของ = ระหว่างงานไป", t["category"] == "working" and t["leg"] == "out", t["reason"])
t = one("อุบลราชธานี", UBN, "ชัยวัฒนา-", date="22 พย 69", future={"22 พย 69"})
check("ลงแค่ลูกค้า ล่วงหน้า = รอออก (ฝั่งไป)", t["leg"] == "out" and "รอออก" in t["reason"], t["reason"])
t = one("อุบลราชธานี", UBN, "ชัยวัฒนา-", date="17 พย 69")
check("ลงแค่ลูกค้าไว้หลายวัน (รอโหลด) = ยังฝั่งไป + บอกวันลงงาน",
      t["leg"] == "out" and "ลงงาน 17 พย" in t["reason"], t["reason"])
t = one("สระบุรี", SAR, "ชัยวัฒนา-")
check("ลงแค่ลูกค้า นอกโซนบ้าน = กำลังไปส่ง", t["leg"] == "out" and "กำลังไปส่ง" in t["reason"], t["reason"])
out = run.classify([], [], {"9999": {"route": "ชัยวัฒนา-", "date": TODAY}}, {TODAY}, set(), POIS,
                   roster=["9999"], drivers={"9999": "ทดสอบ"}, gps2=None, prev_pos={},
                   future_dates=set(), manual_groups={}, prev_trips={}, history={})
check("ลงแค่ลูกค้า ไม่มี GPS = ฝั่งไป (เดิม หางานกลับจากไฟล์)",
      out[0]["category"] == "working" and out[0]["leg"] == "out", out[0]["reason"])
t = one("อุบลราชธานี", UBN, "ชัยวัฒนา-สมุทรสาคร-")
check("ลงปลายทางแล้ว (ยังอยู่บ้าน) = แบบเดิม กำลังจะออก",
      t["leg"] == "out" and "กำลังจะออก" in t["reason"] and "ยังไม่ลงปลายทาง" not in t["reason"], t["reason"])

# 16) ลงแค่ลูกค้าแล้วรถออกไปก่อน → มาลงปลายทาง (+งานกลับ) ทีหลัง: จุดที่วิ่งช่วงยังไม่ลงปลายทางนับเป็นเที่ยวเดียวกัน
#     (ไม่งั้นจอดพักรอบแรกหลังลงปลายทาง = default "ขนกลับ" ผิดฝั่ง)
hist = {"9999": [("2026-11-19 20:00:00", "ชัยวัฒนา-", 14.95, 102.2)]}
t = one("สระบุรี", SAR, "ชัยวัฒนา-สมุทรสาคร-ไทซิง-เมืองวัสดุ", heading=90, history=hist, date="19 พย 69")
check("มาลงปลายทางทีหลัง ความจำช่วงลงแค่ลูกค้ายังใช้ได้ = ยังไปส่ง",
      t["leg"] == "out" and t["trip"]["seen"] and not t["trip"]["reached"], (t["reason"], t["trip"]))
del POIS[run._norm(CUST["name"])]

print("\nALL PASS" if not fails else f"\n{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
