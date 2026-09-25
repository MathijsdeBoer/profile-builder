"""Parametric aluminium profile feature (Part::FeaturePython)."""

import os
import re

import FreeCAD as App
import Part

from . import geometry, profiles

V = App.Vector

ICON_DIR = os.path.join(os.path.dirname(__file__), "resources", "icons")

# (property name, series attribute, tooltip)
DIMENSIONS = (
    ("CellSize", "cell", "Size of one square cell (20 for the 20 series)"),
    ("SlotOpening", "slot_opening", "Width of the slot opening at the face"),
    ("LipThickness", "lip", "Thickness of the lips beside the slot opening"),
    ("SlotHeadWidth", "head_width", "Widest part of the slot, below the lips"),
    ("SlotHeadStraight", "head_straight", "Height of the straight part of the slot head"),
    ("SlotDepth", "slot_depth", "Depth of the slot, measured from the face"),
    ("SlotBottomWidth", "bottom_width", "Width of the slot bottom (on the core)"),
    ("BoreDiameter", "center_bore", "Diameter of the centre bore (core hole for tapping)"),
    ("CornerRadius", "corner_radius", "Radius of the outer corners"),
    ("VChamfer", "v_chamfer", "Depth of the 45 degree V at the slot opening (V-slot only)"),
    ("CornerHoleDiameter", "corner_hole", "Diameter of round corner holes (0 for none)"),
    ("ChamberWall", "chamber_wall", "Wall thickness around hollow corner chambers (0: no chambers)"),
)


# Properties that change the size or orientation of the section; joints that
# involve the profile must be recomputed when one of them changes.
SECTION_PROPS = {"Series", "Columns", "Rows", "CellSize", "Anchor", "Spin", "PathEdge", "JointRole"}
JOINT_ROLES = ("Auto", "Runs through", "Butts")


def is_profile(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "ProfileBuilder::Profile"


def path_edge(obj):
    """The straight edge a profile follows, or None."""
    if not obj.PathEdge:
        return None
    link, subs = obj.PathEdge
    if not subs:
        raise ValueError("PathEdge must reference a single edge")
    return link.getSubObject(subs[0])


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
    c = geometry.anchor_offset(obj.Anchor, width, height)
    rect = (c.x - width / 2, c.x + width / 2, c.y - height / 2, c.y + height / 2)
    edge = path_edge(obj)
    if edge is not None:
        pl = _edge_placement(edge, 0, obj.Spin.Value)
    else:
        pl = obj.Placement
    rot = pl.Rotation
    return Frame(pl.Base, rot.multVec(V(1, 0, 0)), rot.multVec(V(0, 1, 0)),
                 rot.multVec(V(0, 0, 1)), rect)


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
            "Weight class: " + "; ".join(f"{k}: {v}" for k, v in profiles.WEIGHT_TIPS.items())
            + ". Changing it resets the dimensions.", list(profiles.WEIGHTS))
        add("App::PropertyIntegerConstraint", "Columns", "Profile", "Cells along X (2 for a 4020)", (1, 1, 20, 1))
        add("App::PropertyIntegerConstraint", "Rows", "Profile", "Cells along Y (2 for a 2040)", (1, 1, 20, 1))
        add("App::PropertyEnumeration", "SlotStyle", "Profile", "Slot type", list(profiles.SLOT_STYLES))
        for face in profiles.FACES:
            add("App::PropertyBool", f"Closed{face}", "Profile", f"No slots on the {face.lower()} face", False)
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

        for name, _attr, tip in DIMENSIONS:
            add("App::PropertyLength", name, "Dimensions", tip)

        add("App::PropertyFloat", "Density", "Info", "Material density in g/cm^3", profiles.ALUMINIUM_DENSITY)
        add("App::PropertyArea", "SectionArea", "Info", "Cross-section area", mode=1)
        add("App::PropertyFloat", "MassPerMeter", "Info", "Mass per metre in kg/m", mode=1)
        add("App::PropertyFloat", "Mass", "Info", "Mass of this piece in kg", mode=1)
        add("App::PropertyLength", "OverallLength", "Info", "Tip-to-tip length including miters (saw length)", mode=1)

    def onDocumentRestored(self, obj):
        # Adds properties introduced by newer versions to old documents, and
        # new catalog entries to the Series list, without resetting dimensions
        # the user may have customised.
        self._restoring = True
        try:
            self.add_properties(obj)
            if list(obj.getEnumerationsOfProperty("Series")) != list(profiles.SERIES):
                key = obj.Series
                obj.Series = list(profiles.SERIES)
                obj.Series = key
        finally:
            self._restoring = False
        self._update_editor_modes(obj)

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
        if prop in ("Series", "Weight") and "ChamberWall" in obj.PropertiesList:
            apply_series_defaults(obj)
        if prop in ("PathEdge", "StartJoint", "EndJoint"):
            self._update_editor_modes(obj)
        if prop in SECTION_PROPS:
            from . import joints
            joints.touch_joints_of(obj)

    def execute(self, obj):
        dims = dimensions(obj)

        length = obj.Length.Value
        placement = obj.Placement
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
            if obj.StartJoint and abs(obj.MiterStart.Value - miters[0]) > 1e-9:
                obj.MiterStart = miters[0]
            if obj.EndJoint and abs(obj.MiterEnd.Value - miters[1]) > 1e-9:
                obj.MiterEnd = miters[1]
            placement = _edge_placement(edge, extend[0], obj.Spin.Value)
            length = edge.Length + extend[0] + extend[1]
            if abs(obj.Length.Value - length) > 1e-7:
                obj.Length = length

        # The anchor is baked into the section: translating the finished solid
        # would only set its location, which assigning Placement below discards.
        face = geometry.make_section(dims, obj.Columns, obj.Rows, obj.SlotStyle, closed_faces(obj),
                                     obj.CenterBore, obj.CornerHoles, obj.Anchor)
        pivot = geometry.anchor_offset(obj.Anchor, obj.Columns * dims["cell"], obj.Rows * dims["cell"])
        solid = geometry.make_solid(face, length, miters[0], miters[1], tuple(across), pivot)

        obj.Designation = describe(obj)
        obj.SectionArea = face.Area
        density = obj.Density * 1e-6  # g/cm^3 -> kg/mm^3
        obj.MassPerMeter = round(face.Area * 1000 * density, 4)
        obj.Mass = round(solid.Volume * density, 4)
        obj.OverallLength = solid.BoundBox.ZLength

        obj.Shape = solid
        obj.Placement = placement

    def dumps(self):
        return None

    def loads(self, state):
        self._restoring = False
        return None

    # FreeCAD < 1.0 names
    __getstate__ = dumps
    __setstate__ = loads


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
    """What you order: designation plus closed faces, e.g. '2020 (20-6) closed Top'."""
    closed = closed_faces(obj)
    return obj.Designation + (" closed " + ",".join(closed) if closed else "")


class ViewProviderProfile:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.ShapeColor = (0.78, 0.80, 0.83)

    def attach(self, vobj):
        self.Object = vobj.Object

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
    return obj
