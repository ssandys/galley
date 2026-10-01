"""Every QML Text item renders as plain text, never as markup.

A Text with no textFormat defaults to Text.AutoText, which renders anything
that looks like markup as styled text -- and styled text loads <img src=...>,
including from a remote URL. The panel shows strings Galley does not control:
job names (another user's, on a shared queue), printer info and location,
printer-state-message and marker-names from the device, and error text from
the collector. A job titled <img src="https://.../pixel"> made the viewer's
desktop fetch that URL on opening the panel (omarchy-plugin-marketplace#8264).

Galley never renders markup on purpose, so the rule is every Text, static
labels included: a guard that only covers "external" strings has to be kept in
sync by judgement, and the next new label is the one that gets missed.
"""
import os
import re
import unittest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))

TEXT_OPEN = re.compile(r"(?<![\w.])Text\s*\{")
PLAIN = re.compile(r"^\s*textFormat\s*:\s*Text\.PlainText\s*$", re.M)


def qml_sources():
    """Every top-level QML file, globbed so a new file is covered unasked."""
    names = sorted(n for n in os.listdir(ROOT) if n.endswith(".qml"))
    assert names, "no *.qml files found at the repo root -- the glob is broken"
    sources = []
    for name in names:
        with open(os.path.join(ROOT, name)) as f:
            sources.append((name, f.read()))
    return sources


def blank_strings_and_comments(source):
    """Same length as source, with string literals and comments spaced out.

    Lets brace matching ignore a "{" inside a string or comment without
    shifting any offsets, so line numbers still point at the real source.
    """
    out = list(source)
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if c in "\"'":
            j = i + 1
            while j < n and source[j] != c:
                j += 2 if source[j] == "\\" else 1
            for k in range(i + 1, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j + 1
        elif source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def text_items(source):
    """(line, direct body) for each Text item; nested blocks are removed."""
    clean = blank_strings_and_comments(source)
    items = []
    for match in TEXT_OPEN.finditer(clean):
        start = match.end()
        depth, i, body = 1, start, []
        while i < len(clean) and depth:
            c = clean[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif depth == 1:
                body.append(c)
            i += 1
        assert depth == 0, "unbalanced braces after line %d" % (
            clean.count("\n", 0, match.start()) + 1)
        items.append((clean.count("\n", 0, match.start()) + 1, "".join(body)))
    return items


class PlainTextTest(unittest.TestCase):

    def test_every_text_item_is_plain_text(self):
        total = 0
        missing = []
        for name, source in qml_sources():
            for line, body in text_items(source):
                total += 1
                if not PLAIN.search(body):
                    missing.append("%s:%d" % (name, line))
        # Fails loudly rather than passing vacuously if the scrape breaks.
        self.assertGreater(total, 0, "no Text items found -- the scrape is broken")
        self.assertEqual(missing, [],
                         "Text items without textFormat: Text.PlainText")

    def test_scrape_sees_direct_properties_only(self):
        # A nested item's textFormat must not satisfy its parent's check, and
        # a brace in a string must not end the item early.
        source = (
            'Text {\n'
            '  text: "{ not a block"\n'
            '  Item { textFormat: Text.PlainText }\n'
            '}\n'
        )
        [(line, body)] = text_items(source)
        self.assertEqual(line, 1)
        self.assertIsNone(PLAIN.search(body))

    def test_scrape_matches_delegate_text(self):
        [(line, _)] = text_items("ListView {\n  delegate: Text {\n  }\n}\n")
        self.assertEqual(line, 2)

    def test_scrape_ignores_enum_references(self):
        self.assertEqual(text_items("Item { elide: Text.ElideRight }"), [])


if __name__ == "__main__":
    unittest.main()
