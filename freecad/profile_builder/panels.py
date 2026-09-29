"""Sheet panels filling an opening between profiles (enclosure sides, etc.)."""

import math
import os
import re

import FreeCAD as App
import Part

from . import feature

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


def _check_slot(obj, frame, face, n, plane_offset, thickness):
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
                         f"try PlaneOffset {plane_offset + shift:+g} mm")


def _intersect(p1, d1, p2, d2):
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-9:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
    return (p1[0] + d1[0] * t, p1[1] + d1[1] * t)


def panel_outline(obj):
    """(polygon points in world space, plane normal, width, height, area)."""
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
        if abs(f.z.dot(n)) > 1e-3 or abs((a - origin).dot(n)) > 0.5:
            raise ValueError(f"{m.Label} does not lie in the plane of the panel")

    e1 = frames[0].z
    e2 = n.cross(e1)

    def to2d(p):
        d = p - origin
        return (d.dot(e1), d.dot(e2))

    mids = [(a + b) * 0.5 for a, b in segments]
    centroid = sum(mids, V()) * (1.0 / len(mids))
    lines = []
    for m, f, (a, _b), mid in zip(members, frames, segments, mids):
        w = n.cross(f.z)
        if (centroid - mid).dot(w) < 0:
            w = -w
        inner = f.support(w) - f.center_offset().dot(w)
        if obj.Mount == "In slot":
            _check_slot(m, f, _face_towards(f, w), n, obj.PlaneOffset.Value, obj.Thickness.Value)
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

    us = [u for u, _v in corners]
    vs = [v for _u, v in corners]
    area = 0.5 * abs(sum(u1 * v2 - u2 * v1 for (u1, v1), (u2, v2) in zip(corners, corners[1:] + corners[:1])))

    if obj.Mount == "In slot":
        lift = obj.PlaneOffset.Value - obj.Thickness.Value / 2
    else:
        sign = 1 if obj.Side == "Front" else -1
        reach = max(f.support(n * sign) - f.center_offset().dot(n * sign) for f in frames)
        lift = sign * reach + obj.PlaneOffset.Value - (0 if sign > 0 else obj.Thickness.Value)
    points = [origin + e1 * u + e2 * v + n * lift for u, v in corners]
    return points, n, max(us) - min(us), max(vs) - min(vs), area


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
        add("App::PropertyLength", "Width", "Info", "Sheet size along the first profile", mode=1)
        add("App::PropertyLength", "Height", "Info", "Sheet size across the first profile", mode=1)
        add("App::PropertyArea", "Area", "Info", "Area of the panel outline", mode=1)
        add("App::PropertyFloat", "Mass", "Info", "Mass in kg", mode=1)

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

    def execute(self, obj):
        points, n, width, height, area = panel_outline(obj)
        face = Part.Face(Part.makePolygon(points + [points[0]]))
        solid = face.extrude(n * obj.Thickness.Value)
        obj.Width, obj.Height, obj.Area = width, height, area
        obj.Mass = round(solid.Volume * obj.Density * 1e-6, 4)
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


def thermal_fit(obj):
    """(clearance needed per side in mm, warning or None) for a sheet in the slots.

    The sheet and the aluminium frame expand differently. Between the
    assembly temperature and the extremes in use, the difference must fit in
    the room left at the bottom of the slots, half on each side. That room is
    the clearance, plus whatever InsertDepth leaves unused of the slot depth.
    With an unknown expansion (0) there is nothing to check.
    """
    if obj.Mount != "In slot" or obj.Expansion <= 0:
        return 0.0, None
    size = max(obj.Width.Value, obj.Height.Value)
    diff = (obj.Expansion - ALUMINIUM_EXPANSION) * 1e-6
    growth = max(diff * (t - obj.AssemblyTemperature) * size
                 for t in (obj.MinTemperature, obj.MaxTemperature))
    need = max(0.0, growth / 2)
    room = slot_room(obj)
    if need <= room:
        return need, None
    return need, (f"{obj.Label}: the sheet grows {growth:.2f} mm more than the frame over the temperature range; "
                  f"it needs {need:.2f} mm room per side at the slot bottom but has {room:.2f} mm")


def slot_room(obj):
    """Smallest gap between the sheet edge and the slot bottom, over the profiles around it."""
    rooms = [m.SlotDepth.Value - (obj.InsertDepth.Value or m.SlotDepth.Value) + obj.Clearance.Value
             for m in obj.Profiles if feature.is_profile(m)]
    return min(rooms) if rooms else obj.Clearance.Value


def panel_info(obj):
    need, warning = thermal_fit(obj)
    text = (f"<b>Sheet {obj.Width.Value:.1f} × {obj.Height.Value:.1f} mm</b><br>"
            f"{sheet_key(obj)}, {obj.Area.Value / 1e6:.3f} m², {obj.Mass:.2f} kg")
    if obj.Mount != "In slot":
        pass
    elif obj.Expansion <= 0:
        text += "<br><span style='color:gray'>Material not recognised: set Expansion to check the thermal fit</span>"
    elif warning:
        text += (f"<br><span style='color:#c60'>Too tight: needs {need:.2f} mm per side at the slot bottom "
                 f"(has {slot_room(obj):.2f}) between {obj.MinTemperature:g} and {obj.MaxTemperature:g} °C</span>")
    else:
        text += f"<br>Thermal fit OK ({need:.2f} of {slot_room(obj):.2f} mm room per side)"
    return text


PANEL_FIELDS = ("Mount", "Thickness", "Material", "Clearance", "InsertDepth", "Margin", "Side",
                "PlaneOffset", "Density", "Expansion", "MaxTemperature")


def make_panel(doc, profiles, **props):
    obj = doc.addObject("Part::FeaturePython", "Panel")
    Panel(obj)
    obj.Profiles = list(profiles)
    for name, value in props.items():
        setattr(obj, name, value)
    if App.GuiUp:
        ViewProviderPanel(obj.ViewObject)
    return obj
