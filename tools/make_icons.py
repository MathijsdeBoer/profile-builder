"""Regenerate the section icons from the real geometry.

Run with FreeCAD's console:  freecadcmd tools/make_icons.py
"""

import os
import sys

import freecad

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in globals() else os.getcwd()
# Use this checkout, not an installed copy FreeCAD may already have loaded.
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

from freecad.profile_builder import geometry, profiles  # noqa: E402

ICONS = os.path.join(ROOT, "freecad", "profile_builder", "resources", "icons")
FILL, STROKE = "#b8c0cb", "#3a4450"


def section_path(key, cols, rows, box=56.0, origin=(32.0, 32.0)):
    series = profiles.SERIES[key]
    face = geometry.make_section(series.dimensions(), cols, rows)
    scale = box / (max(cols, rows) * series.cell)
    ox, oy = origin
    d = []
    for wire in face.Wires:
        pts = []
        for edge in wire.OrderedEdges:
            q = edge.discretize(Deflection=0.02)
            if pts and (q[0] - pts[-1]).Length > (q[-1] - pts[-1]).Length:
                q.reverse()
            pts += q
        d.append("M" + " L".join(f"{ox + p.x * scale:.2f},{oy - p.y * scale:.2f}" for p in pts) + "Z")
    return " ".join(d)


def svg(body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n'
            f"{body}\n</svg>\n")


def section(key, cols, rows, **kw):
    return (f'<path d="{section_path(key, cols, rows, **kw)}" fill="{FILL}" stroke="{STROKE}" '
            'stroke-width="1.2" stroke-linejoin="round" fill-rule="evenodd"/>')


def write(name, content):
    path = os.path.join(ICONS, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


for key, series in profiles.SERIES.items():
    for cols, rows in series.sizes:
        write(f"sizes/{key}_{cols}x{rows}.svg", svg(section(key, cols, rows)))

write("Profile.svg", svg(section("20-6", 1, 1)))
write("ProfileBuilder.svg", svg(section("20-6", 1, 2, box=58)))
plus = ('<circle cx="49" cy="49" r="12" fill="#3c9a3c" stroke="#fff" stroke-width="2"/>'
        '<path d="M49 42v14M42 49h14" stroke="#fff" stroke-width="3.5" stroke-linecap="round"/>')
write("CreateProfile.svg", svg(section("20-6", 1, 1, box=50, origin=(27, 27)) + "\n" + plus))
print("icons written to", ICONS)
