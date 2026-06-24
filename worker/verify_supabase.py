import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment variables from .env at project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_supabase_headers() -> dict[str, str]:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment")

    return {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def verify_regions_read():
    supabase_url = os.getenv("SUPABASE_URL").rstrip("/")
    headers = get_supabase_headers()
    url = f"{supabase_url}/rest/v1/regions?select=*"
    response = requests.get(url, headers=headers, timeout=30)
    print("Status:", response.status_code)
    print("URL:", url)
    print("Response:", response.text[:2000])
    response.raise_for_status()


def verify_alerts_insert():
    supabase_url = os.getenv("SUPABASE_URL").rstrip("/")
    headers = get_supabase_headers()
    url = f"{supabase_url}/rest/v1/hail_alerts"
    payload = [
        {
            "region_id": 1,
            "mesh_url": "https://example.com/test.grib2",
            "mesh_source": "verification",
            "hail_mm": 10.0,
            "hail_in": 0.39,
            "threshold_mm": 25.4,
        }
    ]
    response = requests.post(url, headers={**headers, "Prefer": "return=representation"}, json=payload, timeout=30)
    print("Status:", response.status_code)
    print("URL:", url)
    print("Response:", response.text[:2000])
    response.raise_for_status()
    return response.json()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Supabase verification script")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only verify reads from Supabase; do not insert test data",
    )
    args = parser.parse_args()

    print("Supabase verification script")
    print("- Verify regions read")
    try:
        verify_regions_read()
    except Exception as exc:
        print("Failed regions read:", exc)
        return 1

    if args.dry_run:
        print("Dry run enabled; skipping hail_alerts insert")
        return 0

    print("- Verify hail_alerts insert")
    try:
        result = verify_alerts_insert()
        print("Insert result:", result)
    except Exception as exc:
        print("Failed alerts insert:", exc)
        return 2

    print("Supabase verification succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
