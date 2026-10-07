"""Sheet panels filling an opening between profiles (enclosure sides, etc.)."""

import html
import math
import os
import re

import FreeCAD as App
import Part

from . import fabrication, feature

V = App.Vector

MOUNTS = ("In slot", "On face")
SIDES = ("Front", "Back")

# Sheet materials: density in g/cm^3 and thermal expansion in 1e-6/K (µm per m
# per kelvin). Typical values; grades differ, so the fit check is a rule of thumb.
MATERIALS = {
    "Acrylic": (1.19, 70.0),
    "Polycarbonate": (1.20, 65.0),
    "PETG": (1.27, 60.0),
    "Aluminium composite": (1.27, 24.0),
    "Aluminium": (2.70, 23.1),
    "Glass": (2.50, 9.0),
    "Steel": (7.85, 12.0),
    "MDF": (0.75, 10.0),
    "Plywood": (0.60, 7.0),
}
# Trade and short names. They are more specific than the generic names above:
# "Aluminium Dibond" is a composite sheet, not solid aluminium.
MATERIAL_ALIASES = {
    "pmma": "Acrylic", "plexiglas": "Acrylic", "plexiglass": "Acrylic", "perspex": "Acrylic",
    "acrylglas": "Acrylic", "pc": "Polycarbonate", "lexan": "Polycarbonate", "makrolon": "Polycarbonate",
    "dibond": "Aluminium composite", "acm": "Aluminium composite", "alucobond": "Aluminium composite",
    "plexi": "Acrylic",
}
# Phrases that contain another material's name but mean one material.
MATERIAL_PHRASES = {"acrylic glass": "Acrylic", "organic glass": "Acrylic", "plexi glass": "Acrylic",
                    "acryl glass": "Acrylic"}
ALUMINIUM_EXPANSION = 23.1  # the frame


def material_data(name):
    """(density, expansion) for a material name, or None when it is not known.

    Case-insensitive, on whole words anywhere in the name ("Clear acrylic
    3 mm", "Glass, tempered"). Trade names and phrases win ("Aluminium
    Dibond", "acrylic glass"); a longer name beats a shorter one inside it
    ("Aluminium composite" before "Aluminium"). When the name mentions two
    different materials ("glass-clear PETG", "steel grey acrylic") it is
    ambiguous and None is returned, so nothing is guessed. The US spelling
    "aluminum" is accepted.
    """
    words = re.findall(r"[a-z0-9]+", name.lower().replace("aluminum", "aluminium"))
    text = " ".join(words)
    for phrase in sorted(MATERIAL_PHRASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return MATERIALS[MATERIAL_PHRASES[phrase]]
    for word in words:
        if word in MATERIAL_ALIASES:
            return MATERIALS[MATERIAL_ALIASES[word]]
    found = []  # (start, end, material)
    for key in MATERIALS:
        for m in re.finditer(rf"\b{re.escape(key.lower())}\b", text):
            found.append((m.start(), m.end(), key))
    # Drop matches inside a longer one ("aluminium" inside "aluminium composite").
    found = [f for f in found if not any(o[0] <= f[0] and f[1] <= o[1] and o != f for o in found)]
    materials = {key for _start, _end, key in found}
    return MATERIALS[materials.pop()] if len(materials) == 1 else None


def is_panel(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "ProfileBuilder::Panel"


def sheet_key(obj):
    return f"{obj.Material} {obj.Thickness.Value:g} mm"


def _segment(obj, frame):
    """Start and end of the member's section-centre line."""
    edge = feature.path_edge(obj)
    length = edge.Length if edge is not None else obj.Length.Value
    start = frame.origin + frame.center_offset()
    return start, start + frame.z * length


def _face_towards(frame, w):
    """Name of the profile face whose outward normal is w (in local terms)."""
    wx, wy = w.dot(frame.x), w.dot(frame.y)
    if abs(wx) >= abs(wy):
        return "Right" if wx > 0 else "Left"
    return "Top" if wy > 0 else "Bottom"


def _check_slot(obj, frame, face, n, plane_offset, thickness, panel_offset=None):
    """Check that the panel plane, ``plane_offset`` from this member's section centre, hits one of its slots.

    ``panel_offset`` is the panel's own PlaneOffset, the value to suggest when the plane misses.
    """
    if panel_offset is None:
        panel_offset = plane_offset
    if getattr(obj, f"Closed{face}"):
        raise ValueError(f"{obj.Label} has no slot on the face towards the panel ({face})")
    if thickness > obj.SlotOpening.Value - 0.2:
        raise ValueError(f"Panel is too thick for the {obj.SlotOpening.Value:g} mm slot of {obj.Label}")
    # Slots run along the face; find where the panel plane crosses it.
    cell = obj.CellSize.Value
    x0, x1, y0, y1 = frame.rect
    if face in ("Left", "Right"):
        axis, start, count, centre = frame.y, y0, obj.Rows, (y0 + y1) / 2
    else:
        axis, start, count, centre = frame.x, x0, obj.Columns, (x0 + x1) / 2
    position = centre + plane_offset * n.dot(axis)
    slots = [start + (k + 0.5) * cell for k in range(count)]
    nearest = min(slots, key=lambda s: abs(s - position))
    if abs(nearest - position) > 0.5:
        shift = (nearest - position) * n.dot(axis)
        raise ValueError(f"The panel plane misses the slots of {obj.Label}; "
                         f"try PlaneOffset {panel_offset + shift:+g} mm")


def _intersect(p1, d1, p2, d2):
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-9:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
    return (p1[0] + d1[0] * t, p1[1] + d1[1] * t)


class Layout:
    """A panel's plane and outline.

    ``corners`` are 2D points (counter-clockwise) in the in-plane basis
    (e1, e2) from ``origin``; the sheet starts ``lift`` along ``n`` from the
    frame plane. ``inward`` holds, per member, the in-plane direction from the
    member towards the opening.
    """

    def __init__(self, members, frames, n, origin, e1, e2, corners, lift, inward):
        self.members, self.frames, self.n, self.origin = members, frames, n, origin
        self.e1, self.e2, self.corners, self.lift, self.inward = e1, e2, corners, lift, inward

    def to2d(self, p):
        d = p - self.origin
        return (d.dot(self.e1), d.dot(self.e2))

    def to3d(self, u, v, height=0.0):
        return self.origin + self.e1 * u + self.e2 * v + self.n * (self.lift + height)


def layout(obj):
    members = [m for m in obj.Profiles if feature.is_profile(m)]
    if len(members) < 3:
        raise ValueError("A panel needs at least three profiles around the opening")
    frames = [feature.member_frame(m) for m in members]
    segments = [_segment(m, f) for m, f in zip(members, frames)]

    n = None
    for i in range(len(frames)):
        for j in range(i + 1, len(frames)):
            c = frames[i].z.cross(frames[j].z)
            if c.Length > 0.1:
                n = c.normalize()
                break
        if n is not None:
            break
    if n is None:
        raise ValueError("The profiles around a panel cannot all be parallel")
    origin = segments[0][0]
    for m, f, (a, _b) in zip(members, frames, segments):
        # Members of different sizes or with a section offset need not be centred on one plane: the
        # section only has to reach the panel plane (the first member's centre plane).
        reach = f.support(n) - f.center_offset().dot(n)
        if abs(f.z.dot(n)) > 1e-3 or abs((a - origin).dot(n)) > reach + 0.5:
            raise ValueError(f"{m.Label} does not lie in the plane of the panel")

    e1 = frames[0].z
    e2 = n.cross(e1)

    def to2d(p):
        d = p - origin
        return (d.dot(e1), d.dot(e2))

    mids = [(a + b) * 0.5 for a, b in segments]
    centroid = sum(mids, V()) * (1.0 / len(mids))
    lines = []
    inward = []
    for m, f, (a, _b), mid in zip(members, frames, segments, mids):
        # Where the panel plane lies relative to this member's own section centre.
        to_plane = obj.PlaneOffset.Value + (origin - a).dot(n)
        w = n.cross(f.z)
        if (centroid - mid).dot(w) < 0:
            w = -w
        inward.append(w)
        inner = f.support(w) - f.center_offset().dot(w)
        if obj.Mount == "In slot":
            _check_slot(m, f, _face_towards(f, w), n, to_plane, obj.Thickness.Value, obj.PlaneOffset.Value)
            depth = obj.InsertDepth.Value or m.SlotDepth.Value
            offset = inner - depth + obj.Clearance.Value
        else:
            outer = f.support(-w) - f.center_offset().dot(-w)
            offset = -outer + obj.Margin.Value
        p = to2d(a + w * offset)
        d = to2d(origin + f.z)
        c2 = to2d(centroid)
        m2 = to2d(mid)
        lines.append((math.atan2(m2[1] - c2[1], m2[0] - c2[0]), p, d))
    lines.sort(key=lambda line: line[0])

    corners = []
    for (_a1, p1, d1), (_a2, p2, d2) in zip(lines, lines[1:] + lines[:1]):
        point = _intersect(p1, d1, p2, d2)
        if point is None:
            raise ValueError("Neighbouring profiles around the panel are parallel; "
                             "select the profiles that form the outline")
        corners.append(point)
    if fabrication.signed_area(corners) < 0:
        corners.reverse()

    if obj.Mount == "In slot":
        lift = obj.PlaneOffset.Value - obj.Thickness.Value / 2
    else:
        sign = 1 if obj.Side == "Front" else -1
        reach = max(f.support(n * sign) - f.center_offset().dot(n * sign) for f in frames)
        lift = sign * reach + obj.PlaneOffset.Value - (0 if sign > 0 else obj.Thickness.Value)
    return Layout(members, frames, n, origin, e1, e2, corners, lift, inward)


def panel_outline(obj):
    """(polygon points in world space, plane normal, width, height, area)."""
    lay = layout(obj)
    corners = lay.corners
    us = [u for u, _v in corners]
    vs = [v for _u, v in corners]
    area = abs(fabrication.signed_area(corners))
    points = [lay.to3d(u, v) for u, v in corners]
    return points, lay.n, max(us) - min(us), max(vs) - min(vs), area


def slot_lines(obj, lay):
    """([(member label, 2D start, 2D end)] of the slot centre lines under an on-face sheet, notes).

    Each line runs where the member's face beside that slot really exists, so
    after joint trims and, on a mitered end, only up to the miter cut. On a
    face with several slots (a 2040 lying flat), SlotChoice picks the outer
    one, the inner one or all.
    """
    sign = 1 if obj.Side == "Front" else -1
    lines, notes = [], []
    for m, f, w in zip(lay.members, lay.frames, lay.inward):
        face = _face_towards(f, lay.n * sign)
        if getattr(m, f"Closed{face}"):
            notes.append(f"no holes along {m.Label}: the face under the sheet has no slot")
            continue
        x0, x1, y0, y1 = f.rect
        cell = m.CellSize.Value
        if face in ("Left", "Right"):
            normal = f.x if face == "Right" else -f.x
            across, fixed = f.y, f.x * (x1 if face == "Right" else x0)
            slots = [y0 + (k + 0.5) * cell for k in range(m.Rows)]
        else:
            normal = f.y if face == "Top" else -f.y
            across, fixed = f.x, f.y * (y1 if face == "Top" else y0)
            slots = [x0 + (k + 0.5) * cell for k in range(m.Columns)]
        if len(slots) > 1 and obj.SlotChoice != "All":
            towards_opening = lambda s: (across * s).dot(w)  # noqa: E731
            slots = [(max if obj.SlotChoice == "Inner" else min)(slots, key=towards_opening)]
        start = (m.Placement.Base - f.origin).dot(f.z)  # 0 unless the profile follows a path edge
        for s in slots:
            base = f.origin + fixed + across * s
            t0, t1 = _face_extent(m, f, base, normal, across, start, m.Length.Value)
            lines.append((m.Label, lay.to2d(base + f.z * t0), lay.to2d(base + f.z * t1)))
    return lines, notes


def _face_extent(m, f, base, normal, across, start, length):
    """(start, end) along the profile axis where the face beside a slot has material.

    Probes both lips beside the slot, just under the face, against the real
    solid, so a miter that cuts the slot short (the inner slot of a wide flat
    profile) is taken into account.
    """
    reach = m.SlotOpening.Value / 2 + 0.3
    lo, hi = start, start + length
    found = None
    for side in (1, -1):
        p = base + across * (side * reach) - normal * 0.3
        probe = Part.makeLine(p + f.z * (start - length), p + f.z * (start + 2 * length))
        ts = [(v.Point - f.origin).dot(f.z) for v in m.Shape.common(probe).Vertexes]
        if not ts:
            continue
        span = (min(ts), max(ts))
        found = span if found is None else (max(found[0], span[0]), min(found[1], span[1]))
    if found is None or found[1] <= found[0]:
        return lo, hi
    return found


def _joint_points(obj, lay):
    """The joints of the panel's own profiles: brackets sit there, so holes keep away."""
    from .joints import is_joint
    names = {m.Name for m in lay.members}
    found = {}
    for m in lay.members:
        for joint in (m.StartJoint, m.EndJoint):
            if joint is not None:
                found[joint.Name] = joint
    for other in obj.Document.Objects:
        if is_joint(other) and names & set(other.PassingMembers):
            found[other.Name] = other  # a T-junction on one of the panel's profiles
    return [lay.to2d(j.Shape.Vertexes[0].Point) for j in found.values() if j.Shape.Vertexes]


class Drawing:
    """The flat part: outline segments, holes and cutouts in the panel's 2D coordinates."""

    def __init__(self, segments, corners, radius, holes, diameter, cutouts, notes):
        self.segments, self.corners, self.radius = segments, corners, radius
        self.holes, self.diameter, self.cutouts, self.notes = holes, diameter, cutouts, notes

    def fingerprint(self):
        """Points that pin down the whole part: a circle's radius, not just its centre, must count."""
        def points(s):
            if s[0] == "line":
                return [s[1], s[2]]
            if s[0] == "arc":
                return [s[1], s[3], s[4]]
            (cx, cy), r = s[1], s[2]  # circle: its four quadrant points survive turning and flipping
            return [(cx + r, cy), (cx - r, cy), (cx, cy + r), (cx, cy - r)]
        loops = [[p for s in loop for p in points(s)] for loop in self.cutouts]
        # A diameter without holes (an in-slot panel, or every hole left out) is not part of the part.
        return fabrication.fingerprint(self.segments, self.holes, self.diameter if self.holes else 0.0, loops)

    def centre(self):
        us = [u for u, _v in self.corners]
        vs = [v for _u, v in self.corners]
        return ((min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2)


def _cutout_segments(edge, lay):
    """An edge of a cutout sketch as 2D segments."""
    kind = edge.Curve.TypeId
    if kind == "Part::GeomLine":
        return [("line", lay.to2d(edge.Vertexes[0].Point), lay.to2d(edge.Vertexes[-1].Point))]
    if kind == "Part::GeomCircle":
        centre, radius = lay.to2d(edge.Curve.Center), edge.Curve.Radius
        if edge.isClosed():
            return [("circle", centre, radius)]
        p = lay.to2d(edge.valueAt(edge.FirstParameter))
        q = lay.to2d(edge.valueAt(edge.LastParameter))
        m = lay.to2d(edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2))
        ccw = (p[0] - centre[0]) * (m[1] - centre[1]) - (p[1] - centre[1]) * (m[0] - centre[0]) > 0
        return [("arc", centre, radius, p, q, ccw)]
    points = [lay.to2d(p) for p in edge.discretize(Deflection=0.02)]
    return [("line", a, b) for a, b in zip(points, points[1:])]


def _cutout_wires(obj, lay):
    """Closed wires of the Cutouts sketch in world space, after checking it lies parallel to the sheet."""
    sketch = getattr(obj, "Cutouts", None)
    if sketch is None:
        return []
    # The sketch may sit in a Body or a Part with its own placement.
    shape = sketch.Shape.copy()
    shape.Placement = sketch.getGlobalPlacement()
    if not shape.Edges:
        return []  # an empty sketch, or only construction geometry
    heights = [(p - lay.origin).dot(lay.n) for e in shape.Edges for p in e.discretize(5)]
    if max(heights) - min(heights) > 0.01:
        raise ValueError(f"The cutout sketch {sketch.Label} must lie parallel to the panel")
    wires = [w for w in shape.Wires if w.isClosed()]
    if len(wires) < len(shape.Wires):
        raise ValueError(f"The cutout sketch {sketch.Label} has an open outline; close every cutout")
    return wires


def drawing(obj, lay=None):
    """The flat part of a panel (see Drawing)."""
    lay = lay or layout(obj)
    notes = []
    segments, radius = fabrication.rounded_outline(lay.corners, obj.CornerRadius.Value)
    if obj.CornerRadius.Value > 0 and radius < obj.CornerRadius.Value - 1e-6:
        notes.append(f"corner radius reduced to {radius:.1f} mm to fit the shortest edge")
    wires = _cutout_wires(obj, lay)
    holes, diameter = [], obj.HoleDiameter.Value
    if diameter > 0 and obj.Mount == "On face":
        lines, line_notes = slot_lines(obj, lay)
        keepouts = list(lay.corners) + _joint_points(obj, lay)
        loops = [[lay.to2d(p) for p in wire.discretize(Deflection=0.05)] for wire in wires]
        # Clip to the rounded outline, not the sharp corners, and keep holes out of the cutouts.
        holes, hole_notes = fabrication.hole_layout(lines, fabrication.polygon_of(segments), diameter,
                                                    obj.HoleSpacing.Value, max(obj.EdgeDistance.Value, diameter / 2),
                                                    keepouts, obj.CornerKeepout.Value, loops)
        notes += line_notes + hole_notes
    elif diameter > 0:
        notes.append("holes are only placed on panels mounted on the face")
    cutouts = [[seg for edge in wire.Edges for seg in _cutout_segments(edge, lay)] for wire in wires]
    return Drawing(segments, lay.corners, radius, holes, diameter, cutouts, notes)


def _sheet_face(lay, d):
    """The sheet's outline as a planar face in world space."""
    P = lambda p: lay.to3d(*p)  # noqa: E731
    if d.radius <= 0:
        points = [P(p) for p in d.corners]
        return Part.Face(Part.makePolygon(points + [points[0]]))
    edges = []
    for s in d.segments:
        if s[0] == "line":
            edges.append(Part.LineSegment(P(s[1]), P(s[2])).toShape())
        else:
            edges.append(Part.Arc(P(s[3]), P(fabrication.arc_midpoint(s)), P(s[4])).toShape())
    return Part.Face(Part.Wire(edges))


SLOT_CHOICES = ("Outer", "Inner", "All")


class Panel:
    Type = "ProfileBuilder::Panel"

    def __init__(self, obj):
        obj.Proxy = self
        self._restoring = False
        self.add_properties(obj)

    def add_properties(self, obj):
        def add(kind, name, group, tip, value=None, mode=None):
            if name in obj.PropertiesList:
                return
            obj.addProperty(kind, name, group, tip)
            if value is not None:
                setattr(obj, name, value)
            if mode is not None:
                obj.setEditorMode(name, mode)

        restoring = getattr(self, "_restoring", False)
        add("App::PropertyLinkList", "Profiles", "Panel", "Profiles around the opening")
        add("App::PropertyEnumeration", "Mount", "Panel",
            "In slot: the sheet edges sit in the slots. On face: the sheet covers the frame.", list(MOUNTS))
        add("App::PropertyLength", "Thickness", "Panel", "Sheet thickness", 3.0)
        add("App::PropertyLength", "Clearance", "Panel", "Gap left at the bottom of each slot", 0.5)
        add("App::PropertyLength", "InsertDepth", "Panel",
            "How far the sheet goes into the slots from the profile face (0: the slot depth)", 0.0)
        add("App::PropertyLength", "Margin", "Panel", "Inset from the outer frame edge (on face)", 0.0)
        add("App::PropertyEnumeration", "Side", "Panel", "Which side of the frame (on face)", list(SIDES))
        add("App::PropertyDistance", "PlaneOffset", "Panel", "Shift of the sheet along its normal", 0.0)
        add("App::PropertyString", "Material", "Panel", "Sheet material, used for pricing", "Acrylic")
        add("App::PropertyFloat", "Density", "Panel",
            "Material density in g/cm^3 (set from the material when it is a known one)", 1.19)
        # An unknown material gets 0, meaning "not known": the thermal check then
        # asks for a value instead of assuming acrylic.
        known = material_data(obj.Material) or (None, 0.0)
        add("App::PropertyFloat", "Expansion", "Fit",
            "Thermal expansion of the sheet in 1e-6/K, set from the material when it is a known one "
            "(0: not known, no thermal check)", known[1])
        add("App::PropertyFloat", "AssemblyTemperature", "Fit", "Temperature when the panel is fitted, in °C", 20.0)
        add("App::PropertyFloat", "MinTemperature", "Fit", "Lowest temperature in use, in °C", 0.0)
        add("App::PropertyFloat", "MaxTemperature", "Fit",
            "Highest temperature in use, in °C (a heated printer enclosure runs at 40-60 °C)", 50.0)
        # Older documents get 0, so their fit results do not change on opening.
        add("App::PropertyLength", "CutTolerance", "Fit",
            "How much the cut sheet may differ from its size, ± (laser or CNC about 0.1-0.2 mm, a saw 0.5-1 mm)",
            0.0 if restoring else 0.2)
        add("App::PropertyLength", "ScrewDiameter", "Fit",
            "Diameter of the screws through the holes, for the play check (0: not checked)", 0.0)
        # Fabrication. The defaults leave existing panels as they were: no holes, square corners.
        add("App::PropertyLength", "HoleDiameter", "Fabrication",
            "Mounting holes on the slot centre lines, on face panels only (0: no holes)", 0.0)
        add("App::PropertyLength", "HoleSpacing", "Fabrication", "Largest distance between two holes", 150.0)
        add("App::PropertyLength", "EdgeDistance", "Fabrication",
            "Smallest distance from a hole centre to the sheet edge", 8.0)
        add("App::PropertyLength", "CornerKeepout", "Fabrication",
            "No holes this close to a corner or a joint, where brackets sit", 25.0)
        add("App::PropertyEnumeration", "SlotChoice", "Fabrication",
            "Which slot gets the holes where a face has several (a 2040 lying flat)", list(SLOT_CHOICES))
        add("App::PropertyLength", "CornerRadius", "Fabrication",
            "Rounded sheet corners (0: square). Rounding keeps acrylic from cracking at the corners", 0.0)
        # A global link, so a sketch inside a Body or a Part can hold the cutouts. Panels saved
        # with the first version had a plain link; it is replaced, keeping the sketch.
        if "Cutouts" in obj.PropertiesList and obj.getTypeIdOfProperty("Cutouts") != "App::PropertyLinkGlobal":
            sketch = obj.Cutouts
            obj.removeProperty("Cutouts")
            add("App::PropertyLinkGlobal", "Cutouts", "Fabrication",
                "Sketch parallel to the sheet whose closed outlines are cut out (fans, cable glands)")
            obj.Cutouts = sketch
        add("App::PropertyLinkGlobal", "Cutouts", "Fabrication",
            "Sketch parallel to the sheet whose closed outlines are cut out (fans, cable glands)")
        add("App::PropertyLength", "Width", "Info", "Sheet size along the first profile", mode=1)
        add("App::PropertyLength", "Height", "Info", "Sheet size across the first profile", mode=1)
        add("App::PropertyArea", "Area", "Info", "Area of the panel outline", mode=1)
        add("App::PropertyFloat", "Mass", "Info", "Mass in kg", mode=1)
        add("App::PropertyInteger", "HoleCount", "Info", "Number of mounting holes", mode=1)
        if "PieceMark" not in obj.PropertiesList:
            add("App::PropertyString", "PieceMark", "Info", "Mark of this sheet in the last cut list", mode=1)
            obj.setPropertyStatus("PieceMark", "Output")  # writing a mark must not trigger a recompute

    def onDocumentRestored(self, obj):
        self._restoring = True
        try:
            self.add_properties(obj)
        finally:
            self._restoring = False

    def onChanged(self, obj, prop):
        if feature.replaying(obj) or getattr(self, "_restoring", False):
            return
        if prop == "Material" and "Expansion" in obj.PropertiesList:
            known = material_data(obj.Material)
            if known is not None:
                obj.Density, obj.Expansion = known
            else:
                # Keep the density (a guess is worse than the last value) but do
                # not keep checking the fit with another material's expansion.
                obj.Expansion = 0.0
        if prop == "Placement":  # also set by each recompute, after the new shape
            from .linear import member_moved  # it may now block a carriage
            member_moved(obj)

    def execute(self, obj):
        lay = layout(obj)
        d = drawing(obj, lay)
        thickness = obj.Thickness.Value
        solid = _sheet_face(lay, d).extrude(lay.n * thickness)
        tools = [Part.makeCylinder(d.diameter / 2, thickness + 2, lay.to3d(u, v, -1), lay.n) for u, v in d.holes]
        for wire in _cutout_wires(obj, lay):
            face = Part.Face(wire)
            height = (wire.Vertexes[0].Point - lay.origin).dot(lay.n)
            face.translate(lay.n * (lay.lift - height - 1))
            tools.append(face.extrude(lay.n * (thickness + 2)))
        if tools:
            solid = solid.cut(Part.makeCompound(tools))
            if not solid.Solids:
                raise ValueError("The cutouts remove the whole sheet (is the frame's own sketch linked as Cutouts?)")
        corners = d.corners
        obj.Width = max(u for u, _v in corners) - min(u for u, _v in corners)
        obj.Height = max(v for _u, v in corners) - min(v for _u, v in corners)
        obj.Area = abs(fabrication.signed_area(corners))
        obj.Mass = round(solid.Volume * obj.Density * 1e-6, 4)
        obj.HoleCount = len(d.holes)
        obj.Shape = solid
        obj.Placement = App.Placement()

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


class ViewProviderPanel:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.ShapeColor = (0.55, 0.75, 0.95)
        vobj.Transparency = 60

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return os.path.join(feature.ICON_DIR, "Panel.svg")

    def claimChildren(self):
        sketch = getattr(self.Object, "Cutouts", None)
        # A sketch inside a Body or Part stays there; claiming it would give it two parents.
        free = sketch is not None and sketch.getParentGeoFeatureGroup() is None
        return [sketch] if free else []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from .simple_panel import PropertyTaskPanel
        Gui.Control.showDialog(PropertyTaskPanel(vobj.Object, PANEL_FIELDS, "Panel", panel_info))
        return True

    def unsetEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        import FreeCADGui as Gui
        Gui.ActiveDocument.setEdit(vobj.Object, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


def relative_change(obj):
    """(largest growth, largest shrinkage) of the sheet against the frame, per mm of sheet.

    Only the difference with aluminium counts: the frame expands too. Both
    are measured from the assembly temperature, so a sheet that expands less
    than aluminium (glass, MDF) shrinks against the frame when it gets hot.
    With an unknown expansion (0) both are 0.
    """
    if obj.Expansion <= 0:
        return 0.0, 0.0
    diff = (obj.Expansion - ALUMINIUM_EXPANSION) * 1e-6
    changes = [diff * (t - obj.AssemblyTemperature) for t in (obj.MinTemperature, obj.MaxTemperature)]
    return max([0.0] + changes), max([0.0] + [-c for c in changes])


def _tolerance(obj):
    return obj.CutTolerance.Value if "CutTolerance" in obj.PropertiesList else 0.0


def thermal_fit(obj):
    """(room needed per side in mm, warning or None) for a sheet in the slots, when it is warmest.

    The sheet may float in its slots, so the growth and the cut tolerance
    together must fit in the gaps at the slot bottoms on both sides. That room
    is the clearance, plus whatever InsertDepth leaves unused of the slot depth.
    """
    if obj.Mount != "In slot":
        return 0.0, None
    size = max(obj.Width.Value, obj.Height.Value)
    growth = relative_change(obj)[0] * size
    tolerance = _tolerance(obj)
    need = growth / 2 + tolerance / 2
    room = slot_room(obj)
    if need <= room + 1e-9:
        return need, None
    return need, (f"{obj.Label}: the sheet needs {need:.2f} mm room per side at the slot bottom but has "
                  f"{room:.2f} mm (it grows {growth:.2f} mm more than the frame over the temperature range, "
                  f"plus the ±{tolerance:g} mm cut tolerance); raise Clearance or reduce InsertDepth")


def cold_fit(obj):
    """Warning or None: does the sheet stay in its slots when it is smallest against the frame?

    That is at the lowest temperature, or at the highest for a sheet that expands
    less than aluminium (glass, MDF, steel). Worst case, the sheet rests against
    the bottom of the opposite slot (a standing panel sits on its lower edge), is
    cut undersize, and has shrunk. What is left in the slot must still reach past
    the slot lips.
    """
    if obj.Mount != "In slot":
        return None
    shrink = relative_change(obj)[1] * max(obj.Width.Value, obj.Height.Value)
    tolerance = _tolerance(obj)
    worst = None
    for m in obj.Profiles:
        if not feature.is_profile(m):
            continue
        depth = obj.InsertDepth.Value or m.SlotDepth.Value
        room = m.SlotDepth.Value - depth + obj.Clearance.Value
        engaged = depth - obj.Clearance.Value - room - shrink - tolerance
        if engaged < m.LipThickness.Value and (worst is None or engaged < worst[0]):
            worst = (engaged, m)
    if worst is None:
        return None
    engaged, m = worst
    return (f"{obj.Label}: at worst the sheet reaches only {max(engaged, 0):.2f} mm into the slot of {m.Label}, "
            f"less than its {m.LipThickness.Value:g} mm lips, and can come out (shrinkage {shrink:.2f} mm, "
            f"cut tolerance ±{tolerance:g} mm); lower Clearance or deepen InsertDepth")


def hole_play(obj, d=None):
    """(play needed around each screw in mm, play there is or None, warning or None), on face panels.

    The sheet is taken as fixed at its centre, so the hole farthest from the
    centre moves most against the frame. Without holes the farthest corner is
    used, as a guide for drilling by hand.
    """
    if obj.Mount != "On face":
        return 0.0, None, None
    d = d or drawing(obj)
    cx, cy = d.centre()
    points = d.holes or d.corners
    reach = max(math.hypot(u - cx, v - cy) for u, v in points)
    need = max(relative_change(obj)) * reach + _tolerance(obj) / 2
    if not d.holes or obj.ScrewDiameter.Value <= 0:
        return need, None, None
    play = (obj.HoleDiameter.Value - obj.ScrewDiameter.Value) / 2
    if play + 1e-9 >= need:
        return need, play, None
    # Round the advice up, so drilling what it says really passes the check.
    drill = math.ceil((obj.ScrewDiameter.Value + 2 * need) * 10 - 1e-9) / 10
    return need, play, (f"{obj.Label}: the outer holes need {need:.2f} mm play around the screws, but "
                        f"Ø{obj.HoleDiameter.Value:g} holes for Ø{obj.ScrewDiameter.Value:g} screws leave "
                        f"{play:.2f} mm; drill at least Ø{drill:.1f}")


def fit_conflict(obj):
    """Warning or None: no Clearance or InsertDepth can pass both the hot and the cold check.

    With e the depth of the sheet edge past the profile face, the hot check needs
    e <= SlotDepth - (growth + tolerance) / 2 and the cold check needs
    e >= (SlotDepth + shrinkage + tolerance + lip) / 2. When the first bound is
    below the second, every setting fails one of them, so the advice of either
    check would only bring back the other.
    """
    if obj.Mount != "In slot":
        return None
    size = max(obj.Width.Value, obj.Height.Value)
    grow, shrink = (rate * size for rate in relative_change(obj))
    tolerance = _tolerance(obj)
    for m in obj.Profiles:
        if not feature.is_profile(m):
            continue
        depth = m.SlotDepth.Value
        highest = depth - (grow + tolerance) / 2
        lowest = (depth + shrink + tolerance + m.LipThickness.Value) / 2
        if highest < lowest:
            return (f"{obj.Label}: no Clearance or InsertDepth keeps this sheet in the slots of {m.Label} over the "
                    f"temperature range (it grows {grow:.2f} mm and shrinks {shrink:.2f} mm against the frame, "
                    f"which needs {2 * (lowest - highest):.2f} mm more slot depth); use deeper slots, a smaller "
                    "or split sheet, a narrower temperature range, or mount it on the face")
    return None


def fit_warnings(obj, d=None):
    """All fit warnings of a panel, for the report."""
    conflict = fit_conflict(obj)
    found = [conflict] if conflict else [thermal_fit(obj)[1], cold_fit(obj)]
    if obj.Mount == "On face":
        found.append(hole_play(obj, d)[2])
    return [w for w in found if w]


def _loose_at(obj):
    """Where the sheet is loosest: the lowest temperature, or the highest for a sheet that
    expands less than aluminium (glass, MDF, steel), or none when only the geometry counts."""
    if relative_change(obj)[1] <= 0:
        return ""
    t = obj.MaxTemperature if obj.Expansion < ALUMINIUM_EXPANSION else obj.MinTemperature
    return f" at {t:g} °C"


def slot_room(obj):
    """Smallest gap between the sheet edge and the slot bottom, over the profiles around it."""
    rooms = [m.SlotDepth.Value - (obj.InsertDepth.Value or m.SlotDepth.Value) + obj.Clearance.Value
             for m in obj.Profiles if feature.is_profile(m)]
    return min(rooms) if rooms else obj.Clearance.Value


def holes_text(obj):
    return f"{obj.HoleCount} × Ø{obj.HoleDiameter.Value:g}" if obj.HoleCount else ""


def panel_info(obj):
    grey = "<br><span style='color:gray'>{}</span>"
    orange = "<br><span style='color:#c60'>{}</span>"
    text = (f"<b>Sheet {obj.Width.Value:.1f} × {obj.Height.Value:.1f} mm</b><br>"
            f"{sheet_key(obj)}, {obj.Area.Value / 1e6:.3f} m², {obj.Mass:.2f} kg")
    try:
        d = drawing(obj)
    except Exception as exc:  # noqa: BLE001  (shown instead of the checks)
        return text + orange.format(html.escape(str(exc)))
    if d.holes:
        text += f"<br>{len(d.holes)} holes Ø{d.diameter:g} on the slot centre lines"
    for note in d.notes:
        text += grey.format(html.escape(note[0].upper() + note[1:]))
    known = obj.Expansion > 0
    if not known:
        text += grey.format("Material not recognised: set Expansion to check the thermal fit")
    # Without a known expansion only the cut tolerance is checked, so name no temperatures.
    range_text = f" between {obj.MinTemperature:g} and {obj.MaxTemperature:g} °C" if known else ""
    what = "Fit" if known else "Cut tolerance fits; thermal fit not checked"
    if obj.Mount == "In slot":
        need, warning = thermal_fit(obj)
        room = slot_room(obj)
        conflict = fit_conflict(obj)
        cold = cold_fit(obj)
        if conflict:
            text += orange.format(html.escape(conflict.split(": ", 1)[1]))
        elif warning:
            text += orange.format(f"Too tight: needs {need:.2f} mm per side at the slot bottom "
                                  f"(has {room:.2f}){range_text}, cut tolerance included")
        else:
            text += f"<br>{what} ({need:.2f} of {room:.2f} mm room per side{range_text})"
        if cold and not conflict:
            text += orange.format(f"Too loose{_loose_at(obj)}: " + html.escape(cold.split(": ", 1)[1]))
        text += grey.format("Slide the sheet in before fitting the last profile around it")
    else:
        need, play, warning = hole_play(obj, d)
        if warning:
            text += orange.format(html.escape(warning.split(": ", 1)[1]))
        elif play is not None:
            label = "Hole play OK" if known else "Hole play covers the cut tolerance; thermal fit not checked"
            text += f"<br>{label}: {need:.2f} mm needed at the outer holes, {play:.2f} mm there"
        else:
            lead = "The outer holes need" if d.holes else "Holes near the corners would need"
            tail = "set ScrewDiameter to check" if d.holes else "set HoleDiameter and ScrewDiameter to check"
            text += grey.format(f"{lead} {need:.2f} mm play around the screws{range_text}; {tail}")
    return text


PANEL_FIELDS = ("Mount", "Thickness", "Material", "Clearance", "InsertDepth", "Margin", "Side",
                "PlaneOffset", "Density", "Expansion", "AssemblyTemperature", "MinTemperature", "MaxTemperature",
                "CutTolerance", "HoleDiameter", "ScrewDiameter", "HoleSpacing", "EdgeDistance", "CornerKeepout",
                "SlotChoice", "CornerRadius")


def make_panel(doc, profiles, cutouts=None, **props):
    obj = doc.addObject("Part::FeaturePython", "Panel")
    Panel(obj)
    obj.Profiles = list(profiles)
    if cutouts is not None:
        obj.Cutouts = cutouts
    for name, value in props.items():
        setattr(obj, name, value)
    if App.GuiUp:
        ViewProviderPanel(obj.ViewObject)
    from .linear import touch_carriages  # a new panel may block a carriage
    touch_carriages(doc)
    return obj


def export_unit():
    """("mm", 1.0) or ("in", 1 / 25.4), following FreeCAD's unit schema."""
    length = App.Units.Quantity("100 mm").getUserPreferred()[2]
    return ("in", 1 / 25.4) if length in ("in", "ft", "'", '"', "thou", "yd", "mi") else ("mm", 1.0)


def _file_part(text):
    """A file name from any text, keeping letters of every script ("Acrylglas_weiß")."""
    return re.sub(r"[^\w.+-]+", "_", text).strip("_")


def export_panels(doc, folder, marks, unit=None):
    """Write a DXF and an SVG file for each different sheet; returns the paths written.

    ``marks`` maps panel names to their marks (Report.marks), so the files match
    the cut list. DXF R12 files have no unit, so the unit is in the file name
    and in the text on layer MARK.
    """
    name, scale = unit or export_unit()
    written, done = [], set()
    for obj in doc.Objects:
        if not is_panel(obj) or not obj.isValid() or obj.Name not in marks or marks[obj.Name] in done:
            continue
        mark = marks[obj.Name]
        done.add(mark)
        d = drawing(obj)
        xmin, ymin, xmax, ymax = fabrication.bounds(d.segments)
        size_text = f"{(xmax - xmin) * scale:.2f} x {(ymax - ymin) * scale:.2f} {name}"
        label = f"{mark}  {sheet_key(obj)}  {size_text}" + (f"  {obj.HoleCount} holes" if d.holes else "")
        # Small enough to fit the sheet, clear of the corner rounding, and above the holes near the lower
        # edge, so a service that engraves layer MARK does not engrave across a hole or off the part.
        size = min(5.0, (ymax - ymin) / 10, (xmax - xmin) / (0.7 * len(label) + 6))
        x0 = xmin + max(3 * size, d.radius)
        y0 = max([ymin + 3 * size] + [v + d.diameter for _u, v in d.holes if v - ymin < 4 * size + d.diameter])
        texts = [(x0, y0, size, label)]
        digits = 0 if name == "mm" else 2
        dims = f"{(xmax - xmin) * scale:.{digits}f}x{(ymax - ymin) * scale:.{digits}f}{name}"
        base = os.path.join(folder, _file_part(f"{mark} {sheet_key(obj)} {dims}"))
        with open(base + ".dxf", "w", encoding="ascii", newline="\r\n") as f:
            f.write(fabrication.dxf_text(d.segments, d.holes, d.diameter, d.cutouts, texts, scale))
        with open(base + ".svg", "w", encoding="utf-8") as f:
            f.write(fabrication.svg_text(d.segments, d.holes, d.diameter, d.cutouts, texts, scale, name))
        written += [base + ".dxf", base + ".svg"]
    return written
