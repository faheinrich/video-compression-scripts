import re
from pathlib import Path

import pytest

from video_helper_core import i18n
from video_helper_core.testing import placeholders, tr_literals

CORE = Path(i18n.__file__).parent
GERMAN_CHARS = re.compile("[äöüÄÖÜß]")


def test_every_core_string_has_a_german_translation():
    assert {k for k in tr_literals(CORE) if k not in i18n.GERMAN} == set()


@pytest.mark.parametrize("key", sorted(i18n.GERMAN))
def test_translation_keeps_placeholders_and_ampersands(key):
    german = i18n.GERMAN[key]
    assert placeholders(german) == placeholders(key)
    assert german.count("&&") == key.count("&&")


def test_source_strings_are_english():
    assert [k for k in tr_literals(CORE) if GERMAN_CHARS.search(k)] == []


def test_apps_can_add_their_texts():
    i18n.register_german({"Hello {name}": "Hallo {name}"})
    try:
        i18n.set_language("de")
        assert i18n.tr("Hello {name}", name="x") == "Hallo x"
        i18n.set_language("en")
        assert i18n.tr("Hello {name}", name="x") == "Hello x"
    finally:
        del i18n.GERMAN["Hello {name}"]
