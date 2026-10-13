"""Parametric aluminium profile feature (Part::FeaturePython)."""

import os
import re

import FreeCAD as App
import Part

from . import geometry, profiles

V = App.Vector

ICON_DIR = os.path.join(os.path.dirname(__file__), "resources", "icons")
QT_TRANSLATE_NOOP = App.Qt.QT_TRANSLATE_NOOP

# (property name, series attribute, tooltip)
DIMENSIONS = (
    ("CellSize", "cell", QT_TRANSLATE_NOOP("App::Property", "Size of one square cell (20 for the 20 series)")),
    ("SlotOpening", "slot_opening", QT_TRANSLATE_NOOP("App::Property", "Width of the slot opening at the face")),
    ("LipThickness", "lip", QT_TRANSLATE_NOOP("App::Property", "Thickness of the lips beside the slot opening")),
    ("SlotHeadWidth", "head_width", QT_TRANSLATE_NOOP("App::Property", "Widest part of the slot, below the lips")),
    ("SlotHeadStraight", "head_straight", QT_TRANSLATE_NOOP("App::Property", "Height of the straight part of the slot head")),
    ("SlotDepth", "slot_depth", QT_TRANSLATE_NOOP("App::Property", "Depth of the slot, measured from the face")),
    ("SlotBottomWidth", "bottom_width", QT_TRANSLATE_NOOP("App::Property", "Width of the slot bottom (on the core)")),
    ("BoreDiameter", "center_bore", QT_TRANSLATE_NOOP("App::Property", "Diameter of the centre bore (core hole for tapping)")),
    ("CornerRadius", "corner_radius", QT_TRANSLATE_NOOP("App::Property", "Radius of the outer corners")),
    ("VChamfer", "v_chamfer", QT_TRANSLATE_NOOP("App::Property", "Depth of the 45 degree V at the slot opening (V-slot only)")),
    ("CornerHoleDiameter", "corner_hole", QT_TRANSLATE_NOOP("App::Property", "Diameter of round corner holes (0 for none)")),
    ("ChamberWall", "chamber_wall", QT_TRANSLATE_NOOP("App::Property", "Wall thickness around hollow corner chambers (0: no chambers)")),
)


CLOSED_TIPS = {
    "Top": QT_TRANSLATE_NOOP("App::Property", "No slots on the top face"),
    "Bottom": QT_TRANSLATE_NOOP("App::Property", "No slots on the bottom face"),
    "Left": QT_TRANSLATE_NOOP("App::Property", "No slots on the left face"),
    "Right": QT_TRANSLATE_NOOP("App::Property", "No slots on the right face"),
}

# Properties that change the size or orientation of the section; joints that
# involve the profile must be recomputed when one of them changes.
SECTION_PROPS = {"Series", "Columns", "Rows", "CellSize", "Anchor", "Spin", "SectionOffsetX",
                 "SectionOffsetY", "PathEdge", "JointRole"}
JOINT_ROLES = ("Auto", "Runs through", "Butts")


def is_profile(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "ProfileBuilder::Profile"


def path_edge(obj):
    """The straight edge a profile follows, or None."""
    if not obj.PathEdge:
        return None
    link, subs = obj.PathEdge
    if not subs:
        raise ValueError(f"{obj.Label}: PathEdge must reference a single edge")
    edge = link.getSubObject(subs[0]) if not subs[0].startswith("?") else None
    # FreeCAD marks an element that no longer exists with a leading "?", for
    # example after the sketch line was deleted.
    if edge is None or edge.isNull() or not hasattr(edge, "Curve"):
        raise ValueError(f"{obj.Label}: its path edge {subs[0].lstrip('?')} of {link.Label} no longer exists "
                         "(was the line deleted?). Pick another edge or remove the profile.")
    return edge


class Frame:
    """World-space axes of a profile plus its section rectangle.

    ``origin`` lies on the profile axis line (the path edge, or the local Z
    axis). ``rect`` is (xmin, xmax, ymin, ymax) of the section in local X/Y,
    which already includes the anchor offset.
    """

    def __init__(self, origin, x, y, z, rect):
        self.origin, self.x, self.y, self.z, self.rect = origin, x, y, z, rect

    def corners(self):
        x0, x1, y0, y1 = self.rect
        return [self.x * a + self.y * b for a in (x0, x1) for b in (y0, y1)]

    def support(self, u):
        """How far the section reaches from the axis line in world direction u."""
        return max(c.dot(u) for c in self.corners())

    def center_offset(self):
        x0, x1, y0, y1 = self.rect
        return self.x * ((x0 + x1) / 2) + self.y * ((y0 + y1) / 2)


def member_frame(obj):
    width = obj.Columns * obj.CellSize.Value
    height = obj.Rows * obj.CellSize.Value
    c = geometry.anchor_offset(obj.Anchor, width, height) + section_offset(obj)
    rect = (c.x - width / 2, c.x + width / 2, c.y - height / 2, c.y + height / 2)
    edge = path_edge(obj)
    if edge is not None:
        pl = _edge_placement(edge, 0, obj.Spin.Value)
    else:
        pl = obj.Placement
    rot = pl.Rotation
    return Frame(pl.Base, rot.multVec(V(1, 0, 0)), rot.multVec(V(0, 1, 0)),
                 rot.multVec(V(0, 0, 1)), rect)


def section_offset(obj):
    x = getattr(obj, "SectionOffsetX", None)
    y = getattr(obj, "SectionOffsetY", None)
    return V(getattr(x, "Value", 0.0), getattr(y, "Value", 0.0), 0)


def ensure_section_offset_properties(obj):
    if "SectionOffsetX" not in obj.PropertiesList:
        obj.addProperty("App::PropertyDistance", "SectionOffsetX", "Path",
                        "Offset the section from its path in local X")
        obj.SectionOffsetX = 0.0
    if "SectionOffsetY" not in obj.PropertiesList:
        obj.addProperty("App::PropertyDistance", "SectionOffsetY", "Path",
                        "Offset the section from its path in local Y")
        obj.SectionOffsetY = 0.0


def _edge_placement(edge, extend_start, spin):
    """Placement whose Z axis runs along a straight edge, starting at its first vertex.

    The local X axis is kept horizontal where possible so the profile height
    (local Y) points up for horizontal edges.
    """
    if not isinstance(edge.Curve, Part.Line):
        raise ValueError("Profiles can only follow straight edges")
    p0, p1 = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    z = p1 - p0
    if z.Length < 1e-9:
        raise ValueError("Path edge has zero length")
    z.normalize()
    x = V(0, 0, 1).cross(z)
    if x.Length < 1e-6:
        x = V(1, 0, 0)
    x.normalize()
    y = z.cross(x)
    base = p0 - z * extend_start
    m = App.Matrix(x.x, y.x, z.x, base.x,
                   x.y, y.y, z.y, base.y,
                   x.z, y.z, z.z, base.z,
                   0, 0, 0, 1)
    return App.Placement(m).multiply(App.Placement(V(), App.Rotation(V(0, 0, 1), spin)))


class Profile:
    Type = "ProfileBuilder::Profile"

    def __init__(self, obj, series=profiles.DEFAULT_SERIES):
        obj.Proxy = self
        self._restoring = False
        self.add_properties(obj)
        obj.Series = series
        apply_series_defaults(obj)

    def add_properties(self, obj):
        def add(kind, name, group, tip, value=None, mode=None):
            if name in obj.PropertiesList:
                return
            obj.addProperty(kind, name, group, tip)
            # Enumerations get their list of choices as the value.
            if value is not None:
                setattr(obj, name, value)
            if mode is not None:
                obj.setEditorMode(name, mode)

        add("App::PropertyEnumeration", "Series", "Profile",
            "Profile series; changing it resets the dimensions", list(profiles.SERIES))
        add("App::PropertyEnumeration", "Weight", "Profile",
            "Weight class: how hollow the section is (Standard, Light, Ultralight or Heavy). "
            "Changing it resets the dimensions.", list(profiles.WEIGHTS))
        add("App::PropertyIntegerConstraint", "Columns", "Profile", "Cells along X (2 for a 4020)", (1, 1, 20, 1))
        add("App::PropertyIntegerConstraint", "Rows", "Profile", "Cells along Y (2 for a 2040)", (1, 1, 20, 1))
        add("App::PropertyEnumeration", "SlotStyle", "Profile", "Slot type", list(profiles.SLOT_STYLES))
        for face in profiles.FACES:
            add("App::PropertyBool", f"Closed{face}", "Profile", CLOSED_TIPS[face], False)
        add("App::PropertyBool", "CenterBore", "Profile", "Cut the centre bores", True)
        add("App::PropertyBool", "CornerHoles", "Profile", "Cut the corner holes or chambers", True)
        add("App::PropertyString", "Designation", "Profile", "Trade name, e.g. 2040", mode=1)

        add("App::PropertyLength", "Length", "Length", "Length along the profile axis", 1000.0)
        add("App::PropertyAngle", "MiterStart", "Length", "Miter angle at the start (positive: + side is long)", 0.0)
        add("App::PropertyAngle", "MiterEnd", "Length", "Miter angle at the end (positive: + side is long)", 0.0)
        add("App::PropertyEnumeration", "MiterAcross", "Length",
            "Axis across which the miters slope", list(profiles.MITER_ACROSS))
        add("App::PropertyEnumeration", "Anchor", "Length",
            "Which point of the section sits on the axis", list(profiles.ANCHORS))

        add("App::PropertyLinkSub", "PathEdge", "Path", "Straight edge the profile follows (sets placement and length)")
        add("App::PropertyDistance", "ExtendStart", "Path", "Extra length before the edge start (negative trims)", 0.0)
        add("App::PropertyDistance", "ExtendEnd", "Path", "Extra length after the edge end (negative trims)", 0.0)
        add("App::PropertyAngle", "Spin", "Path", "Rotation of the profile about its own axis", 0.0)

        add("App::PropertyEnumeration", "JointRole", "Joints",
            "Runs through: this profile runs through all its butt joints. Butts: it always stops "
            "against the other profile. Auto: decided by each joint's rule.", list(JOINT_ROLES))
        add("App::PropertyLink", "StartJoint", "Joints", "Joint at the start of the path edge")
        add("App::PropertyLink", "EndJoint", "Joints", "Joint at the end of the path edge")
        add("App::PropertyDistance", "JointStartOffset", "Joints",
            "Length added (negative: trimmed) at the start by the joint", mode=1)
        add("App::PropertyDistance", "JointEndOffset", "Joints",
            "Length added (negative: trimmed) at the end by the joint", mode=1)
        # Which axis each end's miter slopes across, as built (joints can pick
        # different axes per end). Empty for a square cut.
        add("App::PropertyString", "MiterStartAxis", "Length", "Axis the start miter slopes across", mode=1)
        add("App::PropertyString", "MiterEndAxis", "Length", "Axis the end miter slopes across", mode=1)
        # Set while a joint drives that end's miter, so removing the joint can
        # reset it instead of leaving a stale miter behind.
        add("App::PropertyBool", "StartMiterFromJoint", "Joints", "The start miter is set by a joint", mode=2)
        add("App::PropertyBool", "EndMiterFromJoint", "Joints", "The end miter is set by a joint", mode=2)

        for name, _attr, tip in DIMENSIONS:
            add("App::PropertyLength", name, "Dimensions", tip)

        add("App::PropertyFloat", "Density", "Info", "Material density in g/cm^3", profiles.ALUMINIUM_DENSITY)
        add("App::PropertyArea", "SectionArea", "Info", "Cross-section area", mode=1)
        add("App::PropertyFloat", "MassPerMeter", "Info", "Mass per metre in kg/m", mode=1)
        add("App::PropertyFloat", "Mass", "Info", "Mass of this piece in kg", mode=1)
        add("App::PropertyLength", "OverallLength", "Info", "Tip-to-tip length including miters (saw length)", mode=1)
        # Tooltips are literal, so the translation lookup (by their text) can find them.
        add("App::PropertyFloat", "Ix", "Info", "Second moment of area about local X in cm^4 (load along Y), "
            "of the modelled section, not a datasheet value", mode=1)
        add("App::PropertyFloat", "Iy", "Info", "Second moment of area about local Y in cm^4 (load along X), "
            "of the modelled section, not a datasheet value", mode=1)
        add("App::PropertyFloat", "Wx", "Info", "Section modulus about local X in cm^3, "
            "of the modelled section, not a datasheet value", mode=1)
        add("App::PropertyFloat", "Wy", "Info", "Section modulus about local Y in cm^3, "
            "of the modelled section, not a datasheet value", mode=1)
        add("App::PropertyString", "PieceMark", "Info", "Mark of this piece in the last cut list", mode=1)
        obj.setPropertyStatus("PieceMark", "Output")  # writing a mark must not trigger a recompute

    def onDocumentRestored(self, obj):
        # Adds properties introduced by newer versions to old documents, and
        # new catalog entries to the Series list, without resetting dimensions
        # the user may have customised.
        self._restoring = True
        try:
            had = set(obj.PropertiesList)
            self.add_properties(obj)
            if list(obj.getEnumerationsOfProperty("Series")) != list(profiles.SERIES):
                key = obj.Series
                obj.Series = list(profiles.SERIES)
                obj.Series = key
            # Before the flags existed, a joint always drove its end's miter.
            for end in ("Start", "End"):
                if f"{end}MiterFromJoint" not in had and getattr(obj, f"{end}Joint") is not None:
                    setattr(obj, f"{end}MiterFromJoint", True)
        finally:
            self._restoring = False


        self._update_editor_modes(obj)
        # Outputs added by newer versions (section properties, miter axes) are
        # only filled in by a recompute. Touching here does not stick, because
        # FreeCAD resets the state after loading; see needs_refresh() instead.

    def _update_editor_modes(self, obj):
        if "EndJoint" not in obj.PropertiesList:
            return
        obj.setEditorMode("Length", 1 if obj.PathEdge else 0)
        obj.setEditorMode("Placement", 1 if obj.PathEdge else 0)
        obj.setEditorMode("MiterStart", 1 if obj.StartJoint else 0)
        obj.setEditorMode("MiterEnd", 1 if obj.EndJoint else 0)

    def onChanged(self, obj, prop):
        if "Restore" in obj.State or getattr(self, "_restoring", False):
            return
        if prop in ("PathEdge", "StartJoint", "EndJoint"):
            self._update_editor_modes(obj)  # only the editor, so also while undoing
        # Undo and Cancel write old values back; reacting to them (resetting the
        # dimensions) would change what they restore.
        if not replaying(obj) and prop in ("Series", "Weight") and "ChamberWall" in obj.PropertiesList:
            apply_series_defaults(obj)
        # Marking dependants for recompute writes no property, so it also runs
        # while undoing: a neighbour recomputed outside the undone transaction
        # has no old value to restore, and would otherwise stay stale.
        # A new label only changes what the joint shows in its Through list.
        if prop in SECTION_PROPS or prop == "Label":
            from . import joints
            joints.touch_joints_of(obj)
        if prop in ("Series", "Columns", "Rows", "CellSize", "Anchor", "Spin", "PathEdge"):
            from . import skeleton
            skeleton.touch_skeleton_of(obj)
        if prop in ("SectionOffsetX", "SectionOffsetY") and obj.Document is not None:
            from .linear import touch_carriages
            touch_carriages(obj.Document)
        if prop == "Placement":  # also set by each recompute, after the new shape
            from .linear import member_moved  # it may now block a carriage
            member_moved(obj)

    def execute(self, obj):
        dims = dimensions(obj)

        length = obj.Length.Value
        placement = obj.Placement
        section_shift = section_offset(obj)
        # A miter written by a joint that has since been removed is stale: go
        # back to a square cut instead of keeping the old angle.
        for end in ("Start", "End"):
            if getattr(obj, f"{end}MiterFromJoint") and getattr(obj, f"{end}Joint") is None:
                setattr(obj, f"Miter{end}", 0.0)
                setattr(obj, f"{end}MiterFromJoint", False)
        miters = [obj.MiterStart.Value, obj.MiterEnd.Value]
        across = [obj.MiterAcross, obj.MiterAcross]
        edge = path_edge(obj)
        if edge is not None:
            from . import joints
            extend = [obj.ExtendStart.Value, obj.ExtendEnd.Value]
            offsets = [0.0, 0.0]
            for i, (end, joint) in enumerate((("Start", obj.StartJoint), ("End", obj.EndJoint))):
                if joint is None:
                    continue
                offsets[i], miter, axis = joints.adjustment(joint, obj, end)
                extend[i] += offsets[i]
                miters[i], across[i] = miter, axis
            obj.JointStartOffset, obj.JointEndOffset = offsets
            # Joint-driven miters are shown in the (then read-only) miter properties.
            for i, end in enumerate(("Start", "End")):
                if getattr(obj, f"{end}Joint") is None:
                    continue
                if abs(getattr(obj, f"Miter{end}").Value - miters[i]) > 1e-9:
                    setattr(obj, f"Miter{end}", miters[i])
                if not getattr(obj, f"{end}MiterFromJoint"):
                    setattr(obj, f"{end}MiterFromJoint", True)
            placement = _edge_placement(edge, extend[0], obj.Spin.Value)
            length = edge.Length + extend[0] + extend[1]
            if abs(obj.Length.Value - length) > 1e-7:
                obj.Length = length

        # The anchor is baked into the section: translating the finished solid
        # would only set its location, which assigning Placement below discards.
        face = geometry.make_section(dims, obj.Columns, obj.Rows, obj.SlotStyle, closed_faces(obj),
                                     obj.CenterBore, obj.CornerHoles, obj.Anchor)
        if section_shift.Length:
            face.translate(section_shift)
        pivot = (geometry.anchor_offset(obj.Anchor, obj.Columns * dims["cell"], obj.Rows * dims["cell"])
                 + section_shift)
        solid = geometry.make_solid(face, length, miters[0], miters[1], tuple(across), pivot)

        for i, end in enumerate(("Start", "End")):
            axis = across[i] if abs(miters[i]) > 1e-9 else ""
            if getattr(obj, f"Miter{end}Axis") != axis:
                setattr(obj, f"Miter{end}Axis", axis)

        obj.Designation = describe(obj)
        obj.SectionArea = face.Area
        obj.Ix, obj.Iy, obj.Wx, obj.Wy = section_properties(face)
        density = obj.Density * 1e-6  # g/cm^3 -> kg/mm^3
        obj.MassPerMeter = round(face.Area * 1000 * density, 4)
        obj.Mass = round(solid.Volume * density, 4)
        obj.OverallLength = solid.BoundBox.ZLength

        obj.Shape = solid
        obj.Placement = placement  # onChanged then lets carriages check the new shape

    def dumps(self):
        return None

    def loads(self, state):
        self._restoring = False
        return None

    # FreeCAD < 1.0 names
    __getstate__ = dumps
    __setstate__ = loads


def replaying(obj):
    """True while FreeCAD restores or undoes: property changes then are not user edits."""
    doc = getattr(obj, "Document", None)
    return "Restore" in obj.State or bool(getattr(doc, "Transacting", False))


def problem(obj):
    """Why a profile's current shape and length cannot be trusted, or None.

    Besides an error on the profile itself, this catches a profile that
    FreeCAD skipped because something it depends on failed (a joint, a
    deleted sketch line): such a profile still looks valid but keeps its old
    length, and must not be counted as if it were up to date.
    """
    if not obj.isValid():
        try:
            return obj.getStatusString()
        except Exception:  # noqa: BLE001
            return "error"
    if obj.PathEdge:
        # A failed path (a skeleton below its section sizes, a sketch that does not solve)
        # keeps its old shape, so the edge is still found but the length is stale.
        source = obj.PathEdge[0]
        if source is not None and not source.isValid():
            return f"its path {source.Label} has an error"
        try:
            path_edge(obj)
        except ValueError as e:
            return str(e)
    for joint in (obj.StartJoint, obj.EndJoint):
        if joint is not None and not joint.isValid():
            return f"its joint {joint.Label} has an error"
        for source in getattr(joint, "Sources", None) or ():
            if source is not None and not source.isValid():
                return f"its joint {joint.Label} follows {source.Label}, which has an error"
    if "Touched" in obj.State:
        return "not recomputed (recompute the document, or fix the object it depends on)"
    return None


def needs_refresh(obj):
    """True when a profile's outputs predate this version and a recompute would fill them in.

    Documents saved by older versions lack the section properties and the
    per-end miter axes until the profile is recomputed.
    """
    if "Ix" not in obj.PropertiesList or not obj.isValid() or obj.Shape.isNull():
        return False
    if obj.Ix == 0:
        return True
    return any(abs(getattr(obj, f"Miter{end}").Value) > 1e-9 and not getattr(obj, f"Miter{end}Axis")
               for end in ("Start", "End"))


def section_properties(face):
    """(Ix, Iy in cm^4, Wx, Wy in cm^3) of a section face about its centroid.

    The face lies in the XY plane, so MatrixOfInertia's A11 is the integral of
    y^2 (bending about X) and A22 that of x^2. The section modulus uses the
    outermost fibre, taken from the bounding box.
    """
    m = face.MatrixOfInertia
    c = face.CenterOfMass
    bb = face.BoundBox
    ex = max(bb.XMax - c.x, c.x - bb.XMin)
    ey = max(bb.YMax - c.y, c.y - bb.YMin)
    ix, iy = m.A11, m.A22
    return (round(ix / 1e4, 4), round(iy / 1e4, 4),
            round(ix / ey / 1e3, 4) if ey else 0.0, round(iy / ex / 1e3, 4) if ex else 0.0)


def dimensions(obj):
    return {attr: getattr(obj, name).Value for name, attr, _tip in DIMENSIONS}


def apply_series_defaults(obj):
    dims = profiles.SERIES[obj.Series].dimensions(obj.Weight)
    for name, attr, _tip in DIMENSIONS:
        setattr(obj, name, dims[attr])
    obj.CornerHoles = dims["corner_hole"] > 0 or dims["chamber_wall"] > 0


def describe(obj):
    """Human readable designation, e.g. '2040 Light V-slot (20-6)'."""
    text = profiles.designation(obj.CellSize.Value, obj.Columns, obj.Rows)
    if obj.Weight != "Standard":
        text += " " + obj.Weight
    if obj.SlotStyle != "T-slot":
        text += " " + obj.SlotStyle
    return f"{text} ({obj.Series})"


def auto_label(obj):
    # Not just "2040": FreeCAD would make a duplicate "2041" instead of "2040001".
    return profiles.designation(obj.CellSize.Value, obj.Columns, obj.Rows) + " profile"


def is_auto_label(label):
    return bool(re.fullmatch(r"(Profile\d*|[\d.]+ profile\d*)", label))


def closed_faces(obj):
    return [f for f in profiles.FACES if getattr(obj, f"Closed{f}")]


def product_key(obj):
    """What you order: designation plus closed faces, e.g. '2020 (20-6) closed Top'.

    The closed faces are named as on the upright section (Rows >= Columns), so a
    2x1 "2040 (on side)" with its wide face closed is the same product as a 1x2
    with its wide face closed, and differs from one with a narrow face closed.
    """
    from .pieces import upright
    closed, _cuts = upright(closed_faces(obj), (), obj.Columns, obj.Rows)
    names = [f for f in profiles.FACES if f in closed]
    return obj.Designation + (" closed " + ",".join(names) if names else "")


def legacy_product_key(obj):
    """The product key of versions up to ead3f7d (faces as named on the object).

    Prices saved in older documents use it; look it up when the current key
    has no price.
    """
    closed = closed_faces(obj)
    return obj.Designation + (" closed " + ",".join(closed) if closed else "")


class ViewProviderProfile:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.ShapeColor = (0.78, 0.80, 0.83)

    def attach(self, vobj):
        self.Object = vobj.Object
        if "ShowMark" not in vobj.PropertiesList:
            vobj.addProperty("App::PropertyBool", "ShowMark", "Profile Builder",
                             "Show the piece mark from the last cut list in the 3D view")
        from pivy import coin
        # attach also runs when a document is opened, so the label is rebuilt then.
        self._mark_switch = coin.SoSwitch()
        label = coin.SoAnnotation()  # drawn on top, so the solid does not hide it
        self._mark_position = coin.SoTranslation()
        color = coin.SoBaseColor()
        color.rgb = (0.85, 0.28, 0.06)
        font = coin.SoFont()
        font.size = 16
        self._mark_text = coin.SoText2()
        self._mark_text.justification = coin.SoText2.CENTER
        for node in (self._mark_position, color, font, self._mark_text):
            label.addChild(node)
        self._mark_switch.addChild(label)
        vobj.RootNode.addChild(self._mark_switch)
        self._update_mark(vobj)

    def _update_mark(self, vobj):
        switch = getattr(self, "_mark_switch", None)
        if switch is None:
            return
        obj = vobj.Object
        mark = getattr(obj, "PieceMark", "")
        show = bool(getattr(vobj, "ShowMark", False) and vobj.Visibility and mark)
        if show:
            self._mark_text.string = mark
            try:
                # The root node already carries the placement, so use local coordinates.
                centre = obj.Placement.inverse().multVec(obj.Shape.BoundBox.Center)
                self._mark_position.translation = (centre.x, centre.y, centre.z)
            except Exception:  # noqa: BLE001  (no shape yet)
                pass
        switch.whichChild = 0 if show else -1

    def updateData(self, obj, prop):
        if prop in ("PieceMark", "Shape", "Placement") and obj.ViewObject is not None:
            self._update_mark(obj.ViewObject)

    def onChanged(self, vobj, prop):
        if prop in ("ShowMark", "Visibility"):
            self._update_mark(vobj)

    def getIcon(self):
        return os.path.join(ICON_DIR, "Profile.svg")

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from .taskpanel import ProfileTaskPanel
        Gui.Control.showDialog(ProfileTaskPanel(edit=vobj.Object))
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


def make_profile(series=profiles.DEFAULT_SERIES, cols=1, rows=1, length=1000.0,
                 doc=None, edge=None, **props):
    """Create a Profile object.

    ``edge`` is an optional ``(object, "EdgeN")`` tuple the profile will follow.
    Any other property can be passed by name, e.g. ``SlotStyle="V-slot"``.
    """
    doc = doc or App.ActiveDocument or App.newDocument()
    obj = doc.addObject("Part::FeaturePython", "Profile")
    Profile(obj, series)
    obj.Columns = cols
    obj.Rows = rows
    obj.Length = length
    for name, value in props.items():
        setattr(obj, name, value)
    if edge is not None:
        obj.PathEdge = edge
    if App.GuiUp:
        ViewProviderProfile(obj.ViewObject)
    obj.Label = auto_label(obj)
    from .linear import touch_carriages  # a new profile may block a carriage
    touch_carriages(doc)
    return obj
