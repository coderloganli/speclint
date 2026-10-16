"""Writing rules.

Each sentence rule takes one sentence, and each block rule takes one block
and its sentences. Each rule returns its findings. Rules check
Sentence.masked, so that they do not check inline code. The message tells
the reader (an LLM) what to change.
"""

import re
from collections.abc import Callable
from functools import cache
from importlib.resources import files

from spacy.tokens import Doc, Token

from speclint.models import Block, BlockKind, Finding, Sentence, Severity
from speclint.segment import unmask_fragment
from speclint.vocabulary import GENERAL_GLOSSARY, Vocabulary
from speclint.wordcount import count_words


def semicolon(sentence: Sentence) -> list[Finding]:
    """semicolon: do not use the semicolon. One finding for each sentence."""
    if ";" not in sentence.masked:
        return []
    return [_finding(sentence, "semicolon", "Do not use a semicolon. Write two sentences.")]


# Latin abbreviation (lowercase) -> English words to use.
_LATIN = {
    "e.g.": "for example",
    "i.e.": "that is",
    "etc.": "and so on",
    "cf.": "compare",
    "viz.": "namely",
    "vs.": "versus",
    "vs": "versus",
}
_LATIN_RE = re.compile(r"(?<!\w)(?:e\.g\.|i\.e\.|etc\.|cf\.|viz\.|vs\.?)(?!\w)", re.IGNORECASE)


def latin_abbreviation(sentence: Sentence) -> list[Finding]:
    """latin-abbreviation: do not use Latin abbreviations. One finding for each abbreviation."""
    return [
        _finding(sentence, "latin-abbreviation", f'Do not use "{m.group()}". Write "{_LATIN[m.group().lower()]}".')
        for m in _LATIN_RE.finditer(sentence.masked)
    ]


# Endings that only a contraction has ("isn't", "they're"), and the "'s"
# contractions to report. Other "'s" are possessive ("Apple's"), which is correct.
_CONTRACTION_RE = re.compile(
    r"(?<!\w)(?:\w+n['’]t|\w+['’](?:re|ve|ll|d|m)"
    r"|(?:it|that|there|here|what|who|where|let)['’]s)(?!\w)",
    re.IGNORECASE,
)


def contraction(sentence: Sentence) -> list[Finding]:
    """contraction: do not use contractions. One finding for each contraction.

    Known limit: words that are left out (do not omit nouns, verbs,
    or articles) needs grammar analysis and is not checked here.
    """
    return [
        _finding(sentence, "contraction", f'Do not use the contraction "{m.group()}". Write the full words.')
        for m in _CONTRACTION_RE.finditer(sentence.masked)
    ]


_GENDER_PRONOUN_RE = re.compile(
    r"\b(?:he|she|him|her|his|hers|himself|herself)\b", re.IGNORECASE
)


def gender_pronoun(sentence: Sentence) -> list[Finding]:
    """gendered-pronoun: do not use gender-specific pronouns. One finding for each pronoun.

    Known limit: "man" and "woman" are also gender-specific.
    They are not checked, because "man page" is a common technical term.
    """
    return [
        _finding(
            sentence,
            "gendered-pronoun",
            f'Do not use the gender-specific pronoun "{m.group()}". '
            'Use a neutral noun (for example, "the user") or "they".',
        )
        for m in _GENDER_PRONOUN_RE.finditer(sentence.masked)
    ]


@cache
def _british_spellings() -> dict[str, list[str]]:
    """British spelling -> American spellings, from data/british_spelling.tsv (from ESDB)."""
    text = files("speclint").joinpath("data/british_spelling.tsv").read_text(encoding="utf-8")
    return {
        british: american.split(",")
        for british, american in (line.split("\t") for line in text.splitlines())
    }


# A word, with an apostrophe or hyphen inside it ("centre's", "pre-existing").
_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")


def british_spelling(sentence: Sentence) -> list[Finding]:
    """american-spelling: use American spelling. One finding for each British spelling.

    Known limit: proper nouns with a British spelling ("Centre for Policy
    Studies") are also reported.
    """
    findings = []
    for m in _WORD_RE.finditer(sentence.masked):
        word = m.group()
        american = _british_spellings().get(word.lower().replace("’", "'"))
        if american is None:
            continue
        if word[0].isupper():
            american = [a[0].upper() + a[1:] for a in american]
        options = " or ".join(f'"{a}"' for a in american)
        findings.append(
            _finding(sentence, "american-spelling", f'Use American spelling: write {options}, not "{word}".')
        )
    return findings


def sentence_length(sentence: Sentence) -> list[Finding]:
    """sentence-length: a maximum of 20 words in a procedure, 25 in descriptive text.

    A sentence is procedural if it is in an ordered list item, or in a warning
    or caution (safety instructions are procedures). Other alerts, such as
    notes, give information, so they are descriptive (25 words).
    Known limit: an instruction in a paragraph or a bullet list is checked as
    descriptive text.
    """
    block = sentence.block
    if block.kind is BlockKind.HEADING:  # A heading counts as one word.
        return []
    if block.alert in ("warning", "caution") or (block.ordered and block.alert is None):
        limit, text_type = 20, "A procedure step"
    else:
        limit, text_type = 25, "Descriptive text"
    words = count_words(sentence.masked)
    if words <= limit:
        return []
    message = (
        f"This sentence has {words} words. {text_type} can have a maximum of {limit} words. "
        "Write shorter sentences."
    )
    return [_finding(sentence, "sentence-length", message)]


def paragraph_length(block: Block, sentences: list[Sentence]) -> list[Finding]:
    """paragraph-length: a paragraph has a maximum of six sentences.

    Only paragraphs are checked, not list items or table cells. The finding
    is on the first sentence, so that the report does not show the full paragraph.
    """
    if block.kind is not BlockKind.PARAGRAPH or len(sentences) <= 6:
        return []
    message = (
        f"This paragraph has {len(sentences)} sentences. A paragraph can have a maximum of "
        "6 sentences. Divide it into shorter paragraphs."
    )
    return [_finding(sentences[0], "paragraph-length", message)]


def passive_voice(sentence: Sentence, parsed: Doc) -> list[Finding]:
    """passive-voice: use the active voice. One finding for each passive verb.

    A passive has an auxiliary with the dependency label "auxpass" ("was" in
    "was installed"). This also finds modal + be + past participle ("must be
    adjusted"), which perfect-tense reports.
    The passive can be correct in descriptive text when the agent is unknown.
    That is not checked: all passives are reported, and the LLM decides.
    """
    findings = []
    for token in parsed:
        if token.dep_ != "auxpass":
            continue
        phrase = _verb_phrase(sentence, parsed, token.head)
        findings.append(_finding(sentence, "passive-voice", f'Use the active voice: "{phrase}".'))
    return findings


def verb_tense(sentence: Sentence, parsed: Doc) -> list[Finding]:
    """perfect-tense and progressive-tense: do not use these tenses.

    perfect-tense: a past participle with the auxiliary "have" ("has adjusted").
    progressive-tense: an "-ing" form with the auxiliary "be" ("is running").
    A passive verb is skipped, because passive_voice reports it.
    """
    findings = []
    for verb in parsed:
        auxiliaries = [t for t in verb.children if t.dep_ in ("aux", "auxpass")]
        if not auxiliaries or any(t.dep_ == "auxpass" for t in auxiliaries):
            continue
        lemmas = {t.lemma_.lower() for t in auxiliaries}
        if verb.tag_ == "VBG" and "be" in lemmas:
            rule, tense, use = "progressive-tense", "progressive", "simple present or simple past"
        elif verb.tag_ == "VBN" and "have" in lemmas:
            rule, tense, use = "perfect-tense", "perfect", "simple past or simple present"
        else:
            continue
        phrase = _verb_phrase(sentence, parsed, verb)
        findings.append(
            _finding(sentence, rule, f'Do not use the {tense} tense: "{phrase}". Use the {use}.')
        )
    return findings


# Verbs after which "that" must come before a clause (omitted-that gives
# "make sure", "show", and "recommend"), and verbs that are frequent in
# technical text with the same structure.
_THAT_VERBS = frozenset(
    "ensure show recommend verify check confirm mean say note know think assume find "
    "expect require indicate specify suggest state guarantee tell believe decide see".split()
)
_WH_WORDS = frozenset("what which who whom whose when where why how if whether".split())
_SUBJECTS = frozenset({"nsubj", "nsubjpass", "csubj", "csubjpass", "expl"})
_FINITE_TAGS = frozenset({"VBZ", "VBP", "VBD", "MD"})


def omitted_that(sentence: Sentence, parsed: Doc) -> list[Finding]:
    """omitted-that: do not omit "that" after verbs such as "make sure", "show", "recommend".

    A finding is a clause complement ("ccomp") of such a verb with no
    "that". Filters remove the cases that are not an omitted "that".
    Known limit: when inline code is the subject just before a verb that ends
    in "-s" ("Make sure `x` exists."), the model can tag the verb as a plural
    noun, and the clause is not found. Other placeholder words have the same
    kind of problem in other sentences, so the placeholder is not changed.
    """
    findings = []
    for clause in parsed:
        if clause.dep_ != "ccomp":
            continue
        verb = clause.head
        make_sure = verb.lower_ == "sure" and verb.head.lemma_.lower() == "make"
        if not make_sure and verb.lemma_.lower() not in _THAT_VERBS:
            continue
        words = sorted(clause.subtree, key=lambda t: t.i)
        if words[0].i < verb.i:  # The clause comes first: a quotation or an inversion.
            continue
        if any(t.dep_ == "mark" for t in clause.children):  # "that", "if", "whether"
            continue
        if words[0].lower_ in _WH_WORDS:  # "Check what changed."
            continue
        if not any(t.dep_ in _SUBJECTS for t in clause.children):  # "Make sure to close it."
            continue
        if clause.tag_ not in _FINITE_TAGS and not any(  # "You will see it running."
            t.dep_ in ("aux", "auxpass") and t.tag_ in _FINITE_TAGS for t in clause.children
        ):
            continue
        if verb.i + 1 < len(parsed) and parsed[verb.i + 1].text == ":":  # A label: "Note: ..."
            continue
        if any(t.lower_ == "that" for t in parsed[verb.i + 1 : words[0].i + 1]):  # A parser error
            continue
        name = "make sure" if make_sure else verb.text
        findings.append(_finding(sentence, "omitted-that", f'Write "that" after "{name}".'))
    return findings


_QUOTE_OPEN = {"“"}
_QUOTE_CLOSE = {"”"}


def unknown_words(sentence: Sentence, parsed: Doc, vocabulary: Vocabulary) -> list[Finding]:
    """vocabulary: use only words from the word list and the glossaries.

    A word passes if it is an allowed word or a form of one (as written, or
    its lemma), or a glossary term. Allowed phrases ("make sure") and
    glossary terms with more than one word ("pull request") pass as a whole.
    Numbers, punctuation, inline code, and quoted text (a name or a message
    that the document quotes) are not checked. One finding for each
    sentence, with each word one time.

    For glossary terms, a plural also passes if a simple singular form of it is
    in the glossary (see singulars). A glossary term with an uppercase letter
    (a name, such as "React") passes only with the same case, so that a common
    word ("react") does not pass because of a name.

    Known limits: the part of speech is not checked.
    A lemma error of the parser can make a word pass or fail. A single letter
    used as a label ("cause B") is reported; "A" passes because it is an article.
    """
    covered = _phrase_tokens(parsed, vocabulary.phrases)
    wordlist = vocabulary.wordlist
    words: dict[str, tuple[str, str]] = {}  # lowercase -> (as written, lemma), in order
    quoted = False
    for token in parsed:
        if token.text in _QUOTE_OPEN or token.text in _QUOTE_CLOSE or token.text == '"':
            quoted = token.text in _QUOTE_OPEN or (token.text == '"' and not quoted)
            continue
        if quoted or token.i in covered or not token.is_alpha:
            continue
        names = {token.lower_, token.lemma_.lower()}
        if names & wordlist.allowed or (names | singulars(token.lower_)) & vocabulary.words:
            continue
        if token.text in vocabulary.names or singulars(token.text) & vocabulary.names:
            continue
        words.setdefault(token.lower_, (token.text, token.lemma_.lower()))
    if not words:
        return []
    listed = []
    for lower, (text, lemma) in words.items():
        alternatives = wordlist.alternatives.get(lower) or wordlist.alternatives.get(lemma, [])
        use = f" (use {', '.join(alternatives)})" if alternatives else ""
        listed.append(f'"{text}"{use}')
    message = f"Not approved and not in a glossary: {', '.join(listed)}."
    return [_finding(sentence, "vocabulary", message)]


def unknown_words_help(glossary_target: str) -> str:
    """What to do with vocabulary findings. The hook writes it one time in a report."""
    return (
        "For [vocabulary]: replace each listed word with a word from the word list. If a word "
        f'is a technical term or a name, add it to {glossary_target} as "term | pos | category | note" '
        f"(the format and the categories are in {GENERAL_GLOSSARY})."
    )


def singulars(word: str) -> set[str]:
    """Possible singular forms of a plural noun, for glossary lookups only:
    "dependencies" -> "dependency", "statuses" -> "status", "replicas" -> "replica".

    The parser does not always give the singular lemma ("Restart the replicas
    one at a time." keeps "replicas"). A wrong guess ("class" -> "clas") does
    no harm, because it passes only if the glossary has that word. Approved
    words in the word list do not use these guesses ("news" -> "new" would pass).
    """
    if word.endswith("ies") and len(word) > 4:
        return {word[:-3] + "y"}
    if word.endswith("es") and len(word) > 3:
        return {word[:-2], word[:-1]}
    if word.endswith("s") and not word.endswith("ss") and len(word) > 2:
        return {word[:-1]}
    return set()


def _phrase_tokens(parsed: Doc, phrases: frozenset[tuple[str, ...]]) -> set[int]:
    """The indexes of the tokens that are part of a phrase.

    A lowercase phrase word matches a token as written (any case), its lemma,
    or a singular form. A phrase word with an uppercase letter ("GitHub")
    matches only the same text.
    """
    covered: set[int] = set()
    by_first: dict[str, list[tuple[str, ...]]] = {}
    for phrase in phrases:
        by_first.setdefault(phrase[0].lower(), []).append(phrase)
    for token in parsed:
        candidates = set(by_first.get(token.lower_, []) + by_first.get(token.lemma_.lower(), []))
        for phrase in candidates:
            end = token.i + len(phrase)
            if end <= len(parsed) and all(
                _phrase_word_matches(word, t) for word, t in zip(phrase, parsed[token.i : end])
            ):
                covered.update(range(token.i, end))
    return covered


def _phrase_word_matches(word: str, token: Token) -> bool:
    if word != word.lower():
        return word == token.text or word in singulars(token.text)
    return word in {token.lower_, token.lemma_.lower()} | singulars(token.lower_)


def glossary_problems(vocabulary: Vocabulary) -> list[Finding]:
    """A glossary line that is not correct. The excerpt is the problem, so that
    the hook reports each problem one time."""
    return [
        Finding(rule="list-format", severity=Severity.ERROR, message="Correct this line.", line=0, excerpt=p)
        for p in vocabulary.problems
    ]


def _verb_phrase(sentence: Sentence, parsed: Doc, verb: Token) -> str:
    """The text from the first auxiliary of the verb to the verb ("has been changed"),
    with inline code put back."""
    auxiliaries = [t.i for t in verb.children if t.dep_ in ("aux", "auxpass")]
    return unmask_fragment(sentence, parsed[min(auxiliaries + [verb.i]) : verb.i + 1].text)


def _finding(sentence: Sentence, rule: str, message: str) -> Finding:
    return Finding(
        rule=rule,
        severity=Severity.ERROR,
        message=message,
        line=sentence.line,
        excerpt=sentence.text,
    )


SENTENCE_RULES: list[Callable[[Sentence], list[Finding]]] = [
    semicolon,
    latin_abbreviation,
    contraction,
    gender_pronoun,
    british_spelling,
    sentence_length,
]

# Rules that check a block and all its sentences together.
BLOCK_RULES: list[Callable[[Block, list[Sentence]], list[Finding]]] = [
    paragraph_length,
]

# Rules that check a sentence with its grammar analysis (grammar.parse).
GRAMMAR_RULES: list[Callable[[Sentence, Doc], list[Finding]]] = [
    passive_voice,
    verb_tense,
    omitted_that,
]
