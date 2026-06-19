import argparse
import gzip
import logging
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import numpy as np
import pygrib
import requests

MRMS_MESH_SOURCES = [
    {
        "name": "thredds",
        "base_url": "https://thredds.ncep.noaa.gov/thredds/fileServer/meso_analyses/merged/mesh/",
        "supports_listing": True,
    },
    {
        "name": "mrms-host",
        "base_url": "https://mrms.ncep.noaa.gov/data/2D/merged/mesh/",
        "supports_listing": False,
    },
]
MRMS_S3_BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com/"
MRMS_S3_MESH_PREFIX = "CONUS/MESH_Max_60min_00.50/"
SPRINGFIELD_LAT = 37.21
SPRINGFIELD_LON = -93.29
MM_PER_INCH = 25.4

logger = logging.getLogger("hail_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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


def resolve_latest_mesh_url_from_sources() -> str:
    last_err = None
    for source in MRMS_MESH_SOURCES:
        try:
            return resolve_latest_mesh_url(source["base_url"], source["supports_listing"])
        except Exception as exc:
            logger.warning("Failed source %s (%s): %s", source["name"], source["base_url"], exc)
            last_err = exc

    try:
        return resolve_latest_s3_mesh_url()
    except Exception as exc:
        logger.warning("Failed AWS S3 MRMS fallback: %s", exc)
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
        logger.info("Downloading %s -> %s", source, dest)
        response = requests.get(source, stream=True, timeout=60)
        response.raise_for_status()
        with dest.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
        return dest

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


def read_mesh_value(filename: Path, lat: float, lon: float) -> float:
    # pygrib can often read gzipped files, but to be safe decompress if needed.
    use_path = _decompress_if_needed(filename)
    try:
        with pygrib.open(str(use_path)) as grbs:
            messages = list(grbs)
            if not messages:
                raise RuntimeError(f"No GRIB messages found in {use_path}")

            mesh_message = None
            if len(messages) == 1:
                mesh_message = messages[0]
            else:
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
                        mesh_message = msg
                        break

            if mesh_message is None:
                if len(messages) == 1:
                    mesh_message = messages[0]
                else:
                    available = ", ".join(
                        f"{getattr(m, 'name', None)}({getattr(m, 'shortName', None)})"
                        for m in messages
                    )
                    raise RuntimeError(
                        f"Could not find a MESH GRIB message in {use_path}; available messages: {available}"
                    )

            hail_mm = None
            try:
                values, _, _ = mesh_message.data(lat1=lat, lon1=lon, lat2=lat, lon2=lon)
                if values.size > 0:
                    hail_mm = float(values[0][0])
            except Exception:
                hail_mm = None

            if hail_mm is None:
                lats, lons = mesh_message.latlons()
                distances = np.hypot(lats - lat, lons - lon)
                nearest_idx = np.unravel_index(np.argmin(distances), distances.shape)
                hail_mm = float(mesh_message.values[nearest_idx])

            if hail_mm < 0:
                logger.warning(
                    "Negative hail size %.2f mm at %s,%s treated as 0.0 mm",
                    hail_mm,
                    lat,
                    lon,
                )
                hail_mm = 0.0

            return hail_mm
    finally:
        # cleanup temporary decompressed file if we created one
        if use_path != filename and use_path.exists():
            try:
                use_path.unlink()
            except Exception:
                logger.debug("Failed to remove temp file %s", use_path)


def mm_to_inches(mm_value: float) -> float:
    return mm_value / MM_PER_INCH


def main() -> int:
    parser = argparse.ArgumentParser(description="Hail Lead Engine Phase 0")
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

    args = parser.parse_args()
    source = args.source
    resolved_source = None
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

    hail_mm = read_mesh_value(mesh_path, args.lat, args.lon)
    hail_in = mm_to_inches(hail_mm)

    print("--- HAIL LEAD ENGINE PHASE 0 ---")
    print(f"Requested source: {source}")
    print(f"Resolved source: {resolved_source}")
    print(f"Local file: {mesh_path}")
    print(f"Location: {args.lat}, {args.lon}")
    print(f"Hail size: {hail_mm:.2f} mm / {hail_in:.2f} in")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
