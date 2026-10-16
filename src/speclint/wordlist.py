"""The word list: the common words that a document can use, and the words to avoid.

speclint does not include a word list. A user writes one, or makes one from a
source that they have the right to use, and puts it in one of these places
(the first that exists is used):

- the file that SPECLINT_WORDLIST names
- ~/.config/speclint/wordlist.txt

If there is no word list, the vocabulary check does not run.

Each line is "word | pos | status | forms | use instead":

    remove    | v | allowed | removes, removed, removed |
    should    | v | avoid   |                           | must, if

- word: the base form, in any case; it can have more than one word ("make sure")
- pos: n, v, adj, adv, pron, art, prep, conj, prefix, or empty
- status: "allowed" (the word can be used) or "avoid" (use other words)
- forms: other allowed forms, separated by commas (optional)
- use instead: for "avoid" words, the words to use, separated by commas (optional)

A line that is not correct is not used, and becomes a problem with its file
and line number.
"""

import os
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

WORDLIST_ENV = "SPECLINT_WORDLIST"
POS = ("n", "v", "adj", "adv", "pron", "art", "prep", "conj", "prefix")
STATUS = ("allowed", "avoid")

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")


@dataclass(frozen=True)
class WordList:
    """The words of a word list. All lowercase."""

    allowed: frozenset[str]  # allowed one-word words and their forms
    allowed_phrases: frozenset[tuple[str, ...]]  # "make sure", "made sure", as tokens
    alternatives: dict[str, list[str]]  # word to avoid -> words to use
    problems: list[str] = field(default_factory=list)


def path() -> Path | None:
    """The word list file to use, or None if there is none."""
    named = os.environ.get(WORDLIST_ENV)
    candidate = Path(named) if named else Path.home() / ".config" / "speclint" / "wordlist.txt"
    return candidate if candidate.is_file() else None


def load() -> WordList | None:
    """The word list, or None if there is no word list file."""
    file = path()
    if file is None:
        return None
    try:
        return _load(str(file), file.stat().st_mtime_ns)
    except (OSError, UnicodeDecodeError) as e:
        return WordList(frozenset(), frozenset(), {}, [f"{file}: cannot read: {e}"])


@cache
def _load(file: str, mtime: int) -> WordList:
    return parse(Path(file).read_text(encoding="utf-8"), file)


def tokens(text: str, keep_case: bool = False) -> tuple[str, ...]:
    """Split a phrase into tokens as spaCy splits them: "dead-letter topic"
    -> ("dead", "-", "letter", "topic"). Lowercase unless keep_case."""
    return tuple(_TOKEN_RE.findall(text if keep_case else text.lower()))


def parse(text: str, source: str) -> WordList:
    """Read the lines of a word list. `source` is the file name for problems."""
    allowed: set[str] = set()
    phrases: set[tuple[str, ...]] = set()
    alternatives: dict[str, list[str]] = {}
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        problem = _problem(parts)
        if problem:
            problems.append(f"{source}:{number}: {problem}")
            continue
        word, _pos, status = parts[:3]
        forms = _split(parts[3]) if len(parts) > 3 else []
        if status == "allowed":
            for form in [word, *forms]:
                form_tokens = tokens(form)
                if len(form_tokens) == 1:
                    allowed.add(form_tokens[0])
                elif form_tokens:
                    phrases.add(form_tokens)
        else:
            known = alternatives.setdefault(word.lower(), [])
            for alternative in _split(parts[4]) if len(parts) > 4 else []:
                if alternative not in known:
                    known.append(alternative)
    return WordList(frozenset(allowed), frozenset(phrases), alternatives, problems)


def _problem(parts: list[str]) -> str | None:
    if len(parts) < 3 or not parts[0]:
        return 'write "word | pos | status | forms | use instead" (forms and use instead are optional)'
    if parts[1] and parts[1] not in POS:
        return f'pos "{parts[1]}" must be one of {", ".join(POS)}, or empty'
    if parts[2] not in STATUS:
        return f'status "{parts[2]}" must be "allowed" or "avoid"'
    return None


def _split(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]
