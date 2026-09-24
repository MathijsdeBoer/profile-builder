"""Catalog tests that run without FreeCAD:  python -m pytest tests"""

import importlib.util
import os

import pytest

_spec = importlib.util.spec_from_file_location(
    "profiles", os.path.join(os.path.dirname(__file__), "..", "freecad", "profile_builder", "profiles.py"))
profiles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profiles)


@pytest.mark.parametrize("key", list(profiles.SERIES))
@pytest.mark.parametrize("style", profiles.SLOT_STYLES)
def test_series_dimensions_are_valid(key, style):
    assert profiles.validate(profiles.SERIES[key].dimensions(), style) == []


def test_designations():
    s20 = profiles.SERIES["20-6"]
    assert s20.designation(1, 1) == "2020"
    assert s20.designation(1, 2) == "2040"
    assert s20.designation(2, 1) == "2040"
    assert s20.designation(2, 4) == "4080"
    assert profiles.SERIES["45-10"].designation(1, 2) == "4590"
    assert profiles.SERIES["40-8"].designation(1, 3) == "40120"


def test_presets_round_trip():
    for name, faces in profiles.SLOT_PRESETS:
        assert profiles.closed_faces_for_preset(name) == faces
        assert profiles.preset_for_closed_faces(faces) == name
    assert profiles.preset_for_closed_faces(("Left",)) is None


def test_validate_catches_bad_geometry():
    d = profiles.SERIES["20-6"].dimensions()
    assert profiles.validate({**d, "slot_opening": 12.0})
    assert profiles.validate({**d, "slot_depth": 10.5})
    assert profiles.validate({**d, "center_bore": 9.0})
    assert profiles.validate({**d, "cell": 0.0})
    assert profiles.validate({**d, "v_chamfer": 2.0}, "V-slot")
    assert not profiles.validate({**d, "v_chamfer": 2.0}, "T-slot")
