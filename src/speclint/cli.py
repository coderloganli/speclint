"""Command-line entry point."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from speclint import hook, vocabulary, wordlist
from speclint.engine import check_text
from speclint.rules import unknown_words_help


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speclint")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check Markdown files")
    check.add_argument("paths", nargs="+", type=Path)
    check.add_argument("--format", choices=["text", "json"], default="text")
    sub.add_parser("hook", help="run as a Claude Code PostToolUse hook (reads JSON on stdin)")
    args = parser.parse_args(argv)

    if args.command == "hook":
        code, text = hook.run(sys.stdin.read())
        if text:
            print(text, file=sys.stderr)
        return code

    if wordlist.path() is None:
        print(
            "speclint: no word list, so the vocabulary check is off. Put one in "
            f"~/.config/speclint/wordlist.txt or name it with {wordlist.WORDLIST_ENV}.",
            file=sys.stderr,
        )
    found = False
    failed = False
    help_targets: list[str] = []  # project glossaries, for the vocabulary help
    for path in args.paths:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"speclint: {path}: cannot read: {e}", file=sys.stderr)
            failed = True
            continue
        findings = check_text(source, path)
        found = found or bool(findings)
        target = vocabulary.glossary_target(path)
        if any(f.rule == "vocabulary" for f in findings) and target not in help_targets:
            help_targets.append(target)
        for f in findings:
            if args.format == "json":
                print(json.dumps({"path": str(path), **asdict(f)}))
            else:
                print(f"{path}:{f.line}: [{f.rule}] {f.severity}: {f.message}")
    if args.format == "text":
        for target in help_targets:
            print(unknown_words_help(target))
    # 2: a file could not be read. 1: findings. 0: clean.
    if failed:
        return 2
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
