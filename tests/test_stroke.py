"""Clear run, stroke and position of a carriage (no FreeCAD needed)."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "stroke", os.path.join(os.path.dirname(__file__), "..", "freecad", "profile_builder", "stroke.py"))
stroke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stroke)

RECT_2020 = (-10, 10, -10, 10)
RECT_2040 = (-10, 10, -20, 20)  # 1 column, 2 rows: the Left and Right faces are 40 wide


def test_face_axes_are_right_handed():
    for face, ((tx, ty), (nx, ny)) in stroke.FACE_AXES.items():
        # tangent x normal must be +axis (z): tx*ny - ty*nx == 1
        assert tx * ny - ty * nx == 1, face


def test_envelope_above_the_top_face():
    assert stroke.envelope("Top", RECT_2020, 20, 15, 0) == (-10, 10, 10, 25)


def test_envelope_wraps_back_around_the_sides():
    # A 40 wide plate on the Right face of a 2040 that reaches 5 back over the Top and Bottom faces.
    assert stroke.envelope("Right", RECT_2040, 50, 12, 5) == (5, 22, -25, 25)


def test_envelope_on_every_face_stands_out_of_that_face():
    for face in stroke.FACE_AXES:
        x0, x1, y0, y1 = stroke.envelope(face, RECT_2040, 10, 7, 0)
        assert (x1 - x0, y1 - y0) in ((10, 7), (7, 10))
        # It lies outside the section, touching it.
        assert not stroke.overlaps((x0, x1, y0, y1), RECT_2040)


def test_face_under_is_clipped_to_the_face():
    assert sorted(stroke.face_under("Top", RECT_2020, 60)) == [(-10, 10), (10, 10)]
    assert sorted(stroke.face_under("Left", RECT_2040, 20)) == [(-10, -10), (-10, 10)]


def test_touching_rectangles_do_not_overlap():
    assert not stroke.overlaps((0, 10, 0, 10), (10, 20, 0, 10))
    assert stroke.overlaps((0, 10, 0, 10), (9.9, 20, 0, 10))


def test_rail_between_two_posts_is_one_run_named_after_the_posts():
    # The posts only touch the rail ends.
    runs = stroke.free_runs(20, 580, [(580, 580, "Post B"), (20, 20, "Post A")])
    assert runs == [stroke.Run(20, 580, "Post A", "Post B")]
    assert runs[0].length == 560


def test_a_member_in_the_middle_splits_the_run():
    runs = stroke.free_runs(0, 600, [(240, 260, "Cross")])
    assert [(r.start, r.end, r.start_by, r.end_by) for r in runs] == [(0, 240, None, "Cross"), (260, 600, "Cross", None)]


def test_overlapping_and_outside_blockers():
    runs = stroke.free_runs(0, 600, [(-50, 10, "A"), (100, 200, "B"), (150, 180, "C"), (590, 700, "D"), (800, 900, "E")])
    assert [(r.start, r.end, r.start_by, r.end_by) for r in runs] == [(10, 100, "A", "B"), (200, 590, "B", "D")]


def test_blocked_along_the_whole_rail_leaves_no_run():
    assert stroke.free_runs(0, 600, [(-1, 601, "Panel")]) == []


def test_pick_run_longest_first_of_equals_and_by_number():
    runs = stroke.free_runs(0, 600, [(290, 310, "X")])
    run, message = stroke.pick_run(runs)
    assert run is runs[0] and message is None  # equal runs: the first
    runs = stroke.free_runs(0, 600, [(240, 260, "X")])
    assert stroke.pick_run(runs)[0] is runs[1]
    assert stroke.pick_run(runs, 1)[0] is runs[0]
    run, message = stroke.pick_run(runs, 3)
    assert run is runs[1] and "no run 3" in message
    assert stroke.pick_run([], 0) == (None, None)


def test_stroke_travel_and_centre():
    run = stroke.Run(20, 580)
    usable = stroke.stroke(run.length, 60, 5)
    assert usable == 490
    assert stroke.travel("Percent", 0, 50, usable) == 245
    assert stroke.travel("Percent", 0, 150, usable) == usable  # clamped
    assert stroke.travel("Distance", 100, 50, usable) == 100
    assert stroke.centre(run, 60, 5, 0) == 20 + 5 + 30
    assert stroke.centre(run, 60, 5, usable) == 580 - 5 - 30
    # Too long a carriage is shown in the middle of the run.
    assert stroke.centre(run, 600, 0, 0) == 300
    assert stroke.travel("Percent", 0, 50, -40) == 0


def test_problems():
    run = stroke.Run(20, 580, "Post A", "Post B")
    assert stroke.problems(run, 60, 5, 490, "Percent", 0) == []
    short = stroke.problems(run, 60, 5, 500, "Percent", 0)
    assert len(short) == 1 and "10 mm short of the required 500 mm" in short[0] and "Post A and Post B" in short[0]
    no_fit = stroke.problems(stroke.Run(0, 50), 60, 0, 0, "Percent", 0)
    assert len(no_fit) == 1 and "do not fit" in no_fit[0] and "the start of the rail" in no_fit[0]
    beyond = stroke.problems(run, 60, 5, 0, "Distance", 495)
    assert len(beyond) == 1 and "run into Post B" in beyond[0]
    before = stroke.problems(run, 60, 5, 0, "Distance", -1)
    assert len(before) == 1 and "run into Post A" in before[0]
    assert stroke.problems(run, 60, 5, 0, "Distance", 490) == []


def test_pitch_diameter_of_a_toothed_pulley():
    assert abs(stroke.pitch_diameter(20, 2) - 12.732) < 1e-3  # 20 teeth GT2
    assert stroke.pitch_diameter(0, 2) == 0 and stroke.pitch_diameter(20, 0) == 0


def test_open_belt_length():
    # 2 x 600 + pi x d, where pi x d is 20 teeth x 2 mm, plus 50 for the clamps.
    d = stroke.pitch_diameter(20, 2)
    assert abs(stroke.belt_length(600, d, 50) - 1290) < 1e-9
    # Rounded up to whole teeth, but an exact length stays.
    assert stroke.belt_length(600, d, 49, pitch=2) == 1290
    assert stroke.belt_length(600, d, 50, pitch=2) == 1290
    # Inch belts: XL has a 0.2 in (5.08 mm) pitch.
    assert abs(stroke.belt_length(500, 0, 0, pitch=5.08) - 197 * 5.08) < 1e-9
