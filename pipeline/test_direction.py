#!/usr/bin/env python3
"""Repro + regression harness for has_return direction logic.
รันตรง classify() ด้วย input สังเคราะห์ — เร็ว, deterministic, ไม่ง้อ DTC/OSRM.

ควบคุม:
  idx_now  <- province_th (ผ่าน PROV_IDX)
  idx_out  <- out_name ในเส้นทาง (จุดที่ 2) -> resolve_province
  mv       <- prev_pos เทียบระยะจากฐาน (>1.5km = out/home)
  is_recent<- date ในไฟล์ vs recent_dates
"""
import run

HOME = (15.10, 104.57)   # สินประดิษฐ์
POIS = {run._norm("สินประดิษฐ์"): {"name": "สินประดิษฐ์", "lat": HOME[0],
                                    "lon": HOME[1], "radius": 200, "poly": None}}
# ปิด OSRM ให้ใช้ fallback ระยะทาง (เร็ว + ไม่ยิงเน็ต)
run._osrm_fail = 99

# พิกัดคุม mv (ยิ่ง lon ห่าง 104.57 = ยิ่งไกลฐาน)
POS = {
    "บ้าน": (15.10, 104.55),      # ใกล้ฐานสุด
    "สุรินทร์": (14.88, 103.49),   # กลาง
    "บุรีรัมย์": (14.99, 103.10),   # ไกลกว่า
    "สระบุรี": (14.53, 100.91),    # ไกลมาก
}


def one(num, province, pos_key, route, date, prev_key, recent=("9 กค 69",)):
    lat, lon = POS[pos_key]
    veh = [{"gps_id": "g1", "vehicle_name": f"70-{num}"}]
    rt = [{"gps_id": "g1", "truck_name": f"70-{num}", "province_th": province,
           "district_th": "อ.", "lat": lat, "lon": lon, "heading": 90,
           "gps_speed": 40, "status_name_th": "รถวิ่ง", "time": "2026-07-16 10:00:00"}]
    fuel = {num: {"route": route, "date": date}}
    prev = {num: POS[prev_key]}
    trucks = run.classify(veh, rt, fuel, set(recent), set(), POIS,
                          roster=[num], drivers={num: "ทดสอบ"}, gps2=None,
                          prev_pos=prev)
    t = trucks[0]
    return t["category"], t["reason"]


R_HR = "เจียเม้ง-นนทบุรี-ไทซิง-เมืองวัสดุ"   # has_return, out=นนทบุรี(7), last=เมืองวัสดุ

CASES = [
    # id, province(idx), pos, route, date, prev(->mv), expect_cat, expect_reason_contains
    ("A_old_outbound_moving_out", "บุรีรัมย์", "บุรีรัมย์", R_HR, "1 กค 69",
     "สุรินทร์", "working", "กำลังไปส่ง"),        # งานเก่า ยังไม่ถึงปลายทาง วิ่งออก -> ต้องไปส่ง
    ("B_old_returning_moving_home", "สระบุรี", "สุรินทร์", R_HR, "1 กค 69",
     "สระบุรี", "working", "กำลังขนกลับ"),         # เข้าใกล้ฐาน -> ขนกลับ
    ("C_old_ambiguous_no_move", "สระบุรี", "สระบุรี", R_HR, "1 กค 69",
     "สระบุรี", "working", "กำลังขนกลับ"),         # ไม่ขยับ ไม่ชัด -> default ขนกลับ (ปลอดภัย)
    ("D_new_from_home_moving_out", "ศรีสะเกษ", "สุรินทร์", R_HR, "9 กค 69",
     "บ้าน", "working", "กำลังไปส่ง"),             # 2792: งานใหม่ ออกจากบ้าน -> ไปส่ง
    ("E_past_dest_returning", "สระบุรี", "สุรินทร์", R_HR, "1 กค 69",
     "บ้าน", "working", "กำลังไปส่ง"),             # หลอก: อยู่สระบุรี(4)<นนทบุรี(7) มุ่งออก งานเก่า
]


def main():
    fails = 0
    for cid, prov, pos, route, date, prev, exp_cat, exp_r in CASES:
        cat, reason = one("9999", prov, pos, route, date, prev)
        ok = (cat == exp_cat) and (exp_r in reason)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{mark}] {cid}: got cat={cat} | {reason[:60]}")
        if not ok:
            print(f"        expected cat={exp_cat} reason~'{exp_r}'")
    print(f"\n{'ALL PASS' if fails == 0 else str(fails)+' FAIL'}")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if main() else 0)
