import pathlib
import pytest

from worker.hail_engine import create_hail_alert, load_active_regions, mm_to_inches, read_mesh_value


def test_mm_to_inches():
    assert mm_to_inches(25.4) == pytest.approx(1.0)
    assert mm_to_inches(0.0) == 0.0


def test_load_active_regions_falls_back_without_supabase(monkeypatch):
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('NEXT_PUBLIC_SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)

    regions = load_active_regions()
    assert isinstance(regions, list)
    assert len(regions) == 1
    assert regions[0]['slug'] == 'springfield-mo'


def test_read_mesh_value_nearest_point():
    path = pathlib.Path('MRMS_MESH_Max_60min_00.50_20201016-053400.grib2')
    if not path.exists():
        pytest.skip('Local GRIB2 test file is not available')

    hail_mm = read_mesh_value(path, 37.21, -93.29)
    assert hail_mm >= 0.0
    assert hail_mm <= 100.0


def test_read_mesh_value_uses_single_message():
    path = pathlib.Path('MRMS_MESH_Max_60min_00.50_20201016-053400.grib2')
    if not path.exists():
        pytest.skip('Local GRIB2 test file is not available')

    hail_mm = read_mesh_value(path, 37.21, -93.29)
    assert isinstance(hail_mm, float)


def test_create_hail_alert_sends_email_for_new_alert(monkeypatch):
    sent = {"count": 0}

    class DummyResponse:
        def json(self):
            return [{"id": 101, "triggered_at": "2026-06-24T00:00:00Z"}]

    monkeypatch.setattr("worker.hail_engine.find_alert_by_region_and_mesh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("worker.hail_engine.supabase_request", lambda *_args, **_kwargs: DummyResponse())
    monkeypatch.setattr("worker.hail_engine.has_recent_alert_for_region", lambda *_args, **_kwargs: False)

    def fake_send(*_args, **_kwargs):
        sent["count"] += 1
        return True

    monkeypatch.setattr("worker.hail_engine.send_alert_email", fake_send)

    region = {"id": 1, "name": "Springfield", "slug": "springfield", "threshold_mm": 25.4, "email_enabled": True}
    create_hail_alert(region, "https://example.com/mesh.grib2", "test", 30.0, 1.18)
    assert sent["count"] == 1


def test_create_hail_alert_does_not_resend_within_cooldown(monkeypatch):
    sent = {"count": 0}

    class DummyResponse:
        def json(self):
            return [{"id": 102, "triggered_at": "2026-06-24T00:00:00Z"}]

    monkeypatch.setattr("worker.hail_engine.find_alert_by_region_and_mesh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("worker.hail_engine.supabase_request", lambda *_args, **_kwargs: DummyResponse())
    monkeypatch.setattr("worker.hail_engine.has_recent_alert_for_region", lambda *_args, **_kwargs: True)

    def fake_send(*_args, **_kwargs):
        sent["count"] += 1
        return True

    monkeypatch.setattr("worker.hail_engine.send_alert_email", fake_send)

    region = {"id": 1, "name": "Springfield", "slug": "springfield", "threshold_mm": 25.4, "email_enabled": True}
    create_hail_alert(region, "https://example.com/mesh.grib2", "test", 30.0, 1.18)
    assert sent["count"] == 0


def test_create_hail_alert_respects_email_disabled(monkeypatch):
    sent = {"count": 0}

    class DummyResponse:
        def json(self):
            return [{"id": 103, "triggered_at": "2026-06-24T00:00:00Z"}]

    monkeypatch.setattr("worker.hail_engine.find_alert_by_region_and_mesh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("worker.hail_engine.supabase_request", lambda *_args, **_kwargs: DummyResponse())
    monkeypatch.setattr("worker.hail_engine.has_recent_alert_for_region", lambda *_args, **_kwargs: False)

    def fake_send(*_args, **_kwargs):
        sent["count"] += 1
        return True

    monkeypatch.setattr("worker.hail_engine.send_alert_email", fake_send)

    region = {"id": 1, "name": "Springfield", "slug": "springfield", "threshold_mm": 25.4, "email_enabled": False}
    create_hail_alert(region, "https://example.com/mesh.grib2", "test", 30.0, 1.18)
    assert sent["count"] == 0


def test_send_alert_email_prefixes_subject_and_orders_penske_first(monkeypatch):
    captured = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"id": "msg_test"}

    def fake_post(_endpoint, headers=None, json=None, timeout=None):
        captured["headers"] = headers
        captured["payload"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("worker.hail_engine.is_email_configured", lambda: True)
    monkeypatch.setattr("worker.hail_engine.requests.post", fake_post)

    from worker.hail_engine import send_alert_email

    hits = [
        {
            "name": "Generic Motors",
            "tier": "franchise",
            "hail_in": 1.2,
            "hail_mm": 30.48,
            "dealer_group": None,
        },
        {
            "name": "Penske Auto Mall",
            "tier": "independent",
            "hail_in": 0.7,
            "hail_mm": 17.78,
            "dealer_group": "Penske",
        },
    ]

    sent = send_alert_email(
        region_name="Dallas",
        hail_in=1.2,
        triggered_at="2026-07-13T00:00:00Z",
        dealership_hits=hits,
    )

    assert sent is True
    assert captured["payload"]["subject"].startswith("[PENSKE] Hail Alert:")

    text = captured["payload"]["text"]
    section = text.split("DEALERSHIPS IN SWATH\n", 1)[1]
    first_line = section.splitlines()[0]
    assert "Penske Auto Mall" in first_line


def test_create_hail_alert_dealer_only_sends_for_penske_independent_hit(monkeypatch):
    sent = {"count": 0}

    class DummyResponse:
        def json(self):
            return [{"id": 104, "triggered_at": "2026-06-24T00:00:00Z"}]

    monkeypatch.setattr("worker.hail_engine.find_alert_by_region_and_mesh", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("worker.hail_engine.supabase_request", lambda *_args, **_kwargs: DummyResponse())
    monkeypatch.setattr("worker.hail_engine.has_recent_alert_for_region", lambda *_args, **_kwargs: False)

    def fake_send(*_args, **_kwargs):
        sent["count"] += 1
        return True

    monkeypatch.setattr("worker.hail_engine.send_alert_email", fake_send)
    monkeypatch.setattr("worker.hail_engine.update_hail_alert", lambda *_args, **_kwargs: None)

    region = {"id": 1, "name": "Springfield", "slug": "springfield", "threshold_mm": 25.4, "email_enabled": True}
    penske_independent_hit = {
        "name": "Penske Used Cars",
        "tier": "independent",
        "hail_mm": 15.0,
        "hail_in": 0.59,
        "dealer_group": "Penske",
    }

    create_hail_alert(
        region,
        "https://example.com/mesh.grib2",
        "test",
        hail_mm=15.0,
        hail_in=0.59,
        kml_cells=[],
        dealership_hits=[penske_independent_hit],
        retail_triggered=False,
    )
    assert sent["count"] == 1
