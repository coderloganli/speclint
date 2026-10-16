"""Glossaries of technical terms and names.

The word list gives the common words. A glossary gives the technical terms
and names that a document can also use. speclint reads two glossaries:

- the general software glossary, data/software_glossary.txt in this package
- the project glossary, .speclint/glossary.txt, found in the directory of the
  checked file or in one of its parent directories

A lowercase term matches with any case. A term with an uppercase letter
("GitHub", "React") matches only with the same case.

Each line is "term | pos | category | note". The category tells why the term
is necessary (see CATEGORIES). A line that is not correct is not used, and
becomes a problem with its file and line number.
"""

from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

PROJECT_GLOSSARY = Path(".speclint") / "glossary.txt"

# Category -> the part of speech that it needs.
CATEGORIES = {
    "name": "n",  # products, programming languages, standards, organizations
    "component": "n",  # systems, software components, configurations, infrastructure
    "concept": "n",  # engineering, mathematics, and computing concepts; data types
    "device": "n",  # machines and computers
    "unit": "n",  # units of measurement, time, and dates
    "document": "n",  # documents and parts of documents
    "role": "n",  # persons and groups
    "operation": "v",  # computer operations
}


@dataclass(frozen=True)
class Term:
    """One glossary entry."""

    term: str  # as written, for example "GitHub" or "pull request"
    pos: str  # "n" or "v"
    category: str  # one of CATEGORIES, for example "component" or "operation"
    note: str
    source: str  # file name and line, for reports: ".speclint/glossary.txt:4"


@dataclass
class Glossary:
    """Terms from one or more glossary files, and the problems in those files."""

    terms: dict[tuple[str, str], Term] = field(default_factory=dict)  # (lowercase term, pos)
    problems: list[str] = field(default_factory=list)

    def get(self, term: str, pos: str) -> Term | None:
        """The entry for a term with a part of speech ("n" or "v").

        A term with an uppercase letter (a name, such as "GitHub" or "React")
        matches only with the same case, so that the name does not let the
        common word "react" pass. A lowercase term matches with any case.
        """
        entry = self.terms.get((term.lower(), pos))
        if entry and is_name(entry.term) and entry.term != term:
            return None
        return entry

    def add(self, text: str, source: str) -> None:
        """Add the entries of one glossary file. `source` is the file name for reports."""
        for number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            where = f"{source}:{number}"
            term, problem = _parse_line(line, where)
            if problem:
                self.problems.append(f"{where}: {problem}")
            else:
                self.terms.setdefault((term.term.lower(), term.pos), term)


def is_name(term: str) -> bool:
    """True if a glossary term has an uppercase letter, so that its case must match."""
    return term != term.lower()


def _parse_line(line: str, where: str) -> tuple[Term | None, str | None]:
    """Parse "term | pos | category | note". Returns the term, or a problem."""
    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 3 or not parts[0]:
        return None, 'write "term | pos | category | note" (the note is optional)'
    term, pos, category = parts[:3]
    note = " | ".join(parts[3:])
    if pos not in ("n", "v"):
        return None, f'pos "{pos}" must be "n" (noun) or "v" (verb)'
    if category not in CATEGORIES:
        return None, f'category "{category}" must be one of {", ".join(CATEGORIES)}'
    needed = CATEGORIES[category]
    if pos != needed:
        return None, f'category "{category}" needs pos "{needed}"'
    return Term(term, pos, category, note, where), None


def find_project_glossary(document: Path) -> Path | None:
    """The nearest .speclint/glossary.txt in the directory of `document` or above it."""
    for directory in document.resolve().parents:
        path = directory / PROJECT_GLOSSARY
        if path.is_file():
            return path
    return None


def load(document: Path | None = None) -> Glossary:
    """The general glossary and, if there is one, the project glossary of `document`."""
    glossary = Glossary()
    general = files("speclint").joinpath("data/software_glossary.txt")
    glossary.add(general.read_text(encoding="utf-8"), "software_glossary.txt")
    project = find_project_glossary(document) if document else None
    if project:
        try:
            glossary.add(project.read_text(encoding="utf-8"), str(project))
        except (OSError, UnicodeDecodeError) as e:
            glossary.problems.append(f"{project}: cannot read: {e}")
    return glossary
