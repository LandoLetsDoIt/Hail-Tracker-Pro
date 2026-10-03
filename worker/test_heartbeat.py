from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from worker.heartbeat import build_status_body, in_window, summarize_alerts

EMPTY_SUMMARY = {
    "retail_count": 0,
    "dealer_sent_count": 0,
    "dealer_suppressed_count": 0,
    "active_region_count": 0,
    "highest": None,
}


def test_in_window_accepts_chicago_window():
    now = datetime(2026, 8, 7, 21, 45, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert in_window(now)


def test_summarize_alerts_counts_activity_and_highest_hail():
    alerts = [
        {"region_id": 1, "hail_mm": 30.0, "threshold_mm": 25.4, "email_sent_at": None},
        {"region_id": 1, "hail_mm": 20.0, "threshold_mm": 25.4, "email_sent_at": "2026-08-07T21:00:00Z"},
        {"region_id": 2, "hail_mm": 40.0, "threshold_mm": 25.4, "email_sent_at": "2026-08-07T21:05:00Z"},
    ]
    regions = [{"id": 1, "name": "Springfield"}, {"id": 2, "name": "Kansas City"}]

    summary = summarize_alerts(alerts, regions)

    assert summary["retail_count"] == 2
    assert summary["dealer_sent_count"] == 1
    assert summary["dealer_suppressed_count"] == 0
    assert summary["active_region_count"] == 2
    assert summary["highest"]["region_name"] == "Kansas City"
    assert summary["highest"]["hail_mm"] == 40.0


def test_build_status_body_handles_no_activity():
    body = build_status_body({
        "retail_count": 0,
        "dealer_sent_count": 0,
        "dealer_suppressed_count": 0,
        "active_region_count": 0,
        "highest": None,
    }, 18)

    assert "[NO ACTIVITY]" in body
    assert "Alerts created: 0" in body


def test_build_status_body_flags_engine_down_when_never_ran():
    body = build_status_body({**EMPTY_SUMMARY, "engine_last_run": None}, 18)

    assert "[ENGINE DOWN]" in body
    assert "never" in body


def test_build_status_body_flags_engine_down_when_stale():
    stale = datetime.now(timezone.utc) - timedelta(hours=3)
    body = build_status_body({**EMPTY_SUMMARY, "engine_last_run": stale}, 18)

    assert "[ENGINE DOWN]" in body
    assert "3.0 hours ago" in body


def test_build_status_body_passes_through_when_engine_fresh():
    fresh = datetime.now(timezone.utc) - timedelta(minutes=10)
    body = build_status_body({**EMPTY_SUMMARY, "engine_last_run": fresh}, 18)

    assert "[NO ACTIVITY]" in body


def test_build_status_body_reports_engine_check_failure():
    body = build_status_body({**EMPTY_SUMMARY, "engine_check_error": "GITHUB_TOKEN and GITHUB_REPOSITORY must be set"}, 18)

    assert "[ENGINE CHECK FAILED]" in body
    assert "GITHUB_TOKEN and GITHUB_REPOSITORY must be set" in body
