"""Package metadata that the Addon Manager reads (no FreeCAD needed)."""

import os
import re
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(__file__), "..")
NS = {"p": "https://wiki.freecad.org/Package_Metadata"}


def _package():
    return ET.parse(os.path.join(ROOT, "package.xml")).getroot()


def test_version_is_the_same_in_both_places():
    with open(os.path.join(ROOT, "freecad", "profile_builder", "__init__.py"), encoding="utf-8") as f:
        version = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
    assert _package().find("p:version", NS).text == version


def test_files_named_in_the_metadata_exist():
    pkg = _package()
    paths = [e.text for e in pkg.iter("{%s}icon" % NS["p"])]
    paths.append(pkg.find("p:license", NS).get("file"))
    assert paths and all(os.path.exists(os.path.join(ROOT, p)) for p in paths), paths
    assert os.path.exists(os.path.join(ROOT, "COPYING")), "LGPL-3.0 builds on the GPL-3.0 text"


def test_changelog_has_the_current_version():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        text = f.read()
    version = _package().find("p:version", NS).text
    date = _package().find("p:date", NS).text
    assert f"## {version} ({date})" in text
