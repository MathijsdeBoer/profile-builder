"""Carriages running along a profile: clear run, usable stroke and position.

A Carriage links to a rail profile (``Rail``) and runs on one of its faces. It
is a parametric envelope: ``CarriageLength`` along the rail,
``EnvelopeWidth`` across the face, ``EnvelopeHeight`` out of it and ``Wrap``
back past it, around the sides of the rail (V-wheel plates wrap the side
faces, a guide screwed onto the face does not).

The clear run comes from the members that really block that envelope: every
other profile, every panel and the listed ``Obstacles`` whose shape enters the
envelope swept along the rail. A member butting against another face of the
rail does not block the carriage; a T-junction member on its face does, and
splits the rail into runs. The stroke is the run minus the carriage and an
end stop at each end, and a warning is given when it is below
``RequiredStroke``. The rules are in ``stroke.py``.

An optional belt drive (``BeltItem`` and the pulley sizes) gives the length
of the open belt, which the cut list shows as metre ware (``metreware.py``).

The carriage only reads the rail and the other members and never writes to
them: the rail's length must not depend on the carriage, or there would be a
dependency cycle. It links to the members it checks (``Neighbours``), so it
recomputes after them when they change. New profiles and panels made by the
workbench mark carriages for recompute (``touch_carriages``); a member added
another way is found the next time the carriage recomputes.
"""

import html
import math
import os

import FreeCAD as App
import Part

from . import feature, panels, profiles, stroke

V = App.Vector

TOL = 0.01  # mm: a member this close to the envelope only touches it
PLACEHOLDER_COLOR = (0.90, 0.70, 0.25)


def is_carriage(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "ProfileBuilder::Carriage"


def length_text(value):
    """A length in the user's unit system and number format, e.g. '580.00 mm' or '22.83 in'."""
    try:
        return App.Units.Quantity(float(value), App.Units.Length).UserString
    except Exception:  # noqa: BLE001
        return f"{value:g} mm"


def frame_placement(frame):
    """Placement that maps the rail's local coordinates (x, y, s along the axis) to the world."""
    x, y, z, o = frame.x, frame.y, frame.z, frame.origin
    return App.Placement(App.Matrix(x.x, y.x, z.x, o.x,
                                    x.y, y.y, z.y, o.y,
                                    x.z, y.z, z.z, o.z,
                                    0, 0, 0, 1))


def rail_extent(rail, frame, face, width):
    """(start, end) of the rail under the carriage, along the axis of its frame.

    Mitered ends make the face the carriage runs on shorter or longer than the
    axis; the part of the face under the carriage decides.
    """
    s0 = (rail.Placement.Base - frame.origin).dot(frame.z)
    length = rail.Length.Value
    x0, x1, y0, y1 = frame.rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    lo, hi = s0, s0 + length
    for px, py in stroke.face_under(face, frame.rect, width):
        for end in ("Start", "End"):
            angle = getattr(rail, f"Miter{end}").Value
            if abs(angle) < 1e-9:
                continue
            axis = getattr(rail, f"Miter{end}Axis", "") or rail.MiterAcross
            # See geometry.make_solid: a positive miter makes the + side long.
            shift = ((px - cx) if axis == "X" else (py - cy)) * math.tan(math.radians(angle))
            if end == "Start":
                lo = max(lo, s0 - shift)
            else:
                hi = min(hi, s0 + length + shift)
    return lo, hi


def _local_box(frame, bb):
    """Bounding box (x0, x1, y0, y1, s0, s1) in the rail's frame of a world bounding box.

    Conservative: for a member at an angle to the rail it is larger than the member.
    """
    xs, ys, ss = [], [], []
    for px in (bb.XMin, bb.XMax):
        for py in (bb.YMin, bb.YMax):
            for pz in (bb.ZMin, bb.ZMax):
                d = V(px, py, pz) - frame.origin
                xs.append(d.dot(frame.x))
                ys.append(d.dot(frame.y))
                ss.append(d.dot(frame.z))
    return min(xs), max(xs), min(ys), max(ys), min(ss), max(ss)


def blocked_interval(shape, frame, env, lo, hi):
    """(s0, s1) where a shape enters the carriage envelope swept from lo to hi, or None.

    The envelope is shrunk by TOL, so a member that only touches it (one
    butting against another face of the rail) does not block. A 1 mm slab
    beyond each rail end is included, so a post the rail butts against is
    found as what limits the run there.
    """
    if shape is None or shape.isNull():
        return None
    ex0, ex1, ey0, ey1 = env[0] + TOL, env[1] - TOL, env[2] + TOL, env[3] - TOL
    a, b = lo - 1.0, hi + 1.0
    bx0, bx1, by0, by1, bs0, bs1 = _local_box(frame, shape.BoundBox)
    if not (bx0 < ex1 and ex0 < bx1 and by0 < ey1 and ey0 < by1 and bs0 < b and a < bs1):
        return None
    if not shape.Solids:
        return max(bs0, a), min(bs1, b)  # nothing to intersect: use the box
    placement = frame_placement(frame)
    prism = Part.makeBox(ex1 - ex0, ey1 - ey0, b - a, V(ex0, ey0, a))
    prism.Placement = placement
    try:
        common = shape.common(prism)
    except Exception:  # noqa: BLE001  (a failed boolean: fall back to the box)
        return max(bs0, a), min(bs1, b)
    if common.isNull() or common.Volume < 1e-6:
        return None
    common.Placement = placement.inverse().multiply(common.Placement)
    box = common.BoundBox
    return box.ZMin, box.ZMax


def neighbours(obj):
    """The profiles and panels that can block the carriage (all but its rail and what depends on it)."""
    rail = obj.Rail
    skip = {o.Name for o in obj.InListRecursive} | {obj.Name}
    if rail is not None:
        skip.add(rail.Name)
    return [o for o in obj.Document.Objects
            if (feature.is_profile(o) or panels.is_panel(o)) and o.Name not in skip]


def obstacles(obj):
    """The listed obstacles, without the rail and anything that depends on the carriage."""
    skip = {o.Name for o in obj.InListRecursive} | {obj.Name}
    if obj.Rail is not None:
        skip.add(obj.Rail.Name)
    return [o for o in obj.Obstacles if o is not None and o.Name not in skip and hasattr(o, "Shape")]


def face_at(rail, point):
    """The side face of a rail nearest to a world point (where the user clicked), or None.

    None when the point is not near a side face, for example on an end face.
    """
    frame = feature.member_frame(rail)
    d = point - frame.origin
    x, y = d.dot(frame.x), d.dot(frame.y)
    x0, x1, y0, y1 = frame.rect
    distance = {"Top": abs(y - y1), "Bottom": abs(y - y0), "Left": abs(x - x0), "Right": abs(x - x1)}
    face = min(distance, key=distance.get)
    return face if distance[face] <= 0.35 * rail.CellSize.Value else None


def touch_carriages(doc):
    """Mark the carriages of a document for recompute, so they check a member that was just added.

    A carriage links to the members that exist when it recomputes; a new
    profile or panel is only found by its next recompute.
    """
    for obj in doc.Objects:
        if is_carriage(obj):
            obj.touch()


def face_width(rail, face):
    return (rail.Columns if face in ("Top", "Bottom") else rail.Rows) * rail.CellSize.Value


class Carriage:
    Type = "ProfileBuilder::Carriage"

    def __init__(self, obj):
        obj.Proxy = self
        self._restoring = False
        self.add_properties(obj)
        self._update_editor_modes(obj)

    def add_properties(self, obj):
        def add(kind, name, group, tip, value=None, mode=None):
            if name in obj.PropertiesList:
                return
            obj.addProperty(kind, name, group, tip)
            if value is not None:
                setattr(obj, name, value)
            if mode is not None:
                obj.setEditorMode(name, mode)

        add("App::PropertyLinkGlobal", "Rail", "Carriage", "Profile the carriage runs on")
        add("App::PropertyEnumeration", "Face", "Carriage",
            "Face of the rail the carriage runs on, as named on the profile's section: Top is its local +Y "
            "side, the upper face of a horizontal rail without Spin", list(profiles.FACES))
        add("App::PropertyLength", "CarriageLength", "Carriage", "Length of the carriage along the rail", 60.0)
        add("App::PropertyLength", "EnvelopeWidth", "Carriage",
            "Width of the carriage across the face, centred on the face", 20.0)
        add("App::PropertyLength", "EnvelopeHeight", "Carriage", "How far the carriage stands out from the face", 10.0)
        add("App::PropertyLength", "Wrap", "Carriage",
            "How far the carriage reaches back past the face, around the sides of the rail. V-wheel plates wrap "
            "the side faces; 0 for a guide on the face only.", 0.0)
        add("App::PropertyLength", "EndStopLength", "Carriage",
            "Length taken at each end of the run by an end stop, bumper or limit switch", 0.0)
        add("App::PropertyLinkListGlobal", "Obstacles", "Carriage",
            "Other objects that can block the carriage, such as brackets or motor mounts. "
            "Profiles and panels are found automatically.")
        add("App::PropertyLinkGlobal", "Body", "Carriage",
            "Shown instead of the placeholder box, for example an imported STEP model. Model it with X across "
            "the face, Y out of the face and Z along the rail, the origin at the carriage centre on the face; "
            "its own placement is ignored.")
        add("App::PropertyPlacement", "BodyPlacement", "Carriage", "Adjusts Body in the carriage's coordinates")

        add("App::PropertyLength", "RequiredStroke", "Motion",
            "Stroke the axis needs; a warning is given when the rail cannot give it (0: not checked)", 0.0)
        add("App::PropertyIntegerConstraint", "Run", "Motion",
            "Which free run of the rail the carriage is on when members split it: 0 the longest, "
            "1 the first from the rail start, 2 the next, ...", (0, 0, 99, 1))
        add("App::PropertyEnumeration", "PositionMode", "Motion",
            "Percent: PositionPercent of the stroke. Distance: Position, the travel from the start of the stroke.",
            list(stroke.POSITION_MODES))
        add("App::PropertyFloatConstraint", "PositionPercent", "Motion",
            "Position in percent of the stroke (0: against the end stop at the start of the run)",
            (0.0, 0.0, 100.0, 1.0))
        add("App::PropertyDistance", "Position", "Motion",
            "Travel from the start of the stroke (0: against the end stop at the start of the run). "
            "Drive it with an expression for simple motion checks.", 0.0)

        add("App::PropertyString", "BeltItem", "Belt",
            "Belt that drives the carriage, as you order it, e.g. 'GT2 6 mm' or 'HTD 5M 15 mm'. It is listed "
            "as metre ware in the cut list. Empty: no belt.", "")
        add("App::PropertyLength", "BeltPitch", "Belt",
            "Tooth pitch of the belt (2 mm for GT2, 5 mm for HTD 5M or T5, 5.08 mm for XL); the belt length is "
            "rounded up to whole teeth. 0: no rounding.", 0.0)
        add("App::PropertyIntegerConstraint", "PulleyTeeth", "Belt",
            "Teeth of each of the two equal pulleys; with BeltPitch it gives their pitch diameter", (0, 0, 1000, 1))
        add("App::PropertyLength", "PulleyDiameter", "Belt",
            "Pitch diameter of the two equal pulleys (0: PulleyTeeth x BeltPitch / pi)", 0.0)
        add("App::PropertyLength", "PulleyCentres", "Belt",
            "Distance between the pulley axes (0: the clear run, with the pulleys at the ends of the run)", 0.0)
        add("App::PropertyDistance", "ClampAllowance", "Belt",
            "Belt added for the clamps on the carriage, such as the ends held in them; negative for a gap "
            "between the clamps that the belt does not span", 0.0)

        add("App::PropertyLength", "ClearRun", "Info",
            "Free length of the run, between the members that block the carriage or the rail ends", mode=1)
        add("App::PropertyDistance", "Stroke", "Info",
            "Usable stroke: the clear run minus the carriage and both end stops (negative: it does not fit)", mode=1)
        add("App::PropertyDistance", "Travel", "Info", "Current travel from the start of the stroke", mode=1)
        add("App::PropertyString", "Limits", "Info", "What limits the run at each end", mode=1)
        add("App::PropertyStringList", "Runs", "Info",
            "The free runs of the rail for this envelope, measured from the rail start", mode=1)
        add("App::PropertyLength", "BeltLength", "Info",
            "Length of the open belt: 2 x PulleyCentres + pi x PulleyDiameter + ClampAllowance, "
            "rounded up to whole teeth (0: no belt)", mode=1)
        add("App::PropertyString", "Warning", "Info",
            "What is wrong, for example a stroke below RequiredStroke; empty when all is well", mode=1)
        add("App::PropertyLinkListGlobal", "Neighbours", "Info",
            "Profiles and panels checked for the clear run, so the carriage recomputes when they change", mode=2)
        # The tree description the carriage wrote last, so a user's own description is never replaced.
        add("App::PropertyString", "WrittenDescription", "Info", "Description written by the carriage", mode=2)
        obj.setPropertyStatus("WrittenDescription", "Output")

    def onDocumentRestored(self, obj):
        self._restoring = True
        try:
            self.add_properties(obj)
            # The limits of constrained properties are not saved with the document.
            obj.Run = (min(99, max(0, obj.Run)), 0, 99, 1)
            obj.PulleyTeeth = (min(1000, max(0, obj.PulleyTeeth)), 0, 1000, 1)
            obj.PositionPercent = (min(100.0, max(0.0, obj.PositionPercent)), 0.0, 100.0, 1.0)
        finally:
            self._restoring = False
        self._update_editor_modes(obj)

    def _update_editor_modes(self, obj):
        if "Position" not in obj.PropertiesList:
            return
        percent = obj.PositionMode == "Percent"
        obj.setEditorMode("PositionPercent", 0 if percent else 1)
        obj.setEditorMode("Position", 1 if percent else 0)
        obj.setEditorMode("Placement", 1)

    def onChanged(self, obj, prop):
        if prop == "PositionMode":
            self._update_editor_modes(obj)  # only the editor, so also while undoing
        # Undo and Cancel write old values back; converting them would change what they restore.
        if feature.replaying(obj) or getattr(self, "_restoring", False):
            return
        if prop == "PositionMode" and "Stroke" in obj.PropertiesList:
            # Keep the carriage where it is when switching between percent and distance.
            usable = obj.Stroke.Value
            if obj.PositionMode == "Distance":
                obj.Position = stroke.travel("Percent", 0.0, obj.PositionPercent, usable)
            elif usable > 0:
                obj.PositionPercent = min(100.0, max(0.0, obj.Position.Value / usable * 100))

    def execute(self, obj):
        rail = obj.Rail
        if rail is None or not feature.is_profile(rail):
            raise ValueError(f"{obj.Label}: set Rail to the profile the carriage runs on")
        reason = feature.problem(rail)
        if reason:
            raise ValueError(f"{obj.Label}: its rail {rail.Label} has a problem: {reason}")
        length, width = obj.CarriageLength.Value, obj.EnvelopeWidth.Value
        stop = obj.EndStopLength.Value
        if length <= 0 or width <= 0 or obj.EnvelopeHeight.Value + obj.Wrap.Value <= 0:
            raise ValueError(f"{obj.Label}: CarriageLength, EnvelopeWidth and EnvelopeHeight must be more than 0")

        frame = feature.member_frame(rail)
        env = stroke.envelope(obj.Face, frame.rect, width, obj.EnvelopeHeight.Value, obj.Wrap.Value)
        lo, hi = rail_extent(rail, frame, obj.Face, width)
        if hi - lo <= TOL:
            raise ValueError(f"{obj.Label}: the miters of {rail.Label} leave no {obj.Face.lower()} face to run on")

        found = neighbours(obj)
        if [o.Name for o in obj.Neighbours] != [o.Name for o in found]:
            obj.Neighbours = found
        blocked = []
        for other in found + obstacles(obj):
            interval = blocked_interval(other.Shape, frame, env, lo, hi)
            if interval is not None:
                blocked.append((interval[0], interval[1], other.Label))
        runs = stroke.free_runs(lo, hi, blocked)
        if not runs:
            names = ", ".join(sorted({label for a, b, label in blocked if min(b, hi) - max(a, lo) > TOL}))
            raise ValueError(f"{obj.Label}: the {obj.Face.lower()} face of {rail.Label} is blocked along its "
                             f"whole length by {names}")

        def name(by, end):
            return by if by is not None else f"the {end} of {rail.Label}"

        run, message = stroke.pick_run(runs, obj.Run)
        belt = 0.0
        if obj.BeltItem:
            diameter = obj.PulleyDiameter.Value or stroke.pitch_diameter(obj.PulleyTeeth, obj.BeltPitch.Value)
            if diameter <= 0:
                # An error rather than a warning: the cut list would otherwise list a belt of the wrong length.
                raise ValueError(f"{obj.Label}: set PulleyDiameter, or PulleyTeeth and BeltPitch, "
                                 f"to get the length of the {obj.BeltItem} belt")
            belt = stroke.belt_length(obj.PulleyCentres.Value or run.length, diameter,
                                      obj.ClampAllowance.Value, obj.BeltPitch.Value)
        usable = stroke.stroke(run.length, length, stop)
        moved = stroke.travel(obj.PositionMode, obj.Position.Value, obj.PositionPercent, usable)
        s = stroke.centre(run, length, stop, moved)
        issues = ([message] if message else []) + stroke.problems(
            run, length, stop, obj.RequiredStroke.Value, obj.PositionMode, moved, length_text, name)

        start = (rail.Placement.Base - frame.origin).dot(frame.z)  # the rail's start face
        texts = [f"{i}: {length_text(r.start - start)} to {length_text(r.end - start)} ({length_text(r.length)}), "
                 f"{name(r.start_by, 'start')} to {name(r.end_by, 'end')}" + (", carriage" if r == run else "")
                 for i, r in enumerate(runs, start=1)]
        warning = "; ".join(issues)
        warning = warning[:1].upper() + warning[1:]
        if warning and warning != obj.Warning:
            App.Console.PrintWarning(f"Profile Builder: {obj.Label}: {warning}\n")
        obj.ClearRun = run.length
        obj.Stroke = usable
        obj.Travel = moved
        obj.BeltLength = belt
        obj.Limits = f"{name(run.start_by, 'start')} to {name(run.end_by, 'end')}"
        if list(obj.Runs) != texts:
            obj.Runs = texts
        if obj.Warning != warning:
            obj.Warning = warning
        # A short summary in the tree, unless the user wrote a description of their own.
        if obj.Label2 in ("", obj.WrittenDescription):
            text = f"Stroke {length_text(usable)}" + (" (see Warning)" if warning else "")
            if obj.Label2 != text:
                obj.Label2 = text
            if obj.WrittenDescription != text:
                obj.WrittenDescription = text

        (px, py), _w = stroke.face_point(obj.Face, frame.rect)
        (tx, ty), (nx, ny) = stroke.FACE_AXES[obj.Face]
        t, n, z = frame.x * tx + frame.y * ty, frame.x * nx + frame.y * ny, frame.z
        o = frame.origin + frame.x * px + frame.y * py + z * s
        placement = App.Placement(App.Matrix(t.x, n.x, z.x, o.x,
                                             t.y, n.y, z.y, o.y,
                                             t.z, n.z, z.z, o.z,
                                             0, 0, 0, 1))
        obj.Shape = self._shape(obj, length, width)
        obj.Placement = placement

    @staticmethod
    def _shape(obj, length, width):
        """The carriage in its own coordinates: X across the face, Y out of it, Z along the rail."""
        body = obj.Body
        if body is not None and not getattr(body, "Shape", Part.Shape()).isNull():
            shape = body.Shape
            # Replace the body's own placement by BodyPlacement; transformed() only sets a
            # location, so the geometry is not copied.
            moved = shape.transformed(obj.BodyPlacement.multiply(shape.Placement.inverse()).toMatrix())
            # Wrapped in a compound, so assigning the carriage's Placement keeps the body's offset.
            return Part.makeCompound([moved])
        height, wrap = obj.EnvelopeHeight.Value, obj.Wrap.Value
        return Part.makeBox(width, height + wrap, length, V(-width / 2, -wrap, -length / 2))

    def dumps(self):
        return None

    def loads(self, state):
        self._restoring = False
        return None

    __getstate__ = dumps
    __setstate__ = loads


class ViewProviderCarriage:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.ShapeColor = PLACEHOLDER_COLOR

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return os.path.join(feature.ICON_DIR, "Carriage.svg")

    def claimChildren(self):
        body = getattr(getattr(self, "Object", None), "Body", None)
        return [body] if body is not None else []

    def updateData(self, obj, prop):
        # The body is shown through the carriage; hide the original when it is linked.
        if prop == "Body" and obj.Body is not None and "Restore" not in obj.State:
            vobj = getattr(obj.Body, "ViewObject", None)
            if vobj is not None:
                vobj.Visibility = False

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from .linear_ui import CarriageTaskPanel
        Gui.Control.showDialog(CarriageTaskPanel(vobj.Object))
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


def carriage_info(obj):
    """Summary for the task panel (HTML)."""
    if obj.Rail is None:
        return "Set the rail the carriage runs on."
    required = obj.RequiredStroke.Value
    lines = [f"<b>Stroke {html.escape(length_text(obj.Stroke.Value))}</b>"
             + (f" (required {html.escape(length_text(required))})" if required > 0 else "")]
    lines.append(f"Clear run {html.escape(length_text(obj.ClearRun.Value))}, "
                 f"from {html.escape(obj.Limits)}")
    lines.append(f"On the {obj.Face.lower()} face of {html.escape(obj.Rail.Label)}")
    if len(obj.Runs) > 1:
        lines.append("Members split the rail into runs:<br>" + "<br>".join(html.escape(r) for r in obj.Runs))
    if obj.BeltItem and obj.BeltLength.Value > 0:
        text = f"Belt {obj.BeltItem}: {length_text(obj.BeltLength.Value)}"
        if obj.BeltPitch.Value > 0:
            text += f", {round(obj.BeltLength.Value / obj.BeltPitch.Value)} teeth"
        lines.append(html.escape(text))
    if obj.Warning:
        lines.append(f"<span style='color:#c60'>{html.escape(obj.Warning)}</span>")
    elif required > 0:
        lines.append("The stroke is enough.")
    return "<br>".join(lines)


def make_carriage(doc, rail, face="Top", body=None, **props):
    """Create a Carriage on a rail profile, sized from the rail's face as a starting point.

    Any property can be passed by name, e.g. ``CarriageLength=90, RequiredStroke=500``.
    """
    obj = doc.addObject("Part::FeaturePython", "Carriage")
    Carriage(obj)
    obj.Rail = rail
    obj.Face = face
    w = face_width(rail, face)
    obj.CarriageLength = 3 * w
    obj.EnvelopeWidth = w
    obj.EnvelopeHeight = w / 2
    if body is not None:
        obj.Body = body
    for name, value in props.items():
        setattr(obj, name, value)
    # Link the members before the first recompute, so they are computed first.
    obj.Neighbours = neighbours(obj)
    if App.GuiUp:
        ViewProviderCarriage(obj.ViewObject)
    return obj
