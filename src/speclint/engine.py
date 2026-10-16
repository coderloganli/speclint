"""Runs the rules on a document."""

from pathlib import Path

from speclint import vocabulary as vocabulary_module
from speclint.grammar import parse
from speclint.models import Finding
from speclint.rules import BLOCK_RULES, GRAMMAR_RULES, SENTENCE_RULES, glossary_problems, unknown_words
from speclint.segment import find_unclosed_fences, parse_blocks, split_sentences


def check_text(source: str, path: Path | None = None) -> list[Finding]:
    """Return the findings for one Markdown source, sorted by line.

    `path` is the file of the source. The vocabulary check uses it to find the
    project glossary. It runs only if there is a word list (wordlist.py).
    """
    vocabulary = vocabulary_module.load(path)
    findings = find_unclosed_fences(source)
    sentences = []
    for block in parse_blocks(source):
        block_sentences = split_sentences(block)
        sentences.extend(block_sentences)
        for block_rule in BLOCK_RULES:
            findings.extend(block_rule(block, block_sentences))

    for sentence in sentences:
        for rule in SENTENCE_RULES:
            findings.extend(rule(sentence))

    if sentences:
        for sentence, parsed in zip(sentences, parse([s.masked for s in sentences])):
            for grammar_rule in GRAMMAR_RULES:
                findings.extend(grammar_rule(sentence, parsed))
            if vocabulary:
                findings.extend(unknown_words(sentence, parsed, vocabulary))
    if vocabulary:
        findings.extend(glossary_problems(vocabulary))

    return sorted(findings, key=lambda f: f.line)
