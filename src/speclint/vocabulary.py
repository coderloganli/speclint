"""The words that a document can use: the word list and the glossary terms.

The word list (wordlist.py) gives the common words. The glossaries
(glossary.py) give the technical terms. If there is no word list, there is no
vocabulary and the vocabulary check does not run.

Known limit: part of speech is not used. A word passes if it is allowed, or in
a glossary, as any part of speech.
"""

from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from speclint import glossary as glossary_module
from speclint import wordlist as wordlist_module
from speclint.glossary import Glossary, is_name
from speclint.wordlist import WordList

GENERAL_GLOSSARY = str(files("speclint").joinpath("data/software_glossary.txt"))


@dataclass(frozen=True)
class Vocabulary:
    wordlist: WordList
    glossary: Glossary
    words: frozenset[str]  # one-word lowercase glossary terms, matched with any case
    names: frozenset[str]  # one-word glossary terms with an uppercase letter, matched exactly
    # Glossary terms and allowed phrases with more than one token. A token with
    # an uppercase letter ("GitHub" in "GitHub Actions") must match exactly.
    phrases: frozenset[tuple[str, ...]]
    glossary_target: str  # the project glossary file that Claude adds terms to
    problems: list[str] = field(default_factory=list)  # in the word list and the glossaries


def load(document: Path | None = None) -> Vocabulary | None:
    """The vocabulary for a document, or None if there is no word list."""
    wordlist = wordlist_module.load()
    if wordlist is None:
        return None
    glossary = glossary_module.load(document)
    words, names, phrases = set(), set(), set(wordlist.allowed_phrases)
    for entry in glossary.terms.values():
        tokens = wordlist_module.tokens(entry.term, keep_case=is_name(entry.term))
        if len(tokens) > 1:
            phrases.add(tokens)
        elif is_name(entry.term):
            names.add(tokens[0])
        else:
            words.add(tokens[0])
    return Vocabulary(
        wordlist,
        glossary,
        frozenset(words),
        frozenset(names),
        frozenset(phrases),
        glossary_target(document),
        wordlist.problems + glossary.problems,
    )


def glossary_target(document: Path | None) -> str:
    """The project glossary: the nearest one, else one in the git root, else
    one next to the document."""
    if document is None:
        return str(glossary_module.PROJECT_GLOSSARY)
    existing = glossary_module.find_project_glossary(document)
    if existing:
        return str(existing)
    for directory in document.resolve().parents:
        if (directory / ".git").exists():
            return str(directory / glossary_module.PROJECT_GLOSSARY)
    return str(document.resolve().parent / glossary_module.PROJECT_GLOSSARY)
