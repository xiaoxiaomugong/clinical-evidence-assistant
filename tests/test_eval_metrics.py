from eval.metrics import ndcg_at_k, recall_at_k


def test_recall_uses_all_labeled_relevant_sources_as_denominator():
    assert recall_at_k([2, 0, 0], 3, total_relevant=2) == 0.5


def test_ndcg_with_explicit_qrels_never_exceeds_one():
    value = ndcg_at_k([2, 0, 2, 0], 4, total_relevant=2)

    assert 0.0 <= value <= 1.0
