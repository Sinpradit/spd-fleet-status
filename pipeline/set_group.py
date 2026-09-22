# -*- coding: utf-8 -*-
"""ตั้งกลุ่มรถจากแอป -> truck-groups.json (ไฟล์ override ที่ pipeline อ่านก่อน DTC/โค้ด)

ใช้จาก workflow_dispatch input `set_group` เช่น "4169:flatbed,4100:pen"
    plate:flatbed|dump|pen  = ตั้งกลุ่ม
    plate:  หรือ plate:auto = ลบ override (กลับไปใช้ DTC/โค้ด)
"""
import json
import os
import re
import sys

FILE = "truck-groups.json"
VALID = {"dump", "pen", "flatbed"}


def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return {str(k): str(v) for k, v in (d.get("groups") or {}).items()} if isinstance(d, dict) else {}
    except Exception:
        return {}


def apply(spec, groups):
    """คืน (groups ใหม่, รายการที่เปลี่ยน) — ข้ามรายการที่ฟอร์แมตผิด/กลุ่มไม่รู้จัก"""
    changed = []
    for item in re.split(r"[,\s]+", (spec or "").strip()):
        if not item or ":" not in item:
            continue
        plate, grp = item.split(":", 1)
        plate = plate.strip().replace("70-", "")
        grp = grp.strip().lower()
        if not plate.isdigit():
            continue
        if grp in ("", "auto", "none"):
            if plate in groups:
                del groups[plate]
                changed.append(f"{plate}:auto")
        elif grp in VALID:
            if groups.get(plate) != grp:
                groups[plate] = grp
                changed.append(f"{plate}:{grp}")
    return groups, changed


def main():
    spec = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SET_GROUP", "")
    groups, changed = apply(spec, load())
    if not changed:
        print("set_group: nothing to change for", repr(spec))
        return
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump({"groups": dict(sorted(groups.items()))}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("set_group: updated", ", ".join(changed), "->", len(groups), "override(s)")


if __name__ == "__main__":
    main()
