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
@pytest.mark.parametrize("weight", profiles.WEIGHTS)
def test_series_dimensions_are_valid(key, style, weight):
    assert profiles.validate(profiles.SERIES[key].dimensions(weight), style) == []


@pytest.mark.parametrize("key", list(profiles.SERIES))
def test_weight_classes_keep_the_slot(key):
    standard = profiles.SERIES[key].dimensions()
    slot = ("cell", "slot_opening", "lip", "head_width", "head_straight", "slot_depth", "bottom_width")
    for weight in profiles.WEIGHTS:
        d = profiles.SERIES[key].dimensions(weight)
        assert {k: d[k] for k in slot} == {k: standard[k] for k in slot}


def test_weight_rules():
    s = profiles.SERIES["40-8"]
    assert s.dimensions("Heavy")["corner_hole"] == 0 and s.dimensions("Heavy")["chamber_wall"] == 0
    assert s.dimensions("Light")["chamber_wall"] > s.dimensions("Ultralight")["chamber_wall"] > 0
    assert s.dimensions("Ultralight")["center_bore"] > s.center_bore
    assert s.tappable("Light") and not s.tappable("Ultralight")


def test_systems_and_labels():
    assert {s.system for s in profiles.SERIES.values()} <= set(profiles.SYSTEMS)
    assert profiles.series_label("20-5") == "20 series, slot 5 (I-type)"
    assert profiles.series_label("20-6") == "20 series, slot 6 (B-type)"
    cells = [(s.cell, s.slot_opening) for s in profiles.SERIES.values()]
    assert cells == sorted(cells)


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
