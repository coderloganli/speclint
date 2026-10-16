from pathlib import Path

from speclint.cli import main
from speclint.engine import check_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_findings_sorted_by_line():
    source = (
        "Examine the parts; replace them.\n"
        "\n"
        "Use a tool, e.g. a wrench.\n"
        "\n"
        "```\n"
        "code\n"
    )
    assert [(f.line, f.rule) for f in check_text(source)] == [(1, "semicolon"), (3, "latin-abbreviation"), (5, "unclosed-code-fence")]


def test_fixture():
    source = (FIXTURES / "deployment-guide.md").read_text(encoding="utf-8")
    assert [(f.line, f.rule) for f in check_text(source)] == [
        (21, "passive-voice"),
        (31, "latin-abbreviation"),
        (49, "semicolon"),
        (49, "contraction"),
        (66, "passive-voice"),
        (72, "passive-voice"),
        (79, "passive-voice"),
    ]


def test_cli_findings(capsys):
    path = FIXTURES / "deployment-guide.md"
    assert main(["check", str(path)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f'{path}:21: [passive-voice] error: Use the active voice: "is not required".',
        f'{path}:31: [latin-abbreviation] error: Do not use "e.g.". Write "for example".',
        f"{path}:49: [semicolon] error: Do not use a semicolon. Write two sentences.",
        f"{path}:49: [contraction] error: Do not use the contraction \"isn't\". Write the full words.",
        f'{path}:66: [passive-voice] error: Use the active voice: "is restored".',
        f'{path}:72: [passive-voice] error: Use the active voice: "are rarely needed".',
        f'{path}:79: [passive-voice] error: Use the active voice: "are handled".',
    ]


def test_cli_clean(tmp_path, capsys):
    path = tmp_path / "clean.md"
    path.write_text("Open the file.\n", encoding="utf-8")
    assert main(["check", str(path)]) == 0
    assert capsys.readouterr().out == ""


def test_paragraphs_are_counted_separately():
    paragraph = " ".join(f"Do step {i}." for i in range(1, 5))
    assert check_text(f"{paragraph}\n\n{paragraph}\n") == []


def test_block_and_sentence_findings_sorted_by_line():
    steps = " ".join(f"Do step {i}." for i in range(1, 7))
    source = f"Intro.\n\n{steps} Do step 7; do step 8.\n"
    assert [(f.line, f.rule) for f in check_text(source)] == [(3, "paragraph-length"), (3, "semicolon")]


def test_grammar_and_sentence_findings_sorted_by_line():
    source = "The pump was installed.\n\nDo A; do B.\n"
    assert [(f.line, f.rule) for f in check_text(source)] == [(1, "passive-voice"), (3, "semicolon")]
