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
