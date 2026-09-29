"""Piece identity and marks (no FreeCAD needed)."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "pieces", os.path.join(os.path.dirname(__file__), "..", "freecad", "profile_builder", "pieces.py"))
pieces = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pieces)

key = pieces.canonical_cuts
X, Y = "X", "Y"


def test_side_drawn_the_other_way_is_the_same_piece():
    # A picture-frame side: both ends long on +X, or (drawn reversed) on -X.
    assert key((), ((45, X), (45, X)), False) == key((), ((-45, X), (-45, X)), False)


def test_trapezoid_and_parallelogram_differ():
    trapezoid = key((), ((45, X), (45, X)), False)
    parallelogram = key((), ((45, X), (-45, X)), False)
    assert trapezoid != parallelogram
    # A parallelogram turned over is still a parallelogram.
    assert parallelogram == key((), ((-45, X), (45, X)), False)


def test_end_for_end():
    # A single miter at the start equals the same miter at the end.
    assert key((), ((30, Y), (0, "")), False) == key((), ((0, ""), (30, Y)), False)


def test_across_x_and_across_y_differ_on_a_2040_but_not_on_a_2020():
    across_x = ((45, X), (45, X))
    across_y = ((45, Y), (45, Y))
    assert key((), across_x, False) != key((), across_y, False)
    assert key((), across_x, True) == key((), across_y, True)


def test_closed_face_limits_the_turns():
    # Closed top, miters across Y: turning end over end about X would move the
    # closed face to the bottom, so (45, 45) and (-45, -45) differ.
    assert key({"Top"}, ((45, Y), (45, Y)), False) != key({"Top"}, ((-45, Y), (-45, Y)), False)
    # Across X the closed top stays on top when flipped about Y: same piece.
    assert key({"Top"}, ((45, X), (45, X)), False) == key({"Top"}, ((-45, X), (-45, X)), False)


def test_square_cuts_and_rounding():
    assert key((), ((0, X), (-0.0, Y)), False) == ((0.0, ""), (0.0, ""))
    assert key((), ((44.99, X), (45.01, X)), False) == key((), ((45, X), (45, X)), False)


def test_prefers_positive_angles():
    assert key((), ((-45, X), (-45, X)), False) == ((45.0, X), (45.0, X))


def test_letters():
    assert [pieces.letters(i) for i in (0, 1, 25, 26, 27, 51, 52)] == ["A", "B", "Z", "AA", "AB", "AZ", "BA"]
