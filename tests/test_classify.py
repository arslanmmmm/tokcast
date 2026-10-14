import pytest

from tokcast.features import TASK_TYPES, classify


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("fix the login bug in auth.py", "bugfix"),
        ("KeyError in parser.py when the line is empty", "bugfix"),
        ("fix the failing tests", "bugfix"),  # 2 bug words beat 1 test word
        ("add unit tests for the error handler", "tests"),  # 2 test words beat 1 bug word
        ("increase coverage of the cli", "tests"),
        ("refactor the auth module to use JWT", "refactor"),
        ("rename user_id to account_id everywhere", "refactor"),
        ("update the README with install steps", "docs"),
        ("explain how the cache works", "explain"),
        ("whats in step 4?", "explain"),
        ("how to delete a request", "explain"),
        ("i dont understand this error message", "bugfix"),  # 1-1 tie: the earlier rule wins
        ("build a new endpoint for pagination", "feature"),
        ("implement retry support", "feature"),
        ("go to milestone 4", "followup"),
        ("thanks!", "followup"),
        ("hello there", "other"),
        ("", "other"),
    ],
)
def test_task_types(prompt, expected):
    assert classify(prompt).task_type == expected


def test_shell_commands_come_from_the_prompt_kind():
    assert classify("<bash-input>ls</bash-input>", "bash-input").task_type == "shell"


def test_matched_words_explain_the_decision():
    result = classify("Fix the BUG, then fix it again")
    assert result.matched == ("fix", "bug")  # lowercased, each word once


def test_missing_text_is_other():
    assert classify(None).task_type == "other"
    assert {classify(t).task_type for t in ["fix", "docs", "go"]} <= set(TASK_TYPES)
