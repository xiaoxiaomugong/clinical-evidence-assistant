import math

import pytest

from eval.metrics_v2 import paired_group_bootstrap, score_retrieval


def test_graded_scores_use_complete_qrels_and_relevance_two_threshold():
    result = score_retrieval(["b", "c", "a"], {"a": 3, "b": 1, "c": 2, "d": 3}, k=3)
    assert result["recall_at_k"] == pytest.approx(2 / 3)
    assert result["mrr_at_k"] == 0.5
    expected_dcg = 1 + 3 / math.log2(3) + 7 / 2
    full_idcg = 7 + 7 / math.log2(3) + 3 / 2
    assert result["ndcg_at_k"] == pytest.approx(expected_dcg / full_idcg)
    assert result["ranking_comparable"] is True


def test_duplicates_consume_slots_without_refilling_top_k():
    result = score_retrieval(["a", "a", "b"], {"a": 3, "b": 3}, k=2)
    assert result["recall_at_k"] == 0.5
    assert result["ndcg_at_k"] == pytest.approx(1 / (1 + 1 / math.log2(3)))
    assert result["duplicate_count"] == 1
    assert result["slots"][1] == {"rank": 2, "doc_id": "a", "relevance": 3, "gain": 0, "status": "duplicate"}


def test_completion_uses_reachable_denominator_without_inflating_recall():
    qrels = {str(number): 2 for number in range(12)}
    result = score_retrieval([str(number) for number in range(12)], qrels)
    assert result["recall_at_k"] == pytest.approx(8 / 12)
    assert result["recall_completion_at_k"] == 1
    assert result["reachable_relevant"] == 8
    assert result["relevant_hits"] == 8
    assert result["returned_count"] == 8


@pytest.mark.parametrize("qrels", [{}, {"a": 0}, {"a": 1}])
def test_no_relevant_qrels_yield_na(qrels):
    result = score_retrieval([], qrels)
    assert all(result[key] is None for key in ("recall_at_k", "recall_completion_at_k", "mrr_at_k", "ndcg_at_k"))
    assert result["ranking_comparable"] is False
    assert result["score_status"] == "no_relevant_qrels"


def test_judged_misses_and_empty_retrieval_are_zero_not_na():
    for ranked in ([], ["b"]):
        result = score_retrieval(ranked, {"a": 3, "b": 0})
        assert all(result[key] == 0 for key in ("recall_at_k", "recall_completion_at_k", "mrr_at_k", "ndcg_at_k"))


def test_unjudged_is_explicit_and_blocks_ranking_conclusions():
    result = score_retrieval(["unknown", "a"], {"a": 3})
    assert result["unjudged_doc_ids"] == ["unknown"]
    assert result["slots"][0]["status"] == "unjudged"
    assert result["slots"][0]["gain"] is None
    assert result["ranking_comparable"] is False
    assert result["score_status"] == "unjudged_candidates"
    assert all(result[key] is None for key in ("recall_at_k", "recall_completion_at_k", "mrr_at_k", "ndcg_at_k"))


def test_mrr_is_truncated_to_requested_budget():
    result = score_retrieval(["miss"] * 8 + ["hit"], {"miss": 0, "hit": 3})
    assert result["mrr_at_k"] == 0
    assert result["relevant_hits"] == 0


def test_mrr_remains_at_eight_when_retrieval_budget_is_larger():
    result = score_retrieval(["miss"] * 8 + ["hit"], {"miss": 0, "hit": 3}, k=40)
    assert result["recall_at_k"] == 1
    assert result["mrr_at_k"] == 0
    assert result["mrr_k"] == 8


@pytest.mark.parametrize("qrels,k", [({"a": 4}, 8), ({"a": -1}, 8), ({"a": 2.5}, 8), ({"a": True}, 8), ({"a": 2}, 0), ({"a": 2}, True)])
def test_invalid_grades_and_budgets_are_rejected(qrels, k):
    with pytest.raises(ValueError):
        score_retrieval(["a"], qrels, k=k)


def test_group_bootstrap_preserves_question_macro_with_unequal_group_sizes():
    result = paired_group_bootstrap({"g1": [0, 0, 0], "g2": [1]}, {"g1": [1, 1, 1], "g2": [0]}, seed=17, n_bootstrap=1000)
    assert result["n_groups"] == 2
    assert result["n_questions"] == 4
    assert result["mean_difference"] == 0.5
    assert result["ci_low"] == -1
    assert result["ci_high"] == 1
    assert result == paired_group_bootstrap({"g1": [0, 0, 0], "g2": [1]}, {"g1": [1, 1, 1], "g2": [0]}, seed=17, n_bootstrap=1000)


def test_group_pairing_prevents_independent_arm_resampling():
    result = paired_group_bootstrap({"g1": [0.1, 0.5], "g2": [0.7]}, {"g1": [0.2, 0.6], "g2": [0.8]}, seed=3, n_bootstrap=100)
    assert result["mean_difference"] == pytest.approx(0.1)
    assert result["ci_low"] == pytest.approx(0.1)
    assert result["ci_high"] == pytest.approx(0.1)


def test_empty_group_bootstrap_is_na_and_unpaired_groups_are_rejected():
    result = paired_group_bootstrap({}, {})
    assert result["mean_difference"] is None
    assert result["ci_low"] is None
    assert result["ci_high"] is None
    with pytest.raises(ValueError, match="same groups"):
        paired_group_bootstrap({"a": [1]}, {"b": [1]})
    with pytest.raises(ValueError, match="paired observations"):
        paired_group_bootstrap({"a": [1, 2]}, {"a": [1]})


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_bootstrap_rejects_missing_or_nonfinite_scores(value):
    with pytest.raises(ValueError, match="finite numeric"):
        paired_group_bootstrap({"a": [value]}, {"a": [1]})
