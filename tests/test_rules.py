import re

import pytest

from speclint import vocabulary, wordlist
from speclint.engine import check_text
from speclint.grammar import parse
from speclint.models import Block, BlockKind, Sentence
from speclint.rules import (
    british_spelling,
    contraction,
    gender_pronoun,
    latin_abbreviation,
    omitted_that,
    paragraph_length,
    passive_voice,
    semicolon,
    sentence_length,
    singulars,
    unknown_words,
    unknown_words_help,
    verb_tense,
)
from speclint.segment import split_sentences


def sentence(text: str) -> Sentence:
    """Return the only sentence in text, masked like the engine does it."""
    [s] = split_sentences(Block(text=text, kind=BlockKind.PARAGRAPH, line=1))
    return s


@pytest.mark.parametrize(
    ("text", "count"),
    [
        pytest.param("Examine the parts; replace the damaged ones.", 1, id="semicolon"),
        pytest.param("Examine the parts.", 0, id="no semicolon"),
        pytest.param("Set `a; b` in the file.", 0, id="semicolon in code"),
        pytest.param("Do A; do B; do C.", 1, id="one finding for each sentence"),
    ],
)
def test_semicolon(text, count):
    findings = semicolon(sentence(text))
    assert len(findings) == count
    assert all(f.rule == "semicolon" and f.excerpt == text for f in findings)


@pytest.mark.parametrize(
    ("text", "messages"),
    [
        pytest.param(
            "Use a tool, e.g. a wrench.", ['Do not use "e.g.". Write "for example".'], id="e.g."
        ),
        pytest.param(
            "Use the CLI, i.e. the speclint command.", ['Do not use "i.e.". Write "that is".'], id="i.e."
        ),
        pytest.param("Install the tools, etc.", ['Do not use "etc.". Write "and so on".'], id="etc."),
        pytest.param("E.g. use a wrench.", ['Do not use "E.g.". Write "for example".'], id="uppercase"),
        pytest.param(
            "Use tools, e.g. a wrench, a drill, etc.",
            ['Do not use "e.g.". Write "for example".', 'Do not use "etc.". Write "and so on".'],
            id="two in one sentence",
        ),
        pytest.param("Run `ls etc.` now.", [], id="in code"),
        pytest.param("Fetch the data from ETCD.", [], id="part of a word: etc"),
        pytest.param("Ask the devs.", [], id="part of a word: end with vs."),
        pytest.param("Enable vsync.", [], id="part of a word: start with vs"),
        pytest.param("Compare REST vs gRPC.", ['Do not use "vs". Write "versus".'], id="vs without period"),
    ],
)
def test_latin_abbreviation(text, messages):
    findings = latin_abbreviation(sentence(text))
    assert [f.message for f in findings] == messages
    assert all(f.rule == "latin-abbreviation" for f in findings)


def words(n: int) -> str:
    """A sentence of n plain words."""
    return " ".join(["word"] * n) + "."


def length_findings(text: str, kind=BlockKind.PARAGRAPH, ordered=False, alert=None):
    block = Block(text=text, kind=kind, line=1, ordered=ordered, alert=alert)
    return [(f.rule, f.message) for s in split_sentences(block) for f in sentence_length(s)]


def message(n: int, limit: int) -> str:
    text_type = "A procedure step" if limit == 20 else "Descriptive text"
    return (
        f"This sentence has {n} words. {text_type} can have a maximum of {limit} words. "
        "Write shorter sentences."
    )


@pytest.mark.parametrize(
    ("n", "block", "expected"),
    [
        pytest.param(20, dict(kind=BlockKind.LIST_ITEM, ordered=True), [], id="ordered list, 20"),
        pytest.param(
            21, dict(kind=BlockKind.LIST_ITEM, ordered=True), [("sentence-length", message(21, 20))], id="ordered list, 21"
        ),
        pytest.param(25, dict(), [], id="paragraph, 25"),
        pytest.param(26, dict(), [("sentence-length", message(26, 25))], id="paragraph, 26"),
        pytest.param(22, dict(kind=BlockKind.LIST_ITEM), [], id="bullet list, 22"),
        pytest.param(21, dict(alert="warning"), [("sentence-length", message(21, 20))], id="warning, 21"),
        pytest.param(22, dict(alert="note"), [], id="note, 22"),
        pytest.param(
            22, dict(kind=BlockKind.LIST_ITEM, ordered=True, alert="note"), [], id="note in ordered list, 22"
        ),
        pytest.param(26, dict(kind=BlockKind.TABLE_CELL), [("sentence-length", message(26, 25))], id="table cell, 26"),
        pytest.param(30, dict(kind=BlockKind.HEADING), [], id="heading, 30"),
    ],
)
def test_sentence_length(n, block, expected):
    assert length_findings(words(n), **block) == expected


def test_sentence_length_uses_ste_word_count():
    text = (
        "Set the timeout value (in seconds for each request to the API) in `config.yaml` "
        "to 30 s and then restart the server now."
    )
    assert len(text.split()) == 23
    assert length_findings(text, kind=BlockKind.LIST_ITEM, ordered=True) == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        pytest.param("Don't touch the cable.", ["Don't"], id="don't"),
        pytest.param("It isn't ready, and you can't start it.", ["isn't", "can't"], id="two in one sentence"),
        pytest.param("It's ready.", ["It's"], id="it's"),
        pytest.param("Apple's Python is old.", [], id="possessive"),
        pytest.param("Don’t touch it.", ["Don’t"], id="curly apostrophe"),
        pytest.param('Run `echo "don\'t"` now.', [], id="in code"),
        pytest.param("Check the users' settings.", [], id="plural possessive"),
    ],
)
def test_contraction(text, found):
    findings = contraction(sentence(text))
    assert [f.message for f in findings] == [
        f'Do not use the contraction "{c}". Write the full words.' for c in found
    ]
    assert all(f.rule == "contraction" for f in findings)


def test_contraction_endings():
    block = Block(
        text="They're ready. We've checked. You'll see it. I'm sure.", kind=BlockKind.PARAGRAPH, line=1
    )
    found = [f.message.split('"')[1] for s in split_sentences(block) for f in contraction(s)]
    assert found == ["They're", "We've", "You'll", "I'm"]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        pytest.param("When the user logs in, he sees the dashboard.", ["he"], id="he"),
        pytest.param("She must give him her key.", ["She", "him", "her"], id="three"),
        pytest.param("Here is the other shell.", [], id="part of a word"),
        pytest.param("Open the man page.", [], id="man is not checked"),
        pytest.param("Set `his_id` in the file.", [], id="in code"),
    ],
)
def test_gender_pronoun(text, found):
    findings = gender_pronoun(sentence(text))
    assert [f.message for f in findings] == [
        f'Do not use the gender-specific pronoun "{p}". Use a neutral noun (for example, "the user") or "they".'
        for p in found
    ]
    assert all(f.rule == "gendered-pronoun" for f in findings)


def paragraph_findings(n: int, kind=BlockKind.PARAGRAPH):
    """Findings for a block of n short sentences."""
    block = Block(text=" ".join(f"Do step {i}." for i in range(1, n + 1)), kind=kind, line=5)
    return [(f.rule, f.line, f.excerpt, f.message) for f in paragraph_length(block, split_sentences(block))]


@pytest.mark.parametrize(
    ("n", "kind", "expected"),
    [
        pytest.param(6, BlockKind.PARAGRAPH, [], id="paragraph, 6"),
        pytest.param(
            7,
            BlockKind.PARAGRAPH,
            [
                (
                    "paragraph-length",
                    5,
                    "Do step 1.",
                    "This paragraph has 7 sentences. A paragraph can have a maximum of 6 sentences. "
                    "Divide it into shorter paragraphs.",
                )
            ],
            id="paragraph, 7",
        ),
        pytest.param(7, BlockKind.LIST_ITEM, [], id="list item, 7"),
        pytest.param(7, BlockKind.TABLE_CELL, [], id="table cell, 7"),
    ],
)
def test_paragraph_length(n, kind, expected):
    assert paragraph_findings(n, kind) == expected


def spelling_messages(text: str) -> list[str]:
    block = Block(text=text, kind=BlockKind.PARAGRAPH, line=1)
    return [f.message for s in split_sentences(block) for f in british_spelling(s)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "Check the behaviour.",
            ['Use American spelling: write "behavior", not "behaviour".'],
            id="behaviour",
        ),
        pytest.param(
            "Behaviours change.",
            ['Use American spelling: write "Behaviors", not "Behaviours".'],
            id="capital and plural",
        ),
        pytest.param(
            "Organise the files and check the organisation.",
            [
                'Use American spelling: write "Organize", not "Organise".',
                'Use American spelling: write "organization", not "organisation".',
            ],
            id="two in one sentence",
        ),
        pytest.param(
            "The data is modelled.", ['Use American spelling: write "modeled", not "modelled".'], id="modelled"
        ),
        pytest.param("Use a grey icon.", ['Use American spelling: write "gray", not "grey".'], id="grey"),
        pytest.param("Set `colour` in the file.", [], id="in code"),
        pytest.param("Check the color and organize the program.", [], id="American"),
        pytest.param("Organize it.", [], id="Oxford spelling is also American"),
        pytest.param(
            "Use a matt finish.",
            ['Use American spelling: write "mat" or "matte", not "matt".'],
            id="two American spellings",
        ),
    ],
)
def test_british_spelling(text, expected):
    assert spelling_messages(text) == expected


def passive_messages(text: str) -> list[str]:
    [s] = split_sentences(Block(text=text, kind=BlockKind.PARAGRAPH, line=1))
    [parsed] = parse([s.masked])
    return [f.message for f in passive_voice(s, parsed)]


@pytest.mark.parametrize(
    ("text", "phrases"),
    [
        pytest.param("The pump was installed by the team.", ["was installed"], id="passive with agent"),
        pytest.param("The team installed the pump.", [], id="active"),
        pytest.param(
            "Restart the server after the config has been changed.", ["has been changed"], id="perfect passive"
        ),
        pytest.param("The volume control must be adjusted.", ["must be adjusted"], id="modal passive"),
        pytest.param(
            "The files are copied and the logs are deleted.", ["are copied", "are deleted"], id="two passives"
        ),
        pytest.param("The file is open.", [], id="adjective after is"),
        pytest.param("The `config.yaml` file is read at startup.", ["is read"], id="inline code"),
    ],
)
def test_passive_voice(text, phrases):
    assert passive_messages(text) == [f'Use the active voice: "{p}".' for p in phrases]


def tense_findings(text: str) -> list[tuple[str, str]]:
    """(rule, message) of all grammar rules, so that a test can see duplicates."""
    [s] = split_sentences(Block(text=text, kind=BlockKind.PARAGRAPH, line=1))
    [parsed] = parse([s.masked])
    return [(f.rule, f.message) for f in passive_voice(s, parsed) + verb_tense(s, parsed)]


def perfect(phrase: str) -> tuple[str, str]:
    return ("perfect-tense", f'Do not use the perfect tense: "{phrase}". Use the simple past or simple present.')


def progressive(phrase: str) -> tuple[str, str]:
    return ("progressive-tense", f'Do not use the progressive tense: "{phrase}". Use the simple present or simple past.')


def passive(phrase: str) -> tuple[str, str]:
    return ("passive-voice", f'Use the active voice: "{phrase}".')


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("The operator has adjusted the linkage.", [perfect("has adjusted")], id="present perfect"),
        pytest.param("The team had finished the test.", [perfect("had finished")], id="past perfect"),
        pytest.param("The config has been changed.", [passive("has been changed")], id="perfect passive: passive-voice only"),
        pytest.param("The server is running.", [progressive("is running")], id="present progressive"),
        pytest.param("The pump was operating at full speed.", [progressive("was operating")], id="past progressive"),
        pytest.param("The file is being copied.", [passive("is being copied")], id="progressive passive: passive-voice only"),
        pytest.param(
            "The team has been testing the build.", [progressive("has been testing")], id="perfect progressive"
        ),
        pytest.param("The system will start the pump.", [], id="simple future"),
        pytest.param("The adjusted linkage is correct.", [], id="past participle as adjective"),
        pytest.param("Running the test takes 2 minutes.", [], id="-ing as subject"),
        pytest.param("The build is going to fail.", [progressive("is going")], id="going to"),
    ],
)
def test_verb_tense(text, expected):
    assert tense_findings(text) == expected


def that_messages(text: str) -> list[str]:
    [s] = split_sentences(Block(text=text, kind=BlockKind.PARAGRAPH, line=1))
    [parsed] = parse([s.masked])
    return [f.message for f in omitted_that(s, parsed)]


@pytest.mark.parametrize(
    ("text", "verbs"),
    [
        pytest.param("Make sure the valve is open.", ["make sure"], id="make sure"),
        pytest.param("Make sure that the valve is open.", [], id="that is there"),
        pytest.param("The manufacturer recommends you prepare the mixture.", ["recommends"], id="recommends"),
        pytest.param("The gauge shows the reservoir is full.", ["shows"], id="shows"),
        pytest.param("Check whether the valve is open.", [], id="wh-word"),
        pytest.param("Make sure to close the valve.", [], id="no clause"),
        pytest.param("You will see it running.", [], id="not finite"),
        pytest.param("Note: the file is read-only.", [], id="label"),
        pytest.param("Make sure `config.yaml` is set.", ["make sure"], id="inline code subject"),
    ],
)
def test_omitted_that(text, verbs):
    assert that_messages(text) == [f'Write "that" after "{v}".' for v in verbs]


def test_verb_phrase_shows_inline_code():
    text = "Runner has `TRACKER` + `MIGRATIONS_SUBDIR` pinned as constants."
    assert tense_findings(text) == [perfect("has `TRACKER` + `MIGRATIONS_SUBDIR` pinned")]


# Rule 1.1: words that are not approved and not in a glossary.
# The word list is a small one for the tests; the general glossary is the real one.

TEST_WORDLIST = """
# word | pos | status | forms | use instead
the | art | allowed | |
a | art | allowed | |
and | conj | allowed | |
that | conj | allowed | |
to | prep | allowed | |
you | pron | allowed | |
filter | n | allowed | |
clean | adj | allowed | |
clean | v | allowed | cleans, cleaned, cleaned |
open | v | allowed | opens, opened, opened |
set | v | allowed | sets, set, set |
read | v | allowed | reads, read, read |
one | adj | allowed | |
at | prep | allowed | |
time | n | allowed | |
new | adj | allowed | |
be | v | allowed | is, was, are, were |
make sure | v | allowed | makes sure, made sure, made sure |
# A made-up verb with a form that the lemmatizer cannot reduce to it.
zork | v | allowed | zorks, zinked, zinked |
commence | v | avoid | | start
"""


@pytest.fixture
def word_list(tmp_path, monkeypatch):
    path = tmp_path / "wordlist.txt"
    path.write_text(TEST_WORDLIST, encoding="utf-8")
    monkeypatch.setenv(wordlist.WORDLIST_ENV, str(path))
    return path


@pytest.fixture
def project(tmp_path):
    """A git project with a document in docs/."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "docs").mkdir()
    return root


def add_glossary(directory, text):
    (directory / ".speclint").mkdir(exist_ok=True)
    (directory / ".speclint" / "glossary.txt").write_text(text, encoding="utf-8")


def unknown(text: str, document=None) -> list[str]:
    """The words that rule 1.1 lists for a one-sentence text."""
    s = sentence(text)
    [parsed] = parse([s.masked])
    findings = unknown_words(s, parsed, vocabulary.load(document))
    if not findings:
        return []
    [finding] = findings
    listed = finding.message.removeprefix("Not approved and not in a glossary: ")
    return re.findall(r'"([^"]+)"(?: \(use ([^)]*)\))?', listed)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("Clean the filter.", [], id="approved words"),
        pytest.param("Clean the widget.", [("widget", "")], id="unknown word"),
        pytest.param("Commence the filter.", [("Commence", "start")], id="alternatives"),
        pytest.param(
            "The widget and the widget jolt.", [("widget", ""), ("jolt", "")], id="each word one time, in order"
        ),
        pytest.param("The filters were cleaned.", [], id="lemma and listed form"),
        pytest.param("The filter zinked.", [], id="form that is only in the forms list"),
        pytest.param("Commit the filter.", [], id="general glossary verb"),
        pytest.param("The commit is clean.", [], id="glossary term with another part of speech"),
        pytest.param("Make sure that the filter is clean.", [], id="approved phrase"),
        pytest.param("You made sure that the filter is clean.", [], id="form of an approved phrase"),
        pytest.param("Set `timeout` to 30.", [], id="inline code and number"),
        pytest.param('Click "New repository".', [], id="quoted text"),
        pytest.param("Click “New repository”.", [], id="curly quotes"),
        pytest.param("Clean the Zorbix filter.", [("Zorbix", "")], id="proper noun"),
    ],
)
def test_unknown_words(word_list, text, expected):
    assert unknown(text) == expected


def test_unknown_words_message(word_list):
    s = sentence("Commence the widget.")
    [parsed] = parse([s.masked])
    [finding] = unknown_words(s, parsed, vocabulary.load())
    assert finding.rule == "vocabulary"
    assert finding.message == 'Not approved and not in a glossary: "Commence" (use start), "widget".'


def test_unknown_words_help():
    assert unknown_words_help("/p/.speclint/glossary.txt") == (
        "For [vocabulary]: replace each listed word with a word from the word list. If a word "
        'is a technical term or a name, add it to /p/.speclint/glossary.txt as "term | pos | category | note" '
        f"(the format and the categories are in {vocabulary.GENERAL_GLOSSARY})."
    )


def test_unknown_words_project_glossary(word_list, project):
    add_glossary(project, "replica | n | component\npull request | n | component\n")
    document = project / "docs" / "a.md"
    assert unknown("Clean the replica.", document) == []
    assert unknown("Open a pull request.", document) == []


PLURAL_GLOSSARY = "replica | n | component\ndependency | n | component\nstatus | n | component\nstatus code | n | component\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # In these sentences, the parser does not give the singular lemma.
        pytest.param("Restart the replicas one at a time.", [], id="lemma not reduced"),
        pytest.param("Replicas clean the filter.", [], id="plural taken as a proper noun"),
        pytest.param("Read the status codes one at a time.", [], id="plural in a multi-word term"),
        pytest.param("Restart the dependencies.", [], id="ies to y"),
        pytest.param("Restart the statuses.", [], id="es"),
        pytest.param("Clean the replicants.", [("replicants", "")], id="singular not in the glossary"),
        pytest.param("The news is clean.", [("news", "")], id="singular is not used for approved words"),
    ],
)
def test_plural_of_glossary_term(word_list, project, text, expected):
    add_glossary(project, PLURAL_GLOSSARY)
    assert unknown(text, project / "docs" / "a.md") == expected


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("dependencies", {"dependency"}),
        ("statuses", {"status", "statuse"}),
        ("caches", {"cach", "cache"}),
        ("replicas", {"replica"}),
        ("class", set()),
        ("is", set()),
        ("api", set()),
    ],
)
def test_singulars(word, expected):
    assert singulars(word) == expected


NAME_GLOSSARY = "React | n | name\nGitHub | n | name\nGitHub Actions | n | name\nconfiguration | n | component\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("React cleans the filter.", [], id="name with the same case"),
        pytest.param("Commence and react to the filter.", [("Commence", "start"), ("react", "")], id="common word"),
        pytest.param("Configuration is clean.", [], id="lowercase term at the start of a sentence"),
        pytest.param("Clean the github filter.", [("github", "")], id="name with a different case"),
        pytest.param("Clean the GitHub Actions filter.", [], id="multi-word name"),
        pytest.param("Clean the GitHub actions filter.", [("actions", "")], id="multi-word name, different case"),
    ],
)
def test_case_of_glossary_names(word_list, project, text, expected):
    add_glossary(project, NAME_GLOSSARY)
    assert unknown(text, project / "docs" / "a.md") == expected


def test_glossary_target(word_list, project, tmp_path):
    document = project / "docs" / "a.md"
    target = vocabulary.glossary_target(document)
    assert target == str(project / ".speclint" / "glossary.txt")  # the git root
    add_glossary(project / "docs", "")
    target = vocabulary.glossary_target(document)
    assert target == str(project / "docs" / ".speclint" / "glossary.txt")  # the nearest one
    outside = tmp_path / "notes" / "b.md"
    target = vocabulary.glossary_target(outside)
    assert target == str(tmp_path / "notes" / ".speclint" / "glossary.txt")  # not in git


def test_glossary_problem_is_a_finding(word_list, project):
    add_glossary(project, "stale | adj | component\n")
    document = project / "docs" / "a.md"
    findings = [f for f in check_text("Clean the filter.\n", document) if f.rule == "list-format"]
    assert [(f.line, f.excerpt) for f in findings] == [
        (0, f'{project / ".speclint" / "glossary.txt"}:1: pos "adj" must be "n" (noun) or "v" (verb)')
    ]


def test_no_word_list_no_rule_1_1(project):
    # The conftest fixture points SPECLINT_WORDLIST to a file that does not exist.
    add_glossary(project, "stale | adj | component\n")
    findings = check_text("Clean the replica.\n", project / "docs" / "a.md")
    assert findings == []


def test_unknown_words_line_and_text(word_list):
    findings = check_text("Clean the filter.\n\nClean the `x` widget.\n")
    assert [(f.rule, f.line, f.excerpt) for f in findings] == [("vocabulary", 3, "Clean the `x` widget.")]
