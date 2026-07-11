from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")

TIGER_TRACTS_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/0/query"
ACS_URL = "https://api.census.gov/data/2023/acs/acs5"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_FALLBACK_URL = "https://overpass.kumi.systems/api/interpreter"

WEIGHTS: dict[str, Any] = {
    "vehicle_density": {
        "max_points": 30,
        "region_scale": "min_max",
        "multifamily_weight": 0.55,
        "osm_weight": 0.45,
        "osm_count_cap": 40.0,
        "osm_mix": {
            "apartments": 0.50,
            "mall": 0.20,
            "retail": 0.30,
        },
    },
    "claim_likelihood": {
        "max_points": 20,
        "vehicle_gate_min_pts": 5,
        "income_band": {
            "min_score": 0.00,
            "low_floor": 25000.0,
            "peak_start": 45000.0,
            "peak_end": 90000.0,
            "high_cap": 150000.0,
        },
    },
}


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


def parse_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if text in ("", "null", "None"):
            return None
        num = float(text)
        # ACS missing sentinels
        if num <= -666666:
            return None
        return num
    except Exception:
        return None


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


def _tract_bbox_from_geometry(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    rings = geometry.get("rings") or []
    if not rings:
        raise RuntimeError("TRACT geometry missing rings")

    xs = []
    ys = []
    for ring in rings:
        for point in ring:
            xs.append(float(point[0]))
            ys.append(float(point[1]))

    return min(ys), min(xs), max(ys), max(xs)


def fetch_tracts_for_bbox(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list[dict[str, Any]]:
    params = {
        "f": "json",
        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "true",
        "outFields": "GEOID,STATE,COUNTY,TRACT,INTPTLAT,INTPTLON",
        "outSR": "4326",
    }
    response = requests.get(TIGER_TRACTS_URL, params=params, timeout=90)
    response.raise_for_status()
    payload = response.json()

    features = payload.get("features") or []
    if not features:
        raise RuntimeError("No census tracts found for region bbox")

    merged: dict[str, dict[str, Any]] = {}

    for feature in features:
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}
        geoid = str(attrs.get("GEOID") or "").strip()
        if not geoid:
            continue

        tract_min_lat, tract_min_lon, tract_max_lat, tract_max_lon = _tract_bbox_from_geometry(geom)

        centroid_lat = parse_float(attrs.get("INTPTLAT"))
        centroid_lon = parse_float(attrs.get("INTPTLON"))
        if centroid_lat is None or centroid_lon is None:
            centroid_lat = (tract_min_lat + tract_max_lat) / 2.0
            centroid_lon = (tract_min_lon + tract_max_lon) / 2.0

        if geoid in merged:
            existing = merged[geoid]
            existing["min_lat"] = min(existing["min_lat"], tract_min_lat)
            existing["min_lon"] = min(existing["min_lon"], tract_min_lon)
            existing["max_lat"] = max(existing["max_lat"], tract_max_lat)
            existing["max_lon"] = max(existing["max_lon"], tract_max_lon)
            existing["centroid_lat"] = (existing["min_lat"] + existing["max_lat"]) / 2.0
            existing["centroid_lon"] = (existing["min_lon"] + existing["max_lon"]) / 2.0
            continue

        merged[geoid] = {
            "tract_geoid": geoid,
            "state": geoid[:2],
            "county": geoid[2:5],
            "tract": geoid[5:],
            "centroid_lat": float(centroid_lat),
            "centroid_lon": float(centroid_lon),
            "min_lat": float(tract_min_lat),
            "min_lon": float(tract_min_lon),
            "max_lat": float(tract_max_lat),
            "max_lon": float(tract_max_lon),
        }

    return list(merged.values())


def fetch_acs_for_tracts(tracts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for tract in tracts:
        grouped[(tract["state"], tract["county"])].append(tract["tract"])

    vars_list = [
        "B19013_001E",  # median household income
        "B25003_001E",  # total occupied housing units
        "B25003_002E",  # owner occupied
        "B25024_001E",  # total housing units
        "B25024_006E",  # 5 to 9 units
        "B25024_007E",  # 10 to 19 units
        "B25024_008E",  # 20 to 49 units
        "B25024_009E",  # 50 or more units
    ]
    get_value = ",".join(vars_list)

    results: dict[str, dict[str, Any]] = {}

    for (state, county), _tract_codes in grouped.items():
        params = {
            "get": get_value,
            "for": "tract:*",
            "in": f"state:{state} county:{county}",
        }
        if CENSUS_API_KEY:
            params["key"] = CENSUS_API_KEY

        response = requests.get(ACS_URL, params=params, timeout=90)
        response.raise_for_status()
        try:
            rows = response.json()
        except Exception as exc:
            snippet = response.text[:400].strip().replace("\n", " ")
            if "Missing Key" in snippet or "valid key" in snippet.lower():
                raise RuntimeError(
                    "Census ACS API requires CENSUS_API_KEY in this environment. "
                    "Set CENSUS_API_KEY in .env and rerun."
                ) from exc
            raise RuntimeError(f"Unexpected ACS response (non-JSON): {snippet}") from exc

        if not isinstance(rows, list) or not rows:
            raise RuntimeError(f"Unexpected ACS response payload: {rows}")
        header = rows[0]

        for row in rows[1:]:
            item = dict(zip(header, row))
            geoid = f"{item['state']}{item['county']}{item['tract']}"

            total_occ = parse_float(item.get("B25003_001E"))
            owner_occ = parse_float(item.get("B25003_002E"))
            total_units = parse_float(item.get("B25024_001E"))
            five_plus = sum(
                parse_float(item.get(var)) or 0.0
                for var in ("B25024_006E", "B25024_007E", "B25024_008E", "B25024_009E")
            )

            owner_share = (owner_occ / total_occ) if total_occ and total_occ > 0 else 0.0
            multifamily_share = (five_plus / total_units) if total_units and total_units > 0 else 0.0

            results[geoid] = {
                "median_income": parse_float(item.get("B19013_001E")),
                "owner_occupied_share": max(0.0, min(1.0, owner_share)),
                "multifamily_5plus_share": max(0.0, min(1.0, multifamily_share)),
                "owner_occupied_units": owner_occ,
                "occupied_units": total_occ,
                "five_plus_units": five_plus,
                "total_units": total_units,
            }

    return results


def fetch_overpass_features(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list[dict[str, Any]]:
    query = f"""
[out:json][timeout:60];
(
  nwr[\"building\"=\"apartments\"]({min_lat},{min_lon},{max_lat},{max_lon});
  nwr[\"shop\"=\"mall\"]({min_lat},{min_lon},{max_lat},{max_lon});
  nwr[\"landuse\"=\"retail\"]({min_lat},{min_lon},{max_lat},{max_lon});
  nwr[\"amenity\"=\"school\"]({min_lat},{min_lon},{max_lat},{max_lon});
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
                # Overpass expects x-www-form-urlencoded with QL in the data form field.
                response = requests.post(
                    endpoint,
                    data={"data": query},
                    headers=headers,
                    timeout=180,
                )
                print(f"Overpass response status: {response.status_code}")
                response.raise_for_status()
                try:
                    data = response.json()
                except Exception as exc:
                    snippet = response.text[:500].strip().replace("\n", " ")
                    raise RuntimeError(f"Overpass returned non-JSON response: {snippet}") from exc
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


def raw_osm_category_counts(elements: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"apartments": 0, "mall": 0, "retail": 0, "school": 0}
    for elem in elements:
        tags = elem.get("tags") or {}
        feature_type = _classify_feature(tags)
        if feature_type:
            counts[feature_type] += 1
    return counts


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


def _classify_feature(tags: dict[str, Any]) -> str | None:
    if tags.get("building") == "apartments":
        return "apartments"
    if tags.get("shop") == "mall":
        return "mall"
    if tags.get("landuse") == "retail":
        return "retail"
    if tags.get("amenity") == "school":
        return "school"
    return None


def assign_osm_counts_to_tracts(tracts: list[dict[str, Any]], elements: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {
        tract["tract_geoid"]: {"apartments": 0, "mall": 0, "retail": 0, "school": 0}
        for tract in tracts
    }

    for elem in elements:
        tags = elem.get("tags") or {}
        feature_type = _classify_feature(tags)
        if not feature_type:
            continue

        center = _feature_center(elem)
        if not center:
            continue
        lat, lon = center

        for tract in tracts:
            if (
                tract["min_lat"] <= lat <= tract["max_lat"]
                and tract["min_lon"] <= lon <= tract["max_lon"]
            ):
                counts[tract["tract_geoid"]][feature_type] += 1
                break

    return counts


def income_band_score(income: float | None) -> float:
    cfg = WEIGHTS["claim_likelihood"]["income_band"]
    if income is None:
        return cfg["min_score"]

    low_floor = cfg["low_floor"]
    peak_start = cfg["peak_start"]
    peak_end = cfg["peak_end"]
    high_cap = cfg["high_cap"]
    min_score = cfg["min_score"]

    if income <= low_floor:
        return min_score
    if low_floor < income < peak_start:
        ratio = (income - low_floor) / (peak_start - low_floor)
        return min_score + ratio * (1.0 - min_score)
    if peak_start <= income <= peak_end:
        return 1.0
    if peak_end < income < high_cap:
        ratio = (high_cap - income) / (high_cap - peak_end)
        return min_score + max(0.0, ratio) * (1.0 - min_score)
    return min_score


def compute_vehicle_base_score(acs: dict[str, Any], osm: dict[str, int]) -> float:
    vcfg = WEIGHTS["vehicle_density"]
    multifamily_share = float(acs.get("multifamily_5plus_share") or 0.0)

    osm_mix = vcfg["osm_mix"]
    osm_weighted_count = (
        osm_mix["apartments"] * osm.get("apartments", 0)
        + osm_mix["mall"] * osm.get("mall", 0)
        + osm_mix["retail"] * osm.get("retail", 0)
    )
    osm_norm = min(1.0, osm_weighted_count / float(vcfg["osm_count_cap"]))

    vehicle_score = (
        vcfg["multifamily_weight"] * multifamily_share
        + vcfg["osm_weight"] * osm_norm
    )

    return max(0.0, min(1.0, vehicle_score))


def vehicle_points_from_region_scale(vehicle_base_score: float, region_min: float, region_max: float) -> int:
    vcfg = WEIGHTS["vehicle_density"]

    if region_max > region_min:
        normalized = (vehicle_base_score - region_min) / (region_max - region_min)
    else:
        # Degenerate case: no spread in region. Keep all tracts at zero unless non-zero exposure exists.
        normalized = 1.0 if vehicle_base_score > 0 else 0.0

    normalized = max(0.0, min(1.0, normalized))
    return int(round(normalized * vcfg["max_points"]))


def compute_claim_points(acs: dict[str, Any], vehicle_pts: int) -> int:
    ccfg = WEIGHTS["claim_likelihood"]

    if vehicle_pts < int(ccfg["vehicle_gate_min_pts"]):
        return 0

    income_score = income_band_score(acs.get("median_income"))
    owner_share = float(acs.get("owner_occupied_share") or 0.0)
    claim_score = income_score * max(0.0, min(1.0, owner_share))
    claim_pts = int(round(max(0.0, min(1.0, claim_score)) * ccfg["max_points"]))
    return claim_pts


def upsert_tract_scores(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    supabase_request(
        "POST",
        "tract_scores?on_conflict=region_id,tract_geoid",
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

    tracts = fetch_tracts_for_bbox(min_lat, min_lon, max_lat, max_lon)
    print(f"Fetched tracts: {len(tracts)}")

    acs_map = fetch_acs_for_tracts(tracts)
    print(f"Fetched ACS records: {len(acs_map)}")

    osm_elements = fetch_overpass_features(min_lat, min_lon, max_lat, max_lon)
    raw_counts = raw_osm_category_counts(osm_elements)
    print(
        "Raw OSM counts before tract bucketing: "
        f"apartments={raw_counts['apartments']}, mall={raw_counts['mall']}, "
        f"retail={raw_counts['retail']}, school={raw_counts['school']}"
    )
    osm_counts = assign_osm_counts_to_tracts(tracts, osm_elements)
    print(f"Fetched OSM elements: {len(osm_elements)}")

    computed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    upsert_rows = []
    scored_rows = []
    prepared_rows = []

    for tract in tracts:
        geoid = tract["tract_geoid"]
        acs = acs_map.get(
            geoid,
            {
                "median_income": None,
                "owner_occupied_share": 0.0,
                "multifamily_5plus_share": 0.0,
                "owner_occupied_units": None,
                "occupied_units": None,
                "five_plus_units": None,
                "total_units": None,
            },
        )
        osm = osm_counts.get(geoid, {"apartments": 0, "mall": 0, "retail": 0, "school": 0})

        vehicle_base_score = compute_vehicle_base_score(acs, osm)

        prepared_rows.append(
            {
                "tract": tract,
                "acs": acs,
                "osm": osm,
                "vehicle_base_score": vehicle_base_score,
            }
        )

    region_vehicle_scores = [item["vehicle_base_score"] for item in prepared_rows]
    region_min_vehicle_score = min(region_vehicle_scores) if region_vehicle_scores else 0.0
    region_max_vehicle_score = max(region_vehicle_scores) if region_vehicle_scores else 0.0
    print(
        "Vehicle density regional scaling: "
        f"mode=min_max, min_raw={region_min_vehicle_score:.4f}, max_raw={region_max_vehicle_score:.4f}"
    )

    for item in prepared_rows:
        tract = item["tract"]
        acs = item["acs"]
        osm = item["osm"]
        geoid = tract["tract_geoid"]

        vehicle_pts = vehicle_points_from_region_scale(
            float(item["vehicle_base_score"]),
            region_min_vehicle_score,
            region_max_vehicle_score,
        )
        claim_pts = compute_claim_points(acs, vehicle_pts)
        total_pts = vehicle_pts + claim_pts

        raw_payload = {
            "acs": acs,
            "osm": osm,
            "vehicle_base_score": item["vehicle_base_score"],
            "region_vehicle_min": region_min_vehicle_score,
            "region_vehicle_max": region_max_vehicle_score,
            "weights": WEIGHTS,
            "total_static_pts": total_pts,
        }

        row = {
            "region_id": region_id,
            "tract_geoid": geoid,
            "centroid_lat": tract["centroid_lat"],
            "centroid_lon": tract["centroid_lon"],
            "min_lat": tract["min_lat"],
            "min_lon": tract["min_lon"],
            "max_lat": tract["max_lat"],
            "max_lon": tract["max_lon"],
            "vehicle_density_pts": vehicle_pts,
            "claim_likelihood_pts": claim_pts,
            "raw": raw_payload,
            "computed_at": computed_at,
        }
        upsert_rows.append(row)

        scored_rows.append(
            {
                "tract_geoid": geoid,
                "vehicle_density_pts": vehicle_pts,
                "claim_likelihood_pts": claim_pts,
                "total_pts": total_pts,
                "median_income": acs.get("median_income"),
                "owner_occupied_share": acs.get("owner_occupied_share"),
                "multifamily_5plus_share": acs.get("multifamily_5plus_share"),
                "apartments": osm.get("apartments", 0),
                "mall": osm.get("mall", 0),
                "retail": osm.get("retail", 0),
                "school": osm.get("school", 0),
            }
        )

    upsert_tract_scores(upsert_rows)

    scored_rows.sort(key=lambda x: (x["total_pts"], x["vehicle_density_pts"], x["claim_likelihood_pts"]), reverse=True)

    print(f"Upserted tract_scores rows: {len(upsert_rows)}")
    print("Top 10 tracts by static score")
    print("GEOID         TOTAL  VEH  CLM  INCOME   OWNER%  MULTI5+%  APTS  MALL  RETAIL  SCHOOL")
    for item in scored_rows[:10]:
        income = item["median_income"]
        owner_pct = 100.0 * float(item["owner_occupied_share"] or 0.0)
        multi_pct = 100.0 * float(item["multifamily_5plus_share"] or 0.0)
        income_text = f"{income:.0f}" if income is not None else "n/a"
        print(
            f"{item['tract_geoid']:<12} {item['total_pts']:>5} {item['vehicle_density_pts']:>4} {item['claim_likelihood_pts']:>4} "
            f"{income_text:>8} {owner_pct:>7.1f} {multi_pct:>9.1f} {item['apartments']:>5} {item['mall']:>5} {item['retail']:>7} {item['school']:>7}"
        )

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static canvass tract scores for a region")
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
