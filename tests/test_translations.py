"""Translatable strings (no FreeCAD needed)."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "update_translations", os.path.join(os.path.dirname(__file__), "..", "tools", "update_translations.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def test_template_is_up_to_date_and_strings_are_literal():
    # Fails when a string changed without running: python tools/update_translations.py
    assert tool.main(["--check"]) == 0


def test_contexts():
    messages, _problems = tool.extract()
    assert "App::Property" in messages and "ProfileBuilder" in messages
    assert "Sheet thickness" in messages["App::Property"]
    assert "Check frame..." in messages["ProfileBuilder_CheckFrame"]


def test_existing_translations_are_kept():
    messages = {"ProfileBuilder": {"Fix": ["check_ui.py"], "New": ["check_ui.py"]}}
    existing = {("ProfileBuilder", "Fix"): ("Repareren", ""), ("ProfileBuilder", "Gone"): ("Weg", "")}
    text = tool.render(messages, "nl", existing)
    assert "<translation>Repareren</translation>" in text
    assert '<translation type="unfinished"></translation>' in text  # "New"
    assert '<translation type="obsolete">Weg</translation>' in text


def test_a_string_that_comes_back_is_no_longer_obsolete(tmp_path):
    messages = {"ProfileBuilder": {"Back": ["check_ui.py"]}}
    text = tool.render(messages, "nl", {("ProfileBuilder", "Back"): ("Terug", "obsolete")})
    assert "<translation>Terug</translation>" in text


def test_an_empty_language_file_reads_as_new(tmp_path):
    empty = tmp_path / "ProfileBuilder_nl.ts"
    empty.write_text("", encoding="utf-8")
    assert tool._read(str(empty)) == {}
