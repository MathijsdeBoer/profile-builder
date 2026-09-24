"""Cross-section and solid generation for aluminium extrusion profiles.

The section is built in the XY plane with the profile centred on the origin
and extruded along +Z. Everything here works on plain dimension dicts (see
``profiles.Series.dimensions``) so it can be used from macros as well::

    from freecad.profile_builder import geometry, profiles
    dims = profiles.SERIES["20-6"].dimensions()
    Part.show(geometry.make_profile(dims, cols=1, rows=2, length=500))
"""

import math

import FreeCAD as App
import Part

from . import profiles

V = App.Vector

# How far cutting tools stick out past the outer face, to avoid coplanar booleans.
OVERSHOOT = 1.0


def _face(points):
    pts = [V(x, y, 0) for x, y in points]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def _circle(cx, cy, diameter):
    return Part.Face(Part.Wire(Part.makeCircle(diameter / 2, V(cx, cy, 0))))


def _rounded_rect(w, h, r):
    if r <= 0:
        return _face([(0, 0), (w, 0), (w, h), (0, h)])
    z = V(0, 0, 1)
    edges = [
        Part.makeLine(V(r, 0, 0), V(w - r, 0, 0)),
        Part.makeCircle(r, V(w - r, r, 0), z, 270, 360),
        Part.makeLine(V(w, r, 0), V(w, h - r, 0)),
        Part.makeCircle(r, V(w - r, h - r, 0), z, 0, 90),
        Part.makeLine(V(w - r, h, 0), V(r, h, 0)),
        Part.makeCircle(r, V(r, h - r, 0), z, 90, 180),
        Part.makeLine(V(0, h - r, 0), V(0, r, 0)),
        Part.makeCircle(r, V(r, r, 0), z, 180, 270),
    ]
    return Part.Face(Part.Wire(edges))


def _mirror(half):
    """Close a right-hand half outline (u >= 0) into a symmetric polygon."""
    return half + [(-u, v) for u, v in reversed(half)]


def slot_outline(d, style):
    """Slot polygon in local (u, v): u across the slot, v into the profile."""
    w = d["slot_opening"] / 2
    t = d["lip"]
    hw = d["head_width"] / 2
    depth = d["slot_depth"]
    b = d["bottom_width"] / 2
    straight = t + d["head_straight"]
    if style == "V-slot":
        # 45 degree V at the opening; the lip underside slopes down to the
        # head so the webs keep the same thickness as the T-slot variant.
        c = d["v_chamfer"]
        half = [
            (w + c + OVERSHOOT, -OVERSHOOT),
            (w, c),
            (w, t),
            (hw, straight),
            (b, depth),
        ]
    else:
        half = [
            (w, -OVERSHOOT),
            (w, t),
            (hw, t),
            (hw, straight),
            (b, depth),
        ]
    return _mirror(half)


def cavity_outline(d):
    """Hollow chamber where two cells meet: two slot heads back to back, no opening."""
    hw = d["head_width"] / 2
    straight = d["lip"] + d["head_straight"]
    depth = d["slot_depth"]
    b = d["bottom_width"] / 2
    half = [(b, -depth), (hw, -straight), (hw, straight), (b, depth)]
    return _mirror(half)


def make_section(d, cols=1, rows=1, style="T-slot", closed=(), center_bore=True,
                 corner_holes=None, anchor="Center"):
    """Return the profile cross-section as a Part.Face in the XY plane.

    ``closed`` is an iterable of face names from ``profiles.FACES`` that get
    no slots. ``corner_holes`` defaults to "on when the series has them".
    ``anchor`` (see ``profiles.ANCHORS``) is the point placed on the origin.
    """
    problems = profiles.validate(d, style)
    if problems:
        raise ValueError("Invalid profile dimensions: " + "; ".join(problems))
    if cols < 1 or rows < 1:
        raise ValueError("Columns and rows must be at least 1")

    s = d["cell"]
    width, height = cols * s, rows * s
    closed = set(closed)
    if corner_holes is None:
        corner_holes = d.get("corner_hole", 0) > 0

    outer = _rounded_rect(width, height, d["corner_radius"])
    tools = []

    slot = slot_outline(d, style)
    for i in range(cols):
        cx = (i + 0.5) * s
        if "Bottom" not in closed:
            tools.append(_face([(cx + u, v) for u, v in slot]))
        if "Top" not in closed:
            tools.append(_face([(cx + u, height - v) for u, v in slot]))
    for j in range(rows):
        cy = (j + 0.5) * s
        if "Left" not in closed:
            tools.append(_face([(v, cy + u) for u, v in slot]))
        if "Right" not in closed:
            tools.append(_face([(width - v, cy + u) for u, v in slot]))

    # Chambers along the shared edges between neighbouring cells.
    cavity = cavity_outline(d)
    for i in range(1, cols):
        for j in range(rows):
            x, cy = i * s, (j + 0.5) * s
            tools.append(_face([(x + v, cy + u) for u, v in cavity]))
    for j in range(1, rows):
        for i in range(cols):
            cx, y = (i + 0.5) * s, j * s
            tools.append(_face([(cx + u, y + v) for u, v in cavity]))

    bore = d["center_bore"]
    if center_bore and bore > 0:
        for i in range(cols):
            for j in range(rows):
                tools.append(_circle((i + 0.5) * s, (j + 0.5) * s, bore))
        # Where four cells meet there is a bore as well.
        for i in range(1, cols):
            for j in range(1, rows):
                tools.append(_circle(i * s, j * s, bore))

    hole = d.get("corner_hole", 0)
    if corner_holes and hole > 0:
        off = (s - d["head_width"]) / 4
        interior = {(i, j) for i in range(1, cols) for j in range(1, rows)}
        for i in range(cols):
            for j in range(rows):
                for ci, cj, sx, sy in ((i, j, 1, 1), (i + 1, j, -1, 1),
                                       (i, j + 1, 1, -1), (i + 1, j + 1, -1, -1)):
                    if (ci, cj) not in interior:
                        tools.append(_circle(ci * s + sx * off, cj * s + sy * off, hole))

    section = outer.cut(tools) if tools else outer
    faces = section.Faces
    if len(faces) != 1:
        raise ValueError(f"Profile section fell apart into {len(faces)} pieces; check the dimensions")
    face = faces[0]
    face.translate(V(-width / 2, -height / 2, 0) + anchor_offset(anchor, width, height))
    return face


def make_solid(face, length, miter_start=0.0, miter_end=0.0, miter_across="X", pivot=V(0, 0, 0)):
    """Extrude a section along +Z, optionally with mitred ends.

    ``length`` is measured along the profile axis: the line parallel to Z
    through ``pivot`` (the section centre). A positive miter angle makes the
    +X (or +Y) side of the profile the long side, so equal positive angles at
    both ends give a picture-frame member. ``miter_across`` is "X" or "Y", or a
    (start, end) pair when the two ends slope across different axes.
    """
    if length <= 0:
        raise ValueError("Profile length must be positive")
    for a in (miter_start, miter_end):
        if abs(a) >= 80:
            raise ValueError("Miter angles must be between -80 and 80 degrees")

    if not (miter_start or miter_end):
        return face.extrude(V(0, 0, length))

    bb = face.BoundBox
    px, py = pivot.x, pivot.y
    reach = max(abs(bb.XMin - px), abs(bb.XMax - px), abs(bb.YMin - py), abs(bb.YMax - py))
    margin = reach * max(math.tan(math.radians(abs(a))) for a in (miter_start, miter_end)) + 1
    base = face.copy()
    base.translate(V(0, 0, -margin))
    solid = base.extrude(V(0, 0, length + 2 * margin))

    if isinstance(miter_across, str):
        miter_across = (miter_across, miter_across)

    def rotation(across):
        # Rotating about Y tilts the cut across X, rotating about X tilts it across Y.
        return (V(0, 1, 0), 1) if across == "X" else (V(1, 0, 0), -1)

    big = 4 * (reach + margin) + length
    start = Part.makeBox(big, big, big, V(px - big / 2, py - big / 2, -big))
    axis, sign = rotation(miter_across[0])
    start.rotate(V(px, py, 0), axis, sign * miter_start)
    end = Part.makeBox(big, big, big, V(px - big / 2, py - big / 2, length))
    axis, sign = rotation(miter_across[1])
    end.rotate(V(px, py, length), axis, -sign * miter_end)
    solid = solid.cut([start, end])
    solids = solid.Solids
    if len(solids) != 1:
        raise ValueError("Miter cuts leave no single solid; reduce the angles or increase the length")
    return solids[0]


def anchor_offset(anchor, width, height):
    """Where the section centre ends up for the given anchor."""
    if anchor == "Bottom left":
        return V(width / 2, height / 2, 0)
    if anchor == "Bottom center":
        return V(0, height / 2, 0)
    return V(0, 0, 0)


def make_profile(d, cols=1, rows=1, length=1000.0, style="T-slot", closed=(),
                 center_bore=True, corner_holes=None, miter_start=0.0, miter_end=0.0,
                 miter_across="X", anchor="Center"):
    """Convenience wrapper: section + extrusion in one call."""
    face = make_section(d, cols, rows, style, closed, center_bore, corner_holes, anchor)
    pivot = anchor_offset(anchor, cols * d["cell"], rows * d["cell"])
    return make_solid(face, length, miter_start, miter_end, miter_across, pivot)
