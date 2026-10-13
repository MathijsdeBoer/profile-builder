"""Frame check: one list of the problems that otherwise pass silently.

Each check returns Finding records. Nothing here changes the document,
except apply_fix(), which the Check frame panel calls for the two repairs
that are obvious: deleting a duplicate profile and joining ends that nearly
meet.
"""

from collections import OrderedDict

import FreeCAD as App
import Part

from . import cutlist, feature, geometry, joints, panels, pricing, skeleton

SEVERITIES = ("Error", "Warning", "Info")
CLASH_VOLUME = 1.0  # mm³: less is taken as faces that only touch
SIMILAR_LENGTH = 1.0  # mm: different cut lengths closer than this are probably meant to be equal


class Finding:
    """A problem: severity, text, the names of the objects involved, and an optional fix.

    ``fix`` is ("delete", [names]) or ("join", [names], tolerance), or None.
    """

    def __init__(self, severity, text, objects=(), fix=None):
        self.severity, self.text, self.objects, self.fix = severity, text, list(objects), fix

    def __repr__(self):
        return f"Finding({self.severity}: {self.text})"


def length(value):
    """A distance in the user's unit schema (mm, inches, ...)."""
    return App.Units.Quantity(value, App.Units.Length).UserString


def fine(value, digits=3):
    """A small distance or difference with enough digits to mean something in any unit schema.

    The schema's own format rounds 0.2 mm to "0.00 in", or to "0" in feet and
    inches, so write it in mm or decimal inches with ``digits`` significant digits.
    """
    unit = App.Units.Quantity(100, App.Units.Length).getUserPreferred()[2]
    imperial = unit in ("in", '"', "ft", "'", "thou", "yd", "mi")
    factor, name = (25.4, "in") if imperial else (1.0, "mm")
    text = f"{value / factor:.{digits}g}"
    if "," in App.Units.Quantity(1.5, App.Units.Length).UserString:
        text = text.replace(".", ",")  # the decimal separator the schema uses
    return f"{text} {name}"


def broken(doc):
    """Objects with an error, which the cut list leaves out."""
    found = []
    for obj in doc.Objects:
        if feature.is_profile(obj):
            reason = feature.problem(obj)
        elif panels.is_panel(obj):
            reason = cutlist._panel_problem(obj)
        elif joints.is_joint(obj):
            reason = None if obj.isValid() else cutlist._status(obj)
        elif cutlist.brackets.is_brackets(obj):
            reason = cutlist.brackets.problem(obj)
        else:
            continue
        if reason:
            found.append(Finding("Error", f"{obj.Label}: {reason}", [obj.Name]))
    return found


def _edges(doc):
    """{profile name: path edge} of the profiles on a sketch edge that still exists."""
    result = {}
    for obj in doc.Objects:
        if feature.is_profile(obj) and obj.PathEdge:
            try:
                edge = feature.path_edge(obj)
            except ValueError:
                continue  # reported by broken()
            if edge is not None:
                result[obj.Name] = edge
    return result


def duplicates(doc):
    """Two or more profiles on the same sketch edge: the cut list counts each.

    The fix keeps the copy that panels, carriages or brackets use. When more
    than one copy is in use, deleting any of them would break something, so no
    fix is offered.
    """
    groups = OrderedDict()
    for obj in doc.Objects:
        if feature.is_profile(obj) and obj.PathEdge and obj.PathEdge[1]:
            groups.setdefault((obj.PathEdge[0].Name, obj.PathEdge[1][0]), []).append(obj)
    found = []
    for (source, sub), objs in groups.items():
        if len(objs) < 2:
            continue
        used = [o for o in objs if _dependents(o)]
        objs = used + [o for o in objs if o not in used]
        fix = ("delete", [o.Name for o in objs[1:]]) if len(used) <= 1 else None
        names = ", ".join(o.Label for o in objs)
        found.append(Finding("Warning", f"{len(objs)} profiles on {doc.getObject(source).Label} {sub} "
                             f"({names}); the cut list counts every one", [o.Name for o in objs], fix))
    return found


def _dependents(obj):
    from . import linear
    return [d for d in obj.InList if panels.is_panel(d) or linear.is_carriage(d) or cutlist.brackets.is_brackets(d)]


def unjoined(doc):
    """Profile ends without a joint that meet, or nearly meet, another profile or joint.

    An end near another profile's end is measured to that end, or to its joint
    when it has one, so the fix makes a corner, never a T. Only when no end is
    near does the edge count (a T-junction). Ends that meet exactly are only
    reported when the two really overlap: collinear bars or corners trimmed by
    hand need no joint. Ends a little apart (up to joints.NEAR_MISS) point at a
    sketch vertex that was not snapped; joining them anyway leaves the gap in
    the length. Each group of ends is reported once.
    """
    edges = _edges(doc)
    found, seen = [], set()
    for name, edge in edges.items():
        p = doc.getObject(name)
        for end, point in (("Start", edge.Vertexes[0].Point), ("End", edge.Vertexes[-1].Point)):
            if getattr(p, f"{end}Joint") is not None:
                continue
            target = _nearest(doc, edges, name, point)
            if target is None:
                continue  # a free end, e.g. a leg on the floor
            gap, other, members = target
            key = frozenset(members)
            if key in seen:
                continue
            seen.add(key)
            where = f"the {end.lower()} of {p.Label}"
            if gap < joints.TOLERANCE:
                if not _overlaps(doc, name, members):
                    continue
                found.append(Finding("Warning", f"{where} meets {other.Label} but has no joint, so the two "
                                     "overlap; run Joints", members, ("join", members, joints.TOLERANCE)))
            else:
                found.append(Finding("Warning", f"{where} is {fine(gap)} from {other.Label} and has no joint; "
                                     "snap the sketch vertex, or join anyway (the gap stays in the length)",
                                     members, ("join", members, gap + 0.01)))
    return found


def _nearest(doc, edges, name, point):
    """(gap, what it is near, member names) for a free end, or None when nothing is within NEAR_MISS."""
    ends, tees = [], []
    for other_name, other in edges.items():
        if other_name == name:
            continue
        q = doc.getObject(other_name)
        for end, vertex in (("Start", other.Vertexes[0].Point), ("End", other.Vertexes[-1].Point)):
            if (vertex - point).Length >= joints.NEAR_MISS:
                continue
            joint = getattr(q, f"{end}Joint")
            if joint is not None and joint.Shape.Vertexes:
                gap = (joint.Shape.Vertexes[0].Point - point).Length
                ends.append((gap, joint, [name] + [e[0].Name for e in joints.ends_of(joint)]))
            else:
                ends.append(((vertex - point).Length, q, [name, other_name]))
        gap = other.distToShape(Part.Vertex(point))[0]
        if gap < joints.NEAR_MISS:
            tees.append((gap, q, [name, other_name]))
    for joint in doc.Objects:
        if joints.is_joint(joint) and joint.Shape.Vertexes:
            gap = (joint.Shape.Vertexes[0].Point - point).Length
            if gap < joints.NEAR_MISS:
                ends.append((gap, joint, [name] + [e[0].Name for e in joints.ends_of(joint)]))
    # A nearby end or joint wins over an edge: the fix must make a corner, not a T.
    pool = ends or tees
    if not pool:
        return None
    gap, other, members = min(pool, key=lambda c: c[0])
    return gap, other, list(dict.fromkeys(members))


def _overlaps(doc, name, members):
    mine = _envelope(doc.getObject(name))
    for other in members:
        if other != name and mine.common(_envelope(doc.getObject(other))).Volume > CLASH_VOLUME:
            return True
    return False


def _envelope(obj):
    """The profile's outer box, with its real length and miters, in world space.

    Booleans on the slotted solids are slow and leave slivers where butted
    faces touch; the outer box answers the same question.
    """
    frame = feature.member_frame(obj)
    x0, x1, y0, y1 = frame.rect
    face = Part.Face(Part.makePolygon([App.Vector(x0, y0, 0), App.Vector(x1, y0, 0), App.Vector(x1, y1, 0),
                                       App.Vector(x0, y1, 0), App.Vector(x0, y0, 0)]))
    width, height = obj.Columns * obj.CellSize.Value, obj.Rows * obj.CellSize.Value
    pivot = geometry.anchor_offset(obj.Anchor, width, height) + feature.section_offset(obj)
    across = (obj.MiterStartAxis or obj.MiterAcross, obj.MiterEndAxis or obj.MiterAcross)
    solid = geometry.make_solid(face, obj.Length.Value, obj.MiterStart.Value, obj.MiterEnd.Value, across, pivot)
    return solid.transformed(obj.Placement.toMatrix())


def clashes(doc):
    """Profiles and panels that overlap each other.

    A panel in the slots of its own profiles is left out: the panel check
    already covers that fit.
    """
    items = []
    for obj in doc.Objects:
        if feature.is_profile(obj) and not feature.problem(obj) and obj.Shape.Solids:
            items.append((obj, _envelope(obj)))
        elif panels.is_panel(obj) and not cutlist._panel_problem(obj) and obj.Shape.Solids:
            items.append((obj, obj.Shape))
    found = []
    for i, (a, sa) in enumerate(items):
        box = sa.BoundBox
        for b, sb in items[i + 1:]:
            if not box.intersect(sb.BoundBox):
                continue
            if _own_slot_panel(a, b) or _own_slot_panel(b, a):
                continue
            volume = sa.common(sb).Volume
            if volume > CLASH_VOLUME:
                found.append(Finding("Warning", f"{a.Label} and {b.Label} overlap ({volume:.0f} mm³)",
                                     [a.Name, b.Name]))
    return found


def _own_slot_panel(panel, profile):
    return (panels.is_panel(panel) and feature.is_profile(profile)
            and profile in panel.Profiles and panel.Mount == "In slot")


def panel_fit(doc):
    """The panel fit warnings and drawing notes (holes left out, radius reduced)."""
    found = []
    for obj in doc.Objects:
        if not panels.is_panel(obj) or cutlist._panel_problem(obj):
            continue
        try:
            drawing = panels.drawing(obj)
        except Exception as exc:  # noqa: BLE001
            found.append(Finding("Error", f"{obj.Label}: {exc}", [obj.Name]))
            continue
        found += [Finding("Warning", w, [obj.Name]) for w in panels.fit_warnings(obj, drawing)]
        found += [Finding("Info", f"{obj.Label}: {n}", [obj.Name]) for n in drawing.notes]
    return found


def carriages(doc):
    from .linear import is_carriage
    return [Finding("Warning", f"{obj.Label}: {obj.Warning}", [obj.Name])
            for obj in doc.Objects if is_carriage(obj) and obj.isValid() and obj.Warning]


def long_pieces(doc):
    """Pieces longer than a stock bar, when buying stock bars."""
    s = pricing.settings_values(doc)
    if s["PurchaseMode"] != "Stock bars":
        return []
    found = []
    for (product, _len, saw, _cuts), objs in cutlist.collect(doc).items():
        bar = cutlist._price(s["StockLengths"], objs[0], product) or s["StockLength"]
        usable = bar - s["EndTrim"]
        if saw > usable:
            found.append(Finding("Warning", f"{len(objs)} × {product} at {length(saw)} is longer than a "
                                 f"{length(bar)} bar; order it cut to size or split it", [o.Name for o in objs]))
    return found


def similar_lengths(doc):
    """Pieces of one product whose lengths differ by less than SIMILAR_LENGTH."""
    by_product = OrderedDict()
    for (product, _len, saw, cuts), objs in cutlist.collect(doc).items():
        by_product.setdefault((product, cuts), []).append((saw, objs))
    found = []
    for (product, _cuts), groups in by_product.items():
        groups.sort(key=lambda g: g[0])
        for (a, objs_a), (b, objs_b) in zip(groups, groups[1:]):
            if 0 < b - a < SIMILAR_LENGTH:
                found.append(Finding("Info", f"{product}: {fine(a, 6)} and {fine(b, 6)} pieces differ by "
                                     f"{fine(b - a)}; if they are meant to be equal, one saw setting saves "
                                     "a mistake", [o.Name for o in objs_a + objs_b]))
    return found


def bare_edges(doc):
    """Straight edges of sketches that carry profiles, but not on this edge."""
    used = OrderedDict()
    for obj in doc.Objects:
        if feature.is_profile(obj) and obj.PathEdge and obj.PathEdge[1]:
            used.setdefault(obj.PathEdge[0].Name, set()).add(obj.PathEdge[1][0])
    found = []
    for source_name, subs in used.items():
        source = doc.getObject(source_name)
        bare = [f"Edge{i + 1}" for i, e in enumerate(source.Shape.Edges)
                if e.Curve.TypeId == "Part::GeomLine" and f"Edge{i + 1}" not in subs]
        if bare:
            listed = ", ".join(bare[:6]) + (", ..." if len(bare) > 6 else "")
            found.append(Finding("Info", f"{source.Label} has {len(bare)} straight edge(s) without a profile "
                                 f"({listed})", [source_name]))
    return found


def box_frames(doc):
    """Box frames whose profiles no longer give the size their skeleton asks for.

    The skeleton sizes itself from the sections on each side, but not from a
    profile moved off its line (a section offset from Align slots, an anchor or
    a spin) or from a changed joint rule.
    """
    found = []
    for obj in doc.Objects:
        if not skeleton.is_skeleton(obj) or not obj.isValid():
            continue
        measured = skeleton.measured_size(obj)
        requested = (obj.Width.Value, obj.Depth.Value, obj.Height.Value)
        if measured is None or all(abs(a - b) <= 0.01 for a, b in zip(measured, requested)):
            continue
        actual, wanted = (" × ".join(length(value) for value in size) for size in (measured, requested))
        names = [obj.Name] + [member.Name for on_edge in skeleton.members(obj).values() for member in on_edge]
        found.append(Finding("Warning", f"{obj.Label}: the frame measures {actual}, not the requested "
                             f"{obj.SizeMode.lower()} size {wanted}. A section offset (Align slots), anchor, "
                             "spin or joint rule moved a profile", names))
    return found


def overall(doc):
    """The outside size of all profiles and panels."""
    box = None
    for obj in doc.Objects:
        if (feature.is_profile(obj) or panels.is_panel(obj)) and obj.isValid() and obj.Shape.Solids:
            box = obj.Shape.BoundBox if box is None else box.united(obj.Shape.BoundBox)
    if box is None:
        return []
    return [Finding("Info", f"Outside size {length(box.XLength)} × {length(box.YLength)} × {length(box.ZLength)} "
                    "(X × Y × Z)")]


CHECKS = (broken, duplicates, unjoined, clashes, panel_fit, carriages, long_pieces, similar_lengths, bare_edges,
          box_frames, overall)
QUICK = (broken, duplicates, unjoined)  # cheap enough to run with every cut list


def run(doc, checks=CHECKS):
    """All findings, errors first. A check that fails is reported, not raised."""
    found = []
    for check in checks:
        try:
            found += check(doc)
        except Exception as exc:  # noqa: BLE001
            found.append(Finding("Error", f"The {check.__name__} check failed: {exc}"))
    return sorted(found, key=lambda f: SEVERITIES.index(f.severity))


def apply_fix(doc, finding):
    """Carry out a finding's fix; returns a message. The caller opens the transaction and recomputes."""
    kind = finding.fix[0]
    objs = [doc.getObject(n) for n in finding.fix[1]]
    objs = [o for o in objs if o is not None]
    if kind == "delete":
        for o in objs:
            doc.removeObject(o.Name)
        return f"deleted {len(objs)} duplicate profile(s)"
    if kind == "join":
        warnings = []
        profiles = [o for o in objs if feature.is_profile(o)]
        before = {o.Name: (o.StartJoint, o.EndJoint) for o in profiles}
        made = joints.create_joints(doc, profiles, tolerance=finding.fix[2], warnings=warnings)
        joined = sum((o.StartJoint, o.EndJoint) != before[o.Name] for o in profiles)
        # A length set by hand stays on top of the trim the joint now makes.
        for o in profiles:
            for end in ("Start", "End"):
                extend = getattr(o, f"Extend{end}").Value
                newly = getattr(o, f"{end}Joint") is not before[o.Name][end == "End"]
                if newly and abs(extend) > 1e-9:
                    warnings.append(f"{o.Label} keeps its Extend{end} of {length(extend)} on top of the "
                                    "joint's trim; set it to 0 if the joint should decide")
        text = f"{len(made)} joint(s) made" if made else f"{joined} end(s) added to a joint"
        return text + (f"; {'; '.join(warnings)}" if warnings else "")
    raise ValueError(f"unknown fix {kind}")
