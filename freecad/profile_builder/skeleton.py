"""Parametric wire skeleton for a generated box frame."""

import math
import os

import FreeCAD as App
import Part

from . import feature

V = App.Vector
SIZE_MODES = ("Outside", "Inside clear", "Centre lines")
SKELETON_TYPE = "ProfileBuilder::Skeleton"

# Edge1-4 are the bottom ring from (0, 0) to (W, 0) onwards, Edge5-8 the top ring, and Edge9-12
# the posts at (0, 0), (W, 0), (W, D) and (0, D). Each side of the frame is set by its posts and
# by the rails that run along it: (posts, rails).
LEFT, RIGHT = ((9, 12), (4, 8)), ((10, 11), (2, 6))  # x = 0, x = W
FRONT, BACK = ((9, 10), (1, 5)), ((11, 12), (3, 7))  # y = 0, y = D
BOTTOM, TOP = (1, 2, 3, 4), (5, 6, 7, 8)


def is_skeleton(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == SKELETON_TYPE


def uniform_sides(post_width, post_depth, rail_width, rail_height):
    """Side sizes (left, right, front, back, bottom, top) of a frame with one post and one rail section."""
    across_x, across_y = max(post_width, rail_width), max(post_depth, rail_width)
    return across_x, across_x, across_y, across_y, rail_height, rail_height


def rails_collide(post_width, post_depth, rail_width):
    """True when rails wider than the post both ways would run into each other at the corners.

    Each rail butts against the post face, so a rail wider than the post in
    both directions reaches into the corner where the other rail also ends.
    """
    return rail_width > max(post_width, post_depth) + 1e-9


def centerline_spans(width, depth, height, size_mode, sides):
    """Centre-line spans for the requested size.

    ``sides`` is the section size at the left, right, front, back, bottom and
    top of the frame (see uniform_sides); the line sits in the middle of it.
    """
    values = (width, depth, height) + tuple(sides)
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("Frame dimensions and section sizes must be positive lengths")
    left, right, front, back, bottom, top = sides
    insets = ((left + right) / 2, (front + back) / 2, (bottom + top) / 2)
    if size_mode == "Outside":
        spans = (width - insets[0], depth - insets[1], height - insets[2])
        if spans[0] <= 0 or spans[1] <= 0 or spans[2] <= 0:
            raise ValueError("Outside dimensions must exceed the section sizes")
    elif size_mode == "Inside clear":
        spans = (width + insets[0], depth + insets[1], height + insets[2])
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


def members(obj):
    """The profiles on the skeleton's edges, by edge number (1-8 rails, 9-12 posts)."""
    found = {}
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
            if 1 <= edge_number <= 12:
                found.setdefault(edge_number, []).append(member)
    return found


def _section_sizes(obj):
    """The largest post width and depth, rail width and height, and the side sizes.

    A side takes the largest section on it, so heavier bottom rails or front
    posts move only that side's line and the requested size still holds.
    """
    sizes = {edge: [_projected_sizes(member) for member in found]
             for edge, found in members(obj).items()}

    def largest(edges, index, fallback):
        return max((size[index] for edge in edges for size in sizes.get(edge, ())), default=fallback)

    post_width, post_depth = obj.FallbackPostWidth.Value, obj.FallbackPostDepth.Value
    rail_width, rail_height = obj.FallbackRailWidth.Value, obj.FallbackRailHeight.Value
    posts, rails = range(9, 13), range(1, 9)

    def side(edges, post_index, post_fallback):
        post_edges, rail_edges = edges
        return max(largest(post_edges, post_index, post_fallback), largest(rail_edges, 0, rail_width))

    sides = (side(LEFT, 0, post_width), side(RIGHT, 0, post_width),
             side(FRONT, 1, post_depth), side(BACK, 1, post_depth),
             largest(BOTTOM, 1, rail_height), largest(TOP, 1, rail_height))
    return (largest(posts, 0, post_width), largest(posts, 1, post_depth),
            largest(rails, 0, rail_width), largest(rails, 1, rail_height), sides)


def measured_size(obj):
    """The frame's size measured from its profiles the way SizeMode asks, or None.

    None when a profile is missing or has no solid. The requested size can
    differ when a profile was moved off its line (a section offset from Align
    slots, an anchor or a spin) or a joint rule was changed.
    """
    if obj.SizeMode == "Centre lines":
        box = obj.Shape.BoundBox
        return box.XLength, box.YLength, box.ZLength
    boxes = {}
    for edge, found in members(obj).items():
        solids = [member.Shape for member in found
                  if member.isValid() and not member.Shape.isNull() and member.Shape.Solids]
        if solids:
            boxes[edge] = [shape.BoundBox for shape in solids]
    if len(boxes) < 12:
        return None
    if obj.SizeMode == "Outside":
        box = App.BoundBox()
        for found in boxes.values():
            for member_box in found:
                box.add(member_box)
        return box.XLength, box.YLength, box.ZLength

    def reach(sides, attr, pick):
        return pick(getattr(box, attr) for edges in sides for edge in edges for box in boxes[edge])

    return (reach(RIGHT, "XMin", min) - reach(LEFT, "XMax", max),
            reach(BACK, "YMin", min) - reach(FRONT, "YMax", max),
            reach((TOP,), "ZMin", min) - reach((BOTTOM,), "ZMax", max))


class Skeleton:
    Type = SKELETON_TYPE

    def __init__(self, obj):
        obj.Proxy = self
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
        self.add_properties(obj)
        choices = list(obj.getEnumerationsOfProperty("SizeMode") or [])
        if choices != list(SIZE_MODES):
            current = obj.SizeMode
            obj.SizeMode = list(SIZE_MODES)
            obj.SizeMode = current if current in SIZE_MODES else SIZE_MODES[0]

    def execute(self, obj):
        post_width, post_depth, rail_width, rail_height, sides = _section_sizes(obj)
        obj.PostWidth = post_width
        obj.PostDepth = post_depth
        obj.RailWidth = rail_width
        obj.RailHeight = rail_height
        spans = centerline_spans(obj.Width.Value, obj.Depth.Value, obj.Height.Value, obj.SizeMode, sides)
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
        return None

    __getstate__ = dumps
    __setstate__ = loads


class ViewProviderSkeleton:
    def __init__(self, vobj):
        vobj.Proxy = self
        self.attach(vobj)
        # Only for a new skeleton: attach also runs when a document is opened, after the
        # user's own colours and line width were restored.
        vobj.LineColor = (0.22, 0.42, 0.62)
        vobj.PointColor = (0.22, 0.42, 0.62)
        vobj.LineWidth = 2.0

    def attach(self, vobj):
        self.Object = vobj.Object

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
