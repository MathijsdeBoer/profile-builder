"""Prices of metre ware (no FreeCAD needed)."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "metreware", os.path.join(os.path.dirname(__file__), "..", "freecad", "profile_builder", "metreware.py"))
metreware = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(metreware)

parse = metreware.parse_price


def test_plain_numbers_are_per_metre():
    assert parse("2.40") == (2.4, "m")
    assert parse(" 2,40 ") == (2.4, "m")
    assert parse("3") == (3.0, "m")
    assert parse(".5") == (0.5, "m")


def test_prices_with_a_unit():
    assert parse("0.75/ft") == (0.75, "ft")
    assert parse("0,75 / ft") == (0.75, "ft")
    assert parse("2.40/m") == (2.4, "m")
    assert parse("0.10/in") == (0.1, "in")
    assert parse("1.20/yd") == (1.2, "yd")
    assert parse("0.75/foot") == (0.75, "ft")
    assert parse("2.40/metre") == (2.4, "m")


def test_empty_or_unknown_prices():
    assert parse("") is None
    assert parse(None) is None
    assert parse("cheap") is None
    assert parse("2.40/km") is None
    assert parse("1,234.50") is None  # thousands separators are not guessed


def test_units_are_lengths_in_metres():
    assert metreware.UNITS["ft"] == 0.3048 and metreware.UNITS["in"] == 0.0254 and metreware.UNITS["m"] == 1.0
