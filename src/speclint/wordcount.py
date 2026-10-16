"""Word counter for the sentence length rule.

These elements count as one word:
- Text in parentheses and quoted text
- A number together with its unit of measurement
- Numbers, abbreviations, identifiers, and hyphenated words.
  These have no spaces, so they are already one word.
- Inline code. It is masked as one placeholder word before this step.

Known limits. The LLM that fixes the text makes the final decision, so
these are not handled and can make the count too high:
- Titles, headings, and proper nouns ("George Washington")
- Uppercase quoted text, formulas, and "No. 1"
- A unit that is a full word ("10 degrees Celsius")
- Nested parentheses or quotes
- The text in parentheses is not counted as a separate sentence.
"""

import re

# Text in parentheses, or in straight or curly double quotes.
_GROUP = re.compile(r"\([^()]*\)|\"[^\"]*\"|“[^”]*”")
# "10", "2.8", "1,000", "5–15"
_NUMBER = re.compile(r"[-+]?\d[\d.,–-]*")
# A word has at least one letter or digit. "—" and "<" are not words.
_HAS_WORD_CHAR = re.compile(r"[^\W_]")
# Units that can follow a number, without a final period ("a.m." is "a.m").
# Units that are also common words ("in", "d") are not included.
_UNITS = frozenset(
    """
    mm cm m km ft mi mg g kg lb oz ml mL L
    ms s sec min h hr a.m p.m
    °C °F K V mV kV A mA W kW Hz kHz MHz GHz Nm Pa kPa MPa psi bar rpm
    KB MB GB TB KiB MiB GiB TiB kbps Mbps Gbps MB/s GB/s km/h mph
    """.split()
)


def count_words(sentence: str) -> int:
    """Return the word count of one masked sentence (Sentence.masked)."""
    tokens = _GROUP.sub(" group ", sentence).split()
    count = 0
    after_number = False
    for token in tokens:
        word = token.rstrip(".,;:!?")
        if not _HAS_WORD_CHAR.search(word):
            continue
        if after_number and word in _UNITS:
            # The unit and the number before it are one word.
            after_number = False
            continue
        count += 1
        after_number = _NUMBER.fullmatch(word) is not None
    return count
