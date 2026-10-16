from speclint import wordlist
from speclint.cli import main


def parse(text: str) -> wordlist.WordList:
    return wordlist.parse(text, "w.txt")


def test_allowed_word_with_forms():
    words = parse("remove | v | allowed | removes, removed, removed |")
    assert words.allowed == {"remove", "removes", "removed"}
    assert words.problems == []


def test_word_to_avoid_with_alternatives():
    words = parse("should | v | avoid | | must, if")
    assert words.alternatives == {"should": ["must", "if"]}
    assert "should" not in words.allowed


def test_blank_lines_and_comments_are_ignored():
    words = parse("# word | pos | status\n\n   \nRemove | v | allowed\n")
    assert words.allowed == {"remove"}
    assert words.problems == []


def test_phrase_and_its_forms():
    words = parse("make sure | v | allowed | makes sure, made sure |")
    assert words.allowed_phrases == {("make", "sure"), ("makes", "sure"), ("made", "sure")}
    assert words.allowed == set()


def test_word_allowed_as_one_part_of_speech_and_avoided_as_another():
    words = parse("check | n | allowed | |\ncheck | v | avoid | | make sure")
    assert "check" in words.allowed  # the vocabulary check does not use the part of speech
    assert words.alternatives == {"check": ["make sure"]}


def test_line_with_a_problem_is_not_used():
    words = parse("remove | v | ok\nremove | verb | allowed\nremove v allowed\nkeep | v | allowed\n")
    assert words.allowed == {"keep"}
    assert words.problems == [
        'w.txt:1: status "ok" must be "allowed" or "avoid"',
        'w.txt:2: pos "verb" must be one of n, v, adj, adv, pron, art, prep, conj, prefix, or empty',
        'w.txt:3: write "word | pos | status | forms | use instead" (forms and use instead are optional)',
    ]


def test_file_named_by_the_environment(tmp_path, monkeypatch):
    file = tmp_path / "mine.txt"
    file.write_text("keep | v | allowed\n", encoding="utf-8")
    monkeypatch.setenv(wordlist.WORDLIST_ENV, str(file))
    assert wordlist.path() == file
    assert wordlist.load().allowed == {"keep"}


def test_file_in_the_user_config_directory(tmp_path, monkeypatch):
    monkeypatch.delenv(wordlist.WORDLIST_ENV)
    monkeypatch.setenv("HOME", str(tmp_path))
    file = tmp_path / ".config" / "speclint" / "wordlist.txt"
    file.parent.mkdir(parents=True)
    file.write_text("keep | v | allowed\n", encoding="utf-8")
    assert wordlist.path() == file
    assert wordlist.load().allowed == {"keep"}


def test_no_word_list(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(wordlist.WORDLIST_ENV)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert wordlist.path() is None
    assert wordlist.load() is None
    doc = tmp_path / "a.md"
    doc.write_text("Examine the parts; replace them.\n", encoding="utf-8")
    assert main(["check", str(doc)]) == 1  # the other rules still run
    captured = capsys.readouterr()
    assert "[semicolon]" in captured.out
    assert "no word list, so the vocabulary check is off" in captured.err


def test_alternatives_from_two_lines_are_listed_one_time():
    words = parse("check | v | avoid | | make sure, examine\ncheck | n | avoid | | examine, test")
    assert words.alternatives == {"check": ["make sure", "examine", "test"]}
