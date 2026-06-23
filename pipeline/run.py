#!/usr/bin/env python3
"""Cloud pipeline (runs on GitHub Actions):
  DTC GPS  +  น้ำมัน.xlsx (via service account)  ->  classify 3 categories
  -> write fleet-status.json at repo root.

Secrets via env: DTC_TOKEN, GDRIVE_SA_KEY (service-account JSON string).
"""
import base64
import io
import json
import os
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
    "ศรีสะเกษ": 0, "อุบลราชธานี": 0, "อำนาจเจริญ": 0, "ยโสธร": 0, "สุรินทร์": 1,
    "บุรีรัมย์": 2, "นครราชสีมา": 3, "สระแก้ว": 3, "สระบุรี": 4, "ปราจีนบุรี": 4,
    "นครนายก": 4, "พระนครศรีอยุธยา": 5, "ฉะเชิงเทรา": 5, "ลพบุรี": 5, "ปทุมธานี": 6,
    "ชลบุรี": 6, "นนทบุรี": 7, "ระยอง": 7, "กรุงเทพมหานคร": 8, "จันทบุรี": 8,
    "สมุทรปราการ": 9, "นครปฐม": 9, "สมุทรสาคร": 9, "ตราด": 9,
}
HOME = {"ศรีสะเกษ", "อุบลราชธานี", "สุรินทร์"}
THAI_MONTH = {1: "มค", 2: "กพ", 3: "มีค", 4: "เมย", 5: "พค", 6: "มิย",
              7: "กค", 8: "สค", 9: "กย", 10: "ตค", 11: "พย", 12: "ธค"}

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


def classify(vehicles, realtime, fuel, today):
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
        has_return = bool(route) and not route.rstrip().endswith("-")
        dest = destination_of(route)
        driver = DRIVER.get(num, "")
        rt = rt_by_num.get(num)
        if rt is None:  # no GPS (e.g. 1163) -> file only
            cat = "find_outbound" if has_return else "find_return"
            reason = ("ไฟล์มีงานกลับแล้ว → กลับถึงบ้าน ว่าง (จากไฟล์)" if has_return
                      else "ไฟล์ลงท้าย - → ส่งของแล้ว รอรับกลับ (จากไฟล์)")
            trucks.append(dict(number=num, driver=driver, group=group, category=cat,
                               gps_status="ไม่มี GPS", province=None, district=None,
                               location_text="—", destination=dest, reason=reason, lat=None,
                               lon=None, speed=None, heading=None, updated=None,
                               from_file=True, stale=False))
            continue
        prov, dist = rt.get("province_th"), rt.get("district_th")
        idx = province_index(prov)
        try:
            heading = float(rt.get("heading")) if rt.get("heading") is not None else None
        except (TypeError, ValueError):
            heading = None
        is_today = (fdate == today)
        head_out = heading is not None and 200 <= heading <= 340
        if route and route.strip().startswith("ทอย"):
            if prov in HOME:
                cat, reason = "find_outbound", "งานทอย อยู่โซนบ้าน ว่างรับงานไป"
            elif idx >= 3:
                cat, reason = "find_return", "งานทอย อยู่โซนกลาง/ตะวันออก รอรับงานกลับ"
            elif head_out:
                cat, reason = "find_return", "งานทอย กำลังมุ่งออก รอรับงานกลับ"
            else:
                cat, reason = "find_outbound", "งานทอย มุ่งเข้าบ้าน ว่างรับงานไป"
        elif not has_return:
            if idx >= COUNT:
                cat, reason = "find_return", "ถึง/เลยจุดนับขาไป ส่งของแล้ว รอรับงานกลับ"
            elif is_today:
                cat, reason = "working", "เพิ่งโหลดของออกขาไปวันนี้ ยังไม่ถึงปลายทาง"
            else:
                cat, reason = "find_outbound", "งานเก่าจบ กลับถึงบ้านแล้ว ว่าง"
        else:
            if idx <= 1:
                if is_today and head_out:
                    cat, reason = "working", "เพิ่งออกงานไกลวันนี้ (heading มุ่งออก)"
                else:
                    cat, reason = "find_outbound", "ขนกลับถึงบ้านแล้ว ว่างรับงานไป"
            else:
                cat, reason = "working", "กำลังขนกลับ / positioning"
        loc = f"{prov} · {dist}" if prov and dist else (prov or "—")
        trucks.append(dict(number=num, driver=driver, group=group, category=cat,
                           gps_status=rt.get("status_name_th") or "", province=prov,
                           district=dist, location_text=loc, destination=dest, reason=reason,
                           lat=rt.get("lat"), lon=rt.get("lon"), speed=rt.get("gps_speed"),
                           heading=heading, updated=rt.get("time"), from_file=False, stale=False))
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
    vehicles, realtime = pull_dtc(token)
    fuel = parse_fuel(download_fuel(sa_json))
    trucks = classify(vehicles, realtime, fuel, today)
    doc = build_doc(trucks, now)
    with open("fleet-status.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"today={today} vehicles={len(vehicles)} realtime={len(realtime)} "
          f"trucks={len(trucks)} summary={doc['summary']}")


if __name__ == "__main__":
    main()
