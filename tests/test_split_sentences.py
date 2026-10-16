from pathlib import Path

import pytest

from speclint.models import Block, BlockKind
from speclint.segment import parse_blocks, split_sentences

FIXTURES = Path(__file__).parent / "fixtures"


def split(text: str) -> list[str]:
    block = Block(text=text, kind=BlockKind.PARAGRAPH, line=10)
    return [s.text for s in split_sentences(block)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Basic
        pytest.param("Open the file. Save it.", ["Open the file.", "Save it."], id="period"),
        pytest.param(
            "Is it done? Yes! Close it.", ["Is it done?", "Yes!", "Close it."], id="question and exclamation"
        ),
        pytest.param("Docker 24.0 or later", ["Docker 24.0 or later"], id="no end punctuation"),
        # A period that does not end a sentence
        pytest.param(
            "Set the value to 3.5 mm. Then close the valve.",
            ["Set the value to 3.5 mm.", "Then close the valve."],
            id="decimal",
        ),
        pytest.param(
            "Use a tool, e.g. a wrench. Then tighten the bolt.",
            ["Use a tool, e.g. a wrench.", "Then tighten the bolt."],
            id="e.g.",
        ),
        pytest.param(
            "See https://example.com/a.b for details. Then continue.",
            ["See https://example.com/a.b for details.", "Then continue."],
            id="url",
        ),
        pytest.param(
            "Use version 1.4.2. Then restart.", ["Use version 1.4.2.", "Then restart."], id="version at end"
        ),
        pytest.param(
            "Normal is 5–15 MB/s. If you see more, stop.",
            ["Normal is 5–15 MB/s.", "If you see more, stop."],
            id="unit with slash",
        ),
        pytest.param("Drive at 10 km/h. Then stop.", ["Drive at 10 km/h.", "Then stop."], id="km/h"),
        pytest.param(
            "Install the tools, etc. Then restart.",
            ["Install the tools, etc.", "Then restart."],
            id="etc. at end",
        ),
        # Inline code
        pytest.param(
            "Edit `config.yaml`. Then restart the server.",
            ["Edit `config.yaml`.", "Then restart the server."],
            id="code at end",
        ),
        pytest.param(
            "Run `npm run build. --prod` now. Then check the output.",
            ["Run `npm run build. --prod` now.", "Then check the output."],
            id="period in code",
        ),
        pytest.param("Type `a  b` now.", ["Type `a  b` now."], id="spaces in code"),
        # Other punctuation
        pytest.param(
            "Run the build. then check the output.",
            ["Run the build.", "then check the output."],
            id="lowercase start",
        ),
        pytest.param(
            'Click "Save." Then close the window.', ['Click "Save."', "Then close the window."], id="quote"
        ),
        pytest.param(
            "Docker: install version 24 or later.", ["Docker: install version 24 or later."], id="colon"
        ),
        pytest.param(
            "It takes 2 minutes;\nif it isn't, check the logs.",
            ["It takes 2 minutes; if it isn't, check the logs."],
            id="semicolon",
        ),
        pytest.param("See  here.", ["See here."], id="spaces collapsed"),
    ],
)
def test_split(text, expected):
    assert split(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "This guide explains the\nservice. It covers\nrollback.",
            [("This guide explains the service.", 10), ("It covers rollback.", 11)],
            id="line break in sentence",
        ),
        pytest.param(
            "Q: Can I deploy?\nNo. Ask the release team.",
            [("Q: Can I deploy?", 10), ("No.", 11), ("Ask the release team.", 11)],
            id="line break between sentences",
        ),
    ],
)
def test_lines(text, expected):
    block = Block(text=text, kind=BlockKind.PARAGRAPH, line=10)
    assert [(s.text, s.line) for s in split_sentences(block)] == expected


def test_sentence_keeps_block():
    block = Block(text="Open the file. Save it.", kind=BlockKind.LIST_ITEM, line=3, ordered=True)
    assert all(s.block is block for s in split_sentences(block))


def test_masked():
    block = Block(text="Edit `a.py`. Then run `x; y` now.", kind=BlockKind.PARAGRAPH, line=1)
    assert [(s.text, s.masked) for s in split_sentences(block)] == [
        ("Edit `a.py`.", "Edit codeph0x."),
        ("Then run `x; y` now.", "Then run codeph1x now."),
    ]


def test_fixture():
    blocks = parse_blocks((FIXTURES / "deployment-guide.md").read_text(encoding="utf-8"))
    result = [[(s.text, s.line) for s in split_sentences(blocks[i])] for i in (1, 26, 37)]
    assert result == [
        [
            ("This guide explains how to deploy the Orders service to the staging environment.", 8),
            ("It covers prerequisites, configuration, and rollback.", 9),
        ],
        [
            ("Apply the manifest.", 49),
            ("The rollout should be complete in about 2 minutes; if it isn't, check the pod logs.", 49),
        ],
        [
            ("Q: Can I deploy to production with this guide?", 78),
            ("No.", 79),
            ("Production deployments are handled by the release team.", 79),
        ],
    ]


def test_placeholder_word_in_text_without_code():
    """A word that looks like a placeholder, but is not one, stays as it is."""
    assert split("Set codeph9x in `a.py`.") == ["Set codeph9x in `a.py`."]
