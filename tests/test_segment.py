from pathlib import Path

import pytest

from speclint.models import Block, BlockKind, Finding, Severity
from speclint.segment import find_unclosed_fences, parse_blocks

H, P, LI, TC = BlockKind.HEADING, BlockKind.PARAGRAPH, BlockKind.LIST_ITEM, BlockKind.TABLE_CELL


def texts(source: str) -> list[str]:
    return [b.text for b in parse_blocks(source)]


def test_example_document():
    source = (
        "# Setup\n"
        "\n"
        "Open the `config.yaml` file.\n"
        "\n"
        "- Set the port.\n"
        "- Save the file.\n"
        "\n"
        "```\n"
        "port: 8080\n"
        "```\n"
    )
    assert parse_blocks(source) == [
        Block(text="Setup", kind=H, line=1),
        Block(text="Open the `config.yaml` file.", kind=P, line=3),
        Block(text="Set the port.", kind=LI, line=5),
        Block(text="Save the file.", kind=LI, line=6),
    ]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("```\nRead the file.\n```\n", id="fenced code"),
        pytest.param("    Read the file.\n", id="indented code"),
        pytest.param("<div>\nRead the file.\n</div>\n", id="html block"),
        pytest.param("---\ntitle: Read the file.\n---\n", id="front matter"),
        pytest.param("#\n", id="empty heading"),
    ],
)
def test_skips_non_prose(source):
    assert parse_blocks(source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("Use **bold** and _italic_.", "Use bold and italic.", id="emphasis"),
        pytest.param("Read [the guide](http://a.b).", "Read the guide.", id="link"),
        pytest.param("See ![the chart](c.png) here.", "See the chart here.", id="image"),
        pytest.param("See ![](c.png) here.", "See  here.", id="image without alt text"),
        pytest.param("A <b>bold</b> word.", "A bold word.", id="inline html"),
        pytest.param("Use \\*stars\\* &amp; dots.", "Use *stars* & dots.", id="escapes"),
        pytest.param("Edit `a.py` now.", "Edit `a.py` now.", id="inline code"),
        pytest.param("Type ``a`b`` now.", "Type ``a`b`` now.", id="code with backtick"),
        pytest.param("Type `` `x` `` now.", "Type `` `x` `` now.", id="code starts with backtick"),
        pytest.param("First line\nsecond line.", "First line\nsecond line.", id="softbreak"),
    ],
)
def test_render(source, expected):
    assert texts(source) == [expected]


def test_list_kinds():
    source = "1. Open the file.\n   - A note.\n2. Save it.\n"
    blocks = parse_blocks(source)
    assert [(b.text, b.kind, b.ordered) for b in blocks] == [
        ("Open the file.", LI, True),
        ("A note.", LI, False),  # the nearest list is a bullet list
        ("Save it.", LI, True),
    ]


def test_table_cells():
    source = "| Name | Value |\n|---|---|\n| port | `8080` |\n"
    blocks = parse_blocks(source)
    assert [(b.text, b.kind, b.line) for b in blocks] == [
        ("Name", TC, 1),
        ("Value", TC, 1),
        ("port", TC, 3),
        ("`8080`", TC, 3),
    ]


def test_blockquote_without_alert():
    blocks = parse_blocks("> Read the file.\n")
    assert blocks == [Block(text="Read the file.", kind=P, line=1)]


def test_alert_marker_is_removed():
    source = "Intro.\n\n> [!WARNING]\n> Do not touch the cable.\n>\n> It is hot.\n"
    blocks = parse_blocks(source)
    assert blocks == [
        Block(text="Intro.", kind=P, line=1),
        Block(text="Do not touch the cable.", kind=P, line=4, alert="warning"),
        Block(text="It is hot.", kind=P, line=6, alert="warning"),
    ]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("> [!NOTE] Text on the same line.\n", id="marker not alone"),
        pytest.param("> [!note]\n> Lowercase marker.\n", id="lowercase"),
        pytest.param("> [!INFO]\n> Unknown type.\n", id="unknown type"),
    ],
)
def test_not_an_alert(source):
    assert [b.alert for b in parse_blocks(source)] == [None]


def test_alert_marker_only():
    assert parse_blocks("> [!TIP]\n") == []


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("Text.\n\n```\ncode\n```\n\nAfter.\n", id="closed"),
        pytest.param("```\nnpm install\n```\n", id="one line of code"),
        pytest.param("```\n```\n", id="empty block"),
    ],
)
def test_closed_fence(source):
    assert find_unclosed_fences(source) == []


@pytest.mark.parametrize(
    ("source", "line"),
    [
        pytest.param("Text.\n\n```\ncode\n\nAfter one.\n\nAfter two.\n", 3, id="mid document"),
        pytest.param("~~~\ncode\n\nAfter.\n", 1, id="tilde"),
        pytest.param("````\ncode\n```\n\nAfter.\n", 1, id="shorter closing marker"),
        pytest.param("1. Step:\n\n   ```\n   code\n\n2. Next step.\n", 3, id="in list item"),
        pytest.param("> ```\n> code\n\nAfter.\n", 1, id="in blockquote"),
        pytest.param("Text.\n\n```", 3, id="last line is opening"),
        pytest.param("```\na\n```\n\n```\nb\n", 5, id="second of two"),
    ],
)
def test_unclosed_fence(source, line):
    assert find_unclosed_fences(source) == [
        Finding(
            rule="unclosed-code-fence",
            severity=Severity.ERROR,
            message="Code fence is not closed. The text after it is not checked.",
            line=line,
            excerpt=source.splitlines()[line - 1].strip(),
        )
    ]


def test_fixture_has_no_unclosed_fence():
    source = (FIXTURES / "deployment-guide.md").read_text(encoding="utf-8")
    assert find_unclosed_fences(source) == []
