"""Collect the translatable strings into Qt Linguist files. Pure Python: no Qt tools needed.

    python tools/update_translations.py           # update the template and every language file
    python tools/update_translations.py --check   # exit 1 if the template is out of date (used by the tests)
    python tools/update_translations.py --add de  # start a language file, e.g. ProfileBuilder_de.ts

The language suffix must be FreeCAD's own code for the language, or FreeCAD will not load the file:
for example de, fr, nl, it, pl, ja, es-ES, pt-BR, pt-PT, sv-SE, zh-CN or zh-TW.

Strings are found in calls to translate(context, text) and QT_TRANSLATE_NOOP(context, text) with
literal arguments, and property tooltips in addProperty(...) calls and the add(...) helpers that
wrap it (context "App::Property"; tooltips kept in tables are marked with QT_TRANSLATE_NOOP).
Command texts use the command name as the context, and everything else "ProfileBuilder".

Translators edit ProfileBuilder_<language>.ts with Qt Linguist, then compile it with
"lrelease ProfileBuilder_<language>.ts" (or pyside6-lrelease). FreeCAD loads the resulting .qm file
from resources/translations when it runs in that language. Enumeration values (Series, Mount,
PurchaseMode, ...) are stored in documents and compared in code, so they are never translated.
"""

import ast
import os
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PACKAGE = os.path.join(ROOT, "freecad", "profile_builder")
FOLDER = os.path.join(PACKAGE, "resources", "translations")
TEMPLATE = os.path.join(FOLDER, "ProfileBuilder.ts")
FUNCTIONS = ("translate", "QT_TRANSLATE_NOOP")


def _name(func):
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def _property_tooltip(node):
    """The literal tooltip of addProperty(type, name, group, tooltip, ...) or of a local add() helper.

    FreeCAD's property editor translates tooltips itself, with the context
    "App::Property", so they need no marking in the code.
    """
    if _name(node.func) not in ("add", "addProperty") or len(node.args) < 4:
        return None
    kind, tip = node.args[0], node.args[3]
    if isinstance(kind, ast.Constant) and str(kind.value).startswith("App::Property"):
        if isinstance(tip, ast.Constant) and isinstance(tip.value, str):
            return tip.value
        if isinstance(tip, (ast.JoinedStr, ast.BinOp)):
            return NOT_LITERAL
    return None


NOT_LITERAL = object()  # a tooltip built at run time, which no translation can match


def extract(package=PACKAGE):
    """({context: {source: [file names]}}, problems) for all modules of the package."""
    messages, problems = {}, []
    for file in sorted(f for f in os.listdir(package) if f.endswith(".py")):
        with open(os.path.join(package, file), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple) and len(node.elts) >= 4:
                # A property table row: (name, "App::Property...", group, tooltip, ...)
                kind, tip = node.elts[1], node.elts[3]
                if isinstance(kind, ast.Constant) and str(kind.value).startswith("App::Property") \
                        and isinstance(tip, ast.Constant) and isinstance(tip.value, str):
                    files = messages.setdefault("App::Property", {}).setdefault(tip.value, [])
                    if file not in files:
                        files.append(file)
                continue
            if not isinstance(node, ast.Call):
                continue
            tip = _property_tooltip(node)
            if tip is NOT_LITERAL:
                problems.append(f"{file}:{node.lineno}: property tooltip built at run time; write it as one literal")
                continue
            if tip is not None:
                files = messages.setdefault("App::Property", {}).setdefault(tip, [])
                if file not in files:
                    files.append(file)
                continue
            if not (_name(node.func) in FUNCTIONS and len(node.args) >= 2):
                continue
            context, text = node.args[:2]
            if isinstance(text, ast.JoinedStr):
                # An f-string is different every time, so no translation can ever match it.
                problems.append(f"{file}:{node.lineno}: f-string passed to {_name(node.func)}; "
                                "translate a template and fill it in with .format()")
            if not (isinstance(context, ast.Constant) and isinstance(text, ast.Constant)):
                continue  # a runtime lookup of a string collected elsewhere, e.g. a property tooltip
            files = messages.setdefault(context.value, {}).setdefault(text.value, [])
            if file not in files:
                files.append(file)
    return messages, problems


def _read(path):
    """{(context, source): (translation, type)} from an existing .ts file."""
    found = {}
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return found
    for ctx in ET.parse(path).getroot().iter("context"):
        name = ctx.findtext("name")
        for msg in ctx.iter("message"):
            tr = msg.find("translation")
            found[(name, msg.findtext("source"))] = (tr.text or "", tr.get("type", ""))
    return found


def render(messages, language=None, existing=None):
    """A .ts file; with ``existing`` translations kept and strings that are gone marked obsolete."""
    existing = existing or {}
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE TS>",
             f'<TS version="2.1"{f" language={chr(34)}{language}{chr(34)}" if language else ""}>']
    contexts = {c: dict(m) for c, m in messages.items()}
    for (ctx, source), _value in existing.items():
        contexts.setdefault(ctx, {})
    for ctx in sorted(contexts):
        lines += ["<context>", f"    <name>{escape(ctx)}</name>"]
        sources = dict(contexts[ctx])
        gone = sorted(s for (c, s) in existing if c == ctx and s not in sources)
        for source in sorted(sources) + gone:
            lines.append("    <message>")
            for file in sources.get(source, []):
                lines.append(f'        <location filename="../../{file}"/>')
            lines.append(f"        <source>{escape(source)}</source>")
            text, kind = existing.get((ctx, source), ("", "unfinished"))
            if source in gone:
                kind = "obsolete"
            elif not text:
                kind = "unfinished"
            elif kind in ("obsolete", "vanished"):
                kind = ""  # back in the code: the old translation counts again
            attr = f' type="{kind}"' if kind else ""
            lines.append(f"        <translation{attr}>{escape(text)}</translation>")
            lines.append("    </message>")
        lines.append("</context>")
    lines.append("</TS>")
    return "\n".join(lines) + "\n"


def main(argv):
    messages, problems = extract()
    for p in problems:
        print("problem: " + p)
    template = render(messages)
    if "--check" in argv:
        with open(TEMPLATE, encoding="utf-8") as f:
            current = f.read() if os.path.exists(TEMPLATE) else ""
        stale = current != template
        if stale:
            print("The translation template is out of date: run python tools/update_translations.py")
        return 1 if stale or problems else 0
    os.makedirs(FOLDER, exist_ok=True)
    with open(TEMPLATE, "w", encoding="utf-8", newline="\n") as f:
        f.write(template)
    languages = [f[len("ProfileBuilder_"):-3] for f in os.listdir(FOLDER)
                 if f.startswith("ProfileBuilder_") and f.endswith(".ts")]
    if "--add" in argv:
        languages.append(argv[argv.index("--add") + 1])
    for lang in sorted(set(languages)):
        path = os.path.join(FOLDER, f"ProfileBuilder_{lang}.ts")
        text = render(messages, lang, _read(path))  # read the translations before overwriting the file
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    count = sum(len(m) for m in messages.values())
    print(f"{count} strings in {len(messages)} contexts; languages: {', '.join(sorted(set(languages))) or 'none yet'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
