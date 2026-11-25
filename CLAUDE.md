# spd-fleet-status — pipeline notes for Claude

This repo is **public**. Never commit secrets (tokens, keys) or add personal/business data here.
Project knowledge and working rules live in the private workspace repo (`CLAUDE.md` + `_memory/`) —
read those first when both repos are available.

## What runs here
- `pipeline/run.py` — runs on GitHub Actions (`.github/workflows/update-fleet.yml`, ~every 15 min via
  `workflow_dispatch`). Pulls GPS (DTC + second GPS vendor), the fuel sheet and the truck roster,
  classifies each truck, and commits `fleet-status.json` (contract: `API_CONTRACT.md` in the workspace repo).
- Secrets come only from Actions secrets (`DTC_TOKEN`, `GDRIVE_SA_KEY`, …).

## Before pushing a change
- Run the offline tests (no network): `python pipeline/test_trip_memory.py`, `pipeline/test_gps_lost.py`,
  `pipeline/test_dtc_down.py`, `pipeline/test_leg.py`, `pipeline/test_direction.py`.
- Changing truck classification (`classify`): also replay real snapshots of `fleet-status.json` from git
  history through the deployed code and the new code, and confirm only the intended trucks change.
- After pushing, wait for the next data round and check the published `fleet-status.json`.
