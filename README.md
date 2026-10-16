# speclint

speclint checks that Markdown documents use plain, simple English: short
sentences, the active voice, simple tenses, and a controlled vocabulary. It
runs as a Claude Code plugin. After Claude writes or edits a Markdown file,
speclint checks it and gives the findings to Claude, which fixes them.

## Install

speclint needs [uv](https://docs.astral.sh/uv/) and Python 3.12 or later.

```sh
git clone https://github.com/coderloganli/speclint.git
cd speclint
uv sync
```

This installs speclint, spaCy, and the spaCy model `en_core_web_sm`.

## Use

Check files from the command line:

```sh
uv run speclint check docs/guide.md
```

```
docs/guide.md:12: [passive-voice] error: Use the active voice: "was installed".
docs/guide.md:31: [latin-abbreviation] error: Do not use "e.g.". Write "for example".
```

Exit code 0 means no findings, 1 means findings, and 2 means a file could not
be read. Use `--format json` for one JSON object for each finding.

Use it with Claude Code:

```sh
claude --plugin-dir /path/to/speclint
```

After each Write or Edit of a `.md` or `.markdown` file, the hook checks the
file. Claude gets the findings and fixes them, or leaves a finding that is
wrong. In one session, each finding is reported one time.

## Rules

| Rule | What it checks |
|---|---|
| `sentence-length` | A maximum of 20 words in a procedure step (ordered list item, warning, caution), 25 in other sentences |
| `paragraph-length` | A maximum of 6 sentences in a paragraph |
| `passive-voice` | Use the active voice (`was installed`) |
| `perfect-tense` | No perfect tense (`has adjusted`) |
| `progressive-tense` | No progressive tense (`is running`) |
| `omitted-that` | Write "that" after verbs such as "make sure" |
| `semicolon` | No semicolons |
| `contraction` | No contractions (`isn't`) |
| `latin-abbreviation` | No Latin abbreviations (`e.g.`, `i.e.`, `etc.`) |
| `gendered-pronoun` | No gender-specific pronouns |
| `american-spelling` | American spelling (`colour` -> `color`) |
| `vocabulary` | Only words from the word list and the glossaries (see below) |
| `unclosed-code-fence` | An unclosed code fence (the text after it is not checked) |
| `list-format` | A line in the word list or a glossary that is not correct |

speclint does not check code: code blocks, inline code, HTML, and front matter
are skipped. For the word count, text in parentheses or quotes, a number with
its unit, and inline code each count as one word.

## Vocabulary

The `vocabulary` rule accepts a word only if it is in the word list or in a
glossary. It reports all other words, so that the writer uses a small set of
common words, and the same term for the same item.

### Word list

**speclint does not include a word list.** Write your own, or make one from a
source that you have the right to use. Without a word list, the `vocabulary`
rule does not run, and the other rules work as usual.

speclint uses the first of these files that exists:

1. the file that the environment variable `SPECLINT_WORDLIST` names
2. `~/.config/speclint/wordlist.txt`

Each line is `word | pos | status | forms | use instead`:

```
# word | pos | status | forms | use instead
remove     | v   | allowed | removes, removed, removed |
the        | art | allowed |                           |
make sure  | v   | allowed | makes sure, made sure     |
utilize    | v   | avoid   |                           | use
```

- `pos`: `n`, `v`, `adj`, `adv`, `pron`, `art`, `prep`, `conj`, `prefix`, or empty.
- `status`: `allowed` (the word can be used) or `avoid` (the report tells the
  writer to use the words in `use instead`).
- `forms`: other forms that are allowed. Regular forms (`removes`, `removed`)
  are also found from the base form.

Because all words that are not in the list are reported, a short list gives
many findings. The list must contain all the common words that your documents
use.

### Glossaries

A glossary gives the technical terms and names that a document can also use.
speclint reads two glossaries:

- the general software glossary in `src/speclint/data/software_glossary.txt`
  (about 400 terms, products, and standards, such as `repository`, `API`,
  `GitHub`, and `JSON`)
- the project glossary, `.speclint/glossary.txt`, in the directory of the
  checked file or in a parent directory

Each line is `term | pos | category | note`:

```
replica       | n | component | database replica
pull request  | n | component | request to merge changes
Kafka         | n | name      | message broker
retry         | v | operation | retry an operation
```

The category tells why the term is necessary: `name`, `component`, `concept`,
`device`, `unit`, `document`, `role` (nouns), or `operation` (verbs). A
lowercase term matches with any case. A term with an uppercase letter
(`GitHub`) matches only with the same case, so that a name such as `React`
does not let the common word "react" pass.

When the `vocabulary` rule reports a word, Claude replaces it, or adds it to
the project glossary if it is a technical term or a name.

## Files that the hook writes

| Path | Content | Override |
|---|---|---|
| `~/.speclint/hook-log.jsonl` | One record for each hook call: the input from Claude Code, the document, and the report | `SPECLINT_LOG` |
| `~/.speclint/state/<session>.json` | The findings that Claude already got in a session, so that each finding is reported one time | `SPECLINT_STATE` |

## Development

```sh
uv run pytest -q
```

## License

MIT. See `LICENSE`.

`src/speclint/data/british_spelling.tsv` is derived from the English Speller
Database (ESDB, https://github.com/en-wl/wordlist). See
`src/speclint/data/ESDB-COPYRIGHT.txt`.
