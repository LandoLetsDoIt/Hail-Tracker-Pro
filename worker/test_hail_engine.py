import pathlib
import pytest

from worker.hail_engine import is_supabase_configured, load_active_regions, mm_to_inches, read_mesh_value


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
