#!/usr/bin/env python3
"""Trip extraction (เฟส 3): ตัด "เที่ยว" ของรถแต่ละคันจากประวัติ GPS
เที่ยว = ออกจากฐานบริษัท (สถานี "สินประดิษฐ์") -> กลับเข้าฐาน (ข้ามวันได้)
ผลลัพธ์ trips.json: สรุปต่อเที่ยว + ซีรีส์น้ำมัน/ระยะทาง (ให้แอปวาดกราฟรายเที่ยว)

Env: DTC_TOKEN (+ GDRIVE_SA_KEY ไม่จำเป็น — ใช้ GPS ล้วน)
"""
import json
import os
from datetime import datetime, timezone, timedelta

from run import (dtc_post, fetch_history, fetch_pois, _haversine_m, _norm,
                 EXCLUDE, GROUP_OF)

DAYS_BACK = 7            # สแกนย้อนหลังกี่วัน (เที่ยวยาว ~3-4 วัน + เผื่อ)
BASE_NAME = "สินประดิษฐ์"  # สถานีฐานบริษัท
BASE_EXTRA_M = 300       # buffer เพิ่มจากรัศมีสถานี
MIN_TRIP_KM = 50         # ไกลสุดจากฐานต้องเกินนี้ถึงนับเป็น "เที่ยว" (ตัดวิ่งวนใกล้บ้าน)
MAX_TRIPS_KEEP = 5       # เก็บล่าสุดกี่เที่ยวต่อคัน
SERIES_PTS = 80          # จุดกราฟต่อเที่ยว


def base_geometry(token):
    pois = fetch_pois(token)
    st = pois.get(_norm(BASE_NAME))
    if not st or not st.get("lat"):
        raise SystemExit("base station not found: " + BASE_NAME)
    r = (st.get("radius") or 200) + BASE_EXTRA_M
    return st["lat"], st["lon"], r


def parse_pts(raw_pts):
    """history dicts -> [(dt, lat, lon, fuel%|None)] เรียงเวลา"""
    out = []
    for p in raw_pts:
        try:
            la, lo = float(p.get("lat") or 0), float(p.get("lon") or 0)
            if not la or not lo:
                continue
            dt = datetime.strptime(p["time"][:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, KeyError):
            continue
        fuel = None
        o = str(p.get("oil") or "")
        if "/" in o:
            try:
                fuel = int(float(o.split("/")[0]))
            except (TypeError, ValueError):
                fuel = None
        out.append((dt, la, lo, fuel))
    out.sort(key=lambda x: x[0])
    return out


def segment_trips(pts, blat, blon, brad):
    """ตัดช่วง ออกฐาน->กลับฐาน; คืน list ของ segment (list จุด) + segment ที่ยังไม่จบ"""
    trips, cur = [], None
    prev_in = True
    for pt in pts:
        in_base = _haversine_m(pt[1], pt[2], blat, blon) <= brad
        if prev_in and not in_base:
            cur = [pt]                     # เพิ่งออกจากฐาน
        elif cur is not None:
            cur.append(pt)
            if in_base:                    # กลับถึงฐาน = จบเที่ยว
                trips.append((cur, False))
                cur = None
        prev_in = in_base
    if cur is not None and len(cur) >= 2:
        trips.append((cur, True))          # เที่ยวที่ยังวิ่งอยู่
    return trips


def _smooth_fuel(seg):
    """median 3 จุด ลดสัญญาณเซนเซอร์เด้ง; คืน list ค่าน้ำมัน (None ได้)"""
    vals = [p[3] for p in seg]
    out = []
    for i in range(len(vals)):
        win = [v for v in vals[max(0, i - 1):i + 2] if v is not None]
        out.append(sorted(win)[len(win) // 2] if win else None)
    return out


def summarize(seg, ongoing, blat, blon, window_start=None):
    dist = 0.0
    maxd = 0.0
    for i in range(1, len(seg)):
        dist += _haversine_m(seg[i - 1][1], seg[i - 1][2], seg[i][1], seg[i][2])
        maxd = max(maxd, _haversine_m(seg[i][1], seg[i][2], blat, blon))
    dist_km, maxd_km = dist / 1000, maxd / 1000
    if maxd_km < MIN_TRIP_KM:
        return None                        # วิ่งวนใกล้บ้าน ไม่นับ
    t0, t1 = seg[0][0], seg[-1][0]
    # เที่ยวชนขอบหน้าต่างสแกน = เริ่มจริงก่อนหน้านั้น (เวลา/กม. เป็นค่าขั้นต่ำ)
    start_estimated = bool(window_start and (t0 - window_start).total_seconds() < 3600)
    sm = _smooth_fuel(seg)
    fuels = [v for v in sm if v is not None]
    refuels = 0
    for i in range(1, len(sm)):
        a, b = sm[i - 1], sm[i]
        if a is not None and b is not None and b - a >= 10:
            refuels += 1
    if refuels > 6:
        refuels = None                     # สัญญาณเซนเซอร์เด้งเกินเหตุ นับไม่ได้
    # ซีรีส์สำหรับกราฟ: [เวลา "d/m HH:MM", fuel, กม.สะสม]
    series = []
    cum = 0.0
    for i, p in enumerate(seg):
        if i:
            cum += _haversine_m(seg[i - 1][1], seg[i - 1][2], p[1], p[2]) / 1000
        series.append([p[0].strftime("%d/%m %H:%M"),
                       p[3], round(cum, 1)])
    if len(series) > SERIES_PTS:
        step = len(series) / SERIES_PTS
        series = [series[int(i * step)] for i in range(SERIES_PTS)] + [series[-1]]
    return {
        "start": t0.strftime("%Y-%m-%d %H:%M"),
        "start_estimated": start_estimated,
        "end": None if ongoing else t1.strftime("%Y-%m-%d %H:%M"),
        "ongoing": ongoing,
        "hours": round((t1 - t0).total_seconds() / 3600, 1),
        "km": round(dist_km),
        "max_km_from_base": round(maxd_km),
        "fuel_start": fuels[0] if fuels else None,
        "fuel_end": fuels[-1] if fuels else None,
        "refuels": refuels,
        "series": series,
    }


def gps2_streams():
    """สตรีมของรถ GPS เจ้าที่ 2 จาก gps2-history.jsonl -> {num: [(dt,lat,lon,fuel)]}"""
    out = {}
    try:
        with open("gps2-history.jsonl", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    dt = datetime.strptime(str(r["time"])[:19], "%Y-%m-%d %H:%M:%S")
                    la, lo = float(r["lat"]), float(r["lon"])
                except (TypeError, ValueError, KeyError):
                    continue
                fu = r.get("fuel")
                out.setdefault(r.get("num"), {})[dt] = (dt, la, lo,
                                                        int(fu) if fu is not None else None)
    except FileNotFoundError:
        pass
    return {n: [byt[k] for k in sorted(byt)] for n, byt in out.items()}


def main():
    token = os.environ["DTC_TOKEN"]
    now = datetime.now(timezone(timedelta(hours=7)))
    blat, blon, brad = base_geometry(token)
    start = (now - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d 00:00:00")
    end = now.strftime("%Y-%m-%d %H:%M:%S")

    vm = dtc_post("/getVehicleMaster", {"api_token_key": token})
    gid_by_num = {v["vehicle_name"].replace("70-", ""): v["gps_id"]
                  for v in vm.get("data", [])}
    ws = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")   # ขอบหน้าต่างสแกน

    result = {}
    for num, gid in sorted(gid_by_num.items()):
        if num in EXCLUDE:
            continue
        pts = parse_pts(fetch_history(token, gid, start, end))
        if len(pts) < 5:
            continue
        trips = []
        for seg, ongoing in segment_trips(pts, blat, blon, brad):
            s = summarize(seg, ongoing, blat, blon, ws)
            if s:
                trips.append(s)
        if trips:
            result[num] = trips[-MAX_TRIPS_KEEP:][::-1]   # ใหม่สุดก่อน

    # รถ GPS เจ้าที่ 2 (จากประวัติสะสมของเรา)
    for num, pts in gps2_streams().items():
        if num in result or num in EXCLUDE or len(pts) < 5:
            continue
        trips = []
        for seg, ongoing in segment_trips(pts, blat, blon, brad):
            s = summarize(seg, ongoing, blat, blon)
            if s:
                trips.append(s)
        if trips:
            result[num] = trips[-MAX_TRIPS_KEEP:][::-1]

    doc = {"generated_at": now.isoformat(), "days_back": DAYS_BACK,
           "trips": result}
    with open("trips.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    ntr = sum(len(v) for v in result.values())
    print(f"trips.json: {len(result)} trucks, {ntr} trips")


if __name__ == "__main__":
    main()
