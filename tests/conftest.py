import pytest

from speclint import hook, wordlist


@pytest.fixture(autouse=True)
def hook_log(tmp_path, monkeypatch):
    """Send the hook log of each test to a temporary file, not to the real log."""
    path = tmp_path / "hook-log.jsonl"
    monkeypatch.setenv(hook.LOG_ENV, str(path))
    return path


@pytest.fixture(autouse=True)
def hook_state(tmp_path, monkeypatch):
    """Keep the session state of each test in a temporary directory."""
    path = tmp_path / "state"
    monkeypatch.setenv(hook.STATE_ENV, str(path))
    return path


@pytest.fixture(autouse=True)
def no_wordlist(tmp_path, monkeypatch):
    """Tests do not use the word list of the person who runs them
    (~/.config/speclint/wordlist.txt). The vocabulary check is off unless a
    test gives a word list."""
    monkeypatch.setenv(wordlist.WORDLIST_ENV, str(tmp_path / "no-wordlist.txt"))
