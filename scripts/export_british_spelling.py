"""Export British-only spellings and their American spellings from ESDB.

ESDB (English Speller Database, https://github.com/en-wl/wordlist) marks each
spelling with a SPELLING code (A: American, B and Z: British, _: all) and a
VARIANT-LEVEL (0: non-variant ... 9: invalid). Build its database first:

    git clone https://github.com/en-wl/wordlist.git esdb && make -C esdb

Then run:

    python scripts/export_british_spelling.py esdb/scowl.db src/speclint/data/british_spelling.tsv

A word is exported if it is a standard British spelling (B or Z, level <= 1)
of a common word (size <= 80), and it is not a standard American spelling
(A or _, level <= 1). Its American spellings are the standard American words
in the same group with the same part of speech, which includes the same
inflection ("behaviours" -> "behaviors"). Words with no American spelling
are not exported.

Output: one line for each word, "british<TAB>american[,american...]",
in lowercase and sorted.
"""

import sqlite3
import sys

QUERY = """
with sized as (
  select group_id, pos, min(size) as size from scowl_data group by group_id, pos
),
british as (
  select distinct w.word, w.group_id, w.pos
    from words_w_variant_info w join sized s using (group_id, pos)
   where w.spelling in ('B', 'Z') and w.variant_level <= 1 and s.size <= 80
),
american as (
  select distinct word, group_id, pos
    from words_w_variant_info
   where spelling in ('A', '_') and variant_level <= 1
)
select b.word, a.word
  from british b join american a on a.group_id = b.group_id and a.pos = b.pos
 where b.word not in (select word from american)
"""


def main(db_path: str, out_path: str) -> None:
    pairs: dict[str, set[str]] = {}
    for british, american in sqlite3.connect(db_path).execute(QUERY):
        pairs.setdefault(british.lower(), set()).add(american.lower())
    with open(out_path, "w", encoding="utf-8") as f:
        for british in sorted(pairs):
            f.write(f"{british}\t{','.join(sorted(pairs[british]))}\n")
    print(f"{len(pairs)} words written to {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
