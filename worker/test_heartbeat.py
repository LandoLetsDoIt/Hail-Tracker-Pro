from datetime import datetime
from zoneinfo import ZoneInfo

from worker.heartbeat import build_status_body, in_window, summarize_alerts


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
