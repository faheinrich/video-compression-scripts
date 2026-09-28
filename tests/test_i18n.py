import ast
import re
import string

import pytest

from conftest import REPO_ROOT
from video_helper_tools.core import i18n

GERMAN_CHARS = re.compile("[äöüÄÖÜß]")


def tr_literals():
    """Every string literal passed to tr() in the app code, with its location."""
    found = {}
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "video_helper_tools").rglob("*.py"))]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr":
                arg = node.args[0]
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), \
                    f"tr() needs a string literal: {path.name}:{node.lineno}"
                found.setdefault(arg.value, f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


def placeholders(text):
    return sorted(field for _, field, _, _ in string.Formatter().parse(text) if field is not None)


def test_every_ui_string_has_a_german_translation():
    missing = {key: loc for key, loc in tr_literals().items() if key not in i18n.GERMAN}
    assert missing == {}


def test_no_unused_translations():
    unused = set(i18n.GERMAN) - set(tr_literals())
    assert unused == set()


@pytest.mark.parametrize("key", sorted(i18n.GERMAN))
def test_translation_keeps_placeholders_and_ampersands(key):
    german = i18n.GERMAN[key]
    assert placeholders(german) == placeholders(key)
    # "&&" is Qt's escape for a literal "&"; a lone "&" would become a keyboard mnemonic.
    assert german.count("&&") == key.count("&&")


def test_source_strings_are_english():
    german_keys = [key for key in tr_literals() if GERMAN_CHARS.search(key)]
    assert german_keys == []


def visible_texts(root):
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QTabWidget, QWidget

    texts = []
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, (QLabel, QAbstractButton)):
            texts.append(widget.text())
        if isinstance(widget, QGroupBox):
            texts.append(widget.title())
        if isinstance(widget, QLineEdit):
            texts.append(widget.placeholderText())
        if isinstance(widget, QComboBox):
            texts.extend(widget.itemText(i) for i in range(widget.count()))
        if isinstance(widget, QTabWidget):
            texts.extend(widget.tabText(i) for i in range(widget.count()))
        texts.append(widget.toolTip())
        texts.append(widget.windowTitle())
    return [t for t in texts if t]


def build_every_page(qapp, language):
    import main

    window = main.VideoHelperToolsSuite()
    combo = window.landing_page.lang_combo
    combo.setCurrentIndex(combo.findData(language))
    qapp.processEvents()
    assert i18n.current_language() == language
    pages = [window.landing_page]
    for name in main.TOOLS:
        window.show_tool(name)
        pages.append(window.tools[name][0])
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
    import main

    window = main.VideoHelperToolsSuite()
    window.show_tool("compressor")
    combo = window.landing_page.lang_combo
    combo.setCurrentIndex(combo.findData("en"))
    qapp.processEvents()

    assert i18n.current_language() == "en"
    assert window.tools == {}  # tool pages are rebuilt lazily in the new language
    window.show_tool("compressor")
    assert window.compressor_tab.btn_run.text() == "Start archiving"
    window.close()

    i18n.set_language("de")
    reopened = main.VideoHelperToolsSuite()
    assert i18n.current_language() == "en"
    assert reopened.landing_page.lang_combo.currentData() == "en"
    reopened.close()


def test_legacy_language_index_is_honoured():
    import main

    assert main.saved_language({"global": {"language_index": 1}}) == "en"
    assert main.saved_language({"global": {"language_index": 3}}) == "de"  # French/Spanish no longer offered
    assert main.saved_language({}) == "de"
