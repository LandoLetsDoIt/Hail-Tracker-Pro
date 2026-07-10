import argparse
import gzip
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pygrib
import requests

# Confirmed from IEM index listings:
# https://mtarchive.geol.iastate.edu/YYYY/MM/DD/mrms/ncep/MESH_Max_1440min/
# Filename pattern: MESH_Max_1440min_00.50_YYYYMMDD-HHMMSS.grib2.gz
IEM_BASE = "https://mtarchive.geol.iastate.edu"
IEM_MESH_SUBPATH = "mrms/ncep/MESH_Max_1440min"
IEM_FILE_RE = re.compile(r"MESH_Max_1440min_00\.50_(\d{8})-(\d{6})\.grib2\.gz")

SPRINGFIELD_MIN_LAT = 37.00
SPRINGFIELD_MAX_LAT = 37.45
SPRINGFIELD_MIN_LON = -93.55
SPRINGFIELD_MAX_LON = -93.11
MM_PER_INCH = 25.4


def mm_to_inches(mm_value: float) -> float:
    return mm_value / MM_PER_INCH


def _decompress_if_needed(path: Path) -> Path:
    if path.suffix == ".gz":
        tmp = Path(tempfile.mkstemp(suffix=".grib2")[1])
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


def list_day_mesh_files(day_utc: datetime) -> list[str]:
    day_path = day_utc.strftime("%Y/%m/%d")
    directory_url = f"{IEM_BASE}/{day_path}/{IEM_MESH_SUBPATH}/"
    response = requests.get(directory_url, timeout=30)
    response.raise_for_status()

    candidates = set(re.findall(r'href=["\']([^"\']+\.grib2\.gz)["\']', response.text, flags=re.IGNORECASE))
    mesh_files = [name for name in candidates if IEM_FILE_RE.fullmatch(Path(name).name)]
    if not mesh_files:
        raise RuntimeError(f"No MESH GRIB2 files found at {directory_url}")

    return sorted(Path(name).name for name in mesh_files)


def choose_end_of_day_file(day_utc: datetime, day_files: list[str]) -> str:
    date_key = day_utc.strftime("%Y%m%d")
    matching = []
    for name in day_files:
        match = IEM_FILE_RE.fullmatch(name)
        if not match:
            continue
        date_part, time_part = match.groups()
        if date_part == date_key:
            matching.append((time_part, name))

    if not matching:
        raise RuntimeError(f"No files found for {date_key}")

    # Prefer the latest available 24-hour max file for the day.
    matching.sort(key=lambda item: item[0])
    return matching[-1][1]


def download_file(url: str, target: Path) -> Path:
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    with target.open("wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    return target


def extract_bbox_points(filename: Path, min_lat: float, min_lon: float, max_lat: float, max_lon: float):
    use_path = _decompress_if_needed(filename)
    try:
        with pygrib.open(str(use_path)) as grbs:
            mesh_message = find_mesh_message(grbs)
            if mesh_message is None:
                raise RuntimeError(f"Could not find MESH GRIB message in {filename}")

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

            sel_lats = lats[bbox_mask]
            sel_lons = lons[bbox_mask]
            sel_vals = values[bbox_mask]
            if sel_vals.size == 0:
                raise RuntimeError("No grid cells found inside bbox")

            # Normalize invalid negatives to 0.0 mm.
            sel_vals = np.where(np.isnan(sel_vals), 0.0, sel_vals)
            sel_vals = np.where(sel_vals < 0, 0.0, sel_vals)
            return sel_lats, sel_lons, sel_vals
    finally:
        if use_path != filename and use_path.exists():
            try:
                use_path.unlink()
            except Exception:
                pass


def extract_point_value(filename: Path, lat: float, lon: float) -> float:
    use_path = _decompress_if_needed(filename)
    try:
        with pygrib.open(str(use_path)) as grbs:
            mesh_message = find_mesh_message(grbs)
            if mesh_message is None:
                raise RuntimeError(f"Could not find MESH GRIB message in {filename}")

            value = None
            try:
                values, _, _ = mesh_message.data(lat1=lat, lon1=lon, lat2=lat, lon2=lon)
                if values.size > 0:
                    value = float(values[0][0])
            except Exception:
                value = None

            if value is None or np.isnan(value):
                lats, lons = mesh_message.latlons()
                lats = np.asarray(lats, dtype=float)
                lons = np.asarray(lons, dtype=float)
                lons = np.where(lons > 180.0, lons - 360.0, lons)
                distances = np.hypot(lats - lat, lons - lon)
                nearest_idx = np.unravel_index(np.nanargmin(distances), distances.shape)
                value = float(mesh_message.values[nearest_idx])

            if np.isnan(value) or value < 0:
                value = 0.0

            return float(value)
    finally:
        if use_path != filename and use_path.exists():
            try:
                use_path.unlink()
            except Exception:
                pass


def build_single_url(day_utc: datetime) -> tuple[str, str]:
    day_files = list_day_mesh_files(day_utc)
    filename = choose_end_of_day_file(day_utc, day_files)
    url = f"{IEM_BASE}/{day_utc.strftime('%Y/%m/%d')}/{IEM_MESH_SUBPATH}/{filename}"
    return filename, url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest MRMS MESH over Springfield bbox using IEM archive files"
    )
    parser.add_argument(
        "--date",
        default="2026-04-28",
        help="UTC date in YYYY-MM-DD (default: 2026-04-28)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="Number of top grid cells to print (default: 15)",
    )
    parser.add_argument(
        "--point",
        nargs="+",
        type=str,
        metavar=("LAT", "LON"),
        help="Optional single point to backtest instead of printing top grid cells",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    point_lat = None
    point_lon = None
    if args.point is not None:
        if len(args.point) == 1:
            raw_point = args.point[0]
            if "," not in raw_point:
                raise ValueError("--point must be provided as LAT LON or LAT,LON")
            lat_text, lon_text = raw_point.split(",", 1)
            point_lat = float(lat_text)
            point_lon = float(lon_text)
        elif len(args.point) == 2:
            point_lat = float(args.point[0])
            point_lon = float(args.point[1])
        else:
            raise ValueError("--point must be provided as LAT LON or LAT,LON")

    day = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    filename, url = build_single_url(day)

    print("--- BACKTEST CONFIG ---")
    print(f"Date (UTC): {args.date}")
    print(f"Selected file: {filename}")
    print(
        f"BBox: lat {SPRINGFIELD_MIN_LAT}..{SPRINGFIELD_MAX_LAT}, "
        f"lon {SPRINGFIELD_MIN_LON}..{SPRINGFIELD_MAX_LON}"
    )
    print("Sampling: single 24-hour maximum file")

    if point_lat is not None and point_lon is not None:
        print(f"Point mode: lat={point_lat:.4f}, lon={point_lon:.4f}")
        print(f"Downloading {filename}")

        downloaded_path = download_file(url, Path(filename))
        try:
            value_mm = extract_point_value(downloaded_path, point_lat, point_lon)
        finally:
            try:
                downloaded_path.unlink(missing_ok=True)
            except Exception:
                pass

        print("\n--- POINT BACKTEST RESULT ---")
        print(f"hail={mm_to_inches(value_mm):.2f} in ({value_mm:.2f} mm)")
        return 0

    print(f"Downloading {filename}")

    downloaded_path = download_file(url, Path(filename))
    try:
        lats, lons, vals_mm = extract_bbox_points(
            downloaded_path,
            SPRINGFIELD_MIN_LAT,
            SPRINGFIELD_MIN_LON,
            SPRINGFIELD_MAX_LAT,
            SPRINGFIELD_MAX_LON,
        )
    finally:
        try:
            downloaded_path.unlink(missing_ok=True)
        except Exception:
            pass

    cell_max_mm: dict[tuple[float, float], float] = {}
    for lat, lon, mm in zip(lats, lons, vals_mm, strict=True):
        key = (round(float(lat), 4), round(float(lon), 4))
        current = cell_max_mm.get(key)
        if current is None or mm > current:
            cell_max_mm[key] = float(mm)

    ranked = sorted(cell_max_mm.items(), key=lambda item: item[1], reverse=True)

    print("\n--- TOP GRID CELLS BY MAX HAIL ---")
    print(f"Top {min(args.top_n, len(ranked))} cells across all sampled hours")
    for idx, ((lat, lon), mm) in enumerate(ranked[: args.top_n], start=1):
        inches = mm_to_inches(mm)
        print(f"{idx:2d}. lat={lat:.4f}, lon={lon:.4f}, hail={inches:.2f} in ({mm:.2f} mm)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
