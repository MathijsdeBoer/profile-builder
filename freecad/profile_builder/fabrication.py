"""Flat sheet parts: rounded outlines, holes along slot lines, DXF and SVG files. Pure Python.

Everything works in the panel's own 2D coordinates, in mm. An outline is a
list of segments, each ("line", p, q) or ("arc", centre, radius, p, q, ccw),
where p and q are the start and end point and ``ccw`` says whether the arc
turns counter-clockwise from p to q.
"""

import math
import unicodedata

TINY = 1e-6


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n)


def signed_area(points):
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))


def rounded_outline(corners, radius):
    """(segments, radius used) for a polygon with every corner rounded.

    The radius is reduced where an edge is too short for two roundings, and
    the smallest radius that fits is returned so callers can report it.
    """
    pts = list(corners)
    if radius <= TINY:
        return [("line", p, q) for p, q in zip(pts, pts[1:] + pts[:1])], 0.0
    count = len(pts)
    fits = radius
    tangents = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % count]
        u, v = _unit(_sub(a, p)), _unit(_sub(b, p))
        half = math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))) / 2
        tangents.append((u, v, half))
        # Each neighbouring edge may give at most half its length to this corner.
        limit = min(_dist(a, p), _dist(b, p)) / 2 * math.tan(half)
        fits = min(fits, limit)
    segments = []
    arcs = []
    for p, (u, v, half) in zip(pts, tangents):
        t = fits / math.tan(half)
        t1 = (p[0] + u[0] * t, p[1] + u[1] * t)
        t2 = (p[0] + v[0] * t, p[1] + v[1] * t)
        bis = _unit((u[0] + v[0], u[1] + v[1]))
        centre = (p[0] + bis[0] * fits / math.sin(half), p[1] + bis[1] * fits / math.sin(half))
        # Turning left at this corner (a convex corner of a counter-clockwise outline) is a ccw arc.
        ccw = (-u[0]) * v[1] - (-u[1]) * v[0] > 0
        arcs.append((t1, t2, centre, ccw))
    for i, (t1, t2, centre, ccw) in enumerate(arcs):
        segments.append(("arc", centre, fits, t1, t2, ccw))
        start = t2
        end = arcs[(i + 1) % count][0]
        if _dist(start, end) > TINY:
            segments.append(("line", start, end))
    return segments, fits


def clip_to_polygon(p, q, polygon, inset):
    """The part of segment p-q at least ``inset`` inside a convex polygon, or None."""
    ccw = signed_area(polygon) > 0
    t0, t1 = 0.0, 1.0
    d = _sub(q, p)
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        e = _unit(_sub(b, a))
        inward = (-e[1], e[0]) if ccw else (e[1], -e[0])
        # Keep the points x with (x - a) . inward >= inset.
        start = (p[0] - a[0]) * inward[0] + (p[1] - a[1]) * inward[1] - inset
        rate = d[0] * inward[0] + d[1] * inward[1]
        if abs(rate) < TINY:
            if start < -TINY:
                return None
            continue
        t = -start / rate
        if rate > 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    if t1 - t0 <= TINY:
        return None
    return (p[0] + d[0] * t0, p[1] + d[1] * t0), (p[0] + d[0] * t1, p[1] + d[1] * t1)


def remove_circles(p, q, centres, radius):
    """Pieces of segment p-q that lie outside all circles of ``radius`` around ``centres``."""
    length = _dist(p, q)
    if length <= TINY:
        return []
    d = ((q[0] - p[0]) / length, (q[1] - p[1]) / length)
    cut = []
    for c in centres:
        along = (c[0] - p[0]) * d[0] + (c[1] - p[1]) * d[1]
        off = abs((c[0] - p[0]) * d[1] - (c[1] - p[1]) * d[0])
        if off < radius:
            half = math.sqrt(radius * radius - off * off)
            cut.append((along - half, along + half))
    pieces, pos = [], 0.0
    for a, b in sorted(cut):
        if a > pos:
            pieces.append((pos, min(a, length)))
        pos = max(pos, b)
        if pos >= length:
            break
    if pos < length:
        pieces.append((pos, length))
    point = lambda s: (p[0] + d[0] * s, p[1] + d[1] * s)  # noqa: E731
    return [(point(a), point(b)) for a, b in pieces if b - a > TINY]


def spaced(p, q, spacing, min_length):
    """Hole centres from p to q, evenly spaced and at most ``spacing`` apart.

    A piece shorter than ``min_length`` gets one hole in the middle.
    """
    length = _dist(p, q)
    if length < min_length:
        return [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)]
    gaps = max(1, math.ceil(length / spacing - 1e-9)) if spacing > TINY else 1
    return [(p[0] + (q[0] - p[0]) * k / gaps, p[1] + (q[1] - p[1]) * k / gaps) for k in range(gaps + 1)]


def hole_layout(lines, polygon, diameter, spacing, edge_distance, keepouts, keepout_radius):
    """(hole centres, notes) for holes along lines inside a convex sheet outline.

    ``lines`` is [(name, p, q)]: the slot centre lines under the sheet. Each is
    clipped to the outline shrunk by ``edge_distance`` and interrupted around
    ``keepouts`` (corners and joints, where brackets sit). Holes closer than
    two diameters to one already placed are dropped, so crossing lines do not
    give double holes.
    """
    holes, notes = [], []
    for name, p, q in lines:
        clipped = clip_to_polygon(p, q, polygon, edge_distance)
        if clipped is None:
            gap = min(_line_distance(p, q, a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1]))
            notes.append(f"no holes along {name}: its slot is {gap:.1f} mm from the sheet edge, "
                         f"closer than the edge distance ({edge_distance:g} mm)")
            continue
        for a, b in remove_circles(*clipped, keepouts, keepout_radius):
            for h in spaced(a, b, spacing, 2 * diameter):
                if all(_dist(h, o) >= 2 * diameter for o in holes):
                    holes.append(h)
    return holes, notes


def _line_distance(p, q, a, b):
    """Distance from the middle of p-q to the line through a and b."""
    m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    e = _unit(_sub(b, a))
    return abs((m[0] - a[0]) * e[1] - (m[1] - a[1]) * e[0])


def outline_points(segments):
    return [s[1] if s[0] == "line" else s[3] for s in segments]


def bounds(segments, holes=(), radius=0.0):
    """(xmin, ymin, xmax, ymax) of the outline, its arcs and the holes."""
    xs, ys = [], []
    for s in segments:
        if s[0] == "line":
            xs += [s[1][0], s[2][0]]
            ys += [s[1][1], s[2][1]]
        else:
            for x, y in _arc_points(s, 16):
                xs.append(x)
                ys.append(y)
    for x, y in holes:
        xs += [x - radius, x + radius]
        ys += [y - radius, y + radius]
    return min(xs), min(ys), max(xs), max(ys)


def _arc_angles(seg):
    """(start, end) in degrees, counter-clockwise from start to end, as DXF wants them."""
    _kind, c, _r, p, q, ccw = seg
    a = math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360
    b = math.degrees(math.atan2(q[1] - c[1], q[0] - c[0])) % 360
    return (a, b) if ccw else (b, a)


def arc_midpoint(seg):
    """The point halfway along an arc segment, from its start to its end."""
    _kind, c, r, p, q, ccw = seg
    a = math.atan2(p[1] - c[1], p[0] - c[0])
    b = math.atan2(q[1] - c[1], q[0] - c[0])
    sweep = (b - a) % (2 * math.pi) if ccw else -((a - b) % (2 * math.pi))
    return (c[0] + r * math.cos(a + sweep / 2), c[1] + r * math.sin(a + sweep / 2))


def _arc_points(seg, count):
    _kind, c, r, _p, _q, _ccw = seg
    a, b = _arc_angles(seg)
    sweep = (b - a) % 360 or 360
    return [(c[0] + r * math.cos(math.radians(a + sweep * k / count)),
             c[1] + r * math.sin(math.radians(a + sweep * k / count))) for k in range(count + 1)]


def fingerprint(segments, holes, diameter, loops=()):
    """A key that is the same for sheets that are the same part, turned or flipped over.

    Built from the outline, the holes and the cutout loops (lists of points),
    rounded to 0.1 mm, in the orientation that sorts first.
    """
    groups = [outline_points(segments) + [s[1] for s in segments if s[0] == "arc"], list(holes)]
    groups += [list(loop) for loop in loops]
    variants = []
    for sx, sy, swap in [(a, b, c) for a in (1, -1) for b in (1, -1) for c in (False, True)]:
        moved = [[((y if swap else x) * sx, (x if swap else y) * sy) for x, y in g] for g in groups]
        flat = [pt for g in moved for pt in g] or [(0, 0)]
        x0, y0 = min(x for x, _y in flat), min(y for _x, y in flat)
        variants.append(tuple(tuple(sorted((round(x - x0, 1) + 0.0, round(y - y0, 1) + 0.0) for x, y in g))
                              for g in moved))
    return (round(diameter, 2), min(variants))


def _ascii(text):
    """DXF R12 files are not Unicode: 'Ø' and '°' would come out garbled."""
    text = text.replace("Ø", "D").replace("°", " deg").replace("×", "x").replace("²", "2")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _num(value):
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def dxf_text(segments, holes, diameter, cutouts=(), texts=(), scale=1.0):
    """A DXF R12 drawing: the outline and cutouts on layer CUT, holes on HOLES, text on MARK.

    ``cutouts`` is a list of segment lists (lines, arcs, or ("circle", centre,
    radius)). ``texts`` is [(x, y, height, text)]. ``scale`` converts mm to the
    unit of the file (1/25.4 for inches); DXF R12 cannot say which unit it uses.
    """
    out = []

    def g(code, value):
        out.append(f"{code:>3}\n{value}")

    def xy(p, first=10):
        # The part's lower left corner goes to the origin, where cutting software expects it.
        g(first, _num((p[0] - xmin) * scale))
        g(first + 10, _num((p[1] - ymin) * scale))
        g(first + 20, "0.0")

    def entity(seg, layer):
        if seg[0] == "line":
            g(0, "LINE")
            g(8, layer)
            xy(seg[1])
            xy(seg[2], 11)
        elif seg[0] == "arc":
            a, b = _arc_angles(seg)
            g(0, "ARC")
            g(8, layer)
            xy(seg[1])
            g(40, _num(seg[2] * scale))
            g(50, _num(a))
            g(51, _num(b))
        else:  # circle
            g(0, "CIRCLE")
            g(8, layer)
            xy(seg[1])
            g(40, _num(seg[2] * scale))

    xmin, ymin, xmax, ymax = bounds(segments, holes, diameter / 2)
    for code, value in ((0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1009"), (9, "$EXTMIN")):
        g(code, value)
    xy((xmin, ymin))
    g(9, "$EXTMAX")
    xy((xmax, ymax))
    g(0, "ENDSEC")
    for code, value in ((0, "SECTION"), (2, "TABLES"), (0, "TABLE"), (2, "LTYPE"), (70, 1), (0, "LTYPE"),
                        (2, "CONTINUOUS"), (70, 0), (3, "Solid line"), (72, 65), (73, 0), (40, "0.0"),
                        (0, "ENDTAB"), (0, "TABLE"), (2, "LAYER"), (70, 3)):
        g(code, value)
    for name, colour in (("CUT", 7), ("HOLES", 1), ("MARK", 3)):
        for code, value in ((0, "LAYER"), (2, name), (70, 0), (62, colour), (6, "CONTINUOUS")):
            g(code, value)
    for code, value in ((0, "ENDTAB"), (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES")):
        g(code, value)
    for seg in segments:
        entity(seg, "CUT")
    for loop in cutouts:
        for seg in loop:
            entity(seg, "CUT")
    for h in holes:
        entity(("circle", h, diameter / 2), "HOLES")
    for x, y, height, text in texts:
        g(0, "TEXT")
        g(8, "MARK")
        xy((x, y))
        g(40, _num(height * scale))
        g(1, _ascii(text))
    g(0, "ENDSEC")
    g(0, "EOF")
    return "\n".join(out) + "\n"


def svg_text(segments, holes, diameter, cutouts=(), texts=(), scale=1.0, unit="mm"):
    """An SVG drawing at true size (width and height carry the unit), for preview or cutting.

    Same arguments as dxf_text. The outline and cutouts are black, holes red,
    text green.
    """
    xmin, ymin, xmax, ymax = bounds(segments, holes, diameter / 2)
    pad = 2.0
    width, height = (xmax - xmin + 2 * pad) * scale, (ymax - ymin + 2 * pad) * scale

    def pt(p):
        # SVG's y axis points down.
        return f"{_num((p[0] - xmin + pad) * scale)},{_num((ymax - p[1] + pad) * scale)}"

    def path(loop):
        parts, at = [], None
        for seg in loop:
            if seg[0] == "circle":
                continue
            start = seg[1] if seg[0] == "line" else seg[3]
            if at is None or _dist(at, start) > 1e-6:
                # Sketch edges need not run head to tail, so start a new piece.
                parts.append(f"M {pt(start)}")
            at = seg[2] if seg[0] == "line" else seg[4]
            if seg[0] == "line":
                parts.append(f"L {pt(seg[2])}")
            else:
                r = _num(seg[2] * scale)
                sweep = (_arc_angles(seg)[1] - _arc_angles(seg)[0]) % 360
                large = 1 if sweep > 180 else 0
                parts.append(f"A {r} {r} 0 {large} {0 if seg[5] else 1} {pt(seg[4])}")
        return " ".join(parts)

    def circle(c, r, colour):
        x, y = pt(c).split(",")
        return f'<circle cx="{x}" cy="{y}" r="{_num(r * scale)}" stroke="{colour}"/>'

    stroke = _num(0.2 * scale)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(width)}{unit}" height="{_num(height)}{unit}" '
             f'viewBox="0 0 {_num(width)} {_num(height)}">',
             f'<g fill="none" stroke="#000" stroke-width="{stroke}">',
             f'<path d="{path(segments)}"/>']
    for loop in cutouts:
        lines += [circle(s[1], s[2], "#000") for s in loop if s[0] == "circle"]
        if any(s[0] != "circle" for s in loop):
            lines.append(f'<path d="{path(loop)}"/>')
    lines += [circle(h, diameter / 2, "#d00") for h in holes]
    lines.append("</g>")
    for x, y, size, text in texts:
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f'<text x="{pt((x, y)).split(",")[0]}" y="{pt((x, y)).split(",")[1]}" '
                     f'font-size="{_num(size * scale)}" font-family="sans-serif" fill="#080">{esc}</text>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"
