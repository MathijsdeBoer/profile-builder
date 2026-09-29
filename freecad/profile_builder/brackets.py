"""Brackets: the user's own bracket part, placed in the corners of the joints.

A Brackets object places one bracket part, typically a supplier's STEP file
imported into the document, in the corners of the butt joints. It is an
App::LinkPython link array: LinkedObject is the part, and execute() writes
ElementCount and PlacementList. The part is shown once per position without
being copied, so it keeps its STEP colours and stays light, and no objects are
created during recompute (``ShowElement`` stays off).

Dependencies stay acyclic. The object links to its Joints and, through the
hidden Members list, to the profiles at them, so it recomputes after them
when a sketch, a profile (size, Spin) or a joint (swap, rule) changes.
Profiles and joints never link to it.

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

from . import feature, joints

V = App.Vector

TYPE = "ProfileBuilder::Brackets"
RULES = ("Inner faces", "All open faces")
FIELDS = ("Rule", "SwapLegs", "SlotOffset", "Item", "ArticleNumber")
SLOT_TOLERANCE = 0.5  # mm: the slots of the two contact faces must line up this well
MEET = 0.01  # mm: how far a butting end may stop short of the other profile's face
OUTWARD = 1.0  # mm: a T-junction side faces out of the frame only beyond this
SQUARE = 0.02  # |cos| below which two contact faces count as square to each other (about 1 degree)
SWAP = App.Rotation(V(1, 1, 0), 180)  # swaps the legs: X <-> Y, Z -> -Z
FACE_AXES = (("Right", "x", 1), ("Left", "x", -1), ("Top", "y", 1), ("Bottom", "y", -1))


def is_brackets(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == TYPE


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
    """Sort key for directions: X before Y before Z, as the joints break ties."""
    return tuple(-round(abs(c), 6) for c in (u.x, u.y, u.z))


# ---- where the brackets go ------------------------------------------------------


def face_slots(obj, frame, normal, across):
    """Slot centre lines on the face of a profile whose outward normal is ``normal``.

    They are returned as distances along ``across`` from the profile's axis
    line. None when the profile has no face that way (it is turned by Spin) or
    the face is closed.
    """
    for name, axis, sign in FACE_AXES:
        if (getattr(frame, axis) * sign).dot(normal) > joints.PARALLEL:
            break
    else:
        return None
    if getattr(obj, f"Closed{name}"):
        return None
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
    if not mine or not theirs:
        return [], None
    corner = vertex + a * second_frame.support(a) + n * first_frame.support(n)
    found = [_placement(corner + across * ((s + t) / 2), a, n)
             for s in mine for t in theirs if abs(s - t) <= SLOT_TOLERANCE]
    if not found:
        return [], f"the slots of {first.Label} and {second.Label} do not line up, so that corner gets no bracket"
    return found, None


def _reach(joint, obj, end):
    """How far the end of a butting profile is from the joint vertex, along the profile."""
    offset, _miter, _axis = joints.adjustment(joint, obj, end)
    return -(offset + getattr(obj, f"Extend{end}").Value)


def joint_spots(joint, rule, centre):
    """([(placement, profile on leg 1, profile on leg 2)], [notes]) for one joint.

    Brackets go into every square corner of a butt joint:
    - between a profile that ends at the joint and the one that runs through
      (on the side where that one continues; both sides at a T-junction, or
      only the side facing ``centre`` with the "Inner faces" rule);
    - between two profiles that end square to each other against the same
      profile, when both ends reach the other's face.
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

    def add(first, first_frame, a, second, second_frame, n):
        placements, note = _corner(vertex, first, first_frame, a, second, second_frame, n)
        found.extend((pl, first, second) for pl in placements)
        if note:
            notes.append(f"{joint.Label}: {note}")

    if through is not None:
        tf = frames[through.Name]
        # Where the through profile continues: one way from a corner, both ways at a T-junction.
        sides = [tf.z, tf.z * -1] if through_end is None else [joints._away(tf, through_end)]
        for obj, _end, a in butting:
            if abs(a.dot(tf.z)) > joints.PERPENDICULAR:
                continue  # in line with it: no corner
            for n in sides:
                if rule == "Inner faces" and len(sides) > 1 and n.dot(centre - vertex) < -OUTWARD:
                    continue  # the side of a T-junction that faces out of the frame
                add(obj, frames[obj.Name], a, through, tf, n)

    # Two profiles ending square to each other: the corner between them.
    for i, first in enumerate(butting):
        for second in butting[i + 1:]:
            (p, pe, pa), (q, qe, qa) = sorted((first, second), key=lambda b: _rank(b[2]))
            if abs(pa.dot(qa)) > joints.PERPENDICULAR:
                continue
            pf, qf = frames[p.Name], frames[q.Name]
            # A profile stopped short of the other one's face (e.g. by a wider
            # through profile) leaves no closed corner between them.
            if _reach(joint, p, pe) > qf.support(pa) + MEET or _reach(joint, q, qe) > pf.support(qa) + MEET:
                continue
            add(p, pf, pa, q, qf, qa)
    return found, notes


def members_of(joint_list):
    """The profiles at the joints (ending or passing through), each once."""
    found = OrderedDict()
    for joint in joint_list:
        for obj, _end in joints.ends_of(joint):
            found.setdefault(obj.Name, obj)
        for obj in joints.passing_of(joint):
            found.setdefault(obj.Name, obj)
    return list(found.values())


def frame_centre(members):
    """Middle of the frame: the midpoints of the members' path edges, weighted by length."""
    total, acc = 0.0, V()
    for obj in members:
        try:
            edge = feature.path_edge(obj)
        except ValueError:
            continue
        if edge is None:
            continue
        mid = (edge.Vertexes[0].Point + edge.Vertexes[-1].Point) * 0.5
        acc += mid * edge.Length
        total += edge.Length
    return acc * (1.0 / total) if total else acc


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
            "Inner faces: at a T-junction, only on the side facing the middle of the frame. "
            "All open faces: on both sides.", list(RULES))
        add("App::PropertyLinkList", "Joints", "Brackets", "Joints whose corners get brackets")
        add("App::PropertyLinkList", "Members", "Brackets",
            "Profiles at the joints, so the brackets follow their changes", mode=2)
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
        for name in ("Count", "Positions", "Notes"):
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
        finally:
            self._restoring = False

    def execute(self, obj):
        if obj.LinkedObject is None:
            # FreeCAD puts the label in front of the message.
            raise ValueError("no bracket part; set LinkedObject to the bracket (for example an imported STEP body)")
        joint_list = [j for j in obj.Joints if joints.is_joint(j)]
        members = members_of(joint_list)
        if [m.Name for m in obj.Members] != [m.Name for m in members]:
            obj.Members = members
        centre = frame_centre(members)
        found, notes = [], []
        for joint in joint_list:
            try:
                spots, why = joint_spots(joint, obj.Rule, centre)
            except ValueError as e:
                spots, why = [], [f"{joint.Label} gets no brackets: {e}"]
            found += [(joint, pl, a, b) for pl, a, b in spots]
            notes += why
        notes = list(dict.fromkeys(notes))  # both sides of a T-junction give the same note
        if not found and not notes:
            notes.append("no corners for brackets found; check the joints, closed faces and Rule")

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
    obj.Members = members_of(joint_list)
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


def resolve(root, sub):
    """(object, subname below it) for a pick, skipping plain groups (they have no placement)."""
    obj = root
    while obj.isDerivedFrom("App::DocumentObjectGroup") and "." in sub:
        head, rest = sub.split(".", 1)
        child = obj.getSubObject(head + ".", 1)
        if child is None:
            break
        obj, sub = child, rest
    return obj, sub


def calibrate(picks):
    """(part, SourceFrame, notes) from picks on a bracket part.

    ``picks`` are (top-level object, subname) pairs in pick order, as an
    unresolved selection gives them: two contact faces, first the one on the
    profile that ends at the joint, and optionally the corner vertex. They may
    be on the part itself (also inside an App::Part, as STEP imports are) or on
    a bracket placed by a Brackets object.
    """
    resolved = [resolve(root, sub) for root, sub in picks]
    if len({obj.Name for obj, _sub in resolved}) != 1:
        raise ValueError("Pick the contact faces on one bracket part")
    obj = resolved[0][0]
    part = obj.LinkedObject if is_brackets(obj) else obj
    if part is None:
        raise ValueError(f"{obj.Label} has no bracket part")
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
        raise ValueError(f"Pick the bracket's two contact faces ({len(faces)} face(s) picked): first the one "
                         "on the profile that ends at the joint, then the one on the profile it meets")
    whole = Part.getShape(part, "", transform=False)
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

    def _panel(self, obj):
        from .simple_panel import PropertyTaskPanel
        return PropertyTaskPanel(obj, FIELDS, "Brackets", info)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        Gui.Control.showDialog(self._panel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        # Not through setEdit: a link without elements would edit its part instead.
        import FreeCADGui as Gui
        if not Gui.Control.activeDialog():
            Gui.Control.showDialog(self._panel(vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads
