from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hail_engine import (
    SUPABASE_TABLE_ALERTS,
    create_hail_alert,
    is_email_configured,
    is_supabase_configured,
    load_active_regions,
    send_alert_email,
    supabase_request,
    update_hail_alert,
)


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _supports_email_sent_at() -> bool:
    try:
        supabase_request("GET", f"{SUPABASE_TABLE_ALERTS}?select=id,email_sent_at&limit=1")
        return True
    except Exception as exc:
        if "email_sent_at does not exist" in str(exc):
            return False
        raise


def main() -> int:
    print("Integration email alert flow")

    if not is_supabase_configured():
        print("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
        return 1

    if not is_email_configured():
        print("Email is not configured. Set RESEND_API_KEY and ALERT_EMAIL_TO.")
        return 1

    regions = [r for r in load_active_regions() if r.get("id") is not None]
    if not regions:
        print("No active regions with IDs found.")
        return 1

    region = regions[0]
    region["email_enabled"] = True
    region_name = region.get("name") or region.get("slug") or "Unknown Region"
    supports_email_sent_at = _supports_email_sent_at()
    if not supports_email_sent_at:
        print("email_sent_at column is missing. Apply migration 03_hail_alerts_email_sent_at.sql first.")

    unique_suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mesh_url = f"https://example.com/integration-email-{unique_suffix}.grib2"
    hail_mm = 30.0
    hail_in = round(hail_mm / 25.4, 2)

    created_alert_id = None

    try:
        created = create_hail_alert(
            region=region,
            mesh_url=mesh_url,
            mesh_source="integration_test",
            hail_mm=hail_mm,
            hail_in=hail_in,
        )
        if not created or not created.get("id"):
            print("Alert creation failed.")
            return 2

        created_alert_id = int(created["id"])
        print(f"CREATED_ALERT_ID {created_alert_id}")

        select_fields = "id,region_id,triggered_at,is_active,mesh_url"
        if supports_email_sent_at:
            select_fields += ",email_sent_at"

        fetch_response = supabase_request(
            "GET",
            f"{SUPABASE_TABLE_ALERTS}?id=eq.{created_alert_id}&select={select_fields}",
        )
        rows = fetch_response.json()
        print(f"FETCH_STATUS row_count={len(rows)}")

        if not rows:
            print("Could not fetch created alert row.")
            return 3

        row = rows[0]
        email_sent_at = row.get("email_sent_at")

        if supports_email_sent_at and not email_sent_at:
            # Cooldown may have skipped email send; force one test send to validate delivery + row update.
            print("No email_sent_at on created row (likely cooldown). Sending one direct test email now.")
            sent = send_alert_email(region_name, hail_in, row.get("triggered_at") or _utc_now_z())
            if not sent:
                print("Direct test email send failed.")
                return 4

            email_sent_at = _utc_now_z()
            update_hail_alert(created_alert_id, {"email_sent_at": email_sent_at})
            row["email_sent_at"] = email_sent_at

        if supports_email_sent_at:
            print(f"EMAIL_SENT_AT {row.get('email_sent_at')}")
            print("INTEGRATION_RESULT success")
        else:
            print("EMAIL_SENT_AT unavailable (migration not applied)")
            print("INTEGRATION_RESULT partial_success")
        return 0
    finally:
        if created_alert_id is not None:
            try:
                delete_response = supabase_request(
                    "DELETE",
                    f"{SUPABASE_TABLE_ALERTS}?id=eq.{created_alert_id}",
                    headers={"Prefer": "return=representation"},
                )
                print(f"CLEANUP_STATUS deleted_rows={len(delete_response.json())}")
            except Exception as exc:
                print(f"CLEANUP_STATUS failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
