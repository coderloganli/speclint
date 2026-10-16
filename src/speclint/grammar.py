"""Grammar analysis with the spaCy model en_core_web_sm.

The model gives each word its part of speech, its fine-grained tag (for
example, past participle), and its dependency relation (for example, the
auxiliary verb of a passive). Grammar rules read these labels.
"""

from functools import cache

import spacy
from spacy.language import Language
from spacy.tokens import Doc


@cache
def _model() -> Language:
    # No rule uses named entities, so do not load that component.
    return spacy.load("en_core_web_sm", exclude=["ner"])


def parse(texts: list[str]) -> list[Doc]:
    """Parse each text. Parse the texts of a document in one call: it is faster."""
    return list(_model().pipe(texts))
