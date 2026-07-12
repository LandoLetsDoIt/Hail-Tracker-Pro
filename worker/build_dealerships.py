from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_FALLBACK_URL = "https://overpass.kumi.systems/api/interpreter"


def get_supabase_headers() -> dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
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
    response = requests.request(method, url, headers=request_headers, timeout=60, **kwargs)
    if not response.ok:
        raise RuntimeError(f"Supabase request failed {method} {url}: {response.status_code} {response.text}")
    return response


def get_region_by_name(region_name: str) -> dict[str, Any]:
    response = supabase_request("GET", "regions?select=*&is_active=eq.true")
    regions = response.json()
    if not regions:
        raise RuntimeError("No active regions found")

    query = region_name.strip().lower()

    for region in regions:
        name = str(region.get("name") or "").strip().lower()
        slug = str(region.get("slug") or "").strip().lower()
        if name == query or slug == query:
            return region

    for region in regions:
        name = str(region.get("name") or "").strip().lower()
        slug = str(region.get("slug") or "").strip().lower()
        if query in name or query in slug:
            return region

    available = ", ".join(str(r.get("name") or r.get("slug") or "unknown") for r in regions)
    raise RuntimeError(f"Region '{region_name}' not found. Available: {available}")


def fetch_overpass_dealerships(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list[dict[str, Any]]:
    query = f"""
[out:json][timeout:60];
(
  nwr[\"shop\"=\"car\"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out center;
""".strip()

    print("--- OVERPASS QUERY ---")
    print(query)

    headers = {
        "User-Agent": "HailTrackerPro/1.0",
        "Accept": "application/json",
    }
    endpoints = [OVERPASS_URL, OVERPASS_FALLBACK_URL]
    last_error = None

    for endpoint in endpoints:
        print(f"Overpass endpoint: {endpoint}")
        for attempt in (1, 2):
            try:
                response = requests.post(
                    endpoint,
                    data={"data": query},
                    headers=headers,
                    timeout=180,
                )
                print(f"Overpass response status: {response.status_code}")
                response.raise_for_status()
                data = response.json()
                return data.get("elements") or []
            except requests.Timeout as exc:
                last_error = exc
                if attempt == 1:
                    print("Overpass timeout; retrying once...")
                    continue
                print("Overpass timed out after one retry")
                break
            except Exception as exc:
                last_error = exc
                print(f"Overpass request failed on {endpoint}: {exc}")
                break

    raise RuntimeError(f"Overpass request failed across instances: {last_error}")


def _feature_center(element: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    if "center" in element:
        c = element["center"]
        return float(c["lat"]), float(c["lon"])
    if "bounds" in element:
        b = element["bounds"]
        return (float(b["minlat"]) + float(b["maxlat"])) / 2.0, (float(b["minlon"]) + float(b["maxlon"])) / 2.0
    return None


def build_rows(region_id: int, elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for elem in elements:
        center = _feature_center(elem)
        if not center:
            continue

        tags = elem.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        if not name:
            name = f"Unnamed dealership {elem.get('id')}"

        brand_val = tags.get("brand")
        brand = str(brand_val).strip() if brand_val is not None and str(brand_val).strip() else None

        elem_type = str(elem.get("type") or "item")
        elem_id = str(elem.get("id") or "")
        osm_id = f"{elem_type}/{elem_id}"

        lat, lon = center
        rows.append(
            {
                "region_id": region_id,
                "name": name,
                "brand": brand,
                "lat": float(lat),
                "lon": float(lon),
                "osm_id": osm_id,
                "active": True,
            }
        )

    return rows


def upsert_dealerships(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    supabase_request(
        "POST",
        "dealerships?on_conflict=osm_id",
        json=rows,
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def build_for_region(region_name: str) -> int:
    region = get_region_by_name(region_name)

    region_id = int(region["id"])
    min_lat = float(region["min_lat"])
    min_lon = float(region["min_lon"])
    max_lat = float(region["max_lat"])
    max_lon = float(region["max_lon"])

    print(f"Region: {region.get('name')} (id={region_id})")
    print(f"BBox: lat {min_lat}..{max_lat}, lon {min_lon}..{max_lon}")

    elements = fetch_overpass_dealerships(min_lat, min_lon, max_lat, max_lon)
    rows = build_rows(region_id, elements)
    upsert_dealerships(rows)

    rows.sort(key=lambda x: (x["name"], x.get("brand") or ""))
    print(f"Upserted dealerships: {len(rows)}")
    for row in rows:
        brand = row.get("brand") or "n/a"
        print(f"- {row['name']} | brand={brand} | osm_id={row['osm_id']} | {row['lat']:.5f},{row['lon']:.5f}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dealership inventory for a region")
    parser.add_argument("region_name", help="Region name or slug from regions table (e.g., Springfield)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return build_for_region(args.region_name)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
