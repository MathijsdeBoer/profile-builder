"""Sheet layout, holes and DXF/SVG output (no FreeCAD needed)."""

import importlib.util
import math
import os

_spec = importlib.util.spec_from_file_location(
    "fabrication", os.path.join(os.path.dirname(__file__), "..", "freecad", "profile_builder", "fabrication.py"))
fab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fab)

SQUARE = [(0, 0), (400, 0), (400, 300), (0, 300)]


def close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_square_corners_without_radius():
    segments, radius = fab.rounded_outline(SQUARE, 0)
    assert radius == 0 and [s[0] for s in segments] == ["line"] * 4


def test_rounded_corners_are_tangent_arcs():
    segments, radius = fab.rounded_outline(SQUARE, 10)
    arcs = [s for s in segments if s[0] == "arc"]
    assert radius == 10 and len(arcs) == 4 and len(segments) == 8
    _kind, centre, r, p, q, ccw = arcs[0]
    assert close(centre, (10, 10)) and r == 10 and ccw
    assert close(p, (0, 10)) and close(q, (10, 0))
    # The path is closed: each segment starts where the previous one ends.
    ends = [s[2] if s[0] == "line" else s[4] for s in segments]
    starts = [s[1] if s[0] == "line" else s[3] for s in segments]
    assert all(close(e, s) for e, s in zip(ends, starts[1:] + starts[:1]))
    # Area of a rounded rectangle.
    assert abs(fab.bounds(segments)[2] - 400) < 1e-6


def test_radius_is_reduced_on_short_edges():
    _segments, radius = fab.rounded_outline([(0, 0), (30, 0), (30, 300), (0, 300)], 20)
    assert abs(radius - 15) < 1e-9


def test_clip_inside_with_inset():
    assert fab.clip_inside((-50, 10), (450, 10), SQUARE, 8) == [((8.0, 10.0), (392.0, 10.0))]
    assert fab.clip_inside((-50, 5), (450, 5), SQUARE, 8) == []
    # Clockwise outlines work too.
    assert fab.clip_inside((-50, 10), (450, 10), SQUARE[::-1], 8) == [((8.0, 10.0), (392.0, 10.0))]


L_SHAPE = [(0, 0), (400, 0), (400, 200), (200, 200), (200, 400), (0, 400)]


def test_clip_inside_a_non_convex_outline():
    # A line through both arms of an L is split at the inner corner.
    pieces = fab.clip_inside((-10, 300), (410, 300), L_SHAPE, 8)
    assert [(round(a[0], 6), round(b[0], 6)) for a, b in pieces] == [(8.0, 192.0)]
    pieces = fab.clip_inside((10, -10), (10, 410), L_SHAPE, 8)
    assert [(round(a[1], 6), round(b[1], 6)) for a, b in pieces] == [(8.0, 392.0)]
    # Along the inner edge, 10 mm inside it.
    pieces = fab.clip_inside((190, -10), (190, 410), L_SHAPE, 8)
    assert [(round(a[1], 6), round(b[1], 6)) for a, b in pieces] == [(8.0, 392.0)]


def test_holes_all_round_an_l_shaped_sheet():
    lines = [("a", (-10, 10), (410, 10)), ("b", (390, -10), (390, 210)), ("c", (410, 190), (190, 190)),
             ("d", (190, 180), (190, 410)), ("e", (210, 390), (-10, 390)), ("f", (10, 410), (10, -10))]
    holes, notes = fab.hole_layout(lines, L_SHAPE, 5, 150, 6, L_SHAPE, 25)
    assert not notes
    assert all(fab.inside(h, L_SHAPE) and fab._to_polygon(h, L_SHAPE) >= 6 - 1e-9 for h in holes)
    sides = {name for name, p, q in lines if any(fab._to_polygon(h, [p, q]) < 1e-6 for h in holes)}
    assert sides == set("abcdef"), sides


def test_rounded_corners_keep_holes_on_the_sheet():
    segments, _ = fab.rounded_outline(SQUARE, 80)
    outline = fab.polygon_of(segments)
    lines = [("bottom", (-10, 10), (410, 10)), ("left", (10, -10), (10, 310))]
    holes, _notes = fab.hole_layout(lines, outline, 5, 150, 8, SQUARE, 10)
    assert holes and all(fab.inside(h, outline) and fab._to_polygon(h, outline) >= 8 - 0.05 for h in holes)


def test_holes_stay_out_of_cutouts():
    fan = [(250 + 15 * math.cos(k * math.pi / 16), 12 + 15 * math.sin(k * math.pi / 16)) for k in range(32)]
    holes, notes = fab.hole_layout([("bottom", (-10, 10), (410, 10))], SQUARE, 5, 50, 6, [], 0, [fan])
    assert all(not fab.inside(h, fan) and fab._to_polygon(h, fan) >= 2.5 for h in holes)
    assert any("cut into a cutout" in n for n in notes)


def test_keepouts_split_a_line():
    pieces = fab.remove_circles((0, 0), (400, 0), [(0, 0), (200, 5), (400, 0)], 25)
    assert [round(p[0][0], 3) for p in pieces] == [25, round(200 + math.sqrt(25 ** 2 - 25), 3)]
    assert len(pieces) == 2 and abs(pieces[1][1][0] - 375) < 1e-9


def test_spacing_is_even_and_not_above_the_maximum():
    holes = fab.spaced((0, 0), (300, 0), 100, 10)
    assert [h[0] for h in holes] == [0, 100, 200, 300]
    holes = fab.spaced((0, 0), (310, 0), 100, 10)
    assert len(holes) == 5 and holes[1][0] == 77.5
    assert fab.spaced((0, 0), (8, 0), 100, 10) == [(4.0, 0.0)]


def test_hole_layout_around_a_square_frame():
    lines = [("bottom", (-10, 10), (410, 10)), ("top", (-10, 290), (410, 290)),
             ("left", (10, -10), (10, 310)), ("right", (390, -10), (390, 310))]
    holes, notes = fab.hole_layout(lines, SQUARE, 5.5, 150, 6, SQUARE, 25)
    assert not notes
    # No two holes closer than two diameters, all inside, none near a corner.
    assert all(math.dist(a, b) >= 11 for i, a in enumerate(holes) for b in holes[i + 1:])
    assert all(min(math.dist(h, c) for c in SQUARE) >= 25 - 1e-9 for h in holes)
    assert len([h for h in holes if h[1] == 10]) == 4  # 350 mm between keep-outs: 3 gaps


def test_line_too_close_to_the_edge_is_reported():
    holes, notes = fab.hole_layout([("A", (0, 4), (400, 4))], SQUARE, 5, 100, 8, [], 0)
    assert not holes and "4.0 mm from the sheet edge" in notes[0]


def test_fingerprint_ignores_turning_and_flipping():
    a, _ = fab.rounded_outline(SQUARE, 5)
    turned = [(300 - y, x) for x, y in SQUARE]
    b, _ = fab.rounded_outline(turned, 5)
    holes = [(20, 10), (380, 10)]
    turned_holes = [(300 - y, x) for x, y in holes]
    flipped_holes = [(400 - x, y) for x, y in holes]
    key = fab.fingerprint(a, holes, 5)
    assert key == fab.fingerprint(b, turned_holes, 5) == fab.fingerprint(a, flipped_holes, 5)
    assert key != fab.fingerprint(a, [(20, 10), (380, 20)], 5)
    assert key != fab.fingerprint(a, holes, 6)


def test_fingerprint_ignores_cutout_order_and_float_noise():
    a, _ = fab.rounded_outline(SQUARE, 0)
    one, two = [(100, 100), (110, 100)], [(280, 200), (290, 200)]
    assert fab.fingerprint(a, [], 0, [one, two]) == fab.fingerprint(a, [], 0, [two, one])
    # 420.05 mm (16.5375 in) computed two ways must round alike.
    b, _ = fab.rounded_outline([(0, 0), (420.05 + 1e-10, 0), (420.05, 300), (0, 300)], 0)
    c, _ = fab.rounded_outline([(0, 0), (420.05 - 1e-10, 0), (420.05, 300), (0, 300)], 0)
    assert fab.fingerprint(b, [], 0) == fab.fingerprint(c, [], 0)


def test_dxf_has_layers_and_entities():
    segments, _ = fab.rounded_outline(SQUARE, 10)
    cutout = [("circle", (200, 150), 30)]
    text = fab.dxf_text(segments, [(20, 20)], 5.5, [cutout], [(10, 10, 5, "P-1 Acrylic 3 mm Ø")], scale=1 / 25.4)
    codes = text.split("\n")
    pairs = list(zip(codes[0::2], codes[1::2]))
    assert pairs[0] == ("  0", "SECTION") and pairs[-1] == ("  0", "EOF")
    entities = [v for c, v in pairs if c.strip() == "0"]
    assert entities.count("ARC") == 4 and entities.count("LINE") == 4 and entities.count("CIRCLE") == 2
    assert entities.count("TEXT") == 1 and "P-1 Acrylic 3 mm D" in text
    text.encode("ascii")  # R12 is not Unicode
    # Inches: the 400 mm edge ends at 400 / 25.4 = 15.748031.
    assert "15.748031" in text


def test_arc_angles_follow_the_dxf_convention():
    segments, _ = fab.rounded_outline(SQUARE, 10)
    first = [s for s in segments if s[0] == "arc"][0]  # bottom-left corner
    assert close(fab._arc_angles(first), (180, 270))


def test_svg_is_true_size():
    segments, _ = fab.rounded_outline(SQUARE, 10)
    svg = fab.svg_text(segments, [(20, 20)], 5, texts=[(10, 10, 5, "A & B")])
    assert 'width="404mm" height="304mm"' in svg and svg.count(" A ") == 4
    assert "A &amp; B" in svg and 'r="2.5"' in svg
