"""Markdown segmentation.

Turns a Markdown source into blocks of prose and then into sentences.
Only prose goes to the rules. Code, HTML, and front matter are skipped.
"""

import re
from functools import cache

import spacy
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.front_matter import front_matter_plugin
from spacy.language import Language

from speclint.models import Block, BlockKind, Finding, Sentence, Severity

_md = MarkdownIt("commonmark").enable("table").use(front_matter_plugin)

# A GitHub alert marker must be alone on the first line of a blockquote.
_ALERT = re.compile(r"\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\n|$)")

# Containers that decide the kind of the prose inside them.
_KINDS = {
    "heading_open": BlockKind.HEADING,
    "th_open": BlockKind.TABLE_CELL,
    "td_open": BlockKind.TABLE_CELL,
    "list_item_open": BlockKind.LIST_ITEM,
}


def parse_blocks(source: str) -> list[Block]:
    """Return the blocks of prose in a Markdown source, in document order.

    Each "inline" token of the parser becomes one block. Code blocks, HTML
    blocks, and front matter have no inline token, so they never become blocks.
    """
    tokens = _md.parse(source)
    blocks: list[Block] = []
    stack: list[Token] = []  # open container tokens, outermost first
    alerts: list[str | None] = []  # alert type of each open blockquote
    for i, token in enumerate(tokens):
        if token.nesting == 1:
            stack.append(token)
            if token.type == "blockquote_open":
                alerts.append(_alert_type(tokens, i))
        elif token.nesting == -1:
            stack.pop()
            if token.type == "blockquote_close":
                alerts.pop()
        elif token.type == "inline":
            block = _make_block(token, stack, alerts[-1] if alerts else None)
            if block is not None:
                blocks.append(block)
    return blocks


def _alert_type(tokens: list[Token], i: int) -> str | None:
    """Return the alert type of the blockquote that opens at tokens[i]."""
    if i + 2 < len(tokens) and tokens[i + 1].type == "paragraph_open":
        m = _ALERT.match(tokens[i + 2].content)
        if m:
            return m.group(1).lower()
    return None


def _make_block(token: Token, stack: list[Token], alert: str | None) -> Block | None:
    text = _render(token.children or [])
    line = token.map[0] + 1
    if alert:
        m = _ALERT.match(text)
        if m:
            text = text[m.end():]
            line += 1
    if not text.strip():
        return None
    kind, ordered = _kind(stack)
    return Block(text=text, kind=kind, line=line, ordered=ordered, alert=alert)


def _kind(stack: list[Token]) -> tuple[BlockKind, bool]:
    """Return the kind of the innermost container, and if it is an ordered list item."""
    for open_token in reversed(stack):
        kind = _KINDS.get(open_token.type)
        if kind is BlockKind.LIST_ITEM:
            nearest_list = next(
                t for t in reversed(stack) if t.type in ("ordered_list_open", "bullet_list_open")
            )
            return kind, nearest_list.type == "ordered_list_open"
        if kind is not None:
            return kind, False
    return BlockKind.PARAGRAPH, False


def _render(children: list[Token]) -> str:
    """Join the inline tokens into plain text.

    Inline code keeps its backticks. A line break becomes "\\n", so that
    split_sentences can find the line of each sentence.
    """
    parts: list[str] = []
    for child in children:
        if child.type in ("text", "text_special"):
            parts.append(child.content)
        elif child.type == "code_inline":
            code = child.content
            if code.startswith("`") or code.endswith("`"):
                code = f" {code} "
            parts.append(child.markup + code + child.markup)
        elif child.type == "image":
            # Keep the alt text, so that the sentence stays complete.
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append("\n")
        # Other tokens (emphasis, links, inline HTML) add no text.
        # The text inside a link or emphasis comes as separate text tokens.
    return "".join(parts)


def find_unclosed_fences(source: str) -> list[Finding]:
    """Return one unclosed-code-fence finding for each code fence that has no closing fence.

    An unclosed fence makes the parser treat all text after it as code,
    so the rules do not see that text. Report it as an error.

    A fence is closed if its last line is not its first line, and the last
    line, without leading spaces and ">" markers, starts with the opening
    marker. Known limit: a last line with text after the marker ("``` x")
    does not close a fence, but this check accepts it.
    """
    lines = source.splitlines()
    findings: list[Finding] = []
    for token in _md.parse(source):
        if token.type != "fence":
            continue
        first, end = token.map
        last = lines[end - 1].lstrip(" \t>")
        if end - 1 > first and last.startswith(token.markup):
            continue
        findings.append(
            Finding(
                rule="unclosed-code-fence",
                severity=Severity.ERROR,
                message="Code fence is not closed. The text after it is not checked.",
                line=first + 1,
                excerpt=lines[first].strip(),
            )
        )
    return findings


def split_sentences(block: Block) -> list[Sentence]:
    """Split one block into sentences.

    Inline code is masked first, so that a period in code does not end a
    sentence. A colon does not end a sentence: the word count applies to the
    colon before a vertical list, and parse_blocks already makes the text
    before a list and each list item into different blocks.

    Known limits. The rules get the result, and the LLM that fixes the text
    makes the final decision, so these are not handled:
    - An ellipsis ("... Then") or one capital letter ("plan B. Then") does
      not end a sentence.
    - Text in parentheses is not a separate sentence.
    - End punctuation in parentheses can end the sentence ("(hopefully!) get").
    """
    masked, codes = mask_code(block.text)
    sentences: list[Sentence] = []
    for span in _sentencizer()(masked).sents:
        raw = span.text
        if not raw.strip():
            continue
        # Count lines to the first visible character: a sentence can start
        # with the line break that comes after the previous sentence.
        start = span.start_char + len(raw) - len(raw.lstrip())
        sentence = " ".join(raw.split())
        sentences.append(
            Sentence(
                text=unmask_code(sentence, codes),
                masked=sentence,
                block=block,
                line=block.line + masked.count("\n", 0, start),
            )
        )
    return sentences


# An inline code span: a run of backticks, the code, and a run of the same length.
_CODE = re.compile(r"(`+).+?(?<!`)\1(?!`)")
# Lowercase, and ends with a letter: spaCy reads "X." as an initial and does
# not end a sentence there, and a digit after the number would change it.
_PLACEHOLDER = re.compile(r"codeph(\d+)x")


def mask_code(text: str) -> tuple[str, list[str]]:
    """Replace each inline code span with a placeholder word.

    Return the masked text and the code spans, in order.
    """
    codes: list[str] = []

    def replace(m: re.Match[str]) -> str:
        codes.append(m.group(0))
        return f"codeph{len(codes) - 1}x"

    return _CODE.sub(replace, text), codes


def unmask_code(text: str, codes: list[str]) -> str:
    """Put the code spans back in place of their placeholders.

    A placeholder with no code span (the document itself contains a word
    such as "codeph9x") stays as it is.
    """

    def replace(m: re.Match[str]) -> str:
        i = int(m.group(1))
        return codes[i] if i < len(codes) else m.group()

    return _PLACEHOLDER.sub(replace, text)


def unmask_fragment(sentence: Sentence, fragment: str) -> str:
    """Put the code spans back into a part of Sentence.masked.

    The placeholders in Sentence.masked and the code spans in Sentence.text
    are in the same order, so the n-th placeholder is the n-th code span.
    """
    codes = dict(
        zip(
            (m.group() for m in _PLACEHOLDER.finditer(sentence.masked)),
            (m.group() for m in _CODE.finditer(sentence.text)),
        )
    )
    return _PLACEHOLDER.sub(lambda m: codes.get(m.group(), m.group()), fragment)


@cache
def _sentencizer() -> Language:
    # The rule-based sentencizer needs no trained model.
    nlp = spacy.blank("en")
    # The tokenizer reads "s." in "MB/s." as an abbreviation, so the sentence
    # does not end there. Remove the abbreviations of one lowercase letter.
    nlp.tokenizer.rules = {
        k: v for k, v in nlp.tokenizer.rules.items() if not re.fullmatch(r"[a-z]\.", k)
    }
    nlp.add_pipe("sentencizer")
    return nlp
