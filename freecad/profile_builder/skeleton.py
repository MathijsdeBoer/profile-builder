"""Parametric wire skeleton for a generated box frame."""

import math
import os

import FreeCAD as App
import Part

from . import feature

V = App.Vector
SIZE_MODES = ("Outside", "Inside clear", "Centre lines")
SKELETON_TYPE = "ProfileBuilder::Skeleton"


def is_skeleton(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == SKELETON_TYPE


def centerline_spans(width, depth, height, size_mode,
                     post_width, post_depth, rail_width, rail_height):
    values = (width, depth, height, post_width, post_depth, rail_width, rail_height)
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("Frame dimensions and section sizes must be positive lengths")
    if size_mode == "Outside":
        spans = (width - max(post_width, rail_width),
                 depth - max(post_depth, rail_width),
                 height - rail_height)
        if spans[0] <= 0 or spans[1] <= 0 or spans[2] <= 0:
            raise ValueError("Outside dimensions must exceed the section sizes")
    elif size_mode == "Inside clear":
        spans = (width + max(post_width, rail_width),
                 depth + max(post_depth, rail_width),
                 height + rail_height)
    elif size_mode == "Centre lines":
        spans = (width, depth, height)
    else:
        raise ValueError(f"Unknown size mode: {size_mode}")
    return spans


def _projected_sizes(profile):
    width = profile.Columns * profile.CellSize.Value
    height = profile.Rows * profile.CellSize.Value
    spin = math.radians(profile.Spin.Value)
    c, s = abs(math.cos(spin)), abs(math.sin(spin))
    return c * width + s * height, s * width + c * height


def _section_sizes(obj):
    post_widths, post_depths = [], []
    rail_widths, rail_heights = [], []
    for member in obj.InList:
        if not feature.is_profile(member) or not member.PathEdge:
            continue
        link, subnames = member.PathEdge
        if getattr(link, "Name", None) != obj.Name:
            continue
        if isinstance(subnames, str):
            subnames = (subnames,)
        for subname in subnames:
            try:
                edge_number = int(subname.lstrip("?")[4:])
            except ValueError:
                continue
            first, second = _projected_sizes(member)
            if edge_number in range(1, 9):
                rail_widths.append(first)
                rail_heights.append(second)
            elif edge_number in range(9, 13):
                post_widths.append(first)
                post_depths.append(second)

    return (
        max(post_widths, default=obj.FallbackPostWidth.Value),
        max(post_depths, default=obj.FallbackPostDepth.Value),
        max(rail_widths, default=obj.FallbackRailWidth.Value),
        max(rail_heights, default=obj.FallbackRailHeight.Value),
    )


class Skeleton:
    Type = SKELETON_TYPE

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

        add("App::PropertyLength", "Width", "Dimensions",
            "Requested width: outside, inside clear or between post centre lines", 600.0)
        add("App::PropertyLength", "Depth", "Dimensions",
            "Requested depth: outside, inside clear or between post centre lines", 600.0)
        add("App::PropertyLength", "Height", "Dimensions",
            "Requested height: outside, inside clear or between rail centre lines", 700.0)
        add("App::PropertyEnumeration", "SizeMode", "Dimensions",
            "How Width, Depth and Height are measured", list(SIZE_MODES))

        add("App::PropertyLength", "PostWidth", "Section sizes",
            "Effective post section width along X", 0.0, 1)
        add("App::PropertyLength", "PostDepth", "Section sizes",
            "Effective post section depth along Y", 0.0, 1)
        add("App::PropertyLength", "RailWidth", "Section sizes",
            "Effective rail section width across the frame", 0.0, 1)
        add("App::PropertyLength", "RailHeight", "Section sizes",
            "Effective rail section height", 0.0, 1)

        add("App::PropertyLength", "FallbackPostWidth", "Section sizes",
            "Post width used when no post profile is attached", 20.0, 2)
        add("App::PropertyLength", "FallbackPostDepth", "Section sizes",
            "Post depth used when no post profile is attached", 20.0, 2)
        add("App::PropertyLength", "FallbackRailWidth", "Section sizes",
            "Rail width used when no rail profile is attached", 20.0, 2)
        add("App::PropertyLength", "FallbackRailHeight", "Section sizes",
            "Rail height used when no rail profile is attached", 20.0, 2)

    def onDocumentRestored(self, obj):
        self._restoring = True
        try:
            self.add_properties(obj)
            choices = list(obj.getEnumerationsOfProperty("SizeMode") or [])
            if choices != list(SIZE_MODES):
                current = obj.SizeMode
                obj.SizeMode = list(SIZE_MODES)
                obj.SizeMode = current if current in SIZE_MODES else SIZE_MODES[0]
        finally:
            self._restoring = False

    def execute(self, obj):
        post_width, post_depth, rail_width, rail_height = _section_sizes(obj)
        obj.PostWidth = post_width
        obj.PostDepth = post_depth
        obj.RailWidth = rail_width
        obj.RailHeight = rail_height
        spans = centerline_spans(obj.Width.Value, obj.Depth.Value, obj.Height.Value, obj.SizeMode,
                                 post_width, post_depth, rail_width, rail_height)
        width, depth, height = spans
        corners = ((0.0, 0.0), (width, 0.0), (width, depth), (0.0, depth))
        segments = []
        for z in (0.0, height):
            segments.extend((V(*corners[i], z), V(*corners[(i + 1) % 4], z)) for i in range(4))
        segments.extend((V(x, y, 0.0), V(x, y, height)) for x, y in corners)
        obj.Shape = Part.makeCompound([Part.makeLine(start, end) for start, end in segments])

    def dumps(self):
        return None

    def loads(self, state):
        self._restoring = False
        return None

    __getstate__ = dumps
    __setstate__ = loads


class ViewProviderSkeleton:
    def __init__(self, vobj):
        vobj.Proxy = self
        self.attach(vobj)

    def attach(self, vobj):
        self.Object = vobj.Object
        vobj.LineColor = (0.22, 0.42, 0.62)
        vobj.PointColor = (0.22, 0.42, 0.62)
        vobj.LineWidth = 2.0

    def getIcon(self):
        return os.path.join(feature.ICON_DIR, "BoxFrame.svg")

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make_skeleton(doc, width=600.0, depth=600.0, height=700.0, size_mode="Outside",
                  post_width=20.0, post_depth=20.0, rail_width=20.0, rail_height=20.0):
    obj = doc.addObject("Part::FeaturePython", "FrameSkeleton")
    Skeleton(obj)
    obj.Width = width
    obj.Depth = depth
    obj.Height = height
    obj.SizeMode = size_mode
    obj.FallbackPostWidth = post_width
    obj.FallbackPostDepth = post_depth
    obj.FallbackRailWidth = rail_width
    obj.FallbackRailHeight = rail_height
    if App.GuiUp:
        ViewProviderSkeleton(obj.ViewObject)
    obj.Label = "Frame skeleton"
    return obj


def touch_skeleton_of(profile):
    path = getattr(profile, "PathEdge", None)
    if path and len(path) == 2 and is_skeleton(path[0]):
        path[0].touch()
