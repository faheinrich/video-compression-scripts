import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT
from video_helper_core import i18n
from video_helper_core.testing import placeholders, tr_literals, visible_texts

import analysis_helper
from analysis_helper import app

GERMAN_CHARS = re.compile("[äöüÄÖÜß]")
CODE = [REPO_ROOT / "analysis_helper", Path(i18n.__file__).parent]


def test_every_ui_string_has_a_german_translation():
    missing = {key: loc for key, loc in tr_literals(*CODE).items() if key not in i18n.GERMAN}
    assert missing == {}


def test_no_unused_translations():
    unused = set(i18n.GERMAN) - set(tr_literals(*CODE))
    assert unused == set()


@pytest.mark.parametrize("key", sorted(i18n.GERMAN))
def test_translation_keeps_placeholders_and_ampersands(key):
    german = i18n.GERMAN[key]
    assert placeholders(german) == placeholders(key)
    # "&&" is Qt's escape for a literal "&"; a lone "&" would become a keyboard mnemonic.
    assert german.count("&&") == key.count("&&")


def test_source_strings_are_english():
    german_keys = [key for key in tr_literals(*CODE) if GERMAN_CHARS.search(key)]
    assert german_keys == []


def build_every_page(qapp, language):
    window = app.AnalysisHelperWindow()
    combo = window.landing_page.lang_combo
    combo.setCurrentIndex(combo.findData(language))
    qapp.processEvents()
    assert i18n.current_language() == language
    pages = [window.landing_page]
    for tool in app.SPEC.tools:
        window.show_tool(tool.key)
        pages.append(window.tools[tool.key])
    qapp.processEvents()
    return window, pages


def test_english_ui_contains_no_german(qapp):
    window, pages = build_every_page(qapp, "en")
    german = sorted({t for page in pages for t in visible_texts(page) if GERMAN_CHARS.search(t)})
    window.close()
    assert german == []


def test_german_ui_shows_no_untranslated_source_strings(qapp):
    window, pages = build_every_page(qapp, "de")
    untranslated = {key for key, german in i18n.GERMAN.items() if german != key}
    leftovers = sorted({t for page in pages for t in visible_texts(page) if t in untranslated})
    window.close()
    assert leftovers == []


def test_language_switch_rebuilds_pages_and_is_remembered(qapp):
    window = app.AnalysisHelperWindow()
    window.show_tool("sync")
    combo = window.landing_page.lang_combo
    combo.setCurrentIndex(combo.findData("en"))
    qapp.processEvents()

    assert i18n.current_language() == "en"
    assert window.tools == {}  # tool pages are rebuilt lazily in the new language
    window.show_tool("sync")
    assert window.tools["sync"] is not None
    window.close()

    i18n.set_language("de")
    reopened = app.AnalysisHelperWindow()
    assert i18n.current_language() == "en"
    assert reopened.landing_page.lang_combo.currentData() == "en"
    reopened.close()


def test_legacy_language_index_is_honoured():
    assert app.saved_language({"global": {"language_index": 1}}) == "en"
    assert app.saved_language({"global": {"language_index": 3}}) == "de"  # French/Spanish no longer offered
    assert app.saved_language({}) == "de"
