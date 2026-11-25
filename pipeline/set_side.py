# -*- coding: utf-8 -*-
"""ย้ายฝั่งรถเองจากแอป (กระดิ่งแจ้งเตือนตัวจับผิด) -> truck-sides.json (pipeline ใช้ทับผลจัดหมวดชั่วคราว)

ใช้จาก workflow_dispatch input `set_side` เช่น "1300:work_out,1571:find_out"
    find_out = หางานไป · find_back = หางานกลับ · work_out = ระหว่างงานไป · work_back = ระหว่างงานกลับ
    plate:  หรือ plate:auto = ยกเลิก (ให้ระบบตัดสินเอง)
ผูกกับงาน (job_key) + ตำแหน่งรถตอนกดย้าย จาก fleet-status.json ล่าสุด → pipeline ยกเลิกเองเมื่อ
รถวิ่งเกิน 2 กม. / งานในไฟล์น้ำมันเปลี่ยน / ครบ 24 ชม. (ดู apply_side_overrides ใน run.py)
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

FILE = "truck-sides.json"
VALID = {"find_out", "find_back", "work_out", "work_back"}


def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return dict(d.get("sides") or {}) if isinstance(d, dict) else {}
    except Exception:
        return {}


def _current_trucks(path="fleet-status.json"):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return {}
    out = {}
    for c in doc.get("categories", []):
        for g in c.get("groups", []):
            for t in g.get("trucks", []):
                if t.get("number"):
                    out[str(t["number"])] = t
    return out


def apply(spec, sides, trucks, now):
    """คืน (sides ใหม่, รายการที่เปลี่ยน) — ข้ามรายการที่ฟอร์แมตผิด/ฝั่งไม่รู้จัก"""
    changed = []
    for item in re.split(r"[,\s]+", (spec or "").strip()):
        if not item or ":" not in item:
            continue
        plate, side = item.split(":", 1)
        plate = plate.strip().replace("70-", "")
        side = side.strip().lower()
        if not plate.isdigit():
            continue
        if side in ("", "auto", "none"):
            if plate in sides:
                del sides[plate]
                changed.append(f"{plate}:auto")
        elif side in VALID:
            t = trucks.get(plate) or {}
            sides[plate] = {"side": side, "job_key": t.get("job_key"), "lat": t.get("lat"),
                            "lon": t.get("lon"), "at": now.isoformat(timespec="minutes")}
            changed.append(f"{plate}:{side}")
    return sides, changed


def main():
    spec = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SET_SIDE", "")
    now = datetime.now(timezone(timedelta(hours=7)))
    sides, changed = apply(spec, load(), _current_trucks(), now)
    if not changed:
        print("set_side: nothing to change for", repr(spec))
        return
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump({"sides": dict(sorted(sides.items()))}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("set_side: updated", ", ".join(changed), "->", len(sides), "override(s)")


if __name__ == "__main__":
    main()
