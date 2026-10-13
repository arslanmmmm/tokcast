from datetime import datetime

import pytest

from tokcast.ingest.sources import ClaudeCodeSource

from .conftest import FIXTURES

SOURCE = ClaudeCodeSource()
S1 = FIXTURES / "-Users-dev-myapp" / "s1.jsonl"
LEGACY = FIXTURES / "-Users-dev-legacy" / "old.jsonl"


@pytest.fixture(scope="module")
def s1():
    return SOURCE.parse_file(S1)


def by_id(parsed):
    return {r.request_id: r for r in parsed.requests}


def test_discover_finds_jsonl_files_in_project_folders():
    assert set(SOURCE.discover(FIXTURES)) == {S1, LEGACY}


def test_split_lines_are_merged_into_one_request(s1):
    # r1 is written as two lines (thinking + tool_use), r4 as two lines too.
    assert sorted(by_id(s1)) == ["r1", "r2", "r4"]


def test_usage_is_counted_once_not_summed_per_line(s1):
    r1 = by_id(s1)["r1"]
    assert (r1.input_tokens, r1.output_tokens) == (3, 120)
    assert (r1.cache_read_tokens, r1.cache_creation_tokens) == (1000, 500)
    assert r1.cache_creation_1h_tokens == 500
    assert r1.thinking_tokens == 80


def test_streaming_partial_counts_keep_the_final_value(s1):
    # r4's first line shows 10 output tokens (partial), the second shows 40 (final).
    assert by_id(s1)["r4"].output_tokens == 40


def test_tool_calls_are_collected_across_lines(s1):
    reqs = by_id(s1)
    assert reqs["r1"].tool_names == ["Read"]
    assert reqs["r4"].tool_names == ["Bash", "Bash"]
    assert reqs["r2"].tool_names == []


def test_synthetic_placeholder_messages_are_not_requests(s1):
    assert all(r.model != "<synthetic>" for r in s1.requests)


def test_requests_are_linked_to_their_turn(s1):
    reqs = by_id(s1)
    assert reqs["r1"].prompt_id == "p1"
    assert reqs["r2"].prompt_id == "p1"  # after a tool result: same turn
    assert reqs["r4"].prompt_id == "p2"  # parent chain passes through a synthetic line


def test_human_prompts_and_their_kinds(s1):
    kinds = {p.prompt_id: p.kind for p in s1.prompts}
    assert kinds == {"p1": "text", "p2": "bash-input"}  # the isMeta line is not a prompt


def test_metadata_fields(s1):
    r1 = by_id(s1)["r1"]
    assert (r1.model, r1.effort, r1.stop_reason) == ("claude-sonnet-5-5", "high", "tool_use")
    assert r1.ts == datetime(2026, 10, 1, 10, 0, 2)  # converted to naive UTC
    session = s1.sessions[0]
    assert (session.cwd, session.git_branch, session.version) == (
        "/Users/dev/myapp",
        "main",
        "2.1.295",
    )


def test_malformed_lines_are_reported_not_raised(s1):
    assert [e.line_no for e in s1.errors] == [8, 9]
    assert "invalid JSON" in s1.errors[0].error
    assert "expected a JSON object" in s1.errors[1].error
    assert s1.n_lines == 15


def test_legacy_format_without_turn_origin_or_prompt_id():
    parsed = SOURCE.parse_file(LEGACY)
    assert [p.prompt_id for p in parsed.prompts] == ["L1"]  # falls back to the line uuid
    reqs = by_id(parsed)
    # lr2's parent is a tool result without a promptId: the walk continues upward.
    assert reqs["lr1"].prompt_id == reqs["lr2"].prompt_id == "L1"
    # lr3's parent doesn't exist: falls back to the latest prompt in file order.
    assert reqs["lr3"].prompt_id == "L1"
    assert reqs["lr2"].cache_read_tokens == 0  # missing usage fields default to 0


def test_no_text_keeps_only_length_and_hash():
    with_text = SOURCE.parse_file(S1).prompts[0]
    without = SOURCE.parse_file(S1, store_text=False).prompts[0]
    assert without.text is None
    assert without.text_chars == len("fix the login bug in auth.py")
    assert without.text_sha256 == with_text.text_sha256


def test_valid_json_with_unexpected_shape_is_reported(tmp_path):
    path = tmp_path / "odd.jsonl"
    path.write_text('{"type":"user","turnOrigin":"human","uuid":"z","message":"oops"}\n')
    parsed = SOURCE.parse_file(path)
    assert parsed.prompts == []
    assert "unexpected structure" in parsed.errors[0].error


def test_empty_and_missing_files(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert SOURCE.parse_file(empty).errors == []
    missing = SOURCE.parse_file(tmp_path / "nope.jsonl")
    assert "cannot read file" in missing.errors[0].error
