"""Brackets: the user's own bracket part, placed in the corners of the joints.

A Brackets object places one bracket part, typically a supplier's STEP file
imported into the document, in the corners of the butt joints. It is an
App::LinkPython link array: LinkedObject is the part, and execute() writes
ElementCount and PlacementList. The part is shown once per position without
being copied, so it keeps its STEP colours and stays light, and no objects are
created during recompute (``ShowElement`` stays off).

Dependencies stay acyclic. The object links to its Joints and, through the
hidden Members and FrameJoints lists, to the profiles and the other joints of
their frame, so it recomputes after them when a sketch, a profile (size, Spin)
or a joint (swap, rule) changes. Profiles and joints never link to it.

The bracket frame (``SourceFrame``, in the part's own coordinates, set by
calibration): the origin lies on the line where the two contact faces meet,
in the middle of the part's width. +X runs along the leg that lies on the
profile ending at the joint, +Y along the leg on the profile it meets, and Z
across the width. So the contact faces face -Y and -X.
"""

import html
import math
import os
from collections import OrderedDict

import FreeCAD as App
import Part

from . import feature, joints, panels

V = App.Vector

TYPE = "ProfileBuilder::Brackets"
RULES = ("Inner faces", "All open faces")
STYLES = ("Corner", "End plate")
FIELDS = ("Rule", "AllJoints", "SkipClaimed", "SwapLegs", "SlotOffset", "Item", "ArticleNumber")
PLATE_FIELDS = ("AllJoints", "SkipClaimed", "PerSlot", "PlateOffset", "Item", "ArticleNumber")
SLOT_TOLERANCE = 0.5  # mm: the slots of the two contact faces must line up this well
FLUSH = 0.5  # mm: the faces of a profile and the one it butts must lie in one plane for an end plate
MEET = 0.01  # mm: how far a butting end may stop short of the other profile's face, besides the joint's Gap
OUTWARD = 1.0  # mm: at a T-junction, a joint or the frame's reach counts on a side only beyond this
SQUARE = 0.02  # |cos| below which two contact faces count as square to each other (about 1 degree)
SWAP = App.Rotation(V(1, 1, 0), 180)  # swaps the legs: X <-> Y, Z -> -Z
FACE_AXES = (("Right", "x", 1), ("Left", "x", -1), ("Top", "y", 1), ("Bottom", "y", -1))


def is_brackets(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == TYPE


def fields(obj):
    """The properties the task panel shows for ``obj``."""
    return PLATE_FIELDS if obj.Style == "End plate" else FIELDS


def _vec(n):
    return ",".join(f"{round(v, 2) + 0.0:.2f}" for v in (n.x, n.y, n.z))


def corner_key(joint, first, second, n):
    """Identifies one corner (or plate side) of a joint in SkippedCorners, by object names, never labels."""
    return f"{joint.Name}|{first.Name}|{second.Name}|{_vec(n)}"


def _side(n):
    for name, axis in (("+X", V(1, 0, 0)), ("-X", V(-1, 0, 0)), ("+Y", V(0, 1, 0)), ("-Y", V(0, -1, 0)),
                       ("+Z", V(0, 0, 1)), ("-Z", V(0, 0, -1))):
        if n.dot(axis) > 0.999:
            return name
    return f"({_vec(n)})"


def corner_label(joint, first, second, n):
    return f"{joint.Label}: {first.Label} / {second.Label}, towards {_side(n)}"


def _placement(origin, x, y):
    """Placement at ``origin`` with the given X and Y axes (Y made square to X), Z = X x Y."""
    x = V(x)
    x.normalize()
    y = y - x * y.dot(x)
    y.normalize()
    z = x.cross(y)
    return App.Placement(App.Matrix(x.x, y.x, z.x, origin.x,
                                    x.y, y.y, z.y, origin.y,
                                    x.z, y.z, z.z, origin.z,
                                    0, 0, 0, 1))


def _rank(u):
    """Sort key for directions: X before Y before Z, as the joints break ties.

    Lines at equal angles to the axes (rails along (1, 1, 0) and (1, -1, 0) in
    a frame turned 45°) are then ordered by their signed direction, so the
    order never depends on object names. The key is that of the line, not of
    the way along it, so a rail ranks the same at both of its ends.
    """
    c = [round(v, 6) + 0.0 for v in (u.x, u.y, u.z)]  # + 0.0 turns -0.0 into 0.0
    sign = next((1 if v > 0 else -1 for v in c if v), 1)
    return tuple(-abs(v) for v in c) + tuple(-v * sign for v in c)


def _square(obj):
    """Whether a profile's Spin keeps its faces square to the axes it was drawn on."""
    spin = obj.Spin.Value
    return abs(spin - 90 * round(spin / 90)) < 1e-6


def _no_face_note(missing, first, second):
    """Why the corner of ``first`` and ``second`` gets no bracket: ``missing`` have no face lying flat in it."""
    if len(missing) == 2:
        return (f"{first.Label} and {second.Label} have no faces square to each other, so that corner gets no "
                "bracket; set their Spin so their faces line up")
    obj = missing[0]
    other = second if obj == first else first
    turned = "" if _square(obj) else f" is turned by its Spin ({obj.Spin.Value:g}°) and"
    return (f"{obj.Label}{turned} has no face square to {other.Label}, so that corner gets no bracket; "
            f"set its Spin so its faces line up with {other.Label}")


# ---- where the brackets go ------------------------------------------------------


def face_slots(obj, frame, normal, across):
    """Slot centre lines on the face of a profile whose outward normal is ``normal``.

    They are returned as distances along ``across`` from the profile's axis
    line. An empty list when the face is closed, None when the profile has no
    face that way: its faces are not square to ``normal``, because of its Spin
    or because the frame is not lined up with the axes it was drawn along.
    """
    for name, axis, sign in FACE_AXES:
        if (getattr(frame, axis) * sign).dot(normal) > joints.PARALLEL:
            break
    else:
        return None
    if getattr(obj, f"Closed{name}"):
        return []
    x0, _x1, y0, _y1 = frame.rect
    cell = obj.CellSize.Value
    if axis == "y":  # Top and Bottom faces: the slots sit side by side along X
        along, start, count = frame.x, x0, obj.Columns
    else:
        along, start, count = frame.y, y0, obj.Rows
    k = along.dot(across)
    if abs(k) < joints.PARALLEL:
        return None
    return [k * (start + (i + 0.5) * cell) for i in range(count)]


def _corner(vertex, first, first_frame, a, second, second_frame, n):
    """(bracket placements, note) for the corner between two profiles at a joint.

    ``first`` runs from the joint in direction ``a``; leg 1 lies on its face
    that faces ``n``. Leg 2 lies on the face of ``second`` that faces ``a`` and
    runs along ``n``. One bracket goes on each slot that lines up on both faces.
    A closed face gets none; slots that do not line up get a note.
    """
    across = a.cross(n)
    across.normalize()
    mine = face_slots(first, first_frame, n, across)
    theirs = face_slots(second, second_frame, a, across)
    missing = [p for p, slots in ((first, mine), (second, theirs)) if slots is None]
    if missing:
        return [], _no_face_note(missing, first, second)
    if not mine or not theirs:
        return [], None  # a closed face
    corner = vertex + a * second_frame.support(a) + n * first_frame.support(n)
    found = [_placement(corner + across * ((s + t) / 2), a, n)
             for s in mine for t in theirs if abs(s - t) <= SLOT_TOLERANCE]
    if not found:
        return [], f"the slots of {first.Label} and {second.Label} do not line up, so that corner gets no bracket"
    return found, None


def _plate(vertex, first, first_frame, a, through, through_frame, m, per_slot, offset):
    """(plate placements, note) for the side of a T-junction whose faces face ``m``.

    ``first`` butts the side of ``through`` and runs from the joint in direction ``a``. The plate lies on
    the faces of both that face ``m``, which must lie in one plane. Its bar end is flush with the far
    face of ``through`` (moved by ``offset`` along ``a``), its stem runs along ``first``, and its +Z
    points away from the profiles. A plate goes over the middle of the butting profile's face, or with
    ``per_slot`` on each of its slots.
    """
    t = through_frame.z
    mine = face_slots(first, first_frame, m, t)
    theirs = face_slots(through, through_frame, m, a)
    missing = [p for p, slots in ((first, mine), (through, theirs)) if slots is None]
    if missing:
        return [], _no_face_note(missing, first, through)
    if not mine or not theirs:
        return [], None  # a closed face
    if abs(first_frame.support(m) - through_frame.support(m)) > FLUSH:
        return [], f"the faces of {first.Label} and {through.Label} are not flush, so that side gets no end plate"
    origin = vertex + a * (offset - through_frame.support(a * -1)) + m * first_frame.support(m)
    across = mine if per_slot else [sum(mine) / len(mine)]
    return [_placement(origin + t * u, a, m.cross(a)) for u in across], None


def _reach(joint, obj, end):
    """How far the end of a butting profile is from the joint vertex, along the profile."""
    offset, _miter, _axis = joints.adjustment(joint, obj, end)
    return -(offset + getattr(obj, f"Extend{end}").Value)


class FrameInfo:
    """The frame that a set of joints belongs to: every joint and profile connected to them.

    The "Inner faces" rule looks at the whole frame, not only at the joints
    that get brackets, so the brackets do not change when other joints are
    picked.
    """

    def __init__(self, joint_list):
        self.joints, self.profiles = frame_of(joint_list)
        self._at = {}  # profile name -> joints where it meets another profile
        self._points = {}
        for joint in self.joints:
            members = _members(joint, live=True)
            if len(members) < 2:
                continue  # a joint left with one profile connects nothing
            for name in members:
                self._at.setdefault(name, []).append(joint)
        self._ends = {}
        for obj in self.profiles:
            try:
                edge = feature.path_edge(obj)
            except ValueError:
                edge = None
            if edge is not None:
                self._ends[obj.Name] = (edge.Vertexes[0].Point, edge.Vertexes[-1].Point)

    def point(self, joint):
        if joint.Name not in self._points:
            ends = joints._live(joints.ends_of(joint))
            self._points[joint.Name] = joints._end_point(*ends[0]) if ends else None
        return self._points[joint.Name]

    def carries_on(self, joint, through, vertex, n):
        """Whether ``through`` runs from ``vertex`` in direction ``n`` on to another joint of the frame."""
        for other in self._at.get(through.Name, []):
            p = None if other == joint else self.point(other)
            if p is not None and (p - vertex).dot(n) > OUTWARD:
                return True
        return False

    def reach(self, through, vertex, n):
        """How far the frame, apart from ``through``, reaches beyond ``vertex`` in direction ``n``."""
        return max([0.0] + [(p - vertex).dot(n) for name, ends in self._ends.items() if name != through.Name
                            for p in ends])

    def inner_sides(self, joint, through, vertex, sides):
        """The sides of a T-junction that face into the frame.

        A side where the profile running through carries on to another joint
        faces into the frame. A side where it ends freely (a stub, such as a
        post standing out above a rail) does not, unless it ends freely both
        ways (posts standing on the floor): then the side where the rest of the
        frame reaches further counts, or both when they reach equally far.
        """
        found = [n for n in sides if self.carries_on(joint, through, vertex, n)]
        if found:
            return found
        reach = [self.reach(through, vertex, n) for n in sides]
        return [n for n, r in zip(sides, reach) if r >= max(reach) - OUTWARD]


def _members(joint, live=False):
    """Names of the profiles at a joint (ending or passing through), each once.

    With ``live``, only those whose path edge still exists.
    """
    ends = joints.ends_of(joint)
    if live:
        ends = joints._live(ends)
    names = [o.Name for o, _e in ends] + [o.Name for o in joints.passing_of(joint)]
    return list(dict.fromkeys(names))


def frame_of(joint_list):
    """([joints], [profiles]) connected to ``joint_list`` through joints, the given joints first."""
    if not joint_list:
        return [], []
    doc = joint_list[0].Document
    members = {joint.Name: _members(joint) for joint in all_joints(doc)}
    at = {}  # profile name -> joints
    for joint in all_joints(doc):
        for name in members[joint.Name]:
            at.setdefault(name, []).append(joint)
    found_joints, found_profiles = OrderedDict(), OrderedDict()
    queue = list(joint_list)
    while queue:
        joint = queue.pop(0)
        if joint.Name in found_joints:
            continue
        found_joints[joint.Name] = joint
        for name in members.get(joint.Name) or _members(joint):
            if name not in found_profiles:
                found_profiles[name] = doc.getObject(name)
                queue += at.get(name, [])
    return list(found_joints.values()), list(found_profiles.values())


def joint_spots(joint, rule, context, style="Corner", per_slot=False, offset=0.0):
    """([(placement, profile on leg 1, profile on leg 2, (corner key, label))], [notes]) for one joint.

    Brackets go into every square corner of a butt joint:
    - between a profile that ends at the joint and the one that runs through
      (on the side where that one continues; both sides at a T-junction, or
      with the "Inner faces" rule only the sides facing into the frame,
      see ``FrameInfo.inner_sides``; ``context`` is the FrameInfo);
    - between two profiles that end square to each other against the same
      profile, when both ends reach the other's face.

    With the "End plate" style, a plate goes on each of the two flush side faces of a T-junction
    instead, across both profiles (see ``_plate``; ``per_slot`` and ``offset`` are its options).
    """
    if not joint.isValid():
        return [], [f"{joint.Label} has an error, so it gets no brackets"]
    if joint.Type != "Butt":
        return [], [f"{joint.Label} is a {joint.Type.lower()} joint; brackets are only placed at butt joints so far"]
    ends = joints._live(joints.ends_of(joint))
    if not ends:
        return [], []
    passing = joints.passing_of(joint)
    through, through_end = joints.through_member(joint)
    vertex = joints._end_point(*ends[0])
    frames = {o.Name: feature.member_frame(o) for o in [o for o, _e in ends] + passing}
    butting = [(o, e, joints._away(frames[o.Name], e)) for o, e in ends if (o, e) != (through, through_end)]

    found, notes = [], []

    def spot(placements, first, second, n):
        corner = (corner_key(joint, first, second, n), corner_label(joint, first, second, n))
        found.extend((pl, first, second, corner) for pl in placements)

    def add(first, first_frame, a, second, second_frame, n):
        placements, note = _corner(vertex, first, first_frame, a, second, second_frame, n)
        spot(placements, first, second, n)
        if note:
            notes.append(f"{joint.Label}: {note}")

    # A profile stopping further from a face than the joint's gap (trimmed, or kept away by a
    # wider through profile) leaves no corner for a bracket there.
    short = joint.Gap.Value + MEET

    if style == "End plate":
        if through is None or through_end is not None:
            return [], [f"{joint.Label} is not a T-junction, so it gets no end plate; end plates go where one "
                        "profile ends on the side of another that runs through"]
        tf = frames[through.Name]
        for obj, end, a in butting:
            if abs(a.dot(tf.z)) > joints.PERPENDICULAR or _reach(joint, obj, end) > tf.support(a) + short:
                continue
            w = a.cross(tf.z)
            w.normalize()
            for m in (w, w * -1):
                placements, note = _plate(vertex, obj, frames[obj.Name], a, through, tf, m, per_slot, offset)
                spot(placements, obj, through, m)
                if note:
                    notes.append(f"{joint.Label}: {note}")
        return found, notes

    if through is not None:
        tf = frames[through.Name]
        # Where the through profile continues: one way from a corner, both ways at a T-junction.
        sides = [tf.z, tf.z * -1] if through_end is None else [joints._away(tf, through_end)]
        if rule == "Inner faces" and len(sides) > 1:
            sides = context.inner_sides(joint, through, vertex, sides)
        for obj, end, a in butting:
            if abs(a.dot(tf.z)) > joints.PERPENDICULAR:
                continue  # in line with it: no corner
            if _reach(joint, obj, end) > tf.support(a) + short:
                continue
            for n in sides:
                add(obj, frames[obj.Name], a, through, tf, n)

    # Two profiles ending square to each other: the corner between them.
    for i, first in enumerate(butting):
        for second in butting[i + 1:]:
            (p, pe, pa), (q, qe, qa) = sorted((first, second), key=lambda b: _rank(b[2]))
            if abs(pa.dot(qa)) > joints.PERPENDICULAR:
                continue
            pf, qf = frames[p.Name], frames[q.Name]
            # Each end must reach the other profile's face; with 3030 posts and
            # 2020 rails, for example, the post keeps the rails apart.
            if _reach(joint, p, pe) > qf.support(pa) + short or _reach(joint, q, qe) > pf.support(qa) + short:
                continue
            add(p, pf, pa, q, qf, qa)
    return found, notes


def all_joints(doc):
    return [o for o in doc.Objects if joints.is_joint(o)]


def _names(objs):
    return [o.Name for o in objs]


def claimed_joints(obj):
    """Names of the joints that other Brackets objects with their own joint choice place brackets at."""
    claimed = set()
    for other in obj.Document.Objects:
        if other is not obj and is_brackets(other) and not other.AllJoints:
            claimed.update(_names(j for j in other.Joints if joints.is_joint(j)))
    return claimed


def effective_joints(obj):
    """The joints ``obj`` places brackets at.

    With AllJoints, every joint except ExcludedJoints and, with SkipClaimed, the joints another
    Brackets object was given explicitly. Otherwise the Joints list as it is.
    """
    if not obj.AllJoints:
        return list(obj.Joints)
    skip = set(_names(obj.ExcludedJoints))
    if obj.SkipClaimed:
        skip |= claimed_joints(obj)
    return [j for j in all_joints(obj.Document) if j.Name not in skip]


def frame_links(joint_list, frame_joints=None, profiles=None):
    """(FrameJoints, Members) for a Brackets object at ``joint_list``: the other joints and the profiles of its frame."""
    if frame_joints is None:
        frame_joints, profiles = frame_of(joint_list)
    chosen = set(_names(joint_list))
    return [j for j in frame_joints if j.Name not in chosen], profiles


def bracket_transform(obj):
    """From the part's own coordinates to the bracket frame at a corner.

    SourceFrame is undone, the bracket is shifted along its width by
    SlotOffset and, with SwapLegs, turned so the legs change places.
    """
    m = App.Placement(V(0, 0, obj.SlotOffset.Value), App.Rotation()).multiply(obj.SourceFrame.inverse())
    if obj.SwapLegs:
        m = App.Placement(V(), SWAP).multiply(m)
    return m


def _same(a, b):
    if len(a) != len(b):
        return False
    for p, q in zip(a, b):
        if (p.Base - q.Base).Length > 1e-9:
            return False
        if max(abs(x - y) for x, y in zip(p.Rotation.Q, q.Rotation.Q)) > 1e-12:
            return False
    return True


class Brackets:
    Type = TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self._restoring = False
        self.add_properties(obj)
        # With ShowElement on, the link would create an object per bracket,
        # which is not allowed during recompute.
        obj.ShowElement = False
        obj.LinkTransform = False

    def add_properties(self, obj):
        def add(kind, name, group, tip, value=None, mode=None):
            if name in obj.PropertiesList:
                return
            obj.addProperty(kind, name, group, tip)
            if value is not None:
                setattr(obj, name, value)
            if mode is not None:
                obj.setEditorMode(name, mode)

        add("App::PropertyEnumeration", "Rule", "Brackets",
            "Inner faces: at a T-junction, only on the sides facing into the frame, where the profile "
            "running through carries on to another joint; not on a free stub, such as a post standing out "
            "above a rail. All open faces: on both sides.", list(RULES))
        add("App::PropertyBool", "AllJoints", "Brackets",
            "Place brackets at every joint in the document, also at joints made later", False)
        add("App::PropertyEnumeration", "Style", "Brackets",
            "Corner: a bracket in each square corner between two profiles. End plate: a plate across "
            "both profiles on each flush side face of a T-junction, where one profile ends on the side "
            "of another.", list(STYLES))
        add("App::PropertyBool", "PerSlot", "Brackets",
            "End plate: one plate on each slot of the butting profile's face, instead of one plate over "
            "the middle of the face (a plate across several slots)", False)
        add("App::PropertyDistance", "PlateOffset", "Brackets",
            "End plate: move the plate along the butting profile, away from the far face of the profile it "
            "butts (the plate's bar end is flush with that face at 0)", 0.0)
        add("App::PropertyStringList", "SkippedCorners", "Brackets",
            "Corners (see Corners) that get no brackets from this object, for example to use another "
            "bracket there")
        add("App::PropertyStringList", "Corners", "Brackets",
            "Every corner this object could place brackets at, as used by SkippedCorners", mode=2)
        add("App::PropertyStringList", "CornerLabels", "Brackets",
            "Joint, profiles and side of each entry of Corners", mode=1)
        add("App::PropertyBool", "SkipClaimed", "Brackets",
            "With AllJoints: leave out the joints that another Brackets object was given explicitly, so "
            "different brackets can be used at different joints without doubling up", False)
        add("App::PropertyLinkList", "ExcludedJoints", "Brackets",
            "With AllJoints: joints that get no brackets from this object")
        add("App::PropertyLinkList", "Joints", "Brackets", "Joints whose corners get brackets")
        add("App::PropertyLinkList", "Members", "Brackets",
            "Profiles of the frame that the joints are in, so the brackets follow their changes", mode=2)
        add("App::PropertyLinkList", "FrameJoints", "Brackets",
            "The frame's other joints, which decide which sides of a T-junction face into the frame", mode=2)
        add("App::PropertyPlacement", "SourceFrame", "Brackets",
            "Bracket frame in the part's own coordinates: origin where the two contact faces meet, "
            "in the middle of the width; +X along the leg on the profile that ends at the joint, +Y along "
            "the leg on the profile it meets. Set by Calibrate bracket.")
        add("App::PropertyBool", "SwapLegs", "Brackets",
            "Put the first leg on the other profile (for brackets with unequal legs)", False)
        add("App::PropertyDistance", "SlotOffset", "Brackets",
            "Shift along the bracket's width, for a bracket whose slot key is not in the middle", 0.0)
        add("App::PropertyString", "Item", "Order",
            "Name in the cut list's hardware list; empty uses the bracket part's label")
        add("App::PropertyString", "ArticleNumber", "Order",
            "Your supplier's article number, shown in the cut list's hardware list")
        add("App::PropertyInteger", "Count", "Brackets", "Number of brackets placed", mode=1)
        add("App::PropertyStringList", "Positions", "Brackets",
            "Joint and profiles of each bracket, in the order of PlacementList", mode=1)
        add("App::PropertyStringList", "Notes", "Brackets", "Joints that got no brackets, and why", mode=1)
        for name in ("Count", "Positions", "Notes", "Corners", "CornerLabels"):
            obj.setPropertyStatus(name, "Output")
        # The link array is an output of execute().
        for name, mode in (("ElementCount", 1), ("PlacementList", 1), ("ShowElement", 2), ("LinkTransform", 2),
                           ("LinkCopyOnChange", 2), ("LinkPlacement", 2), ("Placement", 1)):
            if name in obj.PropertiesList:
                obj.setEditorMode(name, mode)

    def onDocumentRestored(self, obj):
        self._restoring = True
        try:
            self.add_properties(obj)
            if list(obj.getEnumerationsOfProperty("Rule")) != list(RULES):
                rule = obj.Rule
                obj.Rule = list(RULES)
                obj.Rule = rule if rule in RULES else RULES[0]
            if list(obj.getEnumerationsOfProperty("Style")) != list(STYLES):
                style = obj.Style
                obj.Style = list(STYLES)
                obj.Style = style if style in STYLES else STYLES[0]
        finally:
            self._restoring = False
        obj.setEditorMode("Joints", 1 if obj.AllJoints else 0)

    def onChanged(self, obj, prop):
        if prop == "AllJoints" and "Joints" in obj.PropertiesList:
            obj.setEditorMode("Joints", 1 if obj.AllJoints else 0)  # only the view changes

    def mustExecute(self, obj):
        # A joint made later (the Joints command after adding a profile)
        # touches nothing this object depends on, and neither does a profile
        # joined to the frame later.
        if "FrameJoints" not in obj.PropertiesList:
            return False
        if obj.AllJoints and _names(effective_joints(obj)) != _names(obj.Joints):
            return True
        others, profiles = frame_links([j for j in obj.Joints if joints.is_joint(j)])
        return _names(others) != _names(obj.FrameJoints) or _names(profiles) != _names(obj.Members)

    def execute(self, obj):
        if obj.AllJoints:
            everything = effective_joints(obj)
            if _names(obj.Joints) != _names(everything):
                obj.Joints = everything
        joint_list = [j for j in obj.Joints if joints.is_joint(j)]
        context = FrameInfo(joint_list)
        others, profiles = frame_links(joint_list, context.joints, context.profiles)
        if _names(obj.FrameJoints) != _names(others):
            obj.FrameJoints = others
        if _names(obj.Members) != _names(profiles):
            obj.Members = profiles
        if obj.LinkedObject is None:
            # FreeCAD puts the label in front of the message.
            raise ValueError("no bracket part; set LinkedObject to the bracket (for example an imported STEP body)")
        found, notes, corners = [], [], {}
        skipped = set(obj.SkippedCorners)
        for joint in joint_list:
            try:
                spots, why = joint_spots(joint, obj.Rule, context, obj.Style, obj.PerSlot, obj.PlateOffset.Value)
            except ValueError as e:
                spots, why = [], [f"{joint.Label} gets no brackets: {e}"]
            for pl, a, b, (key, label) in spots:
                corners[key] = label
                if key not in skipped:
                    found.append((joint, pl, a, b))
            notes += why
        notes = list(dict.fromkeys(notes))  # both sides of a T-junction give the same note
        if not found and not notes:
            notes.append("every corner is switched off in SkippedCorners" if corners else
                         "no corners for brackets found; check the joints, closed faces and Rule")
        if list(obj.Corners) != list(corners):
            obj.Corners = list(corners)
        if list(obj.CornerLabels) != list(corners.values()):
            obj.CornerLabels = list(corners.values())

        local = bracket_transform(obj)
        inverse = obj.Placement.inverse()
        placements = [inverse.multiply(pl).multiply(local) for _j, pl, _a, _b in found]
        # A link array without elements shows the part once, at the origin.
        # Keep one hidden element instead, so nothing stray is shown.
        empty = not placements
        was_empty = obj.Count == 0 and list(obj.VisibilityList)[:1] == [False]
        if empty:
            placements = [App.Placement()]
        if not _same(list(obj.PlacementList), placements):
            obj.PlacementList = placements
        if obj.ElementCount != len(placements):
            obj.ElementCount = len(placements)
        if empty and list(obj.VisibilityList)[:1] != [False]:
            obj.setElementVisible("0", False)
        elif not empty and was_empty:
            obj.setElementVisible("0", True)

        positions = [f"{j.Label}: {a.Label} / {b.Label}" for j, _pl, a, b in found]
        if obj.Count != len(found):
            obj.Count = len(found)
        if list(obj.Positions) != positions:
            obj.Positions = positions
        if list(obj.Notes) != notes:
            obj.Notes = notes
        return False  # let App::Link finish its own recompute

    def dumps(self):
        return None

    def loads(self, state):
        self._restoring = False
        return None

    __getstate__ = dumps
    __setstate__ = loads


def make_brackets(doc, part, joint_list, frame=None, **props):
    """Create a Brackets object placing ``part`` at the corners of ``joint_list``.

    ``frame`` is the SourceFrame (see ``calibrate``); without it the part is
    used as modelled: contact corner at its origin, legs along +X and +Y.
    """
    obj = doc.addObject("App::LinkPython", "Brackets")
    Brackets(obj)
    obj.LinkedObject = part
    obj.Joints = list(joint_list)
    obj.FrameJoints, obj.Members = frame_links(list(joint_list))
    if frame is not None:
        obj.SourceFrame = frame
    for name, value in props.items():
        setattr(obj, name, value)
    if App.GuiUp:
        ViewProviderBrackets(obj.ViewObject)
    return obj


# ---- calibration ------------------------------------------------------------------


def _normal(face):
    """Unit normal of a flat face (outward for a face of a solid), or None if it is not flat."""
    if not isinstance(getattr(face, "Surface", None), Part.Plane):
        finder = getattr(face, "findPlane", None)
        if finder is None or finder() is None:
            return None
    u0, u1, v0, v1 = face.ParameterRange
    n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    n.normalize()
    return n


def contact_frame(face_a, face_b, part=None, vertex=None):
    """The bracket frame from its two contact faces, in the part's own coordinates.

    ``face_a`` is the face that lies on the profile ending at the joint,
    ``face_b`` the one on the profile it meets. The origin goes on the line
    where their planes meet, in the middle of ``part`` (the whole bracket
    shape) along that line, so the bracket sits centred on the slot. A picked
    corner ``vertex`` is only checked. Returns (SourceFrame, notes).
    """
    normals = [_normal(f) for f in (face_a, face_b)]
    if None in normals:
        raise ValueError("The contact faces must be flat")
    na, nb = normals
    c = na.dot(nb)
    if abs(c) > SQUARE:
        angle = math.degrees(math.acos(min(1.0, abs(c))))
        raise ValueError(f"The two faces are at {90 - angle:.1f}° or {90 + angle:.1f}° to each other; "
                         "pick two faces at 90°, the ones that touch the two profiles")
    # A point on both planes: the line where the contact faces meet.
    ca, cb = face_a.CenterOfMass, face_b.CenterOfMass
    da, db = na.dot(ca), nb.dot(cb)
    p0 = (na * (da - db * c) + nb * (db - da * c)) * (1.0 / (1 - c * c))
    along = na.cross(nb)
    along.normalize()
    # Each leg runs from that line towards the middle of its face.
    x = along.cross(na)
    if x.dot(ca - p0) < 0:
        x = x * -1
    y = along.cross(nb)
    if y.dot(cb - p0) < 0:
        y = y * -1
    frame = _placement(p0, x, y)
    notes = []
    shape = part if part is not None and not part.isNull() else Part.Compound([face_a, face_b])
    if shape.Solids:
        # On a solid the face normals point out of the material: the contact
        # faces must face away from the legs (-Y and -X in the bracket frame).
        wrong = (na.dot(frame.Rotation.multVec(V(0, 1, 0))) > 0) + (nb.dot(frame.Rotation.multVec(V(1, 0, 0))) > 0)
        if wrong == 2:
            raise ValueError("These faces are on the inside of the bracket's corner; pick the two outer faces "
                             "that touch the profiles")
        if wrong == 1:
            notes.append("one of the picked faces faces into the bracket; check that both touch a profile")
    bb = shape.transformed(frame.inverse().toMatrix()).BoundBox
    origin = frame.multVec(V(0, 0, (bb.ZMin + bb.ZMax) / 2))
    result = _placement(origin, frame.Rotation.multVec(V(1, 0, 0)), frame.Rotation.multVec(V(0, 1, 0)))
    if vertex is not None:
        off = vertex - p0
        off = off - along * off.dot(along)
        if off.Length > 1.0:
            notes.append(f"the picked vertex is {off.Length:.1f} mm from where the two faces meet; "
                         "check that you picked the contact faces")
    return result, notes


def plate_frame(face_contact, face_end, part=None):
    """The plate frame from its two faces, in the part's own coordinates.

    ``face_contact`` is the flat face that lies on the profiles, ``face_end`` the face at the end of the
    plate's stem (the part that lies on the butting profile). In the frame, the contact face is the XY
    plane facing -Z (the plate lies on +Z), +X runs along the stem, away from the bar, and the origin is
    at the bar's outer end (the end opposite the stem), in the middle of the plate's width. Returns
    (SourceFrame, notes).
    """
    normals = [_normal(f) for f in (face_contact, face_end)]
    if None in normals:
        raise ValueError("The plate's faces must be flat")
    nc, ne = normals
    if abs(nc.dot(ne)) > SQUARE:
        raise ValueError("The two faces must be square to each other: the face that lies on the profiles, and "
                         "the face at the end of the plate's stem")
    z = nc * -1
    frame = _placement(face_contact.CenterOfMass, ne, z.cross(ne))
    shape = part if part is not None and not part.isNull() else Part.Compound([face_contact, face_end])
    notes = []
    bb = shape.transformed(frame.inverse().toMatrix()).BoundBox
    if shape.Solids:
        if bb.ZMax < 0.5:
            raise ValueError("The first face is the one on the plate's far side; pick the face that lies on the "
                             "profiles")
        if bb.ZMin < -0.5:
            notes.append("part of the plate lies below the face picked as the one on the profiles; check the pick")
    end_x = frame.inverse().multVec(face_end.CenterOfMass).x
    if abs(end_x - bb.XMax) > 0.5:
        notes.append("the second face is not at the end of the plate; check that it is the end of the stem")
    origin = frame.multVec(V(bb.XMin, (bb.YMin + bb.YMax) / 2, 0))
    return _placement(origin, frame.Rotation.multVec(V(1, 0, 0)), frame.Rotation.multVec(V(0, 1, 0))), notes


def _frame_object(obj):
    return feature.is_profile(obj) or joints.is_joint(obj) or panels.is_panel(obj) or is_brackets(obj)


def holds_frame(obj, _seen=None):
    """Whether ``obj`` is, links to, or holds (in a group or App::Part) a profile, joint, panel or Brackets object.

    Such an object cannot be the bracket part: the brackets would show the
    frame itself in every corner.
    """
    seen = set() if _seen is None else _seen
    if obj is None or (obj.Document.Name, obj.Name) in seen:
        return False
    seen.add((obj.Document.Name, obj.Name))
    if _frame_object(obj):
        return True
    linked = obj.getLinkedObject(True)
    if linked is not None and linked != obj and holds_frame(linked, seen):
        return True
    return any(holds_frame(child, seen) for child in (getattr(obj, "Group", None) or []))


def _assembly(obj):
    """An App::Part, or a link to one: a container with its own placement."""
    target = obj.getLinkedObject(True)
    return target is not None and target.isDerivedFrom("App::Part")


def _one_bracket(container):
    """Whether an App::Part holds one bracket (a STEP import: a body, maybe with its screws).

    Not when it holds profiles and the like, or other App::Parts: then it is
    the frame, a whole design or a library of brackets.
    """
    target = container.getLinkedObject(True)
    if holds_frame(target):
        return False
    return not any(_assembly(child) for child in target.Group if not child.isDerivedFrom("App::Origin"))


def resolve(root, sub):
    """(object, subname below it) of the bracket part that a pick is on.

    ``root`` and ``sub`` are the top-level object and full subname of the
    pick. The part is the object the picked face belongs to (a Part feature, a
    PartDesign body, a link to one), or the App::Part directly around it when
    that holds just this bracket, as a STEP import does. Plain groups (they have
    no placement), a design or a library of brackets around it are passed. A
    pick on a bracket placed by a Brackets object gives that object.
    """
    path = [(root, sub)]
    obj, rest = root, sub
    while "." in rest and not is_brackets(obj):
        head, tail = rest.split(".", 1)
        child = obj.getSubObject(head + ".", 1)
        if child is None:
            break
        obj, rest = child, tail
        path.append((obj, rest))
    for obj, rest in path:
        if is_brackets(obj):
            return obj, rest
    k = next((i for i, (o, _r) in enumerate(path)
              if not (o.isDerivedFrom("App::DocumentObjectGroup") or _assembly(o))), len(path) - 1)
    if k > 0 and _assembly(path[k - 1][0]) and _one_bracket(path[k - 1][0]):
        k -= 1
    return path[k]


def calibrate(picks, style="Corner"):
    """(part, SourceFrame, notes) from picks on a bracket part.

    ``picks`` are (top-level object, subname) pairs in pick order, as an
    unresolved selection gives them: two faces, and for the Corner style
    optionally the corner vertex. For Corner they are the contact faces, first
    the one on the profile that ends at the joint (see ``contact_frame``); for
    End plate the face that lies on the profiles, then the one at the end of
    the stem (see ``plate_frame``). They may be on the part itself (also inside
    an App::Part, as STEP imports are) or on a bracket placed by a Brackets
    object.
    """
    resolved = [resolve(root, sub) for root, sub in picks]
    if len({obj.Name for obj, _sub in resolved}) != 1:
        raise ValueError("Pick the contact faces on one bracket part")
    obj = resolved[0][0]
    part = obj.LinkedObject if is_brackets(obj) else obj
    if part is None:
        raise ValueError(f"{obj.Label} has no bracket part")
    if holds_frame(part):
        raise ValueError(f"{part.Label} is or holds a profile, joint or panel of the frame, so it cannot be the "
                         "bracket; pick the contact faces on the bracket part itself")
    faces, vertex = [], None
    for _obj, sub in resolved:
        element = sub.rsplit(".", 1)[-1]
        if not element.startswith(("Face", "Vertex")):
            continue
        shape = obj.getSubObject(sub, 0, App.Matrix(), False)
        if not isinstance(shape, Part.Shape) or shape.isNull():
            raise ValueError(f"{obj.Label} has no element {sub}")
        if is_brackets(obj):
            # Picked on placed bracket i: back into the part's own coordinates.
            index = int(sub.split(".", 1)[0])
            shape = shape.transformed(obj.PlacementList[index].inverse().toMatrix())
        if element.startswith("Face"):
            faces.append(shape)
        else:
            vertex = shape.Vertexes[0].Point
    if len(faces) != 2:
        if style == "End plate":
            raise ValueError(f"Pick the plate's two faces ({len(faces)} face(s) picked): first the one that lies "
                             "on the profiles, then the one at the end of its stem")
        raise ValueError(f"Pick the bracket's two contact faces ({len(faces)} face(s) picked): first the one "
                         "on the profile that ends at the joint, then the one on the profile it meets")
    whole = Part.getShape(part, "", transform=False)
    if style == "End plate":
        frame, notes = plate_frame(faces[0], faces[1], whole)
    else:
        frame, notes = contact_frame(faces[0], faces[1], whole, vertex)
    return part, frame, notes


# ---- reporting --------------------------------------------------------------------


def _status(obj):
    try:
        return obj.getStatusString()
    except Exception:  # noqa: BLE001
        return "error"


def problem(obj):
    """Why a Brackets object's count cannot be trusted, or None (see feature.problem)."""
    if not obj.isValid():
        return _status(obj)
    if obj.LinkedObject is None:
        return "no bracket part (its part was deleted?); set LinkedObject"
    for joint in obj.Joints:
        if not joint.isValid():
            return f"its joint {joint.Label} has an error"
    if "Touched" in obj.State:
        return "not recomputed (recompute the document, or fix the object it depends on)"
    return None


def item_name(obj):
    if obj.Item.strip():
        return obj.Item.strip()
    return obj.LinkedObject.Label if obj.LinkedObject is not None else obj.Label


def hardware(doc):
    """[(qty, item, article number, objects)] of the placed brackets, identical items added up.

    Objects with a problem are left out: the cut list lists them as errors.
    """
    rows = OrderedDict()
    for obj in doc.Objects:
        if is_brackets(obj) and not problem(obj) and obj.Count:
            entry = rows.setdefault((item_name(obj), obj.ArticleNumber.strip()), [0, []])
            entry[0] += obj.Count
            entry[1].append(obj.Label)
    return [(qty, item, article, ", ".join(labels)) for (item, article), (qty, labels) in sorted(rows.items())]


def notes(doc):
    """The notes of all Brackets objects, for the cut list."""
    return [f"{obj.Label}: {note}" for obj in doc.Objects if is_brackets(obj) and not problem(obj)
            for note in obj.Notes]


def info(obj):
    """Summary for the task panel."""
    joint_count = len({p.split(":", 1)[0] for p in obj.Positions})
    lines = [f"{obj.Count} bracket(s) at {joint_count} joint(s)"]
    lines += list(obj.Notes)
    return "<br>".join(html.escape(line) for line in lines)


class ViewProviderBrackets:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return os.path.join(feature.ICON_DIR, "Brackets.svg")

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from .brackets_ui import task_panel
        Gui.Control.showDialog(task_panel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        Gui.Control.closeDialog()
        return True

    def onDelete(self, vobj, subelements):
        # The Brackets command hid the part; show it again when nothing else places it.
        try:
            obj = vobj.Object
            part = obj.LinkedObject
            others = [o for o in obj.Document.Objects if is_brackets(o) and o != obj and o.LinkedObject == part]
            if part is not None and not others and getattr(part, "ViewObject", None) is not None:
                part.ViewObject.Visibility = True
        except Exception:  # noqa: BLE001  (never block the deletion)
            pass
        return True

    def doubleClicked(self, vobj):
        # Not through setEdit: a link without elements would edit its part instead.
        import FreeCADGui as Gui
        from .brackets_ui import task_panel
        if not Gui.Control.activeDialog():
            Gui.Control.showDialog(task_panel(vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads
