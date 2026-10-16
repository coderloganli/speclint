"""Data types shared by all speclint modules."""

from dataclasses import dataclass
from enum import StrEnum


class BlockKind(StrEnum):
    """The Markdown element that contains a block of prose."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Block:
    """One block of prose from a Markdown document.

    Code blocks, HTML, and front matter never become blocks.
    `text` keeps inline code with its backticks, so that later steps
    can treat each inline code span as one word.
    """

    text: str
    kind: BlockKind
    line: int  # 1-based line of the first character in the source file
    ordered: bool = False  # True for an item in an ordered list
    # GitHub alert type of the enclosing blockquote ("note", "warning", ...),
    # from a marker such as "> [!NOTE]". None if there is no alert.
    alert: str | None = None


@dataclass(frozen=True)
class Sentence:
    """One sentence in a block.

    `text` is the sentence as written, for reports. `masked` has each inline
    code span replaced by a placeholder word, so that rules do not check code.
    Both have their whitespace collapsed to single spaces.
    """

    text: str
    masked: str
    block: Block
    line: int  # 1-based line of the first character in the source file


@dataclass(frozen=True)
class Finding:
    """One rule violation."""

    rule: str  # rule name, for example "sentence-length" or "passive-voice"
    severity: Severity
    message: str
    line: int
    excerpt: str
