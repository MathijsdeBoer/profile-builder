"""Frame stiffness estimate: a beam model of the document's frame, solved at two joint-stiffness bounds.

The model (see ``frame_model.py`` for the solver):

- Members are the profiles on path edges. Each is a beam along its section
  centre, with E·I from the modelled section (``Ix``, ``Iy``) and the mass of
  the piece. A profile that runs through T-junctions (``PassingMembers``) is
  split there and stays continuous.
- Nodes are the joints and the free profile ends. A member end reaches its
  node through a rigid link: the anchor offset (``Frame.center_offset``) and,
  for a trimmed end, the part of the joint inside the profile it butts against.
- At a butt joint the profile that runs through is rigidly connected and every
  other member end is connected through a rotational spring. At a miter
  neither profile runs through, so both ends get a spring (see
  ``_joint_springs``). Joint stiffness is not known, so the frame is solved
  twice: with loose joints (k = factor · E·I/L of the butting profile, by
  default 0.5, the limit below which EN 1993-1-8 counts a joint as pinned) and
  with stiff joints (by default rigid). Every result is that range. Which end
  gets which spring follows from the geometry and the joints' through rules,
  never from object names.
- The lowest nodes are the supports, pinned or fixed, each placed on the centre
  line of the profile standing on it. Loads act on the highest nodes: a
  sideways force in X and in Y (shared equally), and a twist about the
  vertical axis through their centre.
- Panels only add mass; their bracing effect is not modelled. T-nut slip, the
  floor, belts, drives and the toolhead are not modelled either.

Values are kept in mm, N, kg and s, and formatted through FreeCAD's unit
schema for display. Nothing here needs the GUI.
"""

import html
import json
import math
import os
from dataclasses import dataclass, field

import FreeCAD as App

from . import feature, joints, panels

V = App.Vector


def solver():
    """The solver module. It needs numpy and scipy, so it is only loaded when used.

    Both ship with FreeCAD 1.x; without them the workbench still loads, and
    only this analysis reports that it cannot run.
    """
    try:
        from . import frame_model
    except ImportError as e:
        raise ValueError("The frame stiffness estimate needs numpy and scipy in FreeCAD's Python, "
                         f"and they could not be loaded ({e}).") from e
    return frame_model

E_ALUMINIUM = 69000.0  # N/mm², 6060/6063/6005 alloys are 68-70 GPa
POISSON = 0.33
# T-slot sections are weak in torsion: the slots open the section, so only the
# core and closed chambers carry it. Vendor tables list torsion constants of
# roughly 10-30 % of the polar moment; the modelled section has no torsion
# constant of its own, so a fixed share is used.
TORSION_SHARE = 0.15
PINNED_LIMIT = 0.5  # EN 1993-1-8, 5.2.2.5: below 0.5 E·I/L a joint counts as nominally pinned
LEVEL = 1.0  # mm: nodes this close to the lowest (highest) height are supports (loaded)
MODES = 3

SETTINGS_NAME = "ProfileBuilderStiffness"
SUPPORTS = ("Pinned", "Fixed")
DEFAULTS = {"LooseJointFactor": PINNED_LIMIT, "StiffJointFactor": 0.0, "Supports": "Pinned", "TopMass": 0.0}
RESULT_VERSION = 1

ESTIMATE_NOTE = (
    "Estimates for comparing designs, not a strength check. Joint stiffness is not known, so each value is a "
    "range between loose joints and stiff joints. Frequencies are for the frame alone: belts, drives, the "
    "toolhead or spindle and the floor are not included. Panels add mass only; their bracing is not "
    "modelled. T-nut slip is not modelled.")


# ---- settings object ----------------------------------------------------------------


class Settings:
    """Document object holding the analysis settings and the stored baseline."""

    Type = "ProfileBuilder::StiffnessSettings"

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

        add("App::PropertyFloat", "LooseJointFactor", "Joints",
            "Joint stiffness at the loose bound, as a multiple of E·I/L of the profile that butts into the joint. "
            "Below 0.5, EN 1993-1-8 counts a joint as pinned.", DEFAULTS["LooseJointFactor"])
        add("App::PropertyFloat", "StiffJointFactor", "Joints",
            "Joint stiffness at the stiff bound, as a multiple of E·I/L of the butting profile (0: rigid joints)",
            DEFAULTS["StiffJointFactor"])
        add("App::PropertyEnumeration", "Supports", "Supports",
            "How the lowest nodes are held. Pinned: standing on feet or the floor. Fixed: bolted down stiffly.",
            list(SUPPORTS))
        add("App::PropertyMass", "TopMass", "Loads",
            "Extra mass carried at the top of the frame (a machine, a bed, a gantry), shared over the highest "
            "nodes. It lowers the natural frequencies.", DEFAULTS["TopMass"])
        add("App::PropertyString", "Baseline", "Baseline", "Stored results to compare variants with (JSON)", mode=2)
        add("App::PropertyStringList", "BaselineInfo", "Baseline", "Summary of the stored baseline", mode=1)

    def onDocumentRestored(self, obj):
        self._restoring = True
        try:
            self.add_properties(obj)
            if list(obj.getEnumerationsOfProperty("Supports")) != list(SUPPORTS):
                value = obj.Supports
                obj.Supports = list(SUPPORTS)
                if value in SUPPORTS:
                    obj.Supports = value
        finally:
            self._restoring = False

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        self._restoring = False
        return None

    __getstate__ = dumps
    __setstate__ = loads


class ViewProviderSettings:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return os.path.join(feature.ICON_DIR, "FrameStiffness.svg")

    def doubleClicked(self, vobj):
        import FreeCADGui as Gui
        from .frame_ui import open_panel
        if not Gui.Control.activeDialog():
            open_panel(vobj.Object.Document)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


def is_settings(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == Settings.Type


def get_settings(doc, create=False):
    obj = doc.getObject(SETTINGS_NAME)
    if obj is None and create:
        obj = doc.addObject("App::FeaturePython", SETTINGS_NAME)
        Settings(obj)
        obj.Label = "Frame stiffness"
        if App.GuiUp:
            ViewProviderSettings(obj.ViewObject)
    return obj


def settings_values(doc):
    """The analysis settings of a document (its settings object, else the defaults)."""
    obj = get_settings(doc)
    if obj is None:
        return dict(DEFAULTS)
    return {"LooseJointFactor": obj.LooseJointFactor, "StiffJointFactor": obj.StiffJointFactor,
            "Supports": obj.Supports, "TopMass": obj.TopMass.Value}


# ---- building the model -------------------------------------------------------------


@dataclass
class Segment:
    """One beam of the model: a profile, or the part of one between two T-junctions."""

    profile: str  # object name
    label: str
    start: int  # node indices
    end: int
    offsets: tuple  # world vectors (tuples) from the nodes to the beam ends
    spring: tuple  # per end: None (rigidly joined) or the scale of its joint spring (see _joint_springs)
    joint: tuple  # (joint label or None, ...) at each end, for the strain-energy shares
    section: object  # frame_model.Section
    y_axis: tuple
    span: float  # length of the whole profile, for E·I/L of its joint springs


@dataclass
class Frame:
    """The frame as nodes and segments, independent of the joint stiffness."""

    nodes: list = field(default_factory=list)  # (x, y, z)
    node_labels: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    masses: dict = field(default_factory=dict)  # node -> kg
    base: list = field(default_factory=list)
    top: list = field(default_factory=list)
    excluded: list = field(default_factory=list)  # objects left out, with the reason
    notes: list = field(default_factory=list)
    frame_mass: float = 0.0  # profiles and panels in the model, kg
    top_mass: float = 0.0
    joint_count: int = 0

    def add_node(self, point, label):
        self.nodes.append((point.x, point.y, point.z))
        self.node_labels.append(label)
        return len(self.nodes) - 1

    def add_mass(self, node, kg):
        if kg > 0:
            self.masses[node] = self.masses.get(node, 0.0) + kg

    def model(self, factor, supports="Pinned"):
        """A frame_model.Model with joint springs of ``factor`` · E·I/L (None: rigid joints)."""
        m = solver().Model()
        for p in self.nodes:
            m.node(p)
        for s in self.segments:
            springs = tuple(None if scale is None else _spring(s, factor, scale) for scale in s.spring)
            m.beam(s.start, s.end, s.section, s.y_axis, s.offsets, springs, tag=s)
        for node, kg in self.masses.items():
            m.add_mass(node, kg)
        for node in self.base:
            m.support(node, range(6) if supports == "Fixed" else (0, 1, 2))
        return m


def _spring(segment, factor, scale=1.0):
    """The joint spring at one end of a segment: scale · factor · (G·J, E·Iy, E·Iz) / L."""
    if factor is None:
        return None
    s, L, k = segment.section, segment.span, scale * factor
    return solver().Spring(k * s.G * s.J / L, k * s.E * s.iy / L, k * s.E * s.iz / L)


def _vec(v):
    return (v.x, v.y, v.z)


def _usable(joint):
    return joint is not None and joint.isValid() and "Touched" not in joint.State


MITER_SPRING = 2.0  # each half of a miter joint; two equal halves in series make factor · E·I/L


def _joint_springs(joint, used):
    """{(profile name, end): spring scale} for the ends at a joint; None is a rigid connection.

    The spring at an end is scale · factor · E·I/L of that end's profile.

    - T-junction: the passing profile is continuous, and every end butting
      into it has a spring (scale 1).
    - Butt joint: the profile that runs through (``joints.through_member``:
      the joint's rule, the profiles' roles, ties broken by direction) is
      rigid, every other end has a spring (scale 1). If that profile is not in
      the model, all ends get springs.
    - Miter: neither profile runs through, so the joint is split into two
      springs in series, one on each profile, of 2 · factor · E·I/L each. For
      two equal profiles the joint then has factor · E·I/L, like a butt joint.
    - A joint with one end in the model (the other profile has an error) is a
      free end.

    Nothing here depends on object names, so recreating or renaming profiles
    does not change the result.
    """
    ends = [(o.Name, e) for o, e in joints.ends_of(joint) if o.Name in used]
    if any(o.Name in used for o in joints.passing_of(joint)):
        return {end: 1.0 for end in ends}
    if len(ends) < 2:
        return {end: None for end in ends}
    if joint.Type == "Miter":
        return {end: MITER_SPRING for end in ends}
    try:
        through, end = joints.through_member(joint)
    except ValueError:
        through, end = None, None
    rigid = (through.Name, end) if through is not None and end is not None else None
    return {e: None if e == rigid else 1.0 for e in ends}


def build_frame(doc, top_mass=0.0):
    """Nodes and segments of the document's frame.

    Raises ValueError when there is nothing to analyse (no profiles on path
    edges, or a frame without height).
    """
    frame = Frame(top_mass=top_mass)
    used = []
    for obj in doc.Objects:
        if not feature.is_profile(obj):
            continue
        why = feature.problem(obj)
        if why:
            frame.excluded.append(f"{obj.Label}: {why}")
        elif not obj.PathEdge:
            frame.excluded.append(f"{obj.Label}: not on a sketch edge, so it is not joined to the frame")
        elif obj.Ix <= 0 or obj.Iy <= 0 or obj.SectionArea.Value <= 0:
            frame.excluded.append(f"{obj.Label}: no section properties yet (recompute the document)")
        else:
            used.append(obj)
    if not used:
        raise ValueError("There are no profiles on sketch edges to analyse. Put profiles on the edges of a "
                         "sketch and join them first.")
    names = {p.Name for p in used}

    joint_nodes, springs = {}, {}

    def joint_node(joint, point):
        if joint.Name not in joint_nodes:
            joint_nodes[joint.Name] = frame.add_node(point, joint.Label)
            springs[joint.Name] = _joint_springs(joint, names)
        return joint_nodes[joint.Name]

    passing = {}  # profile name -> [joint]
    for obj in doc.Objects:
        if joints.is_joint(obj) and _usable(obj):
            for name in obj.PassingMembers:
                if name in names:
                    passing.setdefault(name, []).append(obj)

    free_ends = []  # nodes of profile ends without a joint
    profile_nodes = {}  # profile name -> (start node, end node)
    for p in used:
        edge = feature.path_edge(p)
        p0, p1 = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        f = feature.member_frame(p)
        span = edge.Length
        ends = []
        for end, point in (("Start", p0), ("End", p1)):
            joint = getattr(p, f"{end}Joint")
            if _usable(joint):
                node = joint_node(joint, point)
                ends.append((node, springs[joint.Name].get((p.Name, end)), joint.Label))
            else:
                ends.append((frame.add_node(point, f"{p.Label} ({end.lower()})"), None, None))
                free_ends.append(ends[-1][0])
        profile_nodes[p.Name] = (ends[0][0], ends[1][0])

        stations = [(0.0, ends[0])]
        for joint in passing.get(p.Name, []):
            point = joint.Shape.Vertexes[0].Point if joint.Shape.Vertexes else None
            if point is None:
                continue
            t = (point - p0).dot(f.z)
            if 1e-6 < t < span - 1e-6:
                stations.append((t, (joint_node(joint, point), None, joint.Label)))
        stations.append((span, ends[1]))
        stations.sort(key=lambda s: s[0])

        # A trimmed end stops at the face of the profile it butts against; the
        # part of the joint up to the node is a rigid link. Extended ends
        # overhang the node and only add mass.
        centre = f.center_offset()
        trim_start = max(0.0, -(p.ExtendStart.Value + p.JointStartOffset.Value))
        trim_end = max(0.0, -(p.ExtendEnd.Value + p.JointEndOffset.Value))
        mass_per_mm = p.MassPerMeter / 1000.0
        ix, iy = p.Ix * 1e4, p.Iy * 1e4  # cm⁴ -> mm⁴
        section = solver().Section(
            E=E_ALUMINIUM, G=E_ALUMINIUM / (2 * (1 + POISSON)), A=p.SectionArea.Value,
            iy=ix, iz=iy, J=TORSION_SHARE * (ix + iy), mass_per_length=mass_per_mm)
        # Local y of the beam is the section's X; so bending about it uses Ix.
        modelled = 0.0
        last = len(stations) - 2
        for k, ((t0, a), (t1, b)) in enumerate(zip(stations, stations[1:])):
            cut0 = trim_start if k == 0 else 0.0
            cut1 = trim_end if k == last else 0.0
            length = (t1 - t0) - cut0 - cut1
            if length < 1.0:
                frame.notes.append(f"{p.Label}: a piece shorter than 1 mm between joints was left out")
                continue
            frame.segments.append(Segment(
                p.Name, p.Label, a[0], b[0],
                (_vec(centre + f.z * cut0), _vec(centre - f.z * cut1)),
                (a[1] if k == 0 else None, b[1] if k == last else None),
                (a[2], b[2]), section, _vec(f.x), span))
            modelled += length
        # The rest of the piece (overhangs past the nodes) is lumped at its ends.
        rest = max(0.0, p.Mass - mass_per_mm * modelled) / 2
        frame.add_mass(ends[0][0], rest)
        frame.add_mass(ends[1][0], rest)
    index = _keep_supported(frame)
    _supports_on_axes(frame)
    frame.joint_count = sum(1 for n in joint_nodes.values() if n in index)
    # Ends standing on the floor are supports; others hang free.
    hanging = [n for n in free_ends if n in index and index[n] not in frame.base]
    if hanging:
        frame.notes.append(f"{len(hanging)} profile end(s) above the supports have no joint; "
                           "they are free ends in the model")
    profile_nodes = {name: [index[n] for n in nodes if n in index] for name, nodes in profile_nodes.items()}
    kept = {s.profile for s in frame.segments}

    for obj in doc.Objects:
        if not panels.is_panel(obj):
            continue
        members = [m for m in obj.Profiles if feature.is_profile(m) and m.Name in kept]
        if not obj.isValid() or "Touched" in obj.State:
            frame.excluded.append(f"{obj.Label}: the panel has an error, so its mass is left out")
            continue
        if not members:
            frame.excluded.append(f"{obj.Label}: none of its profiles is in the model, so its mass is left out")
            continue
        corners = sorted({n for m in members for n in profile_nodes[m.Name]})
        for n in corners:
            frame.add_mass(n, obj.Mass / len(corners))
        frame.frame_mass += obj.Mass
    frame.frame_mass += sum(p.Mass for p in used if p.Name in kept)
    for n in frame.top:
        frame.add_mass(n, top_mass / len(frame.top))
    return frame


def _keep_supported(frame):
    """Keep the members connected to the supports, and set the supports and the top.

    The supports are the lowest nodes of the whole frame. Parts that do not
    reach them would just float, so they are left out (and listed). Returns
    {old node index: new node index}.
    """
    zs = [p[2] for p in frame.nodes]
    low = min(zs)
    parent = list(range(len(frame.nodes)))

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for s in frame.segments:
        parent[find(s.start)] = find(s.end)
    on_members = {n for s in frame.segments for n in (s.start, s.end)}
    grounded = {find(n) for n in on_members if zs[n] < low + LEVEL}
    floating = sorted({s.label for s in frame.segments if find(s.start) not in grounded})
    if floating:
        frame.excluded.append("not connected to the supports (the lowest nodes), so left out: " + ", ".join(floating))
    frame.segments = [s for s in frame.segments if find(s.start) in grounded]
    keep = sorted({n for s in frame.segments for n in (s.start, s.end)})
    index = {old: new for new, old in enumerate(keep)}
    frame.nodes = [frame.nodes[n] for n in keep]
    frame.node_labels = [frame.node_labels[n] for n in keep]
    frame.masses = {index[n]: kg for n, kg in frame.masses.items() if n in index}
    for s in frame.segments:
        s.start, s.end = index[s.start], index[s.end]
    if not frame.segments:
        raise ValueError("No profile is connected to the supports (the lowest nodes).")
    zs = [p[2] for p in frame.nodes]
    high = max(zs)
    if high - low < LEVEL:
        raise ValueError("The frame has no height: the lowest nodes are the supports and the loads act on the "
                         "highest ones, so stand the frame up along Z.")
    frame.base = [n for n, z in enumerate(zs) if z < low + LEVEL]
    frame.top = [n for n, z in enumerate(zs) if z > high - LEVEL]
    return index


def _supports_on_axes(frame):
    """Put each support on the centre line of the profile standing on it.

    Nodes are sketch vertices, and an anchored profile sits beside its sketch
    line. A pin beside a post would act partly as a clamp, because the post
    could only turn about it by stretching. So each support node moves to the
    nearest point on the centre line of its most upright member (the average
    point when several are equally upright), and the rigid links of all the
    members at that node are shifted to match. For a post that point is
    straight below its centre, at the node's height. Fixed supports give the
    same result either way.
    """
    for n in frame.base:
        node = V(*frame.nodes[n])
        found = []  # (how upright, nearest point on the centre line)
        for s in frame.segments:
            for end, at, other in ((0, s.start, s.end), (1, s.end, s.start)):
                if at != n:
                    continue
                a = node + V(*s.offsets[end])
                d = V(*frame.nodes[other]) + V(*s.offsets[1 - end]) - a
                if d.Length < 1e-9:
                    continue
                d.normalize()
                found.append((round(abs(d.z), 6), a + d * (node - a).dot(d)))
        if not found:
            continue
        most = max(upright for upright, _p in found)
        points = [p for upright, p in found if upright == most]
        target = V(sum(p.x for p in points) / len(points), sum(p.y for p in points) / len(points),
                   sum(p.z for p in points) / len(points))
        shift = target - node
        if shift.Length < 1e-9:
            continue
        frame.nodes[n] = _vec(target)
        for s in frame.segments:
            if n in (s.start, s.end):
                s.offsets = tuple(_vec(V(*o) - shift) if at == n else o
                                  for o, at in zip(s.offsets, (s.start, s.end)))


# ---- analysis ---------------------------------------------------------------------


def analyse(doc, values=None):
    """Results of the frame at both joint-stiffness bounds, as a JSON-friendly dict.

    Raises ValueError when there is nothing to analyse. Callers run
    ``cutlist.recompute_if_needed(doc)`` first.
    """
    values = dict(DEFAULTS, **(values or settings_values(doc)))
    frame = build_frame(doc, values["TopMass"])
    stiff = values["StiffJointFactor"]
    bounds = {"loose": _bound(frame, max(values["LooseJointFactor"], 1e-6), values["Supports"]),
              "stiff": _bound(frame, stiff if stiff > 0 else None, values["Supports"])}
    result = {
        "version": RESULT_VERSION,
        "settings": values,
        "bounds": bounds,
        "mass": frame.frame_mass,
        "members": len({s.profile for s in frame.segments}),
        "joints": frame.joint_count,
        "supports": len(frame.base),
        "top": len(frame.top),
        "excluded": frame.excluded,
        "notes": frame.notes,
    }
    result.update(_cost(doc))
    return result


def _cost(doc):
    """The cut list's total (None when it could not be built), what has no price, and whether it has errors."""
    from . import cutlist
    try:
        report = cutlist.build_report(doc)
    except Exception:  # noqa: BLE001 - the cost is a side note, never a reason to fail
        return {"cost": None, "currency": "", "unpriced": [], "cost_errors": False}
    return {"cost": report.total, "currency": report.currency, "unpriced": list(report.unpriced),
            "cost_errors": bool(report.errors)}


def _bound(frame, factor, supports):
    model = frame.model(factor, supports)
    out = {"factor": factor, "x": None, "y": None, "twist": None, "modes": [], "flex": {}, "mechanism": None}
    top = frame.top
    pts = [frame.nodes[n] for n in top]
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    arms = [(p[0] - cx, p[1] - cy) for p in pts]
    r2 = sum(x * x + y * y for x, y in arms)
    cases = {"x": {n: (1.0 / len(top), 0.0, 0.0) for n in top},
             "y": {n: (0.0, 1.0 / len(top), 0.0) for n in top}}
    if r2 > 1.0:
        cases["twist"] = {n: (-y / r2, x / r2, 0.0) for n, (x, y) in zip(top, arms)}  # 1 N·mm in total
    try:
        for name, loads in cases.items():
            static = model.solve(loads)
            if name == "twist":
                turn = sum(x * static.displacement(n)[1] - y * static.displacement(n)[0]
                           for n, (x, y) in zip(top, arms)) / r2
                value = 1.0 / turn if turn > 0 else None
            else:
                axis = 0 if name == "x" else 1
                move = sum(static.displacement(n)[axis] for n in top) / len(top)
                value = 1.0 / move if move > 0 else None
            out[name] = value
            out["flex"][name] = _flex(static)
    except solver().MechanismError as e:
        out["mechanism"] = _mechanism_text(frame, e)
        out["x"] = out["y"] = out["twist"] = None
        out["flex"] = {}
        return out
    try:
        modes = model.modes(MODES)
        out["modes"] = [[f, _mode_label(p)] for f, p in zip(modes.frequencies, modes.participation)]
    except ValueError as e:  # scipy's LinAlgError is a ValueError
        out["modes_error"] = f"The natural frequencies could not be computed ({e})."
    return out


def _flex(static):
    """Where the strain energy goes: shares of joints and members, and the largest items."""
    total = static.energy
    if total <= 0:
        return {"joints": 0.0, "largest": []}
    items = {}
    joint_energy = 0.0
    for beam, energy, (at_i, at_j) in zip(static.model.beams, static.beam_energy, static.spring_energy):
        seg = beam.tag
        items[seg.label] = items.get(seg.label, 0.0) + energy
        for label, e in ((seg.joint[0], at_i), (seg.joint[1], at_j)):
            if e > 0:
                items[label] = items.get(label, 0.0) + e
                joint_energy += e
    largest = sorted(items.items(), key=lambda kv: -kv[1])[:3]
    return {"joints": joint_energy / total, "largest": [[label, e / total] for label, e in largest]}


MODE_NAMES = {"X": "sways in X", "Y": "sways in Y", "Z": "bounces vertically", "twist": "twists"}


def _mode_label(participation):
    name, share = max(participation.items(), key=lambda kv: kv[1])
    return MODE_NAMES[name] if share >= 0.1 else "local"


def _mechanism_text(frame, error):
    nodes = set(error.nodes)
    labels = sorted({s.label for s in frame.segments if s.start in nodes or s.end in nodes})
    where = ", ".join(labels[:6]) + (" ..." if len(labels) > 6 else "")
    return (f"The frame can move without bending anything (a mechanism){': ' + where if where else ''}. "
            "Add a joint, a diagonal, or fixed supports.")


# ---- baseline --------------------------------------------------------------------


def baseline(doc):
    """The stored baseline result, or None."""
    obj = get_settings(doc)
    if obj is None or not obj.Baseline:
        return None
    try:
        data = json.loads(obj.Baseline)
    except ValueError:
        return None
    return data if data.get("version") == RESULT_VERSION else None


def set_baseline(doc, result):
    obj = get_settings(doc, create=True)
    obj.Baseline = json.dumps(result)
    obj.BaselineInfo = [f"{label}: {loose} to {stiff}" for label, loose, stiff, _vs in report_rows(result)]


def clear_baseline(doc):
    obj = get_settings(doc)
    if obj is not None:
        obj.Baseline = ""
        obj.BaselineInfo = []


# ---- formatting through the unit schema ----------------------------------------------------


def _decimal_point():
    return "," if "," in App.Units.Quantity(1.25).UserString else "."


def number(value, digits=3):
    """A number with about ``digits`` significant digits, in the decimal format FreeCAD uses."""
    if value == 0 or not math.isfinite(value):
        return "0" if value == 0 else str(value)
    decimals = max(0, digits - 1 - int(math.floor(math.log10(abs(value)))))
    return f"{value:.{decimals}f}".replace(".", _decimal_point())


def _imperial():
    mass = App.Units.Quantity("1 kg").getUserPreferred()[2]
    length = App.Units.Quantity("100 mm").getUserPreferred()[2]
    return mass == "lb" or length in ("in", "ft", "'", '"', "thou", "yd", "mi")


# kind: (FreeCAD unit of the stored value, metric fallback, imperial fallback); fallbacks are
# (factor from the stored value, unit name)
KINDS = {
    "stiffness": ("N/mm", (1.0, "N/mm"), (5.710147, "lbf/in")),
    "moment": ("N*mm", (1e-3, "N·m"), (7.375621e-4, "lbf·ft")),
    "mass": ("kg", (1.0, "kg"), (2.204623, "lb")),
}


def unit_for(kind, magnitude):
    """(factor, unit name) to show a value of ``kind`` (N/mm, N·mm or kg) the way the unit schema does."""
    base, metric, imperial = KINDS[kind]
    unit = App.Units.Quantity(f"1 {base}")
    try:
        _text, factor, name = (unit * abs(magnitude or 1.0)).getUserPreferred()
    except Exception:  # noqa: BLE001
        factor, name = 0, ""
    # Schemas without a rule for this kind print raw base units ("kg/s^2", "mm^2*kg/s^2"), and
    # FreeCAD before 1.1 shows a moment as energy ("J"), which reads wrong for a torque.
    if not name or not factor or "^" in name or "*" in name or (kind == "moment" and name.endswith("J")):
        return imperial if _imperial() else metric
    if name.endswith("Nm"):
        name = name[:-2] + "N·m"
    return unit.Value / factor, name


def quantity(value, kind):
    if value is None:
        return "–"
    factor, name = unit_for(kind, value)
    return f"{number(value * factor)} {name}"


def twist_text(value):
    """A twist stiffness (N·mm per radian) as moment per degree."""
    if value is None:
        return "–"
    per_degree = value * math.pi / 180
    factor, name = unit_for("moment", per_degree)
    return f"{number(per_degree * factor)} {name}/°"


def frequency_text(mode):
    if not mode:
        return "–"
    f, label = mode
    return f"{number(f)} Hz ({label})"


def _ratio(now, before):
    if not now or not before:
        return None
    return now / before


def ratio_text(low, high):
    """'2.1–2.6×' for the change against the baseline at the two bounds."""
    ratios = sorted(r for r in (low, high) if r is not None)
    if not ratios:
        return ""
    a, b = ratios[0], ratios[-1]
    if abs(b - a) < 0.005 * max(a, b):
        return f"{number(a, 2)}×"
    return f"{number(a, 2)}–{number(b, 2)}×"


def report_rows(result, base=None):
    """[(label, loose, stiff, vs baseline)] for the results table."""
    bounds = [result["bounds"]["loose"], result["bounds"]["stiff"]]
    before = [base["bounds"]["loose"], base["bounds"]["stiff"]] if base else None

    def mode(bound, i):
        modes = bound.get("modes") or []
        return modes[i] if len(modes) > i else None

    def vs(pick):
        if not before:
            return ""
        return ratio_text(*(_ratio(pick(now), pick(was)) for now, was in zip(bounds, before)))

    rows = []
    for key, label in (("x", "Sideways stiffness, X"), ("y", "Sideways stiffness, Y")):
        rows.append((label, *(quantity(b[key], "stiffness") for b in bounds), vs(lambda b, k=key: b.get(k))))
    rows.append(("Twist stiffness", *(twist_text(b["twist"]) for b in bounds), vs(lambda b: b.get("twist"))))
    for i in range(MODES):
        if any(mode(b, i) for b in bounds):
            rows.append((f"Frequency {i + 1}", *(frequency_text(mode(b, i)) for b in bounds),
                         vs(lambda b, i=i: (mode(b, i) or [None])[0])))
    return rows


def _signed(text, value):
    return ("+" if value > 0 else "") + text if value else text


def cost_line(result, base):
    """The cost change against the baseline, or None when neither has a price.

    Products and sheets without a price are not in a total. When the variant
    and the baseline lack different ones, the difference means nothing, so it
    is not given; when they lack the same ones, it leaves those out and says so.
    """
    if not base or not (result.get("cost") or base.get("cost")):
        return None
    if result.get("cost") is None or base.get("cost") is None:
        return "The cost change against the baseline is not known: the cut list could not be built."
    now, was = set(result.get("unpriced") or ()), set(base.get("unpriced") or ())
    if now != was:
        return ("The cost change against the baseline is not known: no price for "
                + ", ".join(sorted(now | was)) + ".")
    from .pricing import format_money
    delta = result["cost"] - base["cost"]
    notes = []
    if now:
        notes.append("no price for " + ", ".join(sorted(now)) + ", so it is left out of both")
    if result.get("cost_errors") or base.get("cost_errors"):
        notes.append("the cut list has errors")
    return (f"Cost {_signed(format_money(delta, result['currency']), delta)} against the baseline"
            + (f" ({'; '.join(notes)})" if notes else "") + ".")


def summary_lines(result, base=None):
    """Lines about the model itself: size, mass, cost, and the change against the baseline."""
    lines = [f"{result['members']} profile(s) and {result['joints']} joint(s). Supports: the {result['supports']} "
             f"lowest node(s), {result['settings']['Supports'].lower()}. The stiffness is measured at the "
             f"{result['top']} highest node(s)."]
    mass = f"Frame mass {quantity(result['mass'], 'mass')}"
    if result["settings"]["TopMass"]:
        mass += f", plus {quantity(result['settings']['TopMass'], 'mass')} on top"
    if base:
        delta = result["mass"] - base["mass"]
        mass += f" ({_signed(quantity(delta, 'mass'), delta)} against the baseline)"
    lines.append(mass + ".")
    cost = cost_line(result, base)
    if cost:
        lines.append(cost)
    if base and base.get("settings") != result.get("settings"):
        lines.append("The baseline was computed with other settings, so the comparison mixes them.")
    return lines


def flex_lines(result):
    """Where the frame flexes at the loose bound, per load case."""
    lines = []
    flex = result["bounds"]["loose"].get("flex", {})
    for key, name in (("x", "Sideways in X"), ("y", "Sideways in Y"), ("twist", "Twist")):
        if key not in flex:
            continue
        f = flex[key]
        largest = ", ".join(f"{label} {number(100 * share, 2)} %" for label, share in f["largest"])
        lines.append(f"{name}: {number(100 * f['joints'], 2)} % of the flexing is in the joints; most in {largest}")
    return lines


def assumption_lines(result):
    s = result["settings"]
    loose = s["LooseJointFactor"]
    stiff = s["StiffJointFactor"]
    stiff_text = "rigid" if stiff <= 0 else f"k = {number(stiff, 2)} · E·I/L"
    return [ESTIMATE_NOTE,
            f"Loose joints: k = {number(loose, 2)} · E·I/L of the butting profile (below {number(PINNED_LIMIT, 1)}, "
            f"EN 1993-1-8 counts a joint as pinned). Stiff joints: {stiff_text}. At a miter each profile gets a "
            f"spring of {number(MITER_SPRING, 1)}·k of its own, in series, so two equal profiles make k.",
            f"E = {number(E_ALUMINIUM / 1000, 3)} GPa; torsion constant taken as {TORSION_SHARE * 100:g} % of the "
            "polar moment, because the slotted section's own is not modelled."]


def problem_lines(result):
    """[(bound name, message)] for mechanisms and failed frequency analyses."""
    out = []
    for bound in ("loose", "stiff"):
        b = result["bounds"][bound]
        for key in ("mechanism", "modes_error"):
            if b.get(key):
                out.append((f"{bound.capitalize()} joints", b[key]))
    return out


def report_text(result, base=None):
    """The whole report as plain text, for the report view."""
    lines = ["Frame stiffness (estimate)"]
    lines += summary_lines(result, base)
    lines += [f"{bound}: {message}" for bound, message in problem_lines(result)]
    header = ("", "Loose joints", "Stiff joints", "Against baseline" if base else "")
    rows = [header] + report_rows(result, base)
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for r in rows:
        lines.append("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    lines += flex_lines(result)
    lines += [f"Left out: {e}" for e in result["excluded"]]
    lines += result["notes"]
    lines += assumption_lines(result)
    return "\n".join(lines)


def _esc(text):
    return html.escape(text, quote=False)


def report_html(result, base=None):
    """The report as rich text for the task panel."""
    parts = []
    if result["excluded"]:
        parts.append("<p style='color:#c33'><b>Incomplete: left out of the model</b><br>"
                     + "<br>".join(_esc(e) for e in result["excluded"]) + "</p>")
    for bound, message in problem_lines(result):
        parts.append(f"<p style='color:#c33'><b>{bound}:</b> {_esc(message)}</p>")
    head = "<tr><th></th><th>Loose joints</th><th>Stiff joints</th>" + ("<th>Against baseline</th>" if base else "")
    rows = [head + "</tr>"]
    for label, loose, stiff, vs in report_rows(result, base):
        rows.append(f"<tr><td>{_esc(label)}</td><td>{_esc(loose)}</td><td>{_esc(stiff)}</td>"
                    + (f"<td>{_esc(vs)}</td>" if base else "") + "</tr>")
    parts.append("<table cellspacing='0' cellpadding='3' border='0'>" + "".join(rows) + "</table>")
    parts.append("<p>" + "<br>".join(_esc(line) for line in summary_lines(result, base)) + "</p>")
    flex = flex_lines(result)
    if flex:
        parts.append("<p><b>Where it flexes</b> (loose joints)<br>" + "<br>".join(_esc(x) for x in flex) + "</p>")
    if result["notes"]:
        parts.append("<p>" + "<br>".join(_esc(n) for n in result["notes"]) + "</p>")
    parts.append("<p style='color:gray'>" + "<br>".join(_esc(x) for x in assumption_lines(result)) + "</p>")
    return "".join(parts)


def parse_mass(text):
    """Mass in kg from text such as '5 kg', '11 lb' or '5' (in the schema's mass unit); None if invalid."""
    text = text.strip()
    if not text:
        return 0.0
    try:
        q = App.Units.Quantity(text.replace(",", "."))
    except (ValueError, ArithmeticError):
        return None
    if q.Unit == App.Units.Quantity("1 kg").Unit:
        return q.Value if q.Value >= 0 else None
    if q.Unit == App.Units.Unit():
        _t, factor, _name = App.Units.Quantity("1 kg").getUserPreferred()
        value = q.Value * factor
        return value if value >= 0 else None
    return None


def mass_text(kg):
    """A mass in the unit schema's unit, for the mass input (parse_mass reads it back)."""
    factor, name = unit_for("mass", kg)
    text = number(kg * factor, 7)
    if _decimal_point() in text:
        text = text.rstrip("0").rstrip(_decimal_point())
    return f"{text} {name}"
