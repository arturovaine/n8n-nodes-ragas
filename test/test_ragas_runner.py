"""Offline unit tests for the pure helpers in ragas_runner.

These deliberately avoid importing ragas or any provider package (those imports
live inside ``main``), so the suite runs without API keys or heavy dependencies.
"""
import importlib.util
import os

HERE = os.path.dirname(__file__)
RUNNER_PATH = os.path.join(HERE, "..", "nodes", "RagasEvaluate", "ragas_runner.py")

_spec = importlib.util.spec_from_file_location("ragas_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def test_normalize_contexts_list_passthrough():
    assert runner.normalize_contexts(["a", "b"]) == ["a", "b"]


def test_normalize_contexts_none_is_empty():
    assert runner.normalize_contexts(None) == []


def test_normalize_contexts_string_without_delimiter():
    assert runner.normalize_contexts("a single context") == ["a single context"]


def test_normalize_contexts_string_with_delimiter():
    assert runner.normalize_contexts("a||b|| c ", "||") == ["a", "b", "c"]


def test_normalize_contexts_coerces_non_strings():
    assert runner.normalize_contexts([1, 2]) == ["1", "2"]


def test_find_missing_references_ignored_when_not_needed():
    samples = [{"reference": None}, {"reference": ""}]
    assert runner.find_missing_references(samples, ["faithfulness"]) == []


def test_find_missing_references_detects_blanks():
    samples = [{"reference": "gt"}, {"reference": ""}, {"reference": None}, {}]
    assert runner.find_missing_references(samples, ["context_recall"]) == [1, 2, 3]


def test_build_rows_maps_ragas_keys():
    samples = [{"question": "q", "answer": "a", "contexts": ["c1", "c2"], "reference": "r"}]
    rows = runner.build_rows(samples)
    assert rows[0]["user_input"] == "q"
    assert rows[0]["response"] == "a"
    assert rows[0]["retrieved_contexts"] == ["c1", "c2"]
    assert rows[0]["reference"] == "r"


def test_build_rows_omits_blank_reference():
    samples = [{"question": "q", "answer": "a", "contexts": "c", "reference": ""}]
    rows = runner.build_rows(samples)
    assert "reference" not in rows[0]


def test_build_rows_handles_missing_fields():
    rows = runner.build_rows([{}])
    assert rows[0]["user_input"] == ""
    assert rows[0]["response"] == ""
    assert rows[0]["retrieved_contexts"] == []
