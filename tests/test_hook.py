import io
import json
from pathlib import Path

import pytest

from speclint import hook
from speclint.cli import main
from speclint.models import Finding, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def payload(file_path: str, cwd: str = "/", session_id: str | None = None) -> str:
    """Hook input in the shape that Claude Code sends for a Write tool call."""
    data = {
        "hook_event_name": "PostToolUse",
        "cwd": cwd,
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": "..."},
    }
    if session_id is not None:
        data["session_id"] = session_id
    return json.dumps(data)


def test_findings_go_to_claude():
    path = str(FIXTURES / "deployment-guide.md")
    code, text = hook.run(payload(path))
    assert code == hook.FEEDBACK
    assert text == (
        f"speclint found 7 problems in {path}.\n"
        "Fix each one. If a finding is wrong, leave the text as it is.\n"
        "\n"
        '- Line 21 [passive-voice] Use the active voice: "is not required".\n'
        "  Text: Write access is not required.\n"
        '- Line 31 [latin-abbreviation] Do not use "e.g.". Write "for example".\n'
        "  Text: Request timeout, e.g. for slow clients.\n"
        "- Line 49 [semicolon] Do not use a semicolon. Write two sentences.\n"
        "  Text: The rollout should be complete in about 2 minutes; if it isn't, check the pod logs.\n"
        '- Line 49 [contraction] Do not use the contraction "isn\'t". Write the full words.\n'
        "  Text: The rollout should be complete in about 2 minutes; if it isn't, check the pod logs.\n"
        '- Line 66 [passive-voice] Use the active voice: "is restored".\n'
        "  Text: The previous version is restored automatically.\n"
        '- Line 72 [passive-voice] Use the active voice: "are rarely needed".\n'
        "  Text: These options are rarely needed.\n"
        '- Line 79 [passive-voice] Use the active voice: "are handled".\n'
        "  Text: Production deployments are handled by the release team."
    )


def test_clean_file(tmp_path):
    (tmp_path / "clean.md").write_text("Open the file.\n", encoding="utf-8")
    assert hook.run(payload(str(tmp_path / "clean.md"))) == (hook.CLEAN, "")


def test_not_markdown(tmp_path):
    (tmp_path / "main.py").write_text("x = 1; y = 2\n", encoding="utf-8")
    assert hook.run(payload(str(tmp_path / "main.py"))) == (hook.CLEAN, "")


def test_relative_path(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("Do A; do B.\n", encoding="utf-8")
    code, text = hook.run(payload("docs/a.md", cwd=str(tmp_path)))
    assert code == hook.FEEDBACK
    assert text.startswith("speclint found 1 problem in docs/a.md.\n")


def test_bad_json():
    code, text = hook.run("not json")
    assert code == hook.HOOK_ERROR
    assert text.startswith("speclint: cannot read the hook input")


def test_missing_file(tmp_path):
    code, text = hook.run(payload(str(tmp_path / "missing.md")))
    assert code == hook.HOOK_ERROR
    assert "cannot read" in text


def test_cli_hook(monkeypatch, capsys):
    path = str(FIXTURES / "deployment-guide.md")
    monkeypatch.setattr("sys.stdin", io.StringIO(payload(path)))
    assert main(["hook"]) == hook.FEEDBACK
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("speclint found 7 problems")


def read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_log_record(hook_log):
    path = str(FIXTURES / "deployment-guide.md")
    code, text = hook.run(payload(path))
    [record] = read_log(hook_log)
    assert record["input"] == json.loads(payload(path))
    assert record["document"] == (FIXTURES / "deployment-guide.md").read_text(encoding="utf-8")
    assert record["exit_code"] == code == hook.FEEDBACK
    assert record["output"] == text


def test_log_appends_one_record_for_each_call(hook_log, tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    hook.run(payload(str(FIXTURES / "deployment-guide.md")))
    hook.run(payload(str(tmp_path / "main.py")))
    hook.run("not json")
    records = read_log(hook_log)
    assert [(r["exit_code"], r["document"] != "") for r in records] == [
        (hook.FEEDBACK, True),
        (hook.CLEAN, False),  # not Markdown: logged, but not checked
        (hook.HOOK_ERROR, False),
    ]
    assert records[2]["input"] == "not json"  # raw text when the input is not JSON


def test_log_failure_does_not_change_result(monkeypatch, tmp_path):
    # A directory in place of the log file: the log write fails.
    monkeypatch.setenv(hook.LOG_ENV, str(tmp_path))
    path = str(FIXTURES / "deployment-guide.md")
    code, text = hook.run(payload(path))
    assert code == hook.FEEDBACK
    assert text.startswith("speclint found 7 problems")


# Replay: run each recorded call again and compare with the recorded result.

RECORDS = FIXTURES / "hook-records"


def replay(record: dict, tmp_path: Path) -> tuple[int, str]:
    """Run the hook on the recorded document and input. Return the result
    with the original file path, so that it compares with the record."""
    original = record["input"]["tool_input"]["file_path"]
    copy = tmp_path / Path(original).name
    copy.write_text(record["document"], encoding="utf-8")
    data = json.loads(json.dumps(record["input"]))
    data["tool_input"]["file_path"] = str(copy)
    code, text = hook.run(json.dumps(data))
    return code, text.replace(str(copy), original)


def test_replay_round_trip(hook_log, tmp_path):
    """A record that the hook writes replays to the same result."""
    hook.run(payload(str(FIXTURES / "deployment-guide.md")))
    [record] = read_log(hook_log)
    assert replay(record, tmp_path) == (record["exit_code"], record["output"])


def sessions() -> dict[str, list[Path]]:
    """Group the recorded calls by session, in the order of their file names."""
    groups: dict[str, list[Path]] = {}
    for f in sorted(RECORDS.glob("*.json")):
        session = json.loads(f.read_text(encoding="utf-8"))["input"].get("session_id", f.stem)
        groups.setdefault(session, []).append(f)
    return groups


@pytest.mark.parametrize("record_files", list(sessions().values()), ids=lambda fs: fs[0].stem)
def test_replay_recorded(record_files, tmp_path):
    """Replay the calls of one session in order, so that the session state builds up."""
    for f in record_files:
        record = json.loads(f.read_text(encoding="utf-8"))
        assert replay(record, tmp_path) == (record["exit_code"], record["output"]), f.name


# Only new findings: in one session, each finding goes to Claude one time.

SESSION = "session-1"


def test_session_reports_each_finding_once(tmp_path):
    doc = tmp_path / "a.md"
    run = lambda: hook.run(payload(str(doc), session_id=SESSION))  # noqa: E731

    doc.write_text("Do A; do B.\n\nUse e.g. this.\n\nRun X; run Y.\n", encoding="utf-8")
    code, text = run()
    assert code == hook.FEEDBACK
    assert text.startswith(f"speclint found 3 problems in {doc}.\n")

    doc.write_text("Do A. Do B.\n\nUse e.g. this.\n\nRun X; run Y.\n", encoding="utf-8")
    assert run() == (hook.FEEDBACK, f"speclint: 2 problems from the earlier report remain in {doc}.")

    doc.write_text("Do A. Do B.\n\nUse e.g. this.\n\nRun X; run Y.\n\nSee P vs Q.\n", encoding="utf-8")
    code, text = run()
    assert code == hook.FEEDBACK
    assert text == (
        f"speclint found 1 new problem in {doc}.\n"
        "Fix each one. If a finding is wrong, leave the text as it is.\n"
        "\n"
        '- Line 7 [latin-abbreviation] Do not use "vs". Write "versus".\n'
        "  Text: See P vs Q.\n"
        "\n"
        "Also, 2 problems from the earlier report remain."
    )

    doc.write_text("Do A. Do B.\n\nUse this.\n\nRun X. Run Y.\n\nSee P or Q.\n", encoding="utf-8")
    assert run() == (hook.CLEAN, "")


def test_session_files_are_separate(tmp_path):
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text("Do A; do B.\n", encoding="utf-8")
    hook.run(payload(str(tmp_path / "a.md"), session_id=SESSION))
    code, text = hook.run(payload(str(tmp_path / "b.md"), session_id=SESSION))
    assert text.startswith("speclint found 1 problem in ")


def test_new_session_starts_again(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("Do A; do B.\n", encoding="utf-8")
    hook.run(payload(str(doc), session_id="session-1"))
    code, text = hook.run(payload(str(doc), session_id="session-2"))
    assert text.startswith("speclint found 1 problem in ")


def test_no_session_sends_full_list_each_time(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("Do A; do B.\n", encoding="utf-8")
    first = hook.run(payload(str(doc)))
    assert hook.run(payload(str(doc))) == first
    assert first[1].startswith("speclint found 1 problem in ")


def test_state_write_failure_sends_full_list(tmp_path, monkeypatch):
    # A file in place of the state directory: the state write fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv(hook.STATE_ENV, str(blocker / "state"))
    doc = tmp_path / "a.md"
    doc.write_text("Do A; do B.\n", encoding="utf-8")
    first = hook.run(payload(str(doc), session_id=SESSION))
    assert hook.run(payload(str(doc), session_id=SESSION)) == first
    assert first[1].startswith("speclint found 1 problem in ")


def test_moved_line_is_the_same_finding(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("Do A; do B.\n", encoding="utf-8")
    hook.run(payload(str(doc), session_id=SESSION))
    doc.write_text("# Title\n\nIntro text.\n\nDo A; do B.\n", encoding="utf-8")  # now on line 5
    assert hook.run(payload(str(doc), session_id=SESSION)) == (
        hook.FEEDBACK,
        f"speclint: 1 problem from the earlier report remains in {doc}.",
    )


# Rule 1.1: the help text is written one time, after the findings.


def test_report_has_rule_1_1_help_one_time():
    findings = [
        Finding("vocabulary", Severity.ERROR, 'Not approved and not in a glossary: "replica".', 3, "Clean the replica."),
        Finding("semicolon", Severity.ERROR, "Do not use a semicolon. Write two sentences.", 5, "A; b."),
        Finding("vocabulary", Severity.ERROR, 'Not approved and not in a glossary: "lag".', 7, "The lag."),
    ]
    report = hook.format_report("a.md", findings, help_text="HELP")
    assert report.count("HELP") == 1
    assert report.endswith("\n\nHELP")


def test_report_without_rule_1_1_has_no_help():
    findings = [Finding("semicolon", Severity.ERROR, "Do not use a semicolon. Write two sentences.", 5, "A; b.")]
    assert "HELP" not in hook.format_report("a.md", findings, help_text="HELP")
