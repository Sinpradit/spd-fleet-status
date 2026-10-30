# -*- coding: utf-8 -*-
"""ทิศงาน (leg) ของรถหมวดกำลังทำงาน — ครอบทุกแม่แบบข้อความเหตุผลใน classify + ส่วนต่อท้าย ETA/สถานี.
รัน: PYTHONPATH=pipeline python pipeline/test_leg.py"""
import importlib.util
import os

spec = importlib.util.spec_from_file_location(
    "run", os.path.join(os.path.dirname(__file__), "run.py"))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

CASES = {
    "มีงาน เซ็นจูรี่ รอออก (20 กย)": "out",
    "กำลังไปส่ง (ประเมินจากโซน)": "out",
    "เพิ่งออกงาน (ประเมินจากโซน)": "out",
    "รับงานขาไปแล้ว กำลังจะออก": "out",
    "กำลังไปส่ง — ถึง ฉะเชิงเทรา แล้ว ยังไม่ถึง สมุทรสาคร": "out",
    "เพิ่งออกงาน กำลังไปส่ง (แหลมฉบัง)": "out",
    "กำลังไปส่ง (แหลมฉบัง)": "out",
    "กำลังขนกลับ (ประเมินจากโซน)": "back",
    "กำลังขนกลับ ใกล้ถึงบ้าน": "back",
    "อยู่ที่ เจียเม้งนนทบุรี — ส่งของ (มีงานกลับต่อ)": "back",
    "อยู่ที่ แก่งคอย — รับของขากลับ": "back",
    "รอเชื่อมข้อมูล GPS (เจ้าที่ 2) / ยังไม่มีงานในไฟล์": None,
}
SUFFIXES = ["", " · อีก ~2 ชม. ถึง แหลมฉบัง", " · อีก ~8 ชม. ถึงบ้าน", " · 📍สินประดิษฐ์", " · GPS เจ้าที่ 2"]

bad = []
for reason, want in CASES.items():
    for suf in SUFFIXES:
        got = run.leg_of("working", reason + suf)
        if got != want:
            bad.append((reason + suf, got, want))
assert run.leg_of("find_return", "กำลังขนกลับ") is None
if bad:
    for b in bad:
        print("FAIL", b)
    raise SystemExit(1)
print(f"leg_of OK: {len(CASES)} templates x {len(SUFFIXES)} suffixes")
