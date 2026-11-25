# -*- coding: utf-8 -*-
"""ย้ายฝั่งเองจากแอป (กระดิ่ง): set_side.py เขียน truck-sides.json · pipeline ใช้ทับผลจนกว่า
รถวิ่งเกิน 2 กม. / งานในไฟล์เปลี่ยน / ครบ 24 ชม. · ตัวจับผิดไม่เตือนการย้ายเอง · เตือน 24 ชม. ส่งให้แอป
รัน: python pipeline/test_side_override.py (ออฟไลน์)"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402
import set_side  # noqa: E402

TZ = timezone(timedelta(hours=7))
NOW = datetime(2026, 11, 25, 14, 30, tzinfo=TZ)
JOB = "กระชับมิตร อุบลธัญกิจ-กระชับมิตร-|23 พย 69"
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


def truck(**kw):
    t = {"number": "1300", "category": "find_outbound", "leg": None, "lat": 14.8427, "lon": 105.1101,
         "job_key": JOB, "driver": "เอ็ม2", "reason": "ว่าง พร้อมรับงานไป · อีก ~1.5 ชม. ถึงบ้าน",
         "eta_hours": 1.5, "location_text": "อุบลราชธานี · เดชอุดม"}
    t.update(kw)
    return t


def ov(side="work_out", at=NOW - timedelta(hours=1), **kw):
    o = {"side": side, "job_key": JOB, "lat": 14.8427, "lon": 105.1101, "at": at.isoformat(timespec="minutes")}
    o.update(kw)
    return o


# ---------- 1) set_side.py ----------
cur = {"1300": truck()}
sides, ch = set_side.apply("1300:work_out, 1571:bogus, x:find_out", {}, cur, NOW)
check("set_side ผูกงาน+ตำแหน่งตอนกด", sides.get("1300", {}).get("job_key") == JOB
      and sides["1300"]["side"] == "work_out" and sides["1300"]["lat"] == 14.8427, sides)
check("set_side ข้ามฝั่ง/ทะเบียนผิดรูป", ch == ["1300:work_out"], ch)
sides, ch = set_side.apply("1300:auto", sides, cur, NOW)
check("set_side :auto = ยกเลิก", "1300" not in sides and ch == ["1300:auto"], (sides, ch))

# ---------- 2) apply_side_overrides ----------
t = truck()
keep, log = run.apply_side_overrides([t], {"1300": ov()}, NOW)
check("ย้ายเอง → ระหว่างงานไป", t["category"] == "working" and t["leg"] == "out" and t["side_src"] == "manual", t)
check("ย้ายเอง: ไม่บอก ETA เดิม + เหตุผลบอกว่าย้ายเอง", t["eta_hours"] is None and t["reason"].startswith("ย้ายเอง → ระหว่างงานไป")
      and "ระบบว่า: ว่าง" in t["reason"], t["reason"])
check("ยังมีผล = เก็บไว้", "1300" in keep, keep)
for side, cat, leg in (("find_out", "find_outbound", None), ("find_back", "find_return", None),
                       ("work_back", "working", "back")):
    t = truck(category="working", leg="out")
    run.apply_side_overrides([t], {"1300": ov(side=side)}, NOW)
    check(f"ย้ายไป {side}", (t["category"], t["leg"]) == (cat, leg), (t["category"], t["leg"]))

t = truck(job_key="ชัยวัฒนา-เอี่ยมเฮงล้ง-|25 พย 69")
keep, log = run.apply_side_overrides([t], {"1300": ov()}, NOW)
check("ลงงานใหม่ = หมดผล ระบบตัดสินเอง", "1300" not in keep and t["category"] == "find_outbound" and "side_src" not in t, log)
t = truck(lat=14.90, lon=105.11)                                  # ขยับ ~6 กม.
keep, log = run.apply_side_overrides([t], {"1300": ov()}, NOW)
check("รถวิ่งเกิน 2 กม. = หมดผล", "1300" not in keep and t["category"] == "find_outbound", log)
t = truck(lat=14.8500, lon=105.1101)                              # ขยับ ~800 ม.
keep, _ = run.apply_side_overrides([t], {"1300": ov()}, NOW)
check("ขยับไม่ถึง 2 กม. = ยังมีผล", "1300" in keep and t["category"] == "working", t["category"])
t = truck()
keep, log = run.apply_side_overrides([t], {"1300": ov(at=NOW - timedelta(hours=25))}, NOW)
check("ครบ 24 ชม. = หมดผล", "1300" not in keep and t["category"] == "find_outbound", log)
keep, log = run.apply_side_overrides([truck()], {"9999": ov()}, NOW)
check("ไม่พบรถ = ทิ้ง", keep == {}, log)

# ---------- 3) ตัวจับผิดไม่เตือนการย้ายเอง ----------
prev = {"categories": [{"groups": [{"trucks": [truck()]}]}]}
moved = truck(category="working", leg="out", side_src="manual")
check("ย้ายเอง ไม่ถูกจับผิด", run.detect_flips(prev, [moved], NOW) == [])
prev_m = {"categories": [{"groups": [{"trucks": [truck(category="working", leg="out", side_src="manual")]}]}]}
check("ย้ายเองหมดผล ไม่ถูกจับผิด", run.detect_flips(prev_m, [truck()], NOW) == [])
check("ระบบสลับเอง ยังถูกจับเหมือนเดิม",
      len(run.detect_flips({"categories": [{"groups": [{"trucks": [truck(category="working", leg="out")]}]}]},
                           [truck()], NOW)) == 1)

# ---------- 4) เตือน 24 ชม. สำหรับแอป ----------
work = tempfile.mkdtemp()
p = os.path.join(work, "flip-alerts.jsonl")
with open(p, "w", encoding="utf-8") as f:
    for hrs, n in ((30, "1571"), (5, "2270"), (1, "1300")):
        t0 = (NOW - timedelta(hours=hrs)).isoformat(timespec="minutes")
        f.write(json.dumps({"t": t0, "n": n, "from": "ระหว่างงานไป", "to": "หางานไป", "loc": "x",
                            "to_reason": "ว่าง"}, ensure_ascii=False) + "\n")
al = run.recent_flip_alerts(NOW, path=p)
check("เตือนเฉพาะ 24 ชม. ใหม่สุดก่อน", [a["n"] for a in al] == ["1300", "2270"], al)
check("เตือนมี id ไว้กดรับทราบในแอป", al and al[0]["id"].startswith("1300|"), al[:1])
check("ไม่มีไฟล์เตือน = ว่าง (ไม่ล้ม)", run.recent_flip_alerts(NOW, path=os.path.join(work, "none.jsonl")) == [])

print("\nALL PASS" if not fails else f"\n{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
