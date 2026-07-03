#!/usr/bin/env python3
"""Cloud pipeline (runs on GitHub Actions):
  DTC GPS  +  น้ำมัน.xlsx (via service account)  ->  classify 3 categories
  -> write fleet-status.json at repo root.

Secrets via env: DTC_TOKEN, GDRIVE_SA_KEY (service-account JSON string).
"""
import base64
import io
import json
import math
import os
import re
import ssl
import urllib.request
from datetime import datetime, timezone, timedelta

import openpyxl
from google.oauth2 import service_account
from googleapiclient.discovery import build as gbuild
from googleapiclient.http import MediaIoBaseDownload

# ---------- constants ----------
DTC_BASE = "https://gps.dtc.co.th:8099"
FUEL_FILE_ID = "1tf9x5I7ombD15wV-89KRLn-F_7Kco7MA"
COUNT = 3

GROUPS = {
    "dump": ["1290", "1571", "2270", "2943"],
    "pen": ["1266", "1268", "1286"],
    "flatbed": ["1163", "1169", "1300", "1974", "2187", "2592", "2792", "2827",
                "3001", "3066", "3070", "3604", "3606", "3608", "3610", "3637", "3971"],
}
GROUP_OF = {n: g for g, ns in GROUPS.items() for n in ns}
GROUP_LABEL = {"dump": "ดั้ม", "pen": "คอก", "flatbed": "พื้นเรียบ"}
GROUP_ORDER = ["dump", "pen", "flatbed"]
CAT_ORDER = ["find_outbound", "find_return", "working"]
CAT_LABEL = {"find_outbound": "หางานไป", "find_return": "หางานกลับ", "working": "อยู่ระหว่างทำงาน"}
EXCLUDE = {"2168", "1288", "1250"}

DRIVER = {
    "1571": "ตั้ม", "2270": "สอ", "2943": "ต้อม", "1266": "เพชร", "1268": "สิน",
    "1286": "เดวิด", "1290": "ยอด", "1169": "ศักดิ์", "2187": "ป้อม", "1163": "ต่อ",
    "1300": "เอ็ม2", "1974": "พัน", "2592": "บิน", "2792": "หมู", "2827": "มิตร",
    "3001": "จำนง", "3066": "คอม", "3070": "เอ็ม", "3604": "บี", "3606": "สุพจ",
    "3608": "อำนาจ", "3610": "พจ", "3637": "เล่", "3971": "แม็ก",
}

PROV_IDX = {
    "ศรีสะเกษ": 0, "อุบลราชธานี": 0, "อำนาจเจริญ": 0, "ยโสธร": 0, "ร้อยเอ็ด": 0,
    "สุรินทร์": 1,
    "บุรีรัมย์": 2, "นครราชสีมา": 3, "สระแก้ว": 3, "สระบุรี": 4, "ปราจีนบุรี": 4,
    "นครนายก": 4, "พระนครศรีอยุธยา": 5, "ฉะเชิงเทรา": 5, "ลพบุรี": 5, "ปทุมธานี": 6,
    "ชลบุรี": 6, "นนทบุรี": 7, "ระยอง": 7, "สุพรรณบุรี": 8, "กรุงเทพมหานคร": 8,
    "จันทบุรี": 8, "สมุทรปราการ": 9, "นครปฐม": 9, "สมุทรสาคร": 9, "ตราด": 9,
    "กาญจนบุรี": 9,
}
HOME = {"ศรีสะเกษ", "อุบลราชธานี", "สุรินทร์"}

# province-name aliases found inside route waypoints -> canonical province
PROVINCE_ALIASES = {
    "ศรีสะเกษ": "ศรีสะเกษ", "ศก": "ศรีสะเกษ", "อุบล": "อุบลราชธานี", "อบ": "อุบลราชธานี",
    "สุรินทร์": "สุรินทร์", "บุรีรัมย์": "บุรีรัมย์", "นครราชสีมา": "นครราชสีมา",
    "โคราช": "นครราชสีมา", "สระแก้ว": "สระแก้ว", "สระบุรี": "สระบุรี",
    "ปราจีน": "ปราจีนบุรี", "ฉะเชิงเทรา": "ฉะเชิงเทรา", "อยุธยา": "พระนครศรีอยุธยา",
    "ปทุมธานี": "ปทุมธานี", "นนทบุรี": "นนทบุรี", "ชลบุรี": "ชลบุรี", "ระยอง": "ระยอง",
    "จันทบุรี": "จันทบุรี", "ตราด": "ตราด", "สมุทรปราการ": "สมุทรปราการ",
    "สมุทรสาคร": "สมุทรสาคร", "นครปฐม": "นครปฐม", "สุพรรณบุรี": "สุพรรณบุรี",
    "กาญ": "กาญจนบุรี", "กรุงเทพ": "กรุงเทพมหานคร", "กทม": "กรุงเทพมหานคร",
    "ร้อยเอ็ด": "ร้อยเอ็ด", "ยโสธร": "ยโสธร", "อำนาจ": "อำนาจเจริญ",
}

# place/customer name (substring) -> province  (from truck-fleet-accounting place DB)
PLACE_DB = {
    "ยูนิเวอร์แซล": "สมุทรสาคร", "ยูนิทรินิตี้": "สมุทรปราการ", "ไทยลี": "สมุทรปราการ",
    "กระชับมิตร": "สระบุรี", "จงเช่อ": "ระยอง", "แหลมฉบัง": "ชลบุรี",
    "ราชสีมาไรซ์": "นครราชสีมา", "โคกกรวด": "นครราชสีมา", "นครหลวง": "พระนครศรีอยุธยา",
    "คลอง7": "ปทุมธานี", "แคปปิตอล": "พระนครศรีอยุธยา", "บางไทร": "พระนครศรีอยุธยา",
    "เอี่ยมศิริ": "ศรีสะเกษ", "บีบีพี": "สุรินทร์", "bbp": "สุรินทร์",
    "เอี่ยมอุบล": "อุบลราชธานี", "ผักบุ้ง": "ศรีสะเกษ", "ย่งล้ง": "สุรินทร์",
    "ชัยทิพย์": "สระบุรี", "สตึก": "บุรีรัมย์", "อุทัยโปรดิว": "สมุทรปราการ",
    "บ้านโคก": "ศรีสะเกษ", "เฮียเหลา": "ชลบุรี", "อุบลอินเตอร์": "อุบลราชธานี",
    "โตเต็ม": "ศรีสะเกษ", "เอี่ยมอีสาน": "อุบลราชธานี", "เอี่ยมอำนาจ": "อำนาจเจริญ",
    "ธัญหิรัณย์": "ศรีสะเกษ", "ซันฟลาวเวอร์": "อุบลราชธานี", "สินทวีการเกษตร": "ศรีสะเกษ",
    "ซินเคอหยวน": "ระยอง", "ประสิทธิ์ชัย": "อุบลราชธานี", "cps": "ศรีสะเกษ",
    "หนองกี่": "บุรีรัมย์", "จงเจริญ": "ศรีสะเกษ", "ตั้งไพบูลย์": "ศรีสะเกษ",
    "พัฒนกิจ": "ศรีสะเกษ", "ธัญกิจไรซ์": "ศรีสะเกษ", "แสงเจริญเขื่องใน": "อุบลราชธานี",
    "แสงเจริญ": "ศรีสะเกษ", "เอกไรซ์": "อุบลราชธานี", "ส.เจริญกิจ": "ศรีสะเกษ",
    "แซเอี้ยง": "ศรีสะเกษ", "โอแลม": "นนทบุรี", "บีวีซีเจริญทรัพย์": "สมุทรปราการ",
    "ส.สินทวี": "ศรีสะเกษ", "โพนทราย": "ร้อยเอ็ด", "สุขสวัสดิ์ค้าไม้": "นนทบุรี",
    "วัดมหาวงศ์": "สมุทรปราการ", "ทาทาระยอง": "ระยอง", "ทาทาบ่อวิน": "ชลบุรี",
    "ปูนมอร์ต้า": "สระบุรี", "แก่งคอย": "สระบุรี", "สยามมอร์ตาร์": "สระบุรี",
    "โชคชัยไพบูลย์": "ศรีสะเกษ", "มังกรทองปราสาท": "สุรินทร์", "สยามไฟเบอร์": "สระบุรี",
    "ปุ๋ยกระต่าย": "พระนครศรีอยุธยา", "ดีซี": "ปทุมธานี", "ไทยบำรุง": "ศรีสะเกษ",
    "สินประดิษฐ์การโยธา": "ศรีสะเกษ", "คำเขื่อนแก้วกรีน": "ศรีสะเกษ", "หนองแห่": "อำนาจเจริญ",
    "ปราสาท": "สุรินทร์", "พูนศักดิ์": "สุรินทร์", "เมืองวัสดุ": "อุบลราชธานี",
    "อุบลวัสดุ": "อุบลราชธานี", "เจียเม้ง": "ศรีสะเกษ", "ซีพีโนนคูณ": "ศรีสะเกษ",
    "โนนคูณ": "ศรีสะเกษ", "พิบูล": "อุบลราชธานี", "บกด หนองแค": "สระบุรี",
    "ซีแพ็คหนองแค": "สระบุรี", "หนองแค": "สระบุรี", "นอร์ทอีส": "สระบุรี",
    "เตียเหลียง": "อุบลราชธานี", "ดูโฮม": "พระนครศรีอยุธยา",
    # known districts -> province
    "หน้าพระลาน": "สระบุรี", "เขื่องใน": "อุบลราชธานี", "บางกรวย": "นนทบุรี",
    "บางบัวทอง": "นนทบุรี", "บางปะหัน": "พระนครศรีอยุธยา", "พระประแดง": "สมุทรปราการ",
    "มหาชนะชัย": "ยโสธร", "กันทรารมย์": "ศรีสะเกษ", "วังน้อย": "พระนครศรีอยุธยา",
    "บุณฑริก": "อุบลราชธานี", "บ่อวิน": "ชลบุรี",
    # common spelling variants seen in the fuel file
    "สมุทรปรากร": "สมุทรปราการ", "สมุทปราการ": "สมุทรปราการ",
    "สมุทรปราการ": "สมุทรปราการ", "อยุธยา": "พระนครศรีอยุธยา",
}
_RESOLVE = {**PLACE_DB, **{k.lower(): v for k, v in PLACE_DB.items()},
            **PROVINCE_ALIASES}
_RESOLVE_KEYS = sorted(_RESOLVE, key=len, reverse=True)


def resolve_province(name):
    """Map a route waypoint (place/customer/province name) to a province."""
    if not name:
        return None
    n = name.strip()
    nl = n.lower()
    for k in _RESOLVE_KEYS:
        if k in n or k in nl:
            return _RESOLVE[k]
    return None
THAI_MONTH = {1: "มค", 2: "กพ", 3: "มีค", 4: "เมย", 5: "พค", 6: "มิย",
              7: "กค", 8: "สค", 9: "กย", 10: "ตค", 11: "พย", 12: "ธค"}

# ---------- DTC stations (POI) + ETA ----------
# route-waypoint substring -> POI name (normalized, no spaces) for arrival/ETA
DEST_POI = {
    "นนทบุรี": "เจียเม้งนนทบุรี",
    "แก่งคอย": "สยามมอร์ตาร์แก่งคอย2", "สยามมอร์ตาร์": "สยามมอร์ตาร์แก่งคอย2",
    "ปูนมอร์ต้า": "สยามมอร์ตาร์แก่งคอย2",
    "นครหลวง": "ซีพีนครหลวง", "ซีพีนครหลวง": "ซีพีนครหลวง",
    "บีบีพี": "BBPRiceMill", "bbp": "BBPRiceMill",
    "ดีซี": "ศูนย์กระจายสินค้าดูโฮมลำลูกกา", "ลำลูกกา": "ศูนย์กระจายสินค้าดูโฮมลำลูกกา",
    "ดูโฮมอยุธยา": "ดูโฮมอยุธยา", "ดูโฮม อยุธยา": "ดูโฮมอยุธยา",
    "ทีเจ": "บริษัททีเจครอปอยุธยาจำกัด",
}
HOME_POI = "สินประดิษฐ์"          # ฐานบ้าน — ใช้คิด ETA ขากลับ
TRUCK_FACTOR = 1.2                 # รถบรรทุกช้ากว่าเวลารถเก๋งของ OSRM


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def fetch_pois(token):
    """DTC POIs -> {norm_name: {name, lat, lon, radius, poly:[(lat,lon)..]}}
    Circle (type C) has lat/lon+area_m; polygon (type P) has WKT geo_polygon."""
    try:
        d = dtc_post("/getPOI", {"api_token_key": token})
    except Exception:
        return {}
    out = {}
    for p in d.get("data", []):
        name = (p.get("poi_name") or "").strip()
        if not name:
            continue
        key = _norm(name)
        st = out.setdefault(key, {"name": name, "lat": None, "lon": None,
                                  "radius": 0, "poly": None})
        try:
            lat, lon = float(p.get("lat") or 0), float(p.get("lon") or 0)
        except (TypeError, ValueError):
            lat = lon = 0
        if lat and lon:                       # circle point
            st["name"] = name                 # prefer point-style entry's name
            st["lat"], st["lon"] = lat, lon
            try:
                st["radius"] = max(float(p.get("area_m") or 0), 150)
            except (TypeError, ValueError):
                st["radius"] = 200
        gp = p.get("geo_polygon") or ""
        nums = re.findall(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", gp)
        if nums:
            poly = [(float(la), float(lo)) for lo, la in nums]   # WKT = lon lat
            st["poly"] = poly
            if not st["lat"]:                 # centroid as reference point
                st["lat"] = sum(x for x, _ in poly) / len(poly)
                st["lon"] = sum(y for _, y in poly) / len(poly)
    return out


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _in_poly(lat, lon, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        la1, lo1 = poly[i]
        la2, lo2 = poly[(i + 1) % n]
        if (lo1 > lon) != (lo2 > lon):
            t = (lon - lo1) / (lo2 - lo1)
            if lat < la1 + t * (la2 - la1):
                inside = not inside
    return inside


def station_of(lat, lon, pois):
    """POI display-name the point is inside (polygon, or within circle radius
    + small buffer), else None."""
    for st in pois.values():
        if st["poly"] and _in_poly(lat, lon, st["poly"]):
            return st["name"]
        if st["lat"] and _haversine_m(lat, lon, st["lat"], st["lon"]) <= (st["radius"] or 200) + 100:
            return st["name"]
    return None


def match_dest_poi(out_name, pois):
    if not out_name:
        return None
    n, nl = _norm(out_name), _norm(out_name).lower()
    for k in sorted(DEST_POI, key=len, reverse=True):
        if _norm(k) in n or _norm(k) in nl:
            return pois.get(_norm(DEST_POI[k]))
    return None


_osrm_fail = 0


def osrm_eta_hours(lat1, lon1, lat2, lon2):
    """Driving hours (truck-adjusted) via OSRM public server; None on failure."""
    global _osrm_fail
    if _osrm_fail >= 2:                       # server down → stop trying this run
        return None
    url = (f"https://router.project-osrm.org/route/v1/driving/"
           f"{lon1},{lat1};{lon2},{lat2}?overview=false")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "spd-fleetview"})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read().decode("utf-8"))
        sec = d["routes"][0]["duration"]
        _osrm_fail = 0
        return sec / 3600.0 * TRUCK_FACTOR
    except Exception:
        _osrm_fail += 1
        return None


def fmt_eta(h):
    if h is None:
        return None
    if h < 0.95:
        m = max(int(round(h * 60 / 10.0) * 10), 10)
        return f"~{m} นาที"
    half = round(h * 2) / 2
    return f"~{half:g} ชม."

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def thai_today(now):
    return f"{now.day} {THAI_MONTH[now.month]} {(now.year + 543) % 100:02d}"


def dtc_post(path, body):
    req = urllib.request.Request(DTC_BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=40, context=_ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def pull_dtc(token):
    vm = dtc_post("/getVehicleMaster", {"api_token_key": token})
    vehicles = vm.get("data", [])
    gps_ids = [v["gps_id"] for v in vehicles]
    rt = dtc_post("/getRealtimeData", {"api_token_key": token, "gps_list": gps_ids})
    return vehicles, rt.get("data", [])


def download_fuel(sa_json):
    info = json.loads(sa_json.lstrip("﻿").strip())
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    svc = gbuild("drive", "v3", credentials=creds, cache_discovery=False)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=FUEL_FILE_ID))
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf


def parse_fuel(xlsx_buf):
    wb = openpyxl.load_workbook(xlsx_buf, data_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(min_col=1, max_col=2, values_only=True))
        route = date = None
        ridx = None
        for i in range(len(rows) - 1, -1, -1):
            b = rows[i][1]
            if isinstance(b, str) and b.strip():
                route, ridx = b.rstrip(), i
                break
        if ridx is not None:
            for j in range(ridx, -1, -1):
                a = rows[j][0]
                if a is not None and str(a).strip():
                    date = str(a).strip()
                    break
        digits = "".join(c for c in ws.title if c.isdigit())
        if digits:
            out[digits] = {"route": route, "date": date}
    return out


def province_index(prov):
    return PROV_IDX.get(prov, 5)


def destination_of(route):
    if not route:
        return None
    parts = [p.strip() for p in route.split("-")]
    last = next((p for p in reversed(parts) if p), None)
    if last and "งาน" in last:
        last = last.split("งาน")[0].strip()
    return last or None


def route_waypoints(route):
    """Cleaned non-empty waypoints; strip 'งาน[ลูกค้า]' suffix on each point."""
    if not route:
        return []
    out = []
    for p in route.split("-"):
        p = p.strip()
        if not p:
            continue
        if "งาน" in p:
            p = p.split("งาน")[0].strip()
        if p:
            out.append(p)
    return out


def classify(vehicles, realtime, fuel, recent_dates, unknown=None, pois=None):
    pois = pois or {}
    num_by_gps = {v["gps_id"]: v["vehicle_name"].replace("70-", "") for v in vehicles}
    rt_by_num = {}
    for r in realtime:
        num = (r.get("truck_name") or "").replace("70-", "") or num_by_gps.get(r.get("gps_id"), "")
        rt_by_num[num] = r
    trucks = []
    for num in sorted(set(GROUP_OF) - EXCLUDE):
        group = GROUP_OF[num]
        f = fuel.get(num, {})
        route, fdate = f.get("route"), f.get("date")
        is_toy = bool(route) and route.strip().startswith("ทอย")
        has_return = bool(route) and not route.rstrip().endswith("-") and not is_toy
        disp_dest = destination_of(route)        # what the app shows
        wps = route_waypoints(route)
        # outbound destination = 2nd waypoint (จุดที่ 2); fall back to 1st/last
        out_name = wps[1] if len(wps) >= 2 else (wps[-1] if wps else None)
        idx_out = PROV_IDX.get(resolve_province(out_name)) if out_name else None
        driver = DRIVER.get(num, "")
        rt = rt_by_num.get(num)

        if rt is None:  # no GPS (e.g. 1163) -> file only
            cat = "find_outbound" if has_return else "find_return"
            reason = ("ไฟล์มีงานกลับแล้ว → กลับถึงบ้าน ว่าง (จากไฟล์)" if has_return
                      else "ไฟล์ลงท้าย - → ส่งของแล้ว รอรับกลับ (จากไฟล์)")
            trucks.append(dict(number=num, driver=driver, group=group, category=cat,
                               gps_status="ไม่มี GPS", province=None, district=None,
                               location_text="—", destination=disp_dest, reason=reason, lat=None,
                               lon=None, speed=None, heading=None, updated=None,
                               from_file=True, stale=False))
            continue

        prov, dist = rt.get("province_th"), rt.get("district_th")
        idx_now = PROV_IDX.get(prov)
        try:
            heading = float(rt.get("heading")) if rt.get("heading") is not None else None
        except (TypeError, ValueError):
            heading = None
        head_out = heading is not None and 200 <= heading <= 340
        is_recent = fdate in recent_dates       # today or yesterday
        # --- station awareness (DTC POI) ---
        try:
            tlat, tlon = float(rt.get("lat") or 0), float(rt.get("lon") or 0)
        except (TypeError, ValueError):
            tlat = tlon = 0
        at_st = station_of(tlat, tlon, pois) if (tlat and tlon) else None
        dest_poi = match_dest_poi(out_name, pois) if not is_toy else None
        at_dest = bool(at_st and dest_poi and _norm(at_st) == _norm(dest_poi["name"]))

        if is_toy:                               # งานทอย — ใช้ตำแหน่ง GPS ล้วน
            zi = idx_now if idx_now is not None else 5
            if prov in HOME:
                cat, reason = "find_outbound", "งานทอย อยู่โซนบ้าน ว่างรับงานไป"
            elif zi >= 3:
                cat, reason = "find_return", "งานทอย อยู่โซนกลาง/ตะวันออก รอรับงานกลับ"
            elif head_out:
                cat, reason = "find_return", "งานทอย มุ่งออก รอรับงานกลับ"
            else:
                cat, reason = "find_outbound", "งานทอย มุ่งเข้าบ้าน ว่างรับงานไป"
        elif idx_now is None or idx_out is None:
            # FALLBACK: map จังหวัดไม่ได้ → ใช้ logic โซนแบบเดิม (จุดนับ index 3)
            if unknown is not None and idx_out is None and out_name:
                unknown.add(out_name)
            zi = idx_now if idx_now is not None else 5
            if not has_return:
                if zi >= COUNT:
                    cat, reason = "find_return", "เลยจุดนับขาไป รอรับงานกลับ (ประเมินจากโซน)"
                elif zi <= 1 and not is_recent:
                    cat, reason = "find_outbound", "อยู่บ้าน งานเก่า → ว่าง (ประเมินจากโซน)"
                else:
                    cat, reason = "working", "กำลังไปส่ง (ประเมินจากโซน)"
            else:
                if zi <= 1:
                    cat, reason = (("working", "เพิ่งออกงาน (ประเมินจากโซน)") if
                                   (is_recent and head_out) else
                                   ("find_outbound", "ถึงบ้านแล้ว ว่าง (ประเมินจากโซน)"))
                else:
                    cat, reason = "working", "กำลังขนกลับ (ประเมินจากโซน)"
        else:
            # ROUTE-PROGRESS: เทียบตำแหน่งรถกับปลายทางขาไปจริงของเที่ยวนี้
            if not has_return:                    # รู้แค่ขาไป (ลงท้าย "-")
                if at_dest:                       # อยู่ในสถานีปลายทางจริง (POI)
                    cat, reason = "find_return", f"ถึง {at_st} แล้ว — ส่งของแล้ว รอรับงานกลับ"
                elif idx_now >= idx_out:
                    cat, reason = "find_return", f"ถึงปลายทางขาไป ({out_name}) แล้ว ส่งของแล้ว รอรับงานกลับ"
                elif idx_now <= 1:
                    if is_recent:
                        cat, reason = "working", "รับงานขาไปแล้ว กำลังจะออก"
                    else:
                        cat, reason = "find_outbound", "ว่าง พร้อมรับงานไป"
                else:
                    cat, reason = "working", f"กำลังไปส่ง — ถึง {prov} แล้ว ยังไม่ถึง {out_name}"
            else:                                 # มีงานกลับครบเที่ยว
                if at_dest:
                    cat, reason = "working", f"อยู่ที่ {at_st} — ส่งของ (มีงานกลับต่อ)"
                elif idx_now <= 1:                # ถึงโซนบ้าน
                    if is_recent and head_out:
                        cat, reason = "working", "เพิ่งออกงานวันนี้ (มุ่งออก)"
                    else:
                        cat, reason = "find_outbound", "ขนกลับถึงบ้านแล้ว ว่างรับงานไป"
                elif head_out and idx_now < idx_out:
                    cat, reason = "working", f"กำลังไปส่ง ({out_name})"
                else:
                    near = " ใกล้ถึงบ้าน" if idx_now == 2 else ""
                    cat, reason = "working", "กำลังขนกลับ" + near

        # --- ETA ต่อท้ายเหตุผล (เฉพาะรถที่กำลังวิ่งงาน) ---
        eta_h = None
        if cat == "working" and tlat and tlon and not is_toy:
            if "กำลังไปส่ง" in reason and dest_poi and dest_poi.get("lat") and not at_dest:
                eta_h = osrm_eta_hours(tlat, tlon, dest_poi["lat"], dest_poi["lon"])
                e = fmt_eta(eta_h)
                if e:
                    reason += f" · อีก {e} ถึง {dest_poi['name']}"
            elif "ขนกลับ" in reason:
                home = pois.get(_norm(HOME_POI))
                if home and home.get("lat"):
                    eta_h = osrm_eta_hours(tlat, tlon, home["lat"], home["lon"])
                    e = fmt_eta(eta_h)
                    if e:
                        reason += f" · อีก {e} ถึงบ้าน"
        # รถจอดอยู่ในสถานีอื่นที่รู้จัก (ไม่ใช่ปลายทาง) → บอกไว้
        if at_st and at_st not in reason:
            reason += f" · 📍{at_st}"

        loc = f"{prov} · {dist}" if prov and dist else (prov or "—")
        trucks.append(dict(number=num, driver=driver, group=group, category=cat,
                           gps_status=rt.get("status_name_th") or "", province=prov,
                           district=dist, location_text=loc, destination=disp_dest, reason=reason,
                           lat=rt.get("lat"), lon=rt.get("lon"), speed=rt.get("gps_speed"),
                           heading=heading, updated=rt.get("time"), from_file=False, stale=False,
                           at_station=at_st, eta_hours=(round(eta_h, 1) if eta_h else None)))
    return trucks


def build_doc(trucks, now):
    cats = []
    counts = {}
    for ck in CAT_ORDER:
        ct = [t for t in trucks if t["category"] == ck]
        counts[ck] = len(ct)
        groups = []
        for gk in GROUP_ORDER:
            gt = [t for t in ct if t["group"] == gk]
            if gt:
                groups.append({"key": gk, "label": GROUP_LABEL[gk], "trucks": gt})
        cats.append({"key": ck, "label": CAT_LABEL[ck], "count": len(ct), "groups": groups})
    need = counts["find_outbound"] + counts["find_return"]
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "summary": {"need_work": need, "find_outbound": counts["find_outbound"],
                    "find_return": counts["find_return"], "working": counts["working"]},
        "categories": cats,
    }


def main():
    token = os.environ["DTC_TOKEN"]
    sa_json = os.environ["GDRIVE_SA_KEY"]
    now = datetime.now(timezone(timedelta(hours=7)))
    today = thai_today(now)
    recent_dates = {today, thai_today(now - timedelta(days=1))}  # today + yesterday
    vehicles, realtime = pull_dtc(token)
    fuel = parse_fuel(download_fuel(sa_json))
    pois = fetch_pois(token)
    unknown = set()
    trucks = classify(vehicles, realtime, fuel, recent_dates, unknown, pois)
    doc = build_doc(trucks, now)
    with open("fleet-status.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    n_eta = sum(1 for t in trucks if t.get("eta_hours"))
    n_st = sum(1 for t in trucks if t.get("at_station"))
    print(f"today={today} recent={sorted(recent_dates)} vehicles={len(vehicles)} "
          f"realtime={len(realtime)} trucks={len(trucks)} pois={len(pois)} "
          f"at_station={n_st} eta={n_eta} summary={doc['summary']}")
    if unknown:
        print("UNKNOWN destinations (fell back to zone logic):", ", ".join(sorted(unknown)))


if __name__ == "__main__":
    main()
