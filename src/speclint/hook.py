"""Claude Code PostToolUse hook: check a Markdown file after Claude writes it.

Claude Code sends the tool call as JSON on stdin. When the hook exits with
code 2, Claude Code shows stderr to Claude, and Claude can fix the findings.

Each call is appended to a log file (JSON Lines), so that you can see what
speclint received and what it told Claude, and replay the calls in tests.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from speclint import vocabulary
from speclint.engine import check_text
from speclint.models import Finding
from speclint.rules import unknown_words_help

CLEAN = 0  # Nothing to report. Claude sees nothing.
HOOK_ERROR = 1  # The hook itself failed. Claude Code does not show it to Claude.
FEEDBACK = 2  # Findings. Claude Code shows stderr to Claude.

MARKDOWN_SUFFIXES = (".md", ".markdown")

LOG_ENV = "SPECLINT_LOG"
DEFAULT_LOG = Path.home() / ".speclint" / "hook-log.jsonl"
STATE_ENV = "SPECLINT_STATE"
DEFAULT_STATE_DIR = Path.home() / ".speclint" / "state"


def run(payload: str) -> tuple[int, str]:
    """Return the exit code and the text for stderr. Log the call."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        data = payload
        code, text, document = HOOK_ERROR, f"speclint: cannot read the hook input: {e!r}", ""
    else:
        code, text, document = _check(data)
    _log(data, document, code, text)
    return code, text


def _check(data: object) -> tuple[int, str, str]:
    """Return the exit code, the text for stderr, and the document that was checked."""
    try:
        file_path = data["tool_input"]["file_path"]
    except (KeyError, TypeError) as e:
        return HOOK_ERROR, f"speclint: cannot read the hook input: {e!r}", ""

    # A relative path is relative to the directory that Claude works in.
    # An absolute file_path replaces cwd in the join.
    path = Path(data.get("cwd", "."), file_path)
    if path.suffix.lower() not in MARKDOWN_SUFFIXES:
        return CLEAN, "", ""

    try:
        document = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return HOOK_ERROR, f"speclint: {path}: cannot read: {e}", ""

    findings = check_text(document, path)
    help_text = unknown_words_help(vocabulary.glossary_target(path))
    code, text = _reply(data.get("session_id"), file_path, findings, help_text)
    return code, text, document


def _reply(
    session_id: object, file_path: str, findings: list[Finding], help_text: str = ""
) -> tuple[int, str]:
    """Tell Claude only the findings that it did not get before in this session.

    Claude can send several edits in one response. It gets all their hook
    replies together, after the last edit, so a full list after each edit is
    out of date and repeats what Claude already knows.
    """
    reported = _load_reported(session_id, file_path)
    if reported is None:  # No session state: send the full list each time.
        return _full_report(file_path, findings, help_text)

    new = [f for f in findings if _key(f) not in reported]
    remaining = len(findings) - len(new)
    try:
        _save_reported(session_id, file_path, reported | {_key(f) for f in new})
    except OSError:
        return _full_report(file_path, findings, help_text)

    if new:
        return FEEDBACK, format_report(
            file_path, new, earlier=bool(reported), remaining=remaining, help_text=help_text
        )
    if remaining:
        return FEEDBACK, f"speclint: {_remaining(remaining)} in {file_path}."
    return CLEAN, ""


def _full_report(file_path: str, findings: list[Finding], help_text: str) -> tuple[int, str]:
    if not findings:
        return CLEAN, ""
    return FEEDBACK, format_report(file_path, findings, help_text=help_text)


def format_report(
    file_path: str,
    findings: list[Finding],
    earlier: bool = False,
    remaining: int = 0,
    help_text: str = "",
) -> str:
    """Write the findings as instructions for Claude.

    earlier: Claude got a report for this file before, so these findings are new.
    remaining: the number of findings from the earlier report that are not fixed.
    help_text: what to do with vocabulary findings; written one time, at the end,
    if there is a vocabulary finding.
    """
    problems = "problem" if len(findings) == 1 else "problems"
    new = "new " if earlier else ""
    lines = [
        f"speclint found {len(findings)} {new}{problems} in {file_path}.",
        "Fix each one. If a finding is wrong, leave the text as it is.",
        "",
    ]
    for f in findings:
        lines.append(f"- Line {f.line} [{f.rule}] {f.message}")
        lines.append(f"  Text: {f.excerpt}")
    if remaining:
        lines += ["", f"Also, {_remaining(remaining)}."]
    if help_text and any(f.rule == "vocabulary" for f in findings):
        lines += ["", help_text]
    return "\n".join(lines)


def _remaining(count: int) -> str:
    if count == 1:
        return "1 problem from the earlier report remains"
    return f"{count} problems from the earlier report remain"


# Session state: the findings that each file got in a report, for each session.
# A finding is the same if its rule and sentence are the same. The line can
# change when Claude edits text above it.


def _key(finding: Finding) -> str:
    return f"{finding.rule}\t{finding.excerpt}"


def _state_file(session_id: str) -> Path:
    directory = Path(os.environ.get(STATE_ENV) or DEFAULT_STATE_DIR)
    return directory / (re.sub(r"[^A-Za-z0-9_-]", "_", session_id) + ".json")


def _load_reported(session_id: object, file_path: str) -> set[str] | None:
    """Return the keys reported for the file in this session, or None if there is no state."""
    if not isinstance(session_id, str) or not session_id:
        return None
    path = _state_file(session_id)
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get(file_path, []))
    except (OSError, ValueError, AttributeError):
        return None


def _save_reported(session_id: str, file_path: str, keys: set[str]) -> None:
    path = _state_file(session_id)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    state[file_path] = sorted(keys)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def log_path() -> Path:
    return Path(os.environ.get(LOG_ENV) or DEFAULT_LOG)


def _log(data: object, document: str, code: int, text: str) -> None:
    """Append one record to the log. A failure here must not change the check."""
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "input": data,  # The JSON from Claude Code, or the raw text if it is not JSON
        "document": document,  # Empty if the file was not checked
        "exit_code": code,
        "output": text,  # The text that Claude sees when exit_code is 2
    }
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
