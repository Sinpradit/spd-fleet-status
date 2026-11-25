# -*- coding: utf-8 -*-
"""ตัวจับผิด: เตือนเมื่อฝั่งของรถเปลี่ยน ทั้งที่รถไม่ขยับ + งานในไฟล์น้ำมันเดิม + คนขับเดิม
(= กติกาตัดสินจากเวลา/เข็มทิศล้วน เช่น 1300 ไป → หาไป ตอนเที่ยงคืน 25 พย)
รัน: python pipeline/test_flip_detector.py   (ออฟไลน์)"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402

NOW = datetime(2026, 11, 25, 0, 4, tzinfo=timezone(timedelta(hours=7)))
JOB = "กระชับมิตร อุบลธัญกิจ-กระชับมิตร-|23 พย 69"
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def truck(cat, leg=None, *, lat=14.8427, lon=105.1101, job=JOB, driver="เอ็ม2", reason="x", num="1300"):
    return {"number": num, "category": cat, "leg": leg, "lat": lat, "lon": lon, "job_key": job,
            "driver": driver, "reason": reason, "location_text": "อุบลราชธานี · เดชอุดม"}


def doc(*ts):
    return {"categories": [{"key": "x", "groups": [{"key": "g", "trucks": list(ts)}]}]}


def flips(prev, cur):
    return run.detect_flips(doc(prev), [cur], NOW)


# 1) เคส 1300: จอดที่เดิม งานเดิม แต่ ไป → หาไป (วันที่หลุดช่วง) = เตือน
a = flips(truck("working", "out", reason="รับงานขาไปแล้ว กำลังจะออก"),
          truck("find_outbound", lat=14.8428, lon=105.1102, reason="ว่าง พร้อมรับงานไป"))
check("จอดนิ่ง งานเดิม ไป→หาไป = เตือน", len(a) == 1 and a[0]["from"] == "ระหว่างงานไป"
      and a[0]["to"] == "หางานไป" and a[0]["n"] == "1300", a)
check("เตือนพร้อมเหตุผลทั้งก่อน/หลัง + ระยะขยับ", a and a[0]["moved_m"] < 50 and "ว่าง" in a[0]["to_reason"], a)

# 2) ไป ↔ กลับ สลับเพราะเข็มทิศแกว่งตอนจอด = เตือน
check("จอดนิ่ง ไป→กลับ = เตือน", len(flips(truck("working", "out"), truck("working", "back"))) == 1)

# 3) เปลี่ยนแบบถูกต้อง = ไม่เตือน
check("รถขยับจริง 8 กม. = ไม่เตือน",
      not flips(truck("working", "out"), truck("find_return", lat=14.9100, lon=105.1101)))
check("ลงงานใหม่ในไฟล์ = ไม่เตือน",
      not flips(truck("find_outbound"), truck("working", "out", job="ชัยวัฒนา-เอี่ยมเฮงล้ง-|25 พย 69")))
check("ถอนคนขับ (เป็นรถจอด) = ไม่เตือน",
      not flips(truck("find_outbound"), truck("parked", driver="")))
check("ฝั่งเดิม (แค่ข้อความเปลี่ยน) = ไม่เตือน",
      not flips(truck("working", "out", reason="a"), truck("working", "out", reason="b")))
check("งานค้างเกิน 7 วัน (ตั้งใจ) = ไม่เตือน",
      not flips(truck("working", "out"), truck("find_outbound", reason="อยู่บ้าน งาน X ค้างเกิน 7 วัน")))
check("ไม่มีพิกัด = ไม่เตือน (ตัดสินไม่ได้)",
      not flips(truck("working", "out"), truck("find_outbound", lat=None, lon=None)))
check("คันใหม่ ไม่มีในรอบก่อน = ไม่เตือน",
      not run.detect_flips(doc(truck("working", "out", num="9999")), [truck("find_outbound")], NOW))
check("รอบก่อนว่าง (รอบแรก) = ไม่เตือน", not run.detect_flips({}, [truck("find_outbound")], NOW))

print("\nALL PASS" if not fails else f"\n{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
