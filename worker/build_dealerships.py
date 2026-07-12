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
SUPABASE_PAGE_SIZE = 1000

MAJOR_BRAND_TOKENS = [
    "chevrolet",
    "chevy",
    "ford",
    "toyota",
    "honda",
    "nissan",
    "kia",
    "hyundai",
    "gmc",
    "buick",
    "ram",
    "dodge",
    "jeep",
    "chrysler",
    "subaru",
    "mazda",
    "vw",
    "volkswagen",
    "bmw",
    "mercedes",
    "lexus",
    "audi",
    "carmax",
    "autonation",
]


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


def paged_select(path_prefix: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        sep = "&" if "?" in path_prefix else "?"
        path = f"{path_prefix}{sep}limit={SUPABASE_PAGE_SIZE}&offset={offset}"
        response = supabase_request("GET", path)
        page = response.json() or []
        rows.extend(page)

        if len(page) < SUPABASE_PAGE_SIZE:
            break
        offset += SUPABASE_PAGE_SIZE

    return rows


def _is_missing_tier_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "Could not find the 'tier' column of 'dealerships'" in message
        or "column dealerships.tier does not exist" in message
    )


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


def classify_tier(name: str, brand: str | None) -> str:
    name_lower = name.lower()
    brand_text = (brand or "").strip()

    if brand_text:
        return "franchise"
    if any(token in name_lower for token in MAJOR_BRAND_TOKENS):
        return "franchise"
    if "auction" in name_lower:
        return "auction"
    return "independent"


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
                "tier": classify_tier(name, brand),
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

    try:
        supabase_request(
            "POST",
            "dealerships?on_conflict=osm_id",
            json=rows,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
    except Exception as exc:
        if not _is_missing_tier_error(exc):
            raise
        rows_without_tier = []
        for row in rows:
            copy_row = dict(row)
            copy_row.pop("tier", None)
            rows_without_tier.append(copy_row)
        supabase_request(
            "POST",
            "dealerships?on_conflict=osm_id",
            json=rows_without_tier,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )


def reclassify_existing_dealerships() -> int:
    rows = paged_select("dealerships?select=region_id,name,brand,lat,lon,osm_id,active")
    if not rows:
        return 0

    updated_rows = []
    for row in rows:
        name = str(row.get("name") or "")
        brand_val = row.get("brand")
        brand = str(brand_val).strip() if brand_val is not None and str(brand_val).strip() else None
        updated_rows.append(
            {
                "region_id": int(row.get("region_id") or 0),
                "name": name,
                "brand": brand,
                "tier": classify_tier(name, brand),
                "lat": float(row.get("lat") or 0.0),
                "lon": float(row.get("lon") or 0.0),
                "osm_id": str(row.get("osm_id") or ""),
                "active": bool(row.get("active", True)),
            }
        )

    try:
        upsert_dealerships(updated_rows)
    except Exception:
        # If tier column is not available yet, the builder still emits summary via on-the-fly classification.
        pass
    return len(updated_rows)


def print_tier_summary_all_regions() -> None:
    regions = paged_select("regions?select=id,name")
    region_names = {int(r["id"]): str(r.get("name") or f"Region {r['id']}") for r in regions if r.get("id") is not None}

    try:
        dealers = paged_select("dealerships?select=region_id,name,brand,tier,active")
    except Exception as exc:
        if not _is_missing_tier_error(exc):
            raise
        dealers = paged_select("dealerships?select=region_id,name,brand,active")

    counts: dict[int, dict[str, int]] = {}
    for dealer in dealers:
        if dealer.get("active") is False:
            continue
        region_id = int(dealer.get("region_id") or 0)
        if region_id not in counts:
            counts[region_id] = {
                "total": 0,
                "franchise": 0,
                "auction": 0,
                "independent": 0,
                "unclassified": 0,
            }

        counts[region_id]["total"] += 1

        raw_tier = dealer.get("tier")
        tier = str(raw_tier).strip().lower() if raw_tier is not None else ""
        if tier not in ("franchise", "auction", "independent"):
            tier = "unclassified"
        counts[region_id][tier] += 1

    print("Tier summary by region")
    print("REGION  TOTAL  FRANCHISE  AUCTION  INDEPENDENT  UNCLASSIFIED  CHECK")

    all_region_ids = sorted(set(region_names.keys()) | set(counts.keys()))
    for region_id in all_region_ids:
        name = region_names.get(region_id, f"Region {region_id}")
        row = counts.get(
            region_id,
            {"total": 0, "franchise": 0, "auction": 0, "independent": 0, "unclassified": 0},
        )
        check_total = row["franchise"] + row["auction"] + row["independent"] + row["unclassified"]
        check_text = "OK" if check_total == row["total"] else f"MISMATCH({check_total})"
        print(
            f"{name}  {row['total']:>5}  {row['franchise']:>9}  {row['auction']:>7}  "
            f"{row['independent']:>11}  {row['unclassified']:>12}  {check_text}"
        )


def reclassify_all_regions_only() -> int:
    reclassified = reclassify_existing_dealerships()
    print(f"Reclassified dealerships: {reclassified}")
    print_tier_summary_all_regions()
    return 0


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
    reclassified = reclassify_existing_dealerships()

    rows.sort(key=lambda x: (x["name"], x.get("brand") or ""))
    print(f"Upserted dealerships: {len(rows)}")
    print(f"Reclassified dealerships: {reclassified}")
    for row in rows:
        brand = row.get("brand") or "n/a"
        print(
            f"- {row['name']} | brand={brand} | tier={row['tier']} | "
            f"osm_id={row['osm_id']} | {row['lat']:.5f},{row['lon']:.5f}"
        )

    print_tier_summary_all_regions()

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dealership inventory for a region")
    parser.add_argument("region_name", nargs="?", help="Region name or slug from regions table (e.g., Springfield)")
    parser.add_argument(
        "--reclassify-all",
        action="store_true",
        help="Reclassify all existing dealership rows and print all-region tier summary",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.reclassify_all:
            return reclassify_all_regions_only()
        if not args.region_name:
            raise RuntimeError("region_name is required unless --reclassify-all is used")
        return build_for_region(args.region_name)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
