# spd-fleet-status — pipeline notes for Claude

This repo is **public**. Never commit secrets (tokens, keys) or add personal/business data here.
Project knowledge and working rules live in the private workspace repo (`CLAUDE.md` + `_memory/`) —
read those first when both repos are available.

## What runs here
- `pipeline/run.py` — runs on GitHub Actions (`.github/workflows/update-fleet.yml`, ~every 15 min via
  `workflow_dispatch`). Pulls GPS (DTC + second GPS vendor), the fuel sheet and the truck roster,
  classifies each truck, and commits `fleet-status.json` (contract: `API_CONTRACT.md` in the workspace repo).
- Secrets come only from Actions secrets (`DTC_TOKEN`, `GDRIVE_SA_KEY`, `CALENDAR_ID`). Never write the calendar owner email (or any personal data) into code — this repo is public.

## Before pushing a change
- Fresh machine / cloud session: `pip install openpyxl google-api-python-client google-auth` first
  (same packages the Actions workflows install; no secrets needed for the tests).
- Run the offline tests (no network): `python pipeline/test_trip_memory.py`, `pipeline/test_gps_lost.py`,
  `pipeline/test_dtc_down.py`, `pipeline/test_leg.py`, `pipeline/test_direction.py`.
- Changing truck classification (`classify`): replay real published rounds through the new code and
  compare with the deployed code — `python pipeline/replay_check.py 200 --vs origin/main`. Expect 0 detector
  hits and differences only for the trucks you meant to change.
- After pushing, wait for the next data round and check the published `fleet-status.json`.

## Flip detector
- Every round, `detect_flips()` flags trucks whose side changed while the truck didn't move (< 500 m) and its
  job and driver stayed the same — a sign the rule decided on time or compass alone. Hits go to the Actions log
  (`::warning`) and `flip-alerts.jsonl`. Check that file first when a truck's status looks wrong.
- The first round after a classifier deploy also flags trucks the new code changed — confirm they are intended.
