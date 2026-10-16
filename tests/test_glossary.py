from importlib.resources import files

import pytest

from speclint.glossary import Glossary, find_project_glossary, load


def parse(text: str) -> Glossary:
    glossary = Glossary()
    glossary.add(text, "g.txt")
    return glossary


def test_entry():
    glossary = parse("commit | v | operation | version control")
    term = glossary.get("commit", "v")
    assert (term.term, term.pos, term.category, term.note) == ("commit", "v", "operation", "version control")
    assert term.source == "g.txt:1"
    assert glossary.problems == []


def test_blank_lines_and_comments_are_ignored():
    glossary = parse("# term | pos | category\n\n   \ncommit | v | operation\n")
    assert list(glossary.terms) == [("commit", "v")]
    assert glossary.get("commit", "v").source == "g.txt:4"
    assert glossary.problems == []


def test_multi_word_term_without_note():
    term = parse("dead-letter topic | n | component").get("dead-letter topic", "n")
    assert term.note == ""


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        pytest.param(
            "stale | adj | component",
            'g.txt:1: pos "adj" must be "n" (noun) or "v" (verb)',
            id="adjective",
        ),
        pytest.param(
            "retry | v", 'g.txt:1: write "term | pos | category | note" (the note is optional)', id="no category"
        ),
        pytest.param("retry | v | component", 'g.txt:1: category "component" needs pos "n"', id="noun category, verb"),
        pytest.param("retry | n | operation", 'g.txt:1: category "operation" needs pos "v"', id="verb category, noun"),
        pytest.param(
            "foo | n | thing",
            'g.txt:1: category "thing" must be one of name, component, concept, device, unit, document, role, operation',
            id="unknown category",
        ),
        pytest.param(
            "foo bar n component", 'g.txt:1: write "term | pos | category | note" (the note is optional)', id="no bars"
        ),
    ],
)
def test_line_with_a_problem_is_not_used(line, problem):
    glossary = parse(line)
    assert glossary.terms == {}
    assert glossary.problems == [problem]


def test_lookup_of_a_lowercase_term_ignores_case():
    glossary = parse("configuration | n | component")
    assert glossary.get("Configuration", "n").term == "configuration"
    assert glossary.get("CONFIGURATION", "n") is not None


def test_lookup_of_a_name_needs_the_same_case():
    glossary = parse("GitHub | n | component")
    assert glossary.get("GitHub", "n").term == "GitHub"
    assert glossary.get("github", "n") is None
    assert glossary.get("Github", "n") is None


def test_lookup_needs_the_same_part_of_speech():
    assert parse("commit | v | operation").get("commit", "n") is None


def test_general_and_project_glossaries(tmp_path):
    (tmp_path / ".speclint").mkdir()
    (tmp_path / ".speclint" / "glossary.txt").write_text("tidewatch | n | component | the project name\n")
    doc = tmp_path / "README.md"
    glossary = load(doc)
    assert glossary.get("tidewatch", "n").source == f"{tmp_path / '.speclint' / 'glossary.txt'}:1"
    assert glossary.get("commit", "v").source.startswith("software_glossary.txt:")


def test_project_glossary_in_a_parent_directory(tmp_path):
    (tmp_path / ".speclint").mkdir()
    (tmp_path / ".speclint" / "glossary.txt").write_text("")
    doc = tmp_path / "docs" / "sub" / "a.md"
    doc.parent.mkdir(parents=True)
    assert find_project_glossary(doc) == tmp_path / ".speclint" / "glossary.txt"


def test_no_project_glossary(tmp_path):
    doc = tmp_path / "docs" / "a.md"
    assert find_project_glossary(doc) is None
    glossary = load(doc)
    assert glossary.problems == []
    assert glossary.get("commit", "v") is not None  # the general glossary is still loaded


def test_project_glossary_that_cannot_be_read(tmp_path):
    (tmp_path / ".speclint").mkdir()
    (tmp_path / ".speclint" / "glossary.txt").write_bytes(b"\xff\xfe bad")
    glossary = load(tmp_path / "a.md")
    assert len(glossary.problems) == 1
    assert "cannot read" in glossary.problems[0]


def test_general_glossary_has_no_problems():
    glossary = load()
    assert glossary.problems == []
    assert len(glossary.terms) == 402


def test_general_glossary_has_no_duplicate_lines():
    # Loading keeps the first of two equal entries, so check the lines themselves.
    text = files("speclint").joinpath("data/software_glossary.txt").read_text(encoding="utf-8")
    keys = [
        tuple(part.strip().lower() for part in line.split("|")[:2])
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    assert duplicates == []


@pytest.mark.parametrize(
    ("term", "pos"),
    [("configuration", "n"), ("file", "n"), ("API", "n"), ("HTTP", "n"), ("GitHub", "n"), ("Python", "n"),
     ("commit", "v"), ("request", "n")],
)
def test_general_glossary_terms(term, pos):
    assert load().get(term, pos) is not None
