"""Joints between profiles that meet at a vertex of their path edges.

A Joint is a small document object at the shared vertex. Profiles link to it
through their StartJoint / EndJoint properties and ask it, while they
recompute, how much to extend or trim that end and whether to miter it.

The joint never links back to the profiles, which would create a dependency
cycle. It finds its members through its InList (the objects linking to it),
plus ``PassingMembers`` for a profile that runs straight through the vertex
(a T-junction). Offsets are measured from the vertex, so they stay correct
when the sketch is stretched; they only depend on profile sizes and angles.
"""

import math
import os

import FreeCAD as App
import Part

from . import feature

V = App.Vector

TYPES = ("Butt", "Miter")
THROUGH_RULES = ("Vertical", "Longest", "Horizontal", "Along X", "Along Y", "Manual")
TOLERANCE = 1e-3  # mm, for matching vertices
NEAR_MISS = 2.0  # mm: vertices closer than this but not matching are probably a drawing error
PARALLEL = 0.999  # |cos| above which two members count as collinear
PERPENDICULAR = 0.02  # |cos| below which two members count as perpendicular


def is_joint(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "ProfileBuilder::Joint"


def ends_of(joint):
    """[(profile, "Start" | "End")] of the profiles whose ends use this joint."""
    result = []
    for obj in joint.InList:
        if feature.is_profile(obj):
            if obj.StartJoint == joint:
                result.append((obj, "Start"))
            if obj.EndJoint == joint:
                result.append((obj, "End"))
    return sorted(result, key=lambda e: (e[0].Name, e[1]))


def passing_of(joint):
    doc = joint.Document
    objs = [doc.getObject(name) for name in joint.PassingMembers]
    return [o for o in objs if o is not None and feature.is_profile(o) and _has_edge(o)]


def _has_edge(obj):
    try:
        return feature.path_edge(obj) is not None
    except ValueError:
        return False


def _live(ends):
    """The ends whose path edge still exists.

    A profile whose sketch line was deleted reports its own error; the others
    in the joint are computed as if it were not there, instead of failing too.
    """
    return [(o, e) for o, e in ends if _has_edge(o)]


def _end_point(obj, end):
    edge = feature.path_edge(obj)
    return edge.Vertexes[0].Point if end == "Start" else edge.Vertexes[-1].Point


def _away(frame, end):
    """Direction from the joint into the member."""
    return frame.z if end == "Start" else -frame.z


def touch_joints_of(obj):
    """Mark the joints involving a profile for recompute."""
    if "EndJoint" not in obj.PropertiesList or getattr(obj, "Document", None) is None:
        return
    for joint in (obj.StartJoint, obj.EndJoint):
        if joint is not None:
            joint.touch()
    for other in obj.Document.Objects:
        if is_joint(other) and obj.Name in other.PassingMembers:
            other.touch()


def through_member(joint):
    """(profile, end) of the member that runs through; end is None for a passing member."""
    passing = passing_of(joint)
    if passing:
        return passing[0], None
    ends = _live(ends_of(joint))
    if not ends:
        return None, None
    if joint.ThroughRule == "Manual":
        # The choice is kept by object name, which survives renaming; older
        # documents only have the label until the joint recomputes once.
        name = getattr(joint, "ThroughName", "")
        for obj, end in ends:
            if (obj.Name == name) if name else (obj.Label == joint.Through):
                return obj, end

    # Per-profile roles come next: a profile marked "Runs through" wins at
    # every joint it is in, one marked "Butts" never runs through.
    through = [e for e in ends if _role(e[0]) == "Runs through"]
    candidates = through or [e for e in ends if _role(e[0]) != "Butts"] or ends

    def axis(e):
        z = feature.member_frame(e[0]).z
        return (round(abs(z.x), 6), round(abs(z.y), 6), round(abs(z.z), 6))

    def length(e):
        return round(feature.path_edge(e[0]).Length, 3)

    def direction(e):
        """Tie-break: X before Y before Z, then the signed line, then the side of the joint.

        Lines at equal angles to the axes (rails along (1, 1, 0) and (1, -1, 0)
        in a frame turned 45°) have the same ``axis``; their signed directions
        tell them apart. The line is flipped so that its first non-zero
        component is positive, so the key does not depend on the way it was
        drawn and a member ranks the same at both of its ends. That leaves only
        collinear members tied, and of those the one on the positive side of
        the joint wins.
        """
        z = feature.member_frame(e[0]).z
        c = [round(v, 6) + 0.0 for v in (z.x, z.y, z.z)]  # + 0.0 turns -0.0 into 0.0
        sign = next((1 if v > 0 else -1 for v in c if v), 1)
        side = sign if e[1] == "Start" else -sign
        return axis(e) + tuple(v * sign for v in c) + (side,)

    # Ties are broken by direction (X before Y before Z), never by object
    # name, so all corners of a symmetric frame make the same choice.
    rule = joint.ThroughRule
    if rule == "Vertical" and max(axis(e)[2] for e in candidates) < 0.9:
        rule = "Longest"
    if rule == "Vertical":
        key = lambda e: (axis(e)[2], length(e), direction(e))  # noqa: E731
    elif rule == "Horizontal":
        key = lambda e: (-axis(e)[2], length(e), direction(e))  # noqa: E731
    elif rule == "Along X":
        key = lambda e: (axis(e)[0], length(e), direction(e))  # noqa: E731
    elif rule == "Along Y":
        key = lambda e: (axis(e)[1], length(e), direction(e))  # noqa: E731
    else:
        key = lambda e: (length(e), direction(e))  # noqa: E731
    return max(candidates, key=key)


def _role(obj):
    return getattr(obj, "JointRole", "Auto")


def swap(joint):
    """Let the next profile of a butt joint run through (sets the rule to Manual)."""
    ends = _live(ends_of(joint))
    if len(ends) < 2 or passing_of(joint):
        return False
    current, _end = through_member(joint)
    names = [o.Name for o, _e in ends]
    nxt = ends[(names.index(current.Name) + 1) % len(ends)][0]
    joint.Proxy._updating = True
    try:
        joint.ThroughRule = "Manual"
        joint.ThroughName = nxt.Name
        # A profile renamed since the joint last recomputed is not in the list yet.
        labels = list(dict.fromkeys(o.Label for o, _e in ends_of(joint)))
        if list(joint.getEnumerationsOfProperty("Through") or []) != labels:
            joint.Through = labels
        joint.Through = nxt.Label
    finally:
        joint.Proxy._updating = False
    return True


def _member_by_label(joint, label):
    for obj in [o for o, _e in ends_of(joint)] + passing_of(joint):
        if obj.Label == label:
            return obj
    return None


def set_runs_through(profiles):
    """Mark profiles to run through all their butt joints.

    Joints involving them that were set by hand go back to automatic, so the
    new roles take effect.
    """
    for p in profiles:
        p.JointRole = "Runs through"
        for joint in (p.StartJoint, p.EndJoint):
            if joint is not None and joint.ThroughRule == "Manual":
                joint.ThroughRule = "Longest"
    # A profile butting into one of these must not also claim to run through.
    chosen = {p.Name for p in profiles}
    for p in profiles:
        for joint in (p.StartJoint, p.EndJoint):
            if joint is None:
                continue
            for other, _end in ends_of(joint):
                if other.Name not in chosen and _role(other) == "Runs through":
                    other.JointRole = "Auto"


def adjustment(joint, obj, end):
    """(length offset, miter angle, miter axis) for one end of a member.

    The offset is added to the member length at that end (negative trims).
    The miter angle follows the Profile convention: positive makes the +axis
    side the long side.
    """
    frame = feature.member_frame(obj)
    away = _away(frame, end)

    if joint.Type == "Miter":
        ends = _live(ends_of(joint))
        if len(ends) != 2 or passing_of(joint):
            raise ValueError(f"{joint.Label}: a miter joint needs exactly two profiles ending in it")
        other, other_end = ends[0] if ends[1] == (obj, end) else ends[1]
        other_away = _away(feature.member_frame(other), other_end)
        if abs(away.dot(other_away)) > PARALLEL:
            raise ValueError(f"{joint.Label}: collinear profiles cannot be mitered")
        m = away - other_away
        m.normalize()
        angle = math.degrees(math.acos(min(1.0, abs(away.dot(m)))))
        if angle >= 80:
            raise ValueError(f"{joint.Label}: the profiles meet at too sharp an angle to miter")
        # Direction across the section in which the profile gets longer.
        g = m - away * m.dot(away)
        g.normalize()
        gx, gy = g.dot(frame.x), g.dot(frame.y)
        if abs(gx) > PARALLEL:
            axis, sign = "X", math.copysign(1, gx)
        elif abs(gy) > PARALLEL:
            axis, sign = "Y", math.copysign(1, gy)
        else:
            raise ValueError(f"{joint.Label}: miter plane is not square to {obj.Label}; check its Spin")
        # The miter plane passes through the vertex; the length is measured at
        # the section centre, which may be offset from the path edge.
        s = -frame.center_offset().dot(m) / away.dot(m)
        return -s, sign * angle, axis

    through, through_end = through_member(joint)
    if through is None:
        return 0.0, 0.0, "X"
    gap = joint.Gap.Value
    if through == obj and through_end == end:
        if not joint.ExtendThrough:
            return 0.0, 0.0, "X"
        reach = 0.0
        for other, other_end in _live(ends_of(joint)):
            if (other, other_end) == (obj, end):
                continue
            other_frame = feature.member_frame(other)
            if abs(_away(other_frame, other_end).dot(away)) > PARALLEL:
                continue
            reach = max(reach, other_frame.support(-away))
        return reach, 0.0, "X"

    through_frame = feature.member_frame(through)
    cos = abs(away.dot(through_frame.z))
    if cos > PARALLEL:
        return -gap / 2, 0.0, "X"
    if cos > PERPENDICULAR:
        angle = math.degrees(math.acos(cos))
        raise ValueError(f"{joint.Label}: butt joints need perpendicular profiles "
                         f"({obj.Label} meets at {angle:.1f} degrees); use a miter joint")
    return -(through_frame.support(away) + gap), 0.0, "X"


class Joint:
    Type = "ProfileBuilder::Joint"

    def __init__(self, obj):
        obj.Proxy = self
        self._updating = False
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

        add("App::PropertyEnumeration", "Type", "Joint", "Butt: one profile runs through, the others stop "
            "against it. Miter: two profiles cut at half the corner angle.", list(TYPES))
        add("App::PropertyEnumeration", "ThroughRule", "Joint",
            "Which profile runs through a butt joint", list(THROUGH_RULES))
        add("App::PropertyEnumeration", "Through", "Joint", "Profile that runs through (sets the rule to Manual)")
        add("App::PropertyString", "ThroughName", "Joint",
            "Internal name of the profile chosen in Through, so renaming profiles keeps the choice", mode=2)
        add("App::PropertyBool", "ExtendThrough", "Joint",
            "Extend the through profile so its end is flush with the others", True)
        add("App::PropertyLength", "Gap", "Joint", "Clearance between butting profiles", 0.0)
        add("App::PropertyStringList", "Members", "Joint", "Profiles in this joint", mode=1)
        add("App::PropertyStringList", "PassingMembers", "Joint",
            "Names of profiles running straight through the vertex (T-junction)", mode=1)
        add("App::PropertyLinkList", "Sources", "Joint",
            "Path objects of the members, so the joint follows sketch changes", mode=2)

    def onDocumentRestored(self, obj):
        self._updating = True
        try:
            self.add_properties(obj)
            # Documents from older versions have a shorter list of rules.
            if list(obj.getEnumerationsOfProperty("ThroughRule")) != list(THROUGH_RULES):
                rule = obj.ThroughRule
                obj.ThroughRule = list(THROUGH_RULES)
                obj.ThroughRule = rule
            # Documents from before ThroughName kept the manual choice by label.
            # Resolve it now, while the labels still match, so a rename made
            # before the next recompute cannot lose it.
            if obj.ThroughRule == "Manual" and not obj.ThroughName:
                member = _member_by_label(obj, obj.Through)
                if member is not None:
                    obj.ThroughName = member.Name
        finally:
            self._updating = False

    def onChanged(self, obj, prop):
        # Undo and Cancel write the old Through back; that is not a new choice.
        if feature.replaying(obj) or getattr(self, "_updating", False):
            return
        if prop == "Through" and "ThroughName" in obj.PropertiesList:
            obj.ThroughRule = "Manual"
            member = _member_by_label(obj, obj.Through)
            if member is not None:
                obj.ThroughName = member.Name

    def execute(self, obj):
        ends = ends_of(obj)
        passing = passing_of(obj)
        live = _live(ends)
        self._updating = True
        try:
            members_objs = [o for o, _e in ends] + passing
            labels = list(dict.fromkeys(o.Label for o in members_objs))
            if obj.ThroughName:
                if obj.Document.getObject(obj.ThroughName) not in members_objs:
                    # The chosen profile was deleted, or this joint is a copy that
                    # names another joint's profile: go back to automatic.
                    obj.ThroughName = ""
                    if obj.ThroughRule == "Manual":
                        obj.ThroughRule = "Longest"
            elif obj.ThroughRule == "Manual":
                chosen = _member_by_label(obj, obj.Through)  # documents from before ThroughName
                if chosen is not None:
                    obj.ThroughName = chosen.Name
            if list(obj.getEnumerationsOfProperty("Through") or []) != labels:
                obj.Through = labels or [""]
            # Always show the profile that really runs through.
            if obj.Type == "Butt" and live:
                through, _end = through_member(obj)
                if through is not None and through.Label in labels and obj.Through != through.Label:
                    obj.Through = through.Label
            members = [f"{o.Label} ({e.lower()})" for o, e in ends]
            members += [f"{o.Label} (passes through)" for o in passing]
            if list(obj.Members) != members:
                obj.Members = members
        finally:
            self._updating = False

        if not live:
            obj.Shape = Part.Shape()
            return
        if obj.Type == "Miter" and (len(live) != 2 or passing):
            raise ValueError(f"{obj.Label}: a miter joint needs exactly two profiles ending in it")
        obj.Shape = Part.Vertex(_end_point(*live[0]))

    def dumps(self):
        return None

    def loads(self, state):
        self._updating = False
        return None

    __getstate__ = dumps
    __setstate__ = loads


class ViewProviderJoint:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.PointSize = 9
        vobj.PointColor = (1.0, 0.55, 0.0)

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return os.path.join(feature.ICON_DIR, "Joint.svg")

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from .simple_panel import PropertyTaskPanel
        Gui.Control.showDialog(PropertyTaskPanel(vobj.Object, JOINT_FIELDS, "Joint", joint_info))
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


JOINT_FIELDS = ("Type", "ThroughRule", "Through", "ExtendThrough", "Gap")


def joint_info(obj):
    lines = []
    for member, end in ends_of(obj):
        offset = getattr(member, f"Joint{end}Offset").Value
        miter = getattr(member, f"Miter{end}").Value
        text = f"{member.Label} ({end.lower()}): {offset:+.1f} mm"
        if miter:
            text += f", miter {abs(miter):.1f}°"
        lines.append(text)
    lines += [f"{m.Label}: passes through" for m in passing_of(obj)]
    return "<br>".join(lines)


def make_joint(doc, joint_type="Butt", rule="Vertical"):
    obj = doc.addObject("Part::FeaturePython", "Joint")
    Joint(obj)
    obj.Type = joint_type
    obj.ThroughRule = rule
    if App.GuiUp:
        ViewProviderJoint(obj.ViewObject)
    return obj


def _joint_group(doc):
    group = doc.getObject("Joints")
    if group is None:
        group = doc.addObject("App::DocumentObjectGroup", "Joints")
    return group


def create_joints(doc, profiles, joint_type="Butt", rule="Vertical", tolerance=TOLERANCE, warnings=None):
    """Create joints wherever profile path edges meet. Returns the new joints.

    Ends that already have a joint are left alone; free ends landing on an
    existing joint are added to it. A free end landing in the middle of another
    profile makes a T-junction with that profile running through. Miter joints
    are only used where exactly two profiles meet; other vertices get butt joints.

    Ends that nearly meet another end or edge (within ``NEAR_MISS``) but not
    within ``tolerance`` get no joint, and a message is added to ``warnings``.
    """
    candidates, edges = [], {}
    for p in profiles:
        if not (feature.is_profile(p) and p.PathEdge):
            continue
        try:
            edges[p.Name] = feature.path_edge(p)
        except ValueError as e:
            # One deleted sketch line must not stop the rest of the frame.
            if warnings is not None:
                warnings.append(f"skipped: {e}")
            continue
        candidates.append(p)

    clusters = []  # [point, existing joint or None, [(profile, end)]]
    for joint in doc.Objects:
        if is_joint(joint) and joint.Shape.Vertexes:
            clusters.append([joint.Shape.Vertexes[0].Point, joint, []])
    for p in candidates:
        edge = edges[p.Name]
        for end, point in (("Start", edge.Vertexes[0].Point), ("End", edge.Vertexes[-1].Point)):
            if getattr(p, f"{end}Joint") is not None:
                continue
            for cluster in clusters:
                if (cluster[0] - point).Length < tolerance:
                    cluster[2].append((p, end))
                    break
            else:
                clusters.append([point, None, [(p, end)]])

    if warnings is not None:
        warnings.extend(_near_misses(clusters, candidates, edges, tolerance))

    created = []
    for point, joint, members in clusters:
        if not members:
            continue
        in_cluster = {p.Name for p, _e in members}
        passing = []
        if joint is None:
            vertex = Part.Vertex(point)
            for q in candidates:
                edge = edges[q.Name]
                if q.Name in in_cluster or edge.distToShape(vertex)[0] > tolerance:
                    continue
                if min((v.Point - point).Length for v in edge.Vertexes) > tolerance:
                    passing.append(q)
            if len(members) + len(passing) < 2:
                continue
            simple_corner = len(members) == 2 and not passing
            joint = make_joint(doc, joint_type if simple_corner else "Butt", rule)
            joint.PassingMembers = [q.Name for q in passing]
            _joint_group(doc).addObject(joint)
            created.append(joint)
        if joint.Type == "Miter" and len(ends_of(joint)) + len(members) > 2:
            # More than two profiles cannot share a miter.
            joint.Type = "Butt"
            if warnings is not None:
                warnings.append(f"{joint.Label} now joins {len(ends_of(joint)) + len(members)} profiles, "
                                "so it was changed from a miter to a butt joint")
        # A profile that ends at this joint no longer passes through it.
        ending = {p.Name for p, _e in members}
        if ending & set(joint.PassingMembers):
            joint.PassingMembers = [n for n in joint.PassingMembers if n not in ending]
        for p, end in members:
            setattr(p, f"{end}Joint", joint)
        sources = list(joint.Sources)
        for p in [m for m, _e in members] + passing:
            link = p.PathEdge[0]
            if link not in sources:
                sources.append(link)
        joint.Sources = sources
    return created


def _near_misses(clusters, candidates, edges, tolerance):
    """Messages for profile ends that almost, but not quite, meet something."""
    messages = []
    ends = [(point, members) for point, _joint, members in clusters if members]
    for i, (p, members) in enumerate(ends):
        for q, others in ends[i + 1:]:
            gap = (p - q).Length
            if tolerance <= gap < NEAR_MISS:
                messages.append(f"{members[0][0].Label} and {others[0][0].Label} end {gap:.2f} mm apart, "
                                "so they get no joint; snap the sketch vertices together")
    # New ends that just miss a joint made in an earlier run.
    existing = [(point, joint) for point, joint, members in clusters if joint is not None and not members]
    for p, members in ends:
        for q, joint in existing:
            gap = (p - q).Length
            if tolerance <= gap < NEAR_MISS:
                messages.append(f"{members[0][0].Label} ends {gap:.2f} mm from {joint.Label}, so it is not "
                                "added to that joint; snap the sketch vertex onto the corner")
    for p, members in ends:
        if len(members) != 1:
            continue
        vertex = Part.Vertex(p)
        for q in candidates:
            if q == members[0][0]:
                continue
            gap = edges[q.Name].distToShape(vertex)[0]
            near_end = min((v.Point - p).Length for v in edges[q.Name].Vertexes) < NEAR_MISS
            if tolerance <= gap < NEAR_MISS and not near_end:
                messages.append(f"{members[0][0].Label} ends {gap:.2f} mm from {q.Label}, "
                                "so it gets no T-joint; snap the sketch vertex onto the line")
    return messages
