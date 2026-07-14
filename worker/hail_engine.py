import argparse
import base64
import gzip
import logging
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import numpy as np
import pygrib
import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, Timeout
from dotenv import load_dotenv

try:
    from kml_builder import build_hail_swath_kml
except ModuleNotFoundError:
    from worker.kml_builder import build_hail_swath_kml

try:
    from canvass_score import score_canvass_targets
except ModuleNotFoundError:
    from worker.canvass_score import score_canvass_targets

# Load environment variables from .env at project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MRMS_MESH_SOURCES = [
    {
        "name": "mrms-host",
        "base_url": "https://mrms.ncep.noaa.gov/data/2D/merged/mesh/",
        "supports_listing": False,
    },
    {
        "name": "thredds",
        "base_url": "https://thredds.ncep.noaa.gov/thredds/fileServer/meso_analyses/merged/mesh/",
        "supports_listing": True,
    },
]
MRMS_NOAA_LATEST_URL = "https://mrms.ncep.noaa.gov/data/2D/MESH_Max_60min/MRMS_MESH_Max_60min.latest.grib2.gz"
MRMS_S3_BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com/"
MRMS_S3_MESH_PREFIX = "CONUS/MESH_Max_60min_00.50/"
SPRINGFIELD_LAT = 37.21
SPRINGFIELD_LON = -93.29
MM_PER_INCH = 25.4
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

logger = logging.getLogger("hail_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_TABLE_REGIONS = "regions"
SUPABASE_TABLE_ALERTS = "hail_alerts"
SUPABASE_TABLE_DEALERSHIPS = "dealerships"
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")
RESEND_FROM_EMAIL = "onboarding@resend.dev"
ALERT_RESEND_WINDOW_HOURS = 6

DEFAULT_WATCHED_REGIONS = [
    {
        "id": None,
        "slug": "springfield-mo",
        "name": "Springfield, MO",
        "min_lat": 37.10,
        "min_lon": -93.45,
        "max_lat": 37.32,
        "max_lon": -93.10,
        "threshold_mm": 25.4,
        "dealer_threshold_mm": 12.7,
    }
]


def is_supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def is_email_configured() -> bool:
    return bool(RESEND_API_KEY and ALERT_EMAIL_TO)


def get_supabase_headers() -> dict[str, str]:
    if not is_supabase_configured():
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to use Supabase integration"
        )

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


def resolve_latest_mesh_url(base_url: str, supports_listing: bool) -> str:
    """Resolve the latest MESH file from a source URL.

    If the source supports directory listing, scrape the HTML for GRIB2 filenames.
    Otherwise try direct candidate file names using the standard MRMS naming pattern.
    """
    logger.info("Resolving latest MESH file from %s", base_url)
    if supports_listing:
        response = requests.get(base_url, timeout=30)
        response.raise_for_status()
        html = response.text

        href_pattern = re.compile(r'href=["\']([^"\']+\.(?:grib2|grib2.gz))["\']', re.IGNORECASE)
        candidate_pattern = re.compile(r'([A-Za-z0-9_\-]+\.(?:grib2|grib2.gz))', re.IGNORECASE)

        candidates = set()
        for match in href_pattern.findall(html):
            candidates.add(Path(match).name)
        if not candidates:
            for match in candidate_pattern.findall(html):
                candidates.add(Path(match).name)

        mesh_candidates = [
            filename
            for filename in candidates
            if re.search(r'mesh|mesh_.*60|min|60min|01h', filename, re.IGNORECASE)
        ]
        if not mesh_candidates:
            raise RuntimeError("Could not discover any MESH GRIB2 files from NOAA MRMS listing")

        latest_filename = sorted(mesh_candidates)[-1]
        resolved = urljoin(base_url, latest_filename)
        logger.info("Discovered latest file: %s", resolved)
        return resolved

    return probe_direct_mesh_url(base_url)


def probe_direct_mesh_url(base_url: str) -> str:
    """Probe candidate mesh filenames for hosts that do not support directory listing."""
    for hour_offset in range(0, 24):
        candidate_time = datetime.utcnow() - timedelta(hours=hour_offset)
        for ext in ["grib2.gz", "grib2"]:
            filename = f"mesh_{candidate_time:%Y%m%d_%H}00.{ext}"
            candidate_url = urljoin(base_url, filename)
            try:
                response = requests.head(
                    candidate_url,
                    timeout=20,
                    allow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if response.status_code == 200:
                    logger.info("Found direct candidate file: %s", candidate_url)
                    return candidate_url
            except requests.RequestException:
                continue
    raise RuntimeError(f"Could not find a direct MESH candidate on {base_url}")


def resolve_latest_s3_mesh_url() -> str:
    logger.info("Resolving latest MESH file from AWS MRMS public S3 bucket")
    params = {
        "list-type": "2",
        "prefix": MRMS_S3_MESH_PREFIX,
        "max-keys": "1000",
    }
    response = requests.get(MRMS_S3_BUCKET, params=params, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.text)
    keys = [
        elem.find("{http://s3.amazonaws.com/doc/2006-03-01/}Key").text
        for elem in root.findall("{http://s3.amazonaws.com/doc/2006-03-01/}Contents")
        if elem.find("{http://s3.amazonaws.com/doc/2006-03-01/}Key") is not None
    ]
    if not keys:
        raise RuntimeError("No MESH objects were found in the public MRMS S3 bucket")

    latest_key = sorted(keys)[-1]
    resolved = MRMS_S3_BUCKET + latest_key
    logger.info("Discovered AWS S3 latest file: %s", resolved)
    return resolved


def resolve_noaa_latest_mesh_url() -> str:
    logger.info("Resolving latest MESH file from NOAA latest URL")
    response = requests.get(
        MRMS_NOAA_LATEST_URL,
        timeout=30,
        stream=True,
        allow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        response.raise_for_status()
        logger.info("Resolved NOAA latest file: %s", MRMS_NOAA_LATEST_URL)
        return MRMS_NOAA_LATEST_URL
    finally:
        response.close()


def resolve_latest_mesh_url_from_sources() -> str:
    last_err = None

    # Primary source: NOAA stable "latest" endpoint for MESH Max 60min.
    try:
        return resolve_noaa_latest_mesh_url()
    except Exception as exc:
        logger.warning("Failed NOAA latest URL fallback: %s", exc)
        last_err = exc

    # Secondary fallback: AWS MRMS public S3 listing.
    try:
        return resolve_latest_s3_mesh_url()
    except Exception as exc:
        logger.warning("Failed AWS S3 MRMS fallback: %s", exc)
        last_err = exc

    # Legacy sources retained for resiliency; Thredds is intentionally last priority.
    for source in MRMS_MESH_SOURCES:
        try:
            return resolve_latest_mesh_url(source["base_url"], source["supports_listing"])
        except Exception as exc:
            logger.warning("Failed source %s (%s): %s", source["name"], source["base_url"], exc)
            last_err = exc

    raise RuntimeError(
        "Could not resolve latest MESH file from any configured MRMS source"
    ) from last_err


def download_mesh(source: str, dest: Path) -> Path:
    """Download or resolve the provided source to a local file path.

    If `source` is `latest`, it will attempt to discover the latest MESH file from NOAA.
    """
    if source.lower() == "latest":
        source = resolve_latest_mesh_url_from_sources()

    if source.startswith(("http://", "https://")):
        retry_delays = [2, 5]
        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info("Downloading %s -> %s (attempt %s/%s)", source, dest, attempt, max_attempts)
                if dest.exists():
                    dest.unlink()

                response = requests.get(source, stream=True, timeout=60)
                response.raise_for_status()
                with dest.open("wb") as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)

                if not dest.exists() or dest.stat().st_size == 0:
                    raise RuntimeError(f"Downloaded file is empty: {dest}")

                if dest.suffix == ".gz":
                    try:
                        with gzip.open(dest, "rb") as gz_file:
                            while gz_file.read(1024 * 1024):
                                pass
                    except Exception as exc:
                        raise RuntimeError(f"Downloaded gzip validation failed for {dest}: {exc}") from exc

                return dest
            except (ChunkedEncodingError, RequestsConnectionError, Timeout, RuntimeError) as exc:
                last_error = exc
                if dest.exists():
                    try:
                        dest.unlink()
                    except Exception:
                        logger.debug("Failed to remove partial download %s", dest)

                if attempt < max_attempts:
                    delay = retry_delays[attempt - 1]
                    logger.warning(
                        "Transient download failure for %s on attempt %s/%s: %s. Retrying in %ss...",
                        source,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                break

        raise RuntimeError(
            f"Failed to download and validate MESH file after {max_attempts} attempts from {source}: {last_error}"
        ) from last_error

    local_path = Path(source)
    if local_path.exists():
        logger.info("Using local MESH file %s", local_path)
        return local_path

    raise FileNotFoundError(f"File not found: {source}")


def _decompress_if_needed(path: Path) -> Path:
    """If the path ends with .gz, decompress to a temporary file and return its Path.

    The caller is responsible for removing temporary files if necessary.
    """
    if path.suffix == ".gz":
        tmp = Path(tempfile.mkstemp(suffix=".grib2")[1])
        logger.info("Decompressing %s -> %s", path, tmp)
        with gzip.open(path, "rb") as f_in, tmp.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        return tmp
    return path


def _mask_to_float(values):
    if np.ma.is_masked(values):
        values = values.filled(np.nan)
    return np.asarray(values, dtype=float)


def find_mesh_message(grbs):
    messages = list(grbs)
    if not messages:
        return None

    if len(messages) == 1:
        return messages[0]

    for msg in messages:
        name = getattr(msg, "name", "") or ""
        short_name = getattr(msg, "shortName", "") or ""
        parameter_name = getattr(msg, "parameterName", None)
        parameter_number = getattr(msg, "parameterNumber", None)

        name_lower = name.lower()
        short_lower = short_name.lower()

        if (
            ("hail" in name_lower and "maximum" in name_lower)
            or ("mesh" in name_lower and "maximum" in name_lower)
            or "hail" in short_lower
            or "mesh" in short_lower
            or parameter_name in ("Maximum Estimated Size of Hail", "MESH")
            or parameter_number == 30
        ):
            return msg

    return None


def _extract_nearest_value(mesh_message, lat: float, lon: float) -> float:
    hail_mm = None
    try:
        values, _, _ = mesh_message.data(lat1=lat, lon1=lon, lat2=lat, lon2=lon)
        if values.size > 0:
            hail_mm = float(values[0][0])
    except Exception:
        hail_mm = None

    if hail_mm is None or np.isnan(hail_mm):
        lats, lons = mesh_message.latlons()
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)
        lons = np.where(lons > 180.0, lons - 360.0, lons)
        distances = np.hypot(lats - lat, lons - lon)
        nearest_idx = np.unravel_index(np.nanargmin(distances), distances.shape)
        hail_mm = float(mesh_message.values[nearest_idx])

    return hail_mm


def read_mesh_value(filename: Path, lat: float, lon: float) -> float:
    use_path = _decompress_if_needed(filename)
    try:
        with pygrib.open(str(use_path)) as grbs:
            mesh_message = find_mesh_message(grbs)
            if mesh_message is None:
                available = ", ".join(
                    f"{getattr(m, 'name', None)}({getattr(m, 'shortName', None)})"
                    for m in grbs
                )
                raise RuntimeError(
                    f"Could not find a MESH GRIB message in {use_path}; available messages: {available}"
                )

            hail_mm = _extract_nearest_value(mesh_message, lat, lon)
            if hail_mm < 0:
                logger.warning(
                    "Negative hail size %.2f mm at %s,%s treated as 0.0 mm",
                    hail_mm,
                    lat,
                    lon,
                )
                hail_mm = 0.0

            return float(hail_mm)
    finally:
        if use_path != filename and use_path.exists():
            try:
                use_path.unlink()
            except Exception:
                logger.debug("Failed to remove temp file %s", use_path)


def read_mesh_max_in_bbox(filename: Path, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> float:
    use_path = _decompress_if_needed(filename)
    try:
        with pygrib.open(str(use_path)) as grbs:
            mesh_message = find_mesh_message(grbs)
            if mesh_message is None:
                available = ", ".join(
                    f"{getattr(m, 'name', None)}({getattr(m, 'shortName', None)})"
                    for m in grbs
                )
                raise RuntimeError(
                    f"Could not find a MESH GRIB message in {use_path}; available messages: {available}"
                )

            values = _mask_to_float(mesh_message.values)
            lats, lons = mesh_message.latlons()
            lats = np.asarray(lats, dtype=float)
            lons = np.asarray(lons, dtype=float)
            lons = np.where(lons > 180.0, lons - 360.0, lons)

            bbox_mask = (
                (lats >= min_lat)
                & (lats <= max_lat)
                & (lons >= min_lon)
                & (lons <= max_lon)
            )

            hail_mm = float(np.nan)
            if np.any(bbox_mask):
                selected = values[bbox_mask]
                if selected.size > 0:
                    hail_mm = float(np.nanmax(selected))

            if np.isnan(hail_mm):
                center_lat = (min_lat + max_lat) / 2.0
                center_lon = (min_lon + max_lon) / 2.0
                distances = np.hypot(lats - center_lat, lons - center_lon)
                nearest_idx = np.unravel_index(np.nanargmin(distances), distances.shape)
                hail_mm = float(values[nearest_idx])

            if np.isnan(hail_mm) or hail_mm < 0:
                if hail_mm < 0:
                    logger.warning(
                        "Negative hail size %.2f mm inside bbox treated as 0.0 mm",
                        hail_mm,
                    )
                hail_mm = 0.0

            return float(hail_mm)
    finally:
        if use_path != filename and use_path.exists():
            try:
                use_path.unlink()
            except Exception:
                logger.debug("Failed to remove temp file %s", use_path)


def read_mesh_cells_in_bbox_at_or_above(
    filename: Path,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    min_hail_mm: float,
) -> list[tuple[float, float, float]]:
    use_path = _decompress_if_needed(filename)
    try:
        with pygrib.open(str(use_path)) as grbs:
            mesh_message = find_mesh_message(grbs)
            if mesh_message is None:
                raise RuntimeError(f"Could not find a MESH GRIB message in {use_path}")

            values = _mask_to_float(mesh_message.values)
            lats, lons = mesh_message.latlons()
            lats = np.asarray(lats, dtype=float)
            lons = np.asarray(lons, dtype=float)
            lons = np.where(lons > 180.0, lons - 360.0, lons)

            bbox_mask = (
                (lats >= min_lat)
                & (lats <= max_lat)
                & (lons >= min_lon)
                & (lons <= max_lon)
            )
            if not np.any(bbox_mask):
                return []

            sel_lats = lats[bbox_mask]
            sel_lons = lons[bbox_mask]
            sel_vals = values[bbox_mask]
            sel_vals = np.where(np.isnan(sel_vals), 0.0, sel_vals)
            sel_vals = np.where(sel_vals < 0.0, 0.0, sel_vals)

            above_mask = sel_vals >= min_hail_mm
            if not np.any(above_mask):
                return []

            result: list[tuple[float, float, float]] = []
            for lat, lon, hail_mm in zip(sel_lats[above_mask], sel_lons[above_mask], sel_vals[above_mask], strict=True):
                result.append((float(lat), float(lon), float(hail_mm)))
            return result
    finally:
        if use_path != filename and use_path.exists():
            try:
                use_path.unlink()
            except Exception:
                logger.debug("Failed to remove temp file %s", use_path)


def mm_to_inches(mm_value: float) -> float:
    return mm_value / MM_PER_INCH


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
    return normalized.strip("-") or "region"


def derive_alert_timestamp(source: str | None) -> str:
    if source:
        source_name = Path(urlparse(source).path).name or Path(source).name
        match = re.search(r"(\d{8})-(\d{6})", source_name)
        if match:
            try:
                # Archive/backtest files encode a file timestamp, not necessarily the exact storm-hit time.
                # For MESH_Max_1440min daily maxima, this is the window-close timestamp, so timing points are
                # approximate in daily-max backtests and exact in live 60-minute operation.
                dt = datetime.strptime(
                    f"{match.group(1)}{match.group(2)}",
                    "%Y%m%d%H%M%S",
                ).replace(tzinfo=timezone.utc)
                return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            except ValueError:
                pass

    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _normalize_region_record(region: dict) -> dict:
    region_name = region.get("name") or region.get("slug") or "Unnamed Region"
    state = region.get("state")
    slug = region.get("slug")
    if not slug:
        slug = _slugify(f"{region_name}-{state}" if state else region_name)

    return {
        "id": region.get("id"),
        "slug": slug,
        "name": region_name,
        "min_lat": float(region.get("min_lat") or region.get("lat_min") or 0.0),
        "min_lon": float(region.get("min_lon") or region.get("lon_min") or 0.0),
        "max_lat": float(region.get("max_lat") or region.get("lat_max") or 0.0),
        "max_lon": float(region.get("max_lon") or region.get("lon_max") or 0.0),
        "threshold_mm": float(region.get("threshold_mm") or 0.0),
        "dealer_threshold_mm": float(region.get("dealer_threshold_mm") or 12.7),
        "email_enabled": bool(region.get("email_enabled", True)),
    }


def load_active_regions() -> list[dict]:
    if is_supabase_configured():
        params = {"select": "*"}
        try:
            response = supabase_request("GET", SUPABASE_TABLE_REGIONS, params=params)
            regions = response.json()
            if regions:
                # filter only active regions when possible
                filtered = []
                for r in regions:
                    if r.get("is_active") is False or r.get("active") is False:
                        continue
                    filtered.append(_normalize_region_record(r))
                return filtered if filtered else [_normalize_region_record(r) for r in regions]
            logger.warning("No active regions found in Supabase; falling back to default regions")
        except Exception as exc:
            logger.warning("Failed to load regions from Supabase: %s", exc)

    logger.info("Supabase not configured, using default watched regions")
    return [region.copy() for region in DEFAULT_WATCHED_REGIONS]


def get_active_region_alert(region_id: int) -> dict | None:
    if not is_supabase_configured() or region_id is None:
        return None

    params = {
        "select": "id,region_id,hail_mm,hail_in,mesh_url,mesh_source,threshold_mm",
        "region_id": f"eq.{region_id}",
        "is_active": "eq.true",
    }
    response = supabase_request("GET", SUPABASE_TABLE_ALERTS, params=params)
    alerts = response.json()
    return alerts[0] if alerts else None


def classify_dealership_tier(name: str, brand: str | None) -> str:
    name_lower = name.lower()
    brand_text = (brand or "").strip()
    if brand_text:
        return "franchise"
    if any(token in name_lower for token in MAJOR_BRAND_TOKENS):
        return "franchise"
    if "auction" in name_lower:
        return "auction"
    return "independent"


def _is_penske_group(value: str | None) -> bool:
    return str(value or "").strip().lower() == "penske"


def _is_penske_hit(hit: dict) -> bool:
    return _is_penske_group(hit.get("dealer_group"))


def _ordered_dealership_hits_for_display(dealership_hits: list[dict]) -> tuple[list[dict], int]:
    # Show franchise/auction first-priority lots, plus any Penske lots regardless of tier.
    display_hits: list[dict] = []
    for hit in dealership_hits:
        tier = str(hit.get("tier") or "").lower()
        if tier in ("franchise", "auction") or _is_penske_hit(hit):
            display_hits.append(hit)

    display_hits.sort(
        key=lambda hit: (
            0 if _is_penske_hit(hit) else 1,
            -float(hit.get("hail_mm") or 0.0),
            str(hit.get("name") or "").lower(),
        )
    )

    hidden_independent_count = len(
        [
            hit
            for hit in dealership_hits
            if str(hit.get("tier") or "").lower() == "independent" and not _is_penske_hit(hit)
        ]
    )
    return display_hits, hidden_independent_count


def load_active_dealerships(region_id: int) -> list[dict]:
    if not is_supabase_configured() or region_id is None:
        return []

    params = {
        "select": "id,region_id,name,brand,dealer_group,tier,lat,lon,osm_id,active",
        "region_id": f"eq.{region_id}",
        "active": "eq.true",
    }
    try:
        response = supabase_request("GET", SUPABASE_TABLE_DEALERSHIPS, params=params)
        return response.json() or []
    except Exception as exc:
        message = str(exc)
        missing_tier = (
            "Could not find the 'tier' column of 'dealerships'" in message
            or "column dealerships.tier does not exist" in message
        )
        missing_group = (
            "Could not find the 'dealer_group' column of 'dealerships'" in message
            or "column dealerships.dealer_group does not exist" in message
        )
        if not (missing_tier or missing_group):
            raise

    if missing_group and not missing_tier:
        fallback_no_group = {
            "select": "id,region_id,name,brand,tier,lat,lon,osm_id,active",
            "region_id": f"eq.{region_id}",
            "active": "eq.true",
        }
        response = supabase_request("GET", SUPABASE_TABLE_DEALERSHIPS, params=fallback_no_group)
        rows = response.json() or []
        for row in rows:
            row["dealer_group"] = None
        return rows

    fallback_params = {
        "select": "id,region_id,name,brand,lat,lon,osm_id,active",
        "region_id": f"eq.{region_id}",
        "active": "eq.true",
    }
    response = supabase_request("GET", SUPABASE_TABLE_DEALERSHIPS, params=fallback_params)
    rows = response.json() or []
    for row in rows:
        row["tier"] = classify_dealership_tier(str(row.get("name") or ""), row.get("brand"))
        row["dealer_group"] = None
    return rows


def _cell_contains_point_1km(cell_lat: float, cell_lon: float, point_lat: float, point_lon: float) -> bool:
    # Approximate 1km grid footprint as a 1km square centered at the MRMS cell center.
    half_km = 0.5
    lat_km = abs(point_lat - cell_lat) * 111.32
    lon_scale = 111.32 * max(0.1, abs(np.cos(np.radians(cell_lat))))
    lon_km = abs(point_lon - cell_lon) * lon_scale
    return lat_km <= half_km and lon_km <= half_km


def detect_dealership_hits(
    dealerships: list[dict],
    swath_cells: list[tuple[float, float, float]],
    threshold_mm: float,
) -> list[dict]:
    threshold_cells = [c for c in swath_cells if float(c[2]) >= threshold_mm]
    if not threshold_cells or not dealerships:
        return []

    hits: list[dict] = []

    for dealer in dealerships:
        dlat = float(dealer.get("lat") or 0.0)
        dlon = float(dealer.get("lon") or 0.0)

        max_hail_mm = None
        for clat, clon, hail_mm in threshold_cells:
            if _cell_contains_point_1km(float(clat), float(clon), dlat, dlon):
                if max_hail_mm is None or float(hail_mm) > max_hail_mm:
                    max_hail_mm = float(hail_mm)

        if max_hail_mm is None:
            continue

        hits.append(
            {
                "name": str(dealer.get("name") or "Dealership"),
                "brand": dealer.get("brand"),
                "dealer_group": dealer.get("dealer_group"),
                "tier": str(dealer.get("tier") or "independent"),
                "hail_mm": float(max_hail_mm),
                "hail_in": mm_to_inches(float(max_hail_mm)),
                "lat": dlat,
                "lon": dlon,
                "osm_id": dealer.get("osm_id"),
            }
        )

    hits.sort(key=lambda x: x["hail_mm"], reverse=True)
    return hits


def print_dealership_hits(region_name: str, hits: list[dict]) -> None:
    print(f"--- DEALERSHIPS IN SWATH: {region_name} ---")
    if not hits:
        print("none")
        return

    display_hits, hidden_independent_count = _ordered_dealership_hits_for_display(hits)

    if display_hits:
        print("NAME  TIER  HAIL_IN")
        for hit in display_hits:
            print(f"{hit['name']}  {hit.get('tier')}  {float(hit['hail_in']):.2f}")
    else:
        print("none")

    print(f"+ {hidden_independent_count} independent lots also in swath (see map)")


def find_alert_by_region_and_mesh(region_id: int, mesh_url: str) -> dict | None:
    if not is_supabase_configured() or region_id is None or not mesh_url:
        return None

    params = {
        "select": "*",
        "region_id": f"eq.{region_id}",
        "mesh_url": f"eq.{mesh_url}",
    }
    try:
        response = supabase_request("GET", SUPABASE_TABLE_ALERTS, params=params)
        alerts = response.json()
        return alerts[0] if alerts else None
    except Exception:
        return None


def has_recent_alert_for_region(region_id: int, within_hours: int, exclude_alert_id: int | None = None) -> bool:
    if not is_supabase_configured() or region_id is None:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)

    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    try:
        params = {
            "select": "id,triggered_at,email_sent_at",
            "region_id": f"eq.{region_id}",
            "order": "triggered_at.desc",
            "limit": "25",
        }
        response = supabase_request("GET", SUPABASE_TABLE_ALERTS, params=params)
        alerts = response.json()

        for alert in alerts:
            if exclude_alert_id is not None and alert.get("id") == exclude_alert_id:
                continue
            reference_time = _parse_timestamp(alert.get("email_sent_at")) or _parse_timestamp(
                alert.get("triggered_at")
            )
            if reference_time and reference_time >= cutoff:
                return True
        return False
    except Exception as exc:
        # Backward compatibility: if email_sent_at does not exist yet, fall back to triggered_at-only query.
        logger.warning("Primary recent-alert query failed for region %s, using fallback: %s", region_id, exc)
        try:
            cutoff_iso = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            fallback_params = {
                "select": "id,triggered_at",
                "region_id": f"eq.{region_id}",
                "triggered_at": f"gte.{cutoff_iso}",
                "order": "triggered_at.desc",
                "limit": "1",
            }
            if exclude_alert_id is not None:
                fallback_params["id"] = f"neq.{exclude_alert_id}"
            fallback_response = supabase_request("GET", SUPABASE_TABLE_ALERTS, params=fallback_params)
            return bool(fallback_response.json())
        except Exception as fallback_exc:
            logger.warning("Fallback recent-alert query failed for region %s: %s", region_id, fallback_exc)
            return False


def send_alert_email(
    region_name: str,
    hail_in: float,
    triggered_at: str,
    kml_filename: str | None = None,
    kml_content: str | None = None,
    top_canvass_targets: list[dict] | None = None,
    dealership_hits: list[dict] | None = None,
    dealer_only: bool = False,
) -> bool:
    if not is_email_configured():
        logger.info("Email alert not configured; skipping send")
        return False

    endpoint = "https://api.resend.com/emails"
    has_penske_hit = any(_is_penske_hit(hit) for hit in (dealership_hits or []))
    subject_prefix = "Hail Alert"
    if has_penske_hit:
        subject_prefix = f"[PENSKE] {subject_prefix}"
    if dealer_only:
        subject_prefix = f"{subject_prefix} [DEALER-ONLY]"
    subject = f"{subject_prefix}: {region_name} reached {hail_in:.2f}\""
    text = (
        "New hail alert triggered.\n"
        f"Region: {region_name}\n"
        f"Hail size: {hail_in:.2f} in\n"
        f"Time: {triggered_at}\n"
    )
    html = (
        "<h2>New hail alert triggered</h2>"
        f"<p><strong>Region:</strong> {region_name}</p>"
        f"<p><strong>Hail size:</strong> {hail_in:.2f} in</p>"
        f"<p><strong>Time:</strong> {triggered_at}</p>"
    )

    if dealer_only:
        text += "EVENT TYPE: DEALER-ONLY\n"
        html += "<p><strong>EVENT TYPE:</strong> DEALER-ONLY</p>"

    if top_canvass_targets:
        text += "\nTOP CANVASS TARGETS\n"
        html += "<h3>TOP CANVASS TARGETS</h3><ul>"
        for idx, target in enumerate(top_canvass_targets[:5], start=1):
            line = (
                f"{idx}. {target.get('geoid')} | score {int(target.get('score') or 0)} | "
                f"{str(target.get('profile_tag') or 'target')} | {float(target.get('hail_in') or 0.0):.2f} in"
            )
            text += line + "\n"
            html += f"<li>{line}</li>"
        html += "</ul>"

    if dealership_hits:
        display_hits, hidden_independent_count = _ordered_dealership_hits_for_display(dealership_hits)

        text += "\nDEALERSHIPS IN SWATH\n"
        html += "<h3>DEALERSHIPS IN SWATH</h3><ul>"
        for hit in display_hits:
            line = (
                f"{hit.get('name')} | {str(hit.get('tier') or 'dealership')} | "
                f"{float(hit.get('hail_in') or 0.0):.2f} in"
            )
            text += line + "\n"
            html += f"<li>{line}</li>"
        html += "</ul>"
        footer = f"+ {hidden_independent_count} independent lots also in swath (see map)"
        text += footer + "\n"
        html += f"<p>{footer}</p>"

    attachments = None
    if kml_filename and kml_content:
        text += "Attached: damage map — open in Google Maps.\n"
        html += "<p>Attached: damage map — open in Google Maps.</p>"
        attachments = [
            {
                "filename": kml_filename,
                "content": base64.b64encode(kml_content.encode("utf-8")).decode("ascii"),
            }
        ]

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [ALERT_EMAIL_TO],
        "subject": subject,
        "text": text,
        "html": html,
    }
    if attachments:
        payload["attachments"] = attachments

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        if response.status_code >= 400:
            logger.warning("Resend email failed: %s %s", response.status_code, response.text)
            return False
        message_id = None
        try:
            response_payload = response.json()
            message_id = response_payload.get("id")
        except Exception:
            message_id = None

        if message_id:
            logger.info("Resend email sent to %s (message_id=%s)", ALERT_EMAIL_TO, message_id)
        else:
            logger.info("Resend email sent to %s (message_id unavailable)", ALERT_EMAIL_TO)
        return True
    except Exception as exc:
        logger.warning("Resend email request failed: %s", exc)
        return False


def create_hail_alert(
    region: dict,
    mesh_url: str,
    mesh_source: str,
    hail_mm: float,
    hail_in: float,
    kml_cells: list[tuple[float, float, float]] | None = None,
    dealership_hits: list[dict] | None = None,
    alert_timestamp: str | None = None,
    retail_triggered: bool = True,
    print_scores: bool = False,
) -> dict:
    if region.get("id") is None:
        raise RuntimeError("Cannot create Supabase alert for a region without an id")
    # Idempotency: if an alert for this region+mesh already exists, return it
    existing = find_alert_by_region_and_mesh(region["id"], mesh_url)
    if existing:
        logger.info("Existing alert found for region %s, mesh %s: id=%s", region.get("id"), mesh_url, existing.get("id"))
        return existing

    payload = {
        "region_id": region["id"],
        "mesh_url": mesh_url,
        "mesh_source": mesh_source,
        "hail_mm": hail_mm,
        "hail_in": hail_in,
        "threshold_mm": float(region.get("threshold_mm") or 0.0),
        "triggered_at": alert_timestamp or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    headers = {"Prefer": "return=representation"}
    response = supabase_request(
        "POST",
        SUPABASE_TABLE_ALERTS,
        json=[payload],
        headers=headers,
    )
    created = response.json()
    if not created:
        return {}

    alert = created[0]
    logger.info("Created alert id=%s for region %s, mesh=%s", alert.get("id"), region.get("id"), mesh_url)

    recent_exists = has_recent_alert_for_region(
        region_id=region["id"],
        within_hours=ALERT_RESEND_WINDOW_HOURS,
        exclude_alert_id=alert.get("id"),
    )
    if recent_exists:
        logger.info(
            "Skipping email for alert id=%s in region %s; another alert fired within the last %s hours",
            alert.get("id"),
            region.get("id"),
            ALERT_RESEND_WINDOW_HOURS,
        )
        return alert

    if not bool(region.get("email_enabled", True)):
        logger.info(
            "Skipping email for alert id=%s in region %s; email_enabled=false",
            alert.get("id"),
            region.get("id"),
        )
        return alert

    triggered_at = alert.get("triggered_at") or alert_timestamp or (datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
    region_name = region.get("name") or region.get("slug") or "Unknown Region"
    dealer_only = not retail_triggered
    primary_dealership_hits = [
        hit
        for hit in (dealership_hits or [])
        if str(hit.get("tier") or "") in ("franchise", "auction")
    ]
    penske_hits = [hit for hit in (dealership_hits or []) if _is_penske_hit(hit)]

    canvass_targets: list[dict] = []
    if retail_triggered and kml_cells and region.get("id") is not None:
        try:
            canvass_targets = score_canvass_targets(
                swath_cells=kml_cells,
                region_id=int(region["id"]),
                alert_timestamp=triggered_at,
            )
            if not canvass_targets:
                logger.info("No tract_scores rows or no hail-gated tracts for region %s; skipping canvass scoring", region.get("id"))
        except Exception as exc:
            logger.warning("Canvass scoring failed for region %s; continuing alert flow: %s", region.get("id"), exc)
            canvass_targets = []

    if print_scores and canvass_targets:
        print(f"--- CANVASS SCORES: {region_name} ---")
        print("RANK  GEOID         SCORE  HAIL_IN  TAG")
        for row in canvass_targets:
            print(
                f"{int(row['rank']):>4}  {row['geoid']:<12} {int(row['score']):>5}  "
                f"{float(row['hail_in']):>7.2f}  {row['profile_tag']}"
            )

    if dealer_only and not primary_dealership_hits and not penske_hits:
        independent_only_count = len(
            [hit for hit in (dealership_hits or []) if str(hit.get("tier") or "") == "independent"]
        )
        logger.info(
            "Skipping email for dealer-only alert id=%s in region %s; no franchise/auction or Penske dealership hits (independent_hits=%s)",
            alert.get("id"),
            region.get("id"),
            independent_only_count,
        )
        return alert

    kml_content = None
    kml_filename = None
    if kml_cells is not None:
        if dealer_only and not (dealership_hits or []) and not kml_cells:
            logger.warning(
                "Dealer-only alert for region %s has zero swath cells and zero dealership hits; skipping empty map attachment",
                region.get("id"),
            )
        else:
            event_date = triggered_at[:10]
            kml_content = build_hail_swath_kml(
                kml_cells,
                region_name=region_name,
                event_date=event_date,
                canvass_targets=canvass_targets[:10],
                dealership_hits=dealership_hits or [],
            )
            safe_region = re.sub(r"[^A-Za-z0-9_-]+", "-", region_name).strip("-") or "region"
            kml_filename = f"damage-map-{safe_region}-{event_date}.kml"

    sent = send_alert_email(
        region_name,
        hail_in,
        triggered_at,
        kml_filename=kml_filename,
        kml_content=kml_content,
        top_canvass_targets=canvass_targets[:5],
        dealership_hits=dealership_hits or [],
        dealer_only=dealer_only,
    )
    if sent:
        try:
            email_sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            update_hail_alert(int(alert["id"]), {"email_sent_at": email_sent_at})
            alert["email_sent_at"] = email_sent_at
        except Exception as exc:
            logger.warning("Failed to update email_sent_at for alert id=%s: %s", alert.get("id"), exc)
    return alert


def update_hail_alert(alert_id: int, data: dict) -> None:
    headers = {"Prefer": "return=representation"}
    supabase_request(
        "PATCH",
        f"{SUPABASE_TABLE_ALERTS}?id=eq.{alert_id}",
        json=data,
        headers=headers,
    )


def clear_hail_alert(alert_id: int) -> None:
    update_hail_alert(
        alert_id,
        {
            "is_active": False,
            "cleared_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        },
    )
    logger.info("Cleared alert id=%s", alert_id)


def process_regions(
    mesh_path: Path,
    mesh_url: str,
    mesh_source: str,
    dry_run: bool = False,
    print_scores: bool = False,
) -> list[dict]:
    regions = load_active_regions()
    results = []
    alert_timestamp = derive_alert_timestamp(mesh_url or mesh_source)
    source_name = Path(urlparse(mesh_url or mesh_source).path).name if (mesh_url or mesh_source) else ""

    if "MESH_Max_1440min" in source_name:
        logger.info(
            "Timing points for %s are using the file window-close timestamp %s; daily-max backtests are approximate, live 60-minute runs are exact",
            source_name,
            alert_timestamp,
        )

    for region in regions:
        threshold_mm = float(region["threshold_mm"])
        dealer_threshold_mm = float(region.get("dealer_threshold_mm") or 12.7)
        swath_floor_mm = min(threshold_mm, dealer_threshold_mm)
        hail_mm = read_mesh_max_in_bbox(
            mesh_path,
            float(region["min_lat"]),
            float(region["min_lon"]),
            float(region["max_lat"]),
            float(region["max_lon"]),
        )
        hail_in = mm_to_inches(hail_mm)
        active_alert = get_active_region_alert(region.get("id"))
        retail_triggered = hail_mm >= threshold_mm
        dealer_triggered = hail_mm >= dealer_threshold_mm
        triggered = retail_triggered or dealer_triggered
        action = "none"

        if triggered:
            if active_alert:
                action = "active_alert"
                if print_scores and region.get("id") is not None:
                    swath_cells: list[tuple[float, float, float]] = []
                    try:
                        swath_cells = read_mesh_cells_in_bbox_at_or_above(
                            mesh_path,
                            float(region["min_lat"]),
                            float(region["min_lon"]),
                            float(region["max_lat"]),
                            float(region["max_lon"]),
                            swath_floor_mm,
                        )
                        if retail_triggered:
                            scored = score_canvass_targets(
                                swath_cells=swath_cells,
                                region_id=int(region["id"]),
                                alert_timestamp=alert_timestamp,
                            )
                            print(f"--- CANVASS SCORES: {region.get('name') or region.get('slug')} ---")
                            print("RANK  GEOID         SCORE  HAIL_IN  TAG")
                            for row in scored:
                                print(
                                    f"{int(row['rank']):>4}  {row['geoid']:<12} {int(row['score']):>5}  "
                                    f"{float(row['hail_in']):>7.2f}  {row['profile_tag']}"
                                )
                    except Exception as exc:
                        logger.warning("Canvass score print failed for region %s: %s", region.get("id"), exc)
                    try:
                        dealerships = load_active_dealerships(int(region["id"]))
                        dealership_hits = detect_dealership_hits(dealerships, swath_cells, dealer_threshold_mm)
                        print_dealership_hits(region.get("name") or region.get("slug") or "Region", dealership_hits)
                    except Exception as exc:
                        logger.warning("Dealership hit print failed for region %s: %s", region.get("id"), exc)
            elif region.get("id") is not None:
                swath_cells = read_mesh_cells_in_bbox_at_or_above(
                    mesh_path,
                    float(region["min_lat"]),
                    float(region["min_lon"]),
                    float(region["max_lat"]),
                    float(region["max_lon"]),
                    swath_floor_mm,
                )

                dealership_hits: list[dict] = []
                try:
                    dealerships = load_active_dealerships(int(region["id"]))
                    if dealerships:
                        dealership_hits = detect_dealership_hits(dealerships, swath_cells, dealer_threshold_mm)
                    else:
                        logger.info("No dealerships loaded for region %s; skipping dealership hit detection", region.get("id"))
                except Exception as exc:
                    logger.warning("Dealership hit detection failed for region %s; continuing alert flow: %s", region.get("id"), exc)
                    dealership_hits = []

                primary_dealership_hits_count = len(
                    [
                        hit
                        for hit in dealership_hits
                        if str(hit.get("tier") or "") in ("franchise", "auction")
                    ]
                )
                penske_hits_count = len([hit for hit in dealership_hits if _is_penske_hit(hit)])
                independent_dealership_hits_count = len(
                    [hit for hit in dealership_hits if str(hit.get("tier") or "") == "independent"]
                )
                email_eligible = retail_triggered or primary_dealership_hits_count > 0 or penske_hits_count > 0
                email_gate_reason = "retail-triggered"
                if not retail_triggered:
                    if primary_dealership_hits_count > 0:
                        email_gate_reason = "dealer-primary-hit"
                    elif penske_hits_count > 0:
                        email_gate_reason = "dealer-penske-hit"
                    else:
                        email_gate_reason = "dealer-only-no-primary-or-penske-hit"

                logger.info(
                    "Email gate region=%s eligible=%s reason=%s dealer_only=%s primary_hits=%s penske_hits=%s independent_hits=%s total_hits=%s",
                    region.get("id"),
                    email_eligible,
                    email_gate_reason,
                    (not retail_triggered),
                    primary_dealership_hits_count,
                    penske_hits_count,
                    independent_dealership_hits_count,
                    len(dealership_hits),
                )

                if not dry_run:
                    create_hail_alert(
                        region,
                        mesh_url,
                        mesh_source,
                        hail_mm,
                        hail_in,
                        kml_cells=swath_cells,
                        dealership_hits=dealership_hits,
                        alert_timestamp=alert_timestamp,
                        retail_triggered=retail_triggered,
                        print_scores=print_scores,
                    )
                    action = "created_alert"
                else:
                    if print_scores and region.get("id") is not None:
                        if dealer_triggered and not retail_triggered and not swath_cells and not dealership_hits:
                            logger.warning(
                                "Dealer-only alert candidate for region %s has zero swath cells and zero dealership hits; empty map would be skipped",
                                region.get("id"),
                            )
                        try:
                            if retail_triggered:
                                scored = score_canvass_targets(
                                    swath_cells=swath_cells,
                                    region_id=int(region["id"]),
                                    alert_timestamp=alert_timestamp,
                                )
                                print(f"--- CANVASS SCORES: {region.get('name') or region.get('slug')} ---")
                                print("RANK  GEOID         SCORE  HAIL_IN  TAG")
                                for row in scored:
                                    print(
                                        f"{int(row['rank']):>4}  {row['geoid']:<12} {int(row['score']):>5}  "
                                        f"{float(row['hail_in']):>7.2f}  {row['profile_tag']}"
                                    )
                        except Exception as exc:
                            logger.warning("Canvass score print failed for region %s: %s", region.get("id"), exc)
                        try:
                            print_dealership_hits(region.get("name") or region.get("slug") or "Region", dealership_hits)
                        except Exception as exc:
                            logger.warning("Dealership hit print failed for region %s: %s", region.get("id"), exc)
                    action = "would_create_alert"
            else:
                action = "threshold_exceeded_no_db"
        else:
            if active_alert and region.get("id") is not None:
                if not dry_run:
                    clear_hail_alert(active_alert["id"])
                    action = "cleared_alert"
                else:
                    action = "would_clear_alert"
            else:
                action = "below_threshold"

        summary = {
            "region": region.get("name") or region.get("slug"),
            "slug": region.get("slug"),
            "hail_mm": hail_mm,
            "hail_in": hail_in,
            "threshold_mm": threshold_mm,
            "dealer_threshold_mm": dealer_threshold_mm,
            "swath_floor_mm": swath_floor_mm,
            "retail_triggered": retail_triggered,
            "dealer_triggered": dealer_triggered,
            "triggered": triggered,
            "action": action,
        }
        logger.info(
            "Region %s: hail=%.2f mm (%.2f in), retail_threshold=%.2f mm, dealer_threshold=%.2f mm, swath_floor=%.2f mm, retail_triggered=%s, dealer_triggered=%s, action=%s",
            summary["region"],
            hail_mm,
            hail_in,
            threshold_mm,
            dealer_threshold_mm,
            swath_floor_mm,
            retail_triggered,
            dealer_triggered,
            action,
        )
        results.append(summary)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Hail Lead Engine Phase 1")
    parser.add_argument(
        "source",
        nargs="?",
        default="latest",
        help="URL, local path, or 'latest' to auto-discover the most recent 60-minute max MESH file",
    )
    parser.add_argument(
        "--lat",
        type=float,
        default=SPRINGFIELD_LAT,
        help="Latitude for the Springfield, MO test point",
    )
    parser.add_argument(
        "--lon",
        type=float,
        default=SPRINGFIELD_LON,
        help="Longitude for the Springfield, MO test point",
    )
    parser.add_argument(
        "--scan-regions",
        action="store_true",
        help="Scan the configured watched regions and update Supabase alert state",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write Supabase alerts; only print what would happen",
    )
    parser.add_argument(
        "--print-scores",
        action="store_true",
        help="Print full scored tract list for triggered regions during scan",
    )
    parser.add_argument(
        "--email-smoke-test",
        action="store_true",
        help="Send a single test email via Resend and exit (no NOAA/Supabase usage)",
    )
    parser.add_argument(
        "--email-region",
        default="Manual Smoke Test",
        help="Region label used by --email-smoke-test",
    )
    parser.add_argument(
        "--email-hail-in",
        type=float,
        default=1.0,
        help="Hail inches used by --email-smoke-test",
    )

    args = parser.parse_args()

    if args.email_smoke_test:
        triggered_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        sent = send_alert_email(args.email_region, args.email_hail_in, triggered_at)
        if sent:
            print("Email smoke test sent successfully")
            return 0
        print("Email smoke test failed; verify RESEND_API_KEY and ALERT_EMAIL_TO")
        return 1

    source = args.source
    resolved_source = None
    try:
        if source.lower() == "latest":
            mesh_url = resolve_latest_mesh_url_from_sources()
            dest_path = Path(urlparse(mesh_url).path).name
            mesh_path = download_mesh(mesh_url, Path(dest_path))
            resolved_source = mesh_url
        elif source.startswith(("http://", "https://")):
            dest_path = Path(urlparse(source).path).name
            mesh_path = download_mesh(source, Path(dest_path))
            resolved_source = source
        else:
            mesh_path = download_mesh(source, Path(source))
            resolved_source = str(mesh_path)
    except Exception as exc:
        logger.error(
            "MESH download cycle skipped: unable to resolve/download/validate source '%s': %s",
            source,
            exc,
        )
        return 0

    print("--- HAIL LEAD ENGINE PHASE 1 ---")
    print(f"Requested source: {source}")
    print(f"Resolved source: {resolved_source}")
    print(f"Local file: {mesh_path}")

    hail_mm = read_mesh_value(mesh_path, args.lat, args.lon)
    hail_in = mm_to_inches(hail_mm)
    print(f"Test point: {args.lat}, {args.lon}")
    print(f"Hail size at point: {hail_mm:.2f} mm / {hail_in:.2f} in")

    if args.scan_regions:
        results = process_regions(
            mesh_path,
            resolved_source,
            resolved_source or source,
            dry_run=args.dry_run,
            print_scores=args.print_scores,
        )
        print("--- REGION SCAN ---")
        for item in results:
            print(
                f"{item['region']}: {item['hail_mm']:.2f} mm / {item['hail_in']:.2f} in, "
                f"threshold={item['threshold_mm']:.2f} mm, action={item['action']}"
            )
    else:
        print(
            "Supabase integration not configured and --scan-regions not set; skipping region scan."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
