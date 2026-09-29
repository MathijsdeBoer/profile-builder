# Addon Manager readiness: licence, metadata, CI and translations

| | |
|---|---|
| Status | Planned |
| Category | FreeCAD integration & UX |
| Effort | M (first estimate M) |
| Value | high |
| Proposed from | freecad-ux |

## Problem

package.xml declares LGPL-3.0-or-later, but the repo has no LICENSE file (checked). package.xml has no repository, bugtracker or readme URLs, which the Addon Manager and a FreeCAD-addons submission expect. It claims freecadmin 0.21, but development and testing happen only on 1.1, and edge behaviour after a sketch line is deleted depends on 1.0 toponaming. The version is in both __init__.py and package.xml. Every string is hard-coded English, while FreeCAD itself is translated into many languages and many users run it in their own language.

## Proposal

Metadata and CI:
- Add the LGPL-3.0 LICENSE and a CHANGELOG.
- Fill in the package.xml url, pythonmin and dependency fields, and take the version from a single source.
- Add a GitHub Actions workflow that runs uvx pytest plus freecadcmd tests/freecad_smoke.py, using a FreeCAD AppImage or conda build.
- Either test on 0.21 or bump freecadmin to 1.0.

Translation scaffolding:
- Wrap command MenuText/ToolTip and the panel labels in translate().
- Mark property tooltips with QT_TRANSLATE_NOOP('App::Property', ...).
- Call Gui.addLanguagePath and add an lupdate script.
- Ship the languages that contributors can translate and review; the .ts files let others add more.

## What exists today

Partly exists: package.xml has name, description, version, maintainer, licence LGPL-3.0-or-later, icon, freecadmin 0.21.0, tags and the workbench subdirectory. The GitHub remote is github.com/MathijsdeBoer/profile-builder. Missing, all confirmed: a LICENSE/COPYING file, <url> entries, pythonmin, a CHANGELOG, CI and any translate() calls. The version is duplicated in package.xml and __init__.__version__.

## Implementation approach

Effort M confirmed: licence and metadata take about an hour, CI half a day to a day, translation scaffolding one to two days, and the actual translations more.

Value per part: the licence files and URLs are high value for very little effort, because the Addon Manager is how most FreeCAD users find and install workbenches; CI is medium; translations help the many users who don't work in English, but pay off best once the UI strings stop changing.

Implementation:
- Add COPYING (GPL-3.0 text) and COPYING.LESSER (LGPL-3.0 text). LGPLv3 is written as additional permissions on top of GPLv3, so both texts are meant to ship.
- package.xml: <url type="repository" branch="main">, plus bugtracker and readme URLs, and pythonmin 3.8.
- A pure-pytest test that checks package.xml <version> equals __version__.
- .github/workflows/test.yml:
  - a job running uvx pytest;
  - a job that downloads the FreeCAD 1.1 AppImage (cached), runs --appimage-extract, then squashfs-root/usr/bin/freecadcmd tests/freecad_smoke.py from the repo root.
- freecad_smoke.py only prints 'N failure(s)' and never exits non-zero. Either grep for '^0 failure' or end the script with os._exit(1 if failures else 0).
- Decide freecadmin: run the smoke test once on 0.21 (conda) or bump it to 1.0.
- Translations:
  - App.Qt.translate in GetResources and the panel labels;
  - QT_TRANSLATE_NOOP('App::Property', ...) for property tooltips;
  - Gui.addLanguagePath(resources/translations) in init_gui;
  - a pylupdate script.
- Never translate enumeration values. Series, Weight, ThroughRule, PurchaseMode, Mount, Side, JointRole and Type are stored in documents and compared as strings in code, e.g. report.mode == 'Cut to size', obj.Mount == 'In slot', joint.Type == 'Miter'.

## Blockers and caveats

- Translations need translators, so each language depends on contributors.
- CI downloads FreeCAD, a few hundred MB, per run unless cached, and the smoke test takes about 75 s.
- 0.21 compatibility has never been tested, so the freecadmin claim is unverified.

## Risks

- Enumeration values must never be translated: Series keys, ThroughRule and Weight are stored in saved documents and must stay English.
- Running freecadcmd in CI takes about 75 s plus the FreeCAD download.

## Prior art

The FreeCAD package.xml metadata spec, and the translation setup used by most workbenches in the Addon Manager.

## Modules

- `package.xml`
- `LICENSE (new)`
- `CHANGELOG (new)`
- `__init__.py`
- `init_gui.py`
- `commands.py`
- `taskpanel.py`
- `simple_panel.py`
- `pricing_ui.py`
- `.github/workflows (new)`
