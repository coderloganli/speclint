import pytest

from speclint.wordcount import count_words


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        # One example for each counting rule
        pytest.param("Make sure that the build passes (the CI badge is green).", 7, id="parentheses"),
        pytest.param("Run the tests again (3).", 5, id="number in parentheses"),
        pytest.param("Retry steps 4 thru 7 a maximum of five times.", 10, id="numbers"),
        pytest.param("The cluster has thirty-two nodes.", 5, id="hyphenated number"),
        pytest.param("Make sure that the CPU temperature is below 80 °C.", 9, id="unit °C"),
        pytest.param("The server weighs 12 kg.", 4, id="unit kg"),
        pytest.param("The backup job runs each day at 2 a.m.", 8, id="a.m."),
        pytest.param("For remote login, use the SSH key.", 7, id="abbreviation"),
        pytest.param("Restart node db-03a.", 3, id="identifier"),
        pytest.param("Click the “Create Repository” button to start the setup.", 8, id="curly quotes"),
        pytest.param("Use a read-only token for the dry-run job.", 8, id="hyphenated words"),
        # Common in software documents
        pytest.param('Touch the "Service Overview" arrow.', 4, id="straight quotes"),
        pytest.param("Edit codeph0x now.", 3, id="masked code"),
        pytest.param("Cancel it — the job is idempotent.", 6, id="dash is not a word"),
        pytest.param("Set the timeout to 30 s.", 5, id="unit s"),
        pytest.param("Normal is 5–15 MB/s.", 3, id="range with unit"),
        pytest.param("Checkout p99 < 800ms", 3, id="comparison sign"),
        pytest.param("", 0, id="empty"),
    ],
)
def test_count_words(sentence, expected):
    assert count_words(sentence) == expected
