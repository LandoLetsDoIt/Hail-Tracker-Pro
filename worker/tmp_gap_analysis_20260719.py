import gzip
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests
import xarray as xr
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE = (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
if not SUPABASE or not KEY:
    raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}


def parse_utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fetch_regions() -> list[dict]:
    url = (
        f"{SUPABASE}/rest/v1/regions"
        "?select=id,name,min_lat,min_lon,max_lat,max_lon,threshold_mm,dealer_threshold_mm"
        "&order=id.asc"
    )
    resp = requests.get(url, headers=HEADERS, timeout=45)
    resp.raise_for_status()
    return resp.json()


def fetch_hail_engine_runs() -> list[dict]:
    owner = "LandoLetsDoIt"
    repo = "Hail-Tracker-Pro"
    out = []
    for page in range(1, 20):
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/hail_engine.yml/runs"
            f"?per_page=100&page={page}"
        )
        resp = requests.get(url, timeout=45)
        resp.raise_for_status()
        batch = resp.json().get("workflow_runs", [])
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


def region_maxes_from_gz(gz_path: Path, regions: list[dict]) -> dict[int, float]:
    raw_path = Path(str(gz_path)[:-3])
    ds = None
    with gzip.open(gz_path, "rb") as f_in, raw_path.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    try:
        ds = xr.open_dataset(raw_path, engine="cfgrib")
        var_name = next(iter(ds.data_vars))
        values = np.asarray(ds[var_name].values, dtype=float)
        lats = np.asarray(ds["latitude"].values, dtype=float)
        lons = np.asarray(ds["longitude"].values, dtype=float)

        if lats.ndim == 1 and lons.ndim == 1 and values.ndim == 2:
            lats, lons = np.meshgrid(lats, lons, indexing="ij")

        lons = np.where(lons > 180.0, lons - 360.0, lons)
        values = np.where(np.isnan(values), np.nan, values)
        values = np.where(values < 0.0, 0.0, values)

        out: dict[int, float] = {}
        for region in regions:
            rid = int(region["id"])
            min_lat = float(region["min_lat"])
            min_lon = float(region["min_lon"])
            max_lat = float(region["max_lat"])
            max_lon = float(region["max_lon"])

            mask = (
                (lats >= min_lat)
                & (lats <= max_lat)
                & (lons >= min_lon)
                & (lons <= max_lon)
            )
            if np.any(mask):
                mm = float(np.nanmax(values[mask]))
            else:
                mm = 0.0
            if np.isnan(mm) or mm < 0.0:
                mm = 0.0
            out[rid] = mm
        return out
    finally:
        if ds is not None:
            try:
                ds.close()
            except Exception:
                pass
        raw_path.unlink(missing_ok=True)


def main() -> int:
    regions = fetch_regions()
    all_runs = fetch_hail_engine_runs()

    target_runs = [r for r in all_runs if str(r.get("created_at", "")).startswith("2026-07-19")]
    target_runs.sort(key=lambda r: parse_utc(r["created_at"]))

    successes = [r for r in target_runs if r.get("conclusion") == "success"]
    failures = [r for r in target_runs if r.get("conclusion") != "success"]

    email_times = [
        parse_utc("2026-07-19T17:29:00Z"),
        parse_utc("2026-07-19T18:55:00Z"),
    ]

    windows = []
    for et in email_times:
        prevs = [s for s in successes if parse_utc(s["updated_at"]) <= et]
        nexts = [s for s in successes if parse_utc(s.get("run_started_at") or s["created_at"]) >= et]
        prev_run = prevs[-1] if prevs else None
        next_run = nexts[0] if nexts else None
        if prev_run and next_run:
            gap_start = parse_utc(prev_run["updated_at"])
            gap_end = parse_utc(next_run.get("run_started_at") or next_run["created_at"])
            windows.append(
                {
                    "email_time_utc": et,
                    "prev_success": prev_run,
                    "next_success": next_run,
                    "gap_start_utc": gap_start,
                    "gap_end_utc": gap_end,
                    "gap_minutes": (gap_end - gap_start).total_seconds() / 60.0,
                }
            )

    crossings = []
    base = "https://noaa-mrms-pds.s3.amazonaws.com/CONUS/MESH_Max_60min_00.50/20260719/"

    for window in windows:
        t = window["gap_start_utc"].replace(second=0, microsecond=0)
        if t.minute % 2 == 1:
            t += timedelta(minutes=1)

        while t <= window["gap_end_utc"]:
            ts = t.strftime("%H%M00")
            filename = f"MRMS_MESH_Max_60min_00.50_20260719-{ts}.grib2.gz"
            url = base + filename
            local = Path(tempfile.gettempdir()) / filename

            resp = requests.get(url, timeout=120)
            if resp.status_code == 200:
                local.write_bytes(resp.content)
                region_mm = region_maxes_from_gz(local, regions)
                local.unlink(missing_ok=True)

                for region in regions:
                    rid = int(region["id"])
                    mm = region_mm[rid]
                    retail = float(region.get("threshold_mm") or 25.4)
                    dealer = float(region.get("dealer_threshold_mm") or 12.7)
                    if mm >= retail or mm >= dealer:
                        crossings.append(
                            {
                                "email_time_utc": window["email_time_utc"].isoformat().replace("+00:00", "Z"),
                                "timestamp_utc": t.isoformat().replace("+00:00", "Z"),
                                "region_id": rid,
                                "region_name": region.get("name"),
                                "hail_mm": round(mm, 2),
                                "hail_in": round(mm / 25.4, 2),
                                "retail_cross": mm >= retail,
                                "dealer_cross": mm >= dealer,
                            }
                        )
            t += timedelta(minutes=2)

    out = {
        "target_run_count": len(target_runs),
        "target_failures": [
            {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "run_started_at": r.get("run_started_at"),
                "updated_at": r.get("updated_at"),
                "status": r.get("status"),
                "conclusion": r.get("conclusion"),
                "html_url": r.get("html_url"),
            }
            for r in failures
        ],
        "windows": [
            {
                "email_time_utc": w["email_time_utc"].isoformat().replace("+00:00", "Z"),
                "prev_success_run_id": w["prev_success"]["id"],
                "prev_success_completed_at_utc": w["prev_success"]["updated_at"],
                "next_success_run_id": w["next_success"]["id"],
                "next_success_started_at_utc": w["next_success"].get("run_started_at") or w["next_success"]["created_at"],
                "gap_start_utc": w["gap_start_utc"].isoformat().replace("+00:00", "Z"),
                "gap_end_utc": w["gap_end_utc"].isoformat().replace("+00:00", "Z"),
                "gap_minutes": round(w["gap_minutes"], 1),
            }
            for w in windows
        ],
        "crossings_count": len(crossings),
        "crossings": crossings[:200],
    }

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
