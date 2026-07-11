from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

WEIGHTS: dict[str, Any] = {
    "hail": {
        "gate_min_mm": 19.0,
        "one_inch_mm": 25.4,
        "max_mm": 63.0,
        "low_band_max_points": 15,
        "max_points": 40,
    },
    "timing": {
        "max_points": 10,
        "min_points": 4,
        "weekday_start_hour": 8,
        "weekday_end_hour": 18,
        "multifamily_share_threshold": 0.40,
        "retail_count_threshold": 3,
        "owner_share_threshold": 0.50,
    },
    "profile": {
        "multifamily_share_apts_heavy": 0.40,
        "apartments_apts_heavy": 5,
        "retail_retail_mix": 3,
        "mall_retail_mix": 1,
    },
}


def is_supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def get_supabase_headers() -> dict[str, str]:
    if not is_supabase_configured():
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def supabase_request(method: str, path: str, **kwargs):
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{path}"
    headers = get_supabase_headers()
    request_headers = {**headers, **kwargs.pop("headers", {})}
    response = requests.request(method, url, headers=request_headers, timeout=30, **kwargs)
    if not response.ok:
        raise RuntimeError(
            f"Supabase request failed {method} {url}: {response.status_code} {response.text}"
        )
    return response


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_region_timezone(region_id: int) -> str:
    try:
        response = supabase_request(
            "GET",
            f"regions?select=id,timezone&id=eq.{region_id}&limit=1",
        )
        rows = response.json()
        if not rows:
            return "America/Chicago"
        return str(rows[0].get("timezone") or "America/Chicago")
    except Exception:
        # Backward compatible path for environments where the timezone column is not migrated yet.
        return "America/Chicago"


def load_region_tract_scores(region_id: int) -> list[dict[str, Any]]:
    response = supabase_request(
        "GET",
        (
            "tract_scores?"
            "select=tract_geoid,centroid_lat,centroid_lon,min_lat,min_lon,max_lat,max_lon,"
            "vehicle_density_pts,claim_likelihood_pts,raw"
            f"&region_id=eq.{region_id}"
        ),
    )
    return response.json() or []


def _cell_inside_tract(cell_lat: float, cell_lon: float, tract: dict[str, Any]) -> bool:
    return (
        float(tract["min_lat"]) <= cell_lat <= float(tract["max_lat"])
        and float(tract["min_lon"]) <= cell_lon <= float(tract["max_lon"])
    )


def _max_hail_for_tract(cells: list[tuple[float, float, float]], tract: dict[str, Any]) -> float | None:
    max_hail = None
    for lat, lon, hail_mm in cells:
        if _cell_inside_tract(float(lat), float(lon), tract):
            if max_hail is None or float(hail_mm) > max_hail:
                max_hail = float(hail_mm)
    return max_hail


def compute_hail_pts(hail_mm: float) -> int:
    cfg = WEIGHTS["hail"]
    gate_min = float(cfg["gate_min_mm"])
    one_inch = float(cfg["one_inch_mm"])
    max_mm = float(cfg["max_mm"])
    low_band_max = float(cfg["low_band_max_points"])
    max_pts = float(cfg["max_points"])

    if hail_mm < gate_min:
        return 0
    if hail_mm >= max_mm:
        return int(round(max_pts))

    if hail_mm < one_inch:
        ratio = (hail_mm - gate_min) / (one_inch - gate_min)
        return int(round(max(0.0, min(1.0, ratio)) * low_band_max))

    ratio = (hail_mm - one_inch) / (max_mm - one_inch)
    points = low_band_max + max(0.0, min(1.0, ratio)) * (max_pts - low_band_max)
    return int(round(points))


def _read_raw_metrics(row: dict[str, Any]) -> tuple[float, int, float]:
    raw = row.get("raw") or {}
    acs = raw.get("acs") or {}
    osm = raw.get("osm") or {}

    multifamily_share = float(acs.get("multifamily_5plus_share") or 0.0)
    owner_share = float(acs.get("owner_occupied_share") or 0.0)

    retail = int(osm.get("retail") or 0)
    return multifamily_share, retail, owner_share


def compute_timing_pts(local_dt: datetime, row: dict[str, Any]) -> int:
    cfg = WEIGHTS["timing"]

    multifamily_share, retail, owner_share = _read_raw_metrics(row)

    is_weekday = local_dt.weekday() < 5
    is_daytime = int(cfg["weekday_start_hour"]) <= local_dt.hour < int(cfg["weekday_end_hour"])

    if is_weekday and is_daytime:
        if (
            multifamily_share >= float(cfg["multifamily_share_threshold"])
            or retail >= int(cfg["retail_count_threshold"])
        ):
            return int(cfg["max_points"])
        return int(cfg["min_points"])

    if owner_share >= float(cfg["owner_share_threshold"]):
        return int(cfg["max_points"])
    return int(cfg["min_points"])


def derive_profile_tag(row: dict[str, Any]) -> str:
    cfg = WEIGHTS["profile"]
    raw = row.get("raw") or {}
    acs = raw.get("acs") or {}
    osm = raw.get("osm") or {}

    multifamily_share = float(acs.get("multifamily_5plus_share") or 0.0)
    apartments = int(osm.get("apartments") or 0)
    retail = int(osm.get("retail") or 0)
    mall = int(osm.get("mall") or 0)

    if (
        multifamily_share >= float(cfg["multifamily_share_apts_heavy"])
        or apartments >= int(cfg["apartments_apts_heavy"])
    ):
        return "apts-heavy"
    if retail >= int(cfg["retail_retail_mix"]) or mall >= int(cfg["mall_retail_mix"]):
        return "retail-mix"
    return "residential"


def score_canvass_targets(
    swath_cells: list[tuple[float, float, float]],
    region_id: int,
    alert_timestamp: str | datetime,
) -> list[dict[str, Any]]:
    if not swath_cells:
        return []

    rows = load_region_tract_scores(region_id)
    if not rows:
        return []

    region_tz = load_region_timezone(region_id)
    alert_utc = parse_timestamp(alert_timestamp)
    try:
        local_dt = alert_utc.astimezone(ZoneInfo(region_tz))
    except Exception:
        local_dt = alert_utc.astimezone(ZoneInfo("America/Chicago"))

    results: list[dict[str, Any]] = []
    gate_min = float(WEIGHTS["hail"]["gate_min_mm"])

    for row in rows:
        max_hail_mm = _max_hail_for_tract(swath_cells, row)
        if max_hail_mm is None or max_hail_mm < gate_min:
            continue

        hail_pts = compute_hail_pts(max_hail_mm)
        timing_pts = compute_timing_pts(local_dt, row)
        vehicle_pts = int(row.get("vehicle_density_pts") or 0)
        claim_pts = int(row.get("claim_likelihood_pts") or 0)

        score = int(round(hail_pts + timing_pts + vehicle_pts + claim_pts))
        hail_in = max_hail_mm / 25.4

        results.append(
            {
                "geoid": str(row.get("tract_geoid")),
                "score": score,
                "hail_mm": float(max_hail_mm),
                "hail_in": float(hail_in),
                "hail_pts": hail_pts,
                "timing_pts": timing_pts,
                "vehicle_density_pts": vehicle_pts,
                "claim_likelihood_pts": claim_pts,
                "profile_tag": derive_profile_tag(row),
                "centroid_lat": float(row.get("centroid_lat") or 0.0),
                "centroid_lon": float(row.get("centroid_lon") or 0.0),
            }
        )

    results.sort(key=lambda x: (x["score"], x["hail_mm"], x["vehicle_density_pts"]), reverse=True)

    for idx, item in enumerate(results, start=1):
        item["rank"] = idx

    return results
