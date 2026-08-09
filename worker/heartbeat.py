import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("heartbeat")

CHICAGO_TZ = ZoneInfo("America/Chicago")
SUPABASE_URL = (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")
RESEND_FROM_EMAIL = "onboarding@resend.dev"
MONITORED_REGIONS_COUNT = 18
HEARTBEAT_BYPASS_WINDOW = os.getenv("HEARTBEAT_BYPASS_WINDOW", "0") == "1"
HEARTBEAT_DRY_RUN = os.getenv("HEARTBEAT_DRY_RUN", "0") == "1"


def in_window(now: datetime | None = None) -> bool:
    """Sanity check only. Timing precision is owned by the external
    cron service that fires workflow_dispatch at 22:00 Central; this
    just guards against a stray/manual dispatch far outside that time.
    """
    if HEARTBEAT_BYPASS_WINDOW:
        return True
    if now is None:
        now = datetime.now(CHICAGO_TZ)
    if now.hour == 21 and now.minute >= 45:
        return True
    if now.hour == 22 and now.minute <= 15:
        return True
    return False


def get_supabase_headers() -> dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }


def fetch_recent_alerts() -> list[dict]:
    since = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=24)
    cutoff_iso = since.isoformat().replace("+00:00", "Z")
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/hail_alerts",
        headers=get_supabase_headers(),
        params={
            "select": "id,region_id,hail_mm,hail_in,threshold_mm,created_at,email_sent_at",
            "created_at": f"gte.{cutoff_iso}",
            "order": "created_at.asc",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def already_sent_today(send_date) -> bool:
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/heartbeat_log",
        headers=get_supabase_headers(),
        params={"select": "sent_date", "sent_date": f"eq.{send_date.isoformat()}"},
        timeout=30,
    )
    response.raise_for_status()
    return len(response.json()) > 0


def mark_sent_today(send_date) -> None:
    headers = get_supabase_headers()
    headers["Content-Type"] = "application/json"
    headers["Prefer"] = "resolution=ignore-duplicates"
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/heartbeat_log",
        headers=headers,
        json={"sent_date": send_date.isoformat()},
        timeout=30,
    )
    response.raise_for_status()


def fetch_regions() -> list[dict]:
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/regions",
        headers=get_supabase_headers(),
        params={
            "select": "id,name",
            "order": "id.asc",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def summarize_alerts(alerts: list[dict], regions: list[dict]) -> dict:
    region_map = {int(region["id"]): region["name"] for region in regions}
    retail_count = 0
    dealer_sent_count = 0
    dealer_suppressed_count = 0
    active_regions: set[int] = set()
    highest = None

    for row in alerts:
        region_id = int(row.get("region_id") or 0)
        hail_mm = float(row.get("hail_mm") or 0.0)
        threshold_mm = float(row.get("threshold_mm") or 0.0)
        is_retail = hail_mm >= threshold_mm
        email_sent = bool(row.get("email_sent_at"))

        if is_retail:
            retail_count += 1
        elif email_sent:
            dealer_sent_count += 1
        else:
            dealer_suppressed_count += 1

        if region_id:
            active_regions.add(region_id)

        if highest is None or hail_mm > highest["hail_mm"]:
            highest = {
                "hail_mm": hail_mm,
                "hail_in": hail_mm / 25.4,
                "region_id": region_id,
                "region_name": region_map.get(region_id, f"region-{region_id}"),
            }

    return {
        "retail_count": retail_count,
        "dealer_sent_count": dealer_sent_count,
        "dealer_suppressed_count": dealer_suppressed_count,
        "active_region_count": len(active_regions),
        "highest": highest,
    }


def build_status_body(summary: dict, monitored_regions_count: int = MONITORED_REGIONS_COUNT) -> str:
    total_alerts = (
        summary["retail_count"]
        + summary["dealer_sent_count"]
        + summary["dealer_suppressed_count"]
    )
    if total_alerts == 0:
        subject = "Hail Tracker — Nightly Status [NO ACTIVITY]"
        body_lines = [
            "No alerts were recorded in the last 24 hours.",
            "Engine status: running and quiet.",
            f"Regions monitored: {monitored_regions_count}",
            "Alerts created: 0",
            "Retail-triggered: 0",
            "Dealer-only sent: 0",
            "Dealer-only suppressed: 0",
            "Highest hail: none",
            "Regions with activity: 0",
        ]
        return "\n".join([subject, *body_lines])

    highest = summary["highest"] or {}
    subject = "Hail Tracker — Nightly Status [OK]"
    body_lines = [
        "Nightly status report.",
        "Engine status: running.",
        f"Regions monitored: {monitored_regions_count}",
        f"Retail-triggered: {summary['retail_count']}",
        f"Dealer-only sent: {summary['dealer_sent_count']}",
        f"Dealer-only suppressed: {summary['dealer_suppressed_count']}",
        f"Highest hail: {highest.get('hail_mm', 0):.1f} mm / {highest.get('hail_in', 0):.2f} in ({highest.get('region_name', 'unknown')})",
        f"Regions with activity: {summary['active_region_count']}",
    ]
    return "\n".join([subject, *body_lines])


def send_status_email(summary: dict) -> bool:
    body = build_status_body(summary)
    if HEARTBEAT_DRY_RUN:
        logger.info("Heartbeat dry run; email body would be:\n%s", body)
        print(body)
        return True

    if not RESEND_API_KEY or not ALERT_EMAIL_TO:
        logger.info("Resend email not configured; skipping heartbeat send")
        return False

    try:
        from hail_engine import send_plain_status_email
    except ModuleNotFoundError:
        from worker.hail_engine import send_plain_status_email

    subject = build_status_body(summary).splitlines()[0]
    text = build_status_body(summary)
    success = send_plain_status_email(subject, text)
    if success:
        logger.info("Heartbeat email sent via existing Resend flow")
    return success


def main() -> int:
    now = datetime.now(CHICAGO_TZ)
    if not in_window(now):
        logger.info("Outside heartbeat window (Central time=%s); skipping", now.isoformat())
        return 0

    try:
        if not HEARTBEAT_DRY_RUN and already_sent_today(now.date()):
            logger.info("Heartbeat already sent for %s; skipping duplicate", now.date().isoformat())
            return 0

        alerts = fetch_recent_alerts()
        regions = fetch_regions()
        summary = summarize_alerts(alerts, regions)
        sent = send_status_email(summary)
        if sent and not HEARTBEAT_DRY_RUN:
            mark_sent_today(now.date())
    except Exception as exc:
        if HEARTBEAT_DRY_RUN:
            logger.warning("Heartbeat dry run using empty summary after error: %s", exc)
            send_status_email({
                "retail_count": 0,
                "dealer_sent_count": 0,
                "dealer_suppressed_count": 0,
                "active_region_count": 0,
                "highest": None,
            })
            return 0

        logger.exception("Heartbeat failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
