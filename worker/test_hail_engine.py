import pathlib
import pytest

from worker.hail_engine import read_mesh_value


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
