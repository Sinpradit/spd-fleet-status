# -*- coding: utf-8 -*-
"""ตรวจก่อน deploy: เล่นซ้ำรอบจริงที่เคย publish (fleet-status.json ใน git history) ผ่านโค้ดใน working tree
แบบต่อเนื่อง (ความจำเที่ยว + ฝั่งรอบก่อน) แล้วให้ตัวจับผิดตรวจผล · ไม่ยิงเน็ต ไม่เขียนไฟล์ใน repo

ใช้ (จากโฟลเดอร์ repo):
  python pipeline/replay_check.py [N]                 # N รอบล่าสุด (ค่าเริ่ม 200 ≈ 2 วัน)
  python pipeline/replay_check.py [N] --vs origin/main  # + เทียบกับโค้ดที่ ref นั้น (เช่น ที่ deploy อยู่)
ผลที่ควรเห็น: ตัวจับผิด 0 ครั้ง และ (ถ้า --vs) ต่างเฉพาะคันที่ตั้งใจแก้"""
import collections
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
args = [a for a in sys.argv[1:]]
VS = args[args.index("--vs") + 1] if "--vs" in args else None
nums = [a for a in args if a.isdigit()]
N = int(nums[0]) if nums else 200
os.chdir(REPO)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._osrm_fail = 99                     # ไม่ยิง OSRM (ETA ใช้ระยะทางตรง)
    return m


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, check=True).stdout


new = load("run_new", os.path.join(HERE, "run.py"))
old = None
if VS:
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "run.py"), "wb") as f:
        f.write(git("show", f"{VS}:pipeline/run.py"))
    old = load("run_old", os.path.join(tmp, "run.py"))

shas = git("log", f"-{N + 1}", "--format=%H", "--", "fleet-status.json").decode().split()[::-1]
snaps = []
for s in shas:
    try:
        snaps.append(json.loads(git("show", f"{s}:fleet-status.json").decode("utf-8")))
    except ValueError:
        pass
if len(snaps) < 2:
    sys.exit(f"มี snapshot แค่ {len(snaps)} รอบ (clone แบบตื้น?) — ลอง git fetch --unshallow")
full_hist = new.load_route_history(datetime.fromisoformat(snaps[-1]["generated_at"]), days=16)
HOME = {new._norm(new.HOME_POI): {"name": new.HOME_POI, "lat": new.BASE_LATLON[0],
                                   "lon": new.BASE_LATLON[1], "radius": 300, "poly": None}}


def call(m, *a, **kw):
    ok = inspect.signature(m.classify).parameters
    return m.classify(*a, **{k: v for k, v in kw.items() if k in ok})


state = {k: {"trips": {}, "out": None} for k in (["new", "old"] if old else ["new"])}
alerts, diffs, changes = [], [], 0
for prev, cur in zip(snaps, snaps[1:]):
    now = datetime.fromisoformat(cur["generated_at"])
    cut = cur["generated_at"][:19].replace("T", " ")
    hist = {n: [p for p in pts if p[0] < cut] for n, pts in full_hist.items()}
    recent = {new.thai_today(now), new.thai_today(now - timedelta(days=1))}
    future = {new.thai_today(now + timedelta(days=k)) for k in range(1, 15)}
    rt, fuel, roster, drivers = [], {}, [], {}
    for t in new._iter_trucks(cur):
        n = t["number"]
        roster.append(n)
        if t.get("driver"):
            drivers[n] = t["driver"]
        if t.get("job_key"):
            r, _, d = t["job_key"].partition("|")
            fuel[n] = {"route": r, "date": d}
        if t.get("lat") and t.get("lon"):
            rt.append({"truck_name": f"70-{n}", "lat": t["lat"], "lon": t["lon"],
                       "province_th": t.get("province"), "district_th": t.get("district"),
                       "heading": t.get("heading"), "gps_speed": t.get("speed"),
                       "time": t.get("updated"), "status_name_th": t.get("gps_status"),
                       "truck_type_name": (new._TYPE_WORD.get(t.get("group"))
                                           if t.get("group_src") == "dtc" else None)})
    pois = {**new.stale_pois(cur), **HOME}
    prev_pos = {t["number"]: (t["lat"], t["lon"]) for t in new._iter_trucks(prev)
                if t.get("lat") and t.get("lon")}
    res = {}
    for k, m in (("new", new), ("old", old)):
        if k not in state:
            continue
        st = state[k]
        pstat = ({t["number"]: {"job_key": t.get("job_key"), "category": t.get("category"),
                                "reason": t.get("reason")} for t in st["out"]} if st["out"] else {})
        out = call(m, [], rt, fuel, recent, set(), pois, roster=roster, drivers=drivers, gps2=None,
                   prev_pos=prev_pos, future_dates=future, manual_groups={}, prev_trips=st["trips"],
                   history=hist, now=now, prev_status=pstat)
        if k == "new" and st["out"] is not None:
            alerts += new.detect_flips({"categories": [{"groups": [{"trucks": st["out"]}]}]}, out, now)
            ps_ = {t["number"]: new._side(t) for t in st["out"]}
            changes += sum(1 for t in out if ps_.get(t["number"], new._side(t)) != new._side(t))
        st["trips"] = {t["number"]: t["trip"] for t in out if t.get("trip")}
        st["out"] = out
        res[k] = {t["number"]: t for t in out}
    if old:
        for n, b in res["new"].items():
            a = res["old"].get(n)
            if a and (new._side(a) != new._side(b) or a.get("reason") != b.get("reason")):
                diffs.append((cur["generated_at"][5:16], n, new._side(a), a.get("reason", ""),
                              new._side(b), b.get("reason", "")))

print(f"เล่นซ้ำ {len(snaps) - 1} รอบ ({snaps[1]['generated_at'][5:16]} → {snaps[-1]['generated_at'][5:16]})"
      f" · การเปลี่ยนฝั่งทั้งหมด (โค้ดใหม่) {changes} ครั้ง")
print(f"ตัวจับผิด (ฝั่งเปลี่ยนทั้งที่ไม่ขยับ): {len(alerts)} ครั้ง",
      dict(collections.Counter(a["n"] for a in alerts).most_common()))
for a in alerts[:40]:
    print(f"  {a['t'][5:16]} {a['n']:5} {a['from']} → {a['to']} | ขยับ {a['moved_m']} ม. | {a['to_reason'][:60]}")
if old:
    per = collections.Counter(d[1] for d in diffs)
    print(f"\nเทียบกับ {VS}: ต่างกัน {len(diffs)} คัน·รอบ · {dict(per.most_common())}")
    shown = set()
    for t, n, sa, ra, sb, rb in diffs:
        if n in shown:
            continue
        shown.add(n)
        print(f"  {t} {n}: [{sa}] {ra[:60]}\n  {'':{len(t) + len(n) + 2}}→ [{sb}] {rb[:60]}")
    side = [d for d in diffs if d[2] != d[4]]       # ต่างที่ "ฝั่ง" จริง (ไม่นับแค่ข้อความเหตุผล)
    sper = collections.Counter(d[1] for d in side)
    print(f"\nต่างที่ฝั่ง: {len(side)} คัน·รอบ · {dict(sper.most_common())}")
    for t, n, sa, ra, sb, rb in side:
        print(f"  {t} {n}: [{sa}] {ra[:50]}  →  [{sb}] {rb[:50]}")
