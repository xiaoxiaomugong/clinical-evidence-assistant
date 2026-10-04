"""Synthetic engineering cases; these are not independently judged clinical data."""

import copy
import hashlib
import importlib
import json

import pytest


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build(*args, **kwargs):
    try:
        scorer = importlib.import_module("eval.independent.scoring")
    except ModuleNotFoundError:
        pytest.fail("independent build_report is not implemented")
    return scorer.build_report(*args, **kwargs)


def fixture(behaviors=("answer",), repeats=1):
    sources = [{"id": "s%d" % i, "text": "SYNTHETIC text %d" % i,
                "locator": {"section": "synthetic", "paragraph": i}} for i in range(8)]
    questions = []
    qrels = []
    for i, behavior in enumerate(behaviors):
        qid = "q%d" % i
        questions.append({"id": qid, "question_group_id": "g%d" % i,
                          "split": "synthetic", "question": "SYNTHETIC question %d" % i,
                          "topic": "engineering", "language": "en", "scenario": "synthetic",
                          "risk": "synthetic", "as_of_date": "2026-10-03",
                          "corpus_profile": "C0", "corpus_manifest_hash": "a" * 64,
                          "expected_behavior": behavior, "expected_reason": "synthetic",
                          "allowed_refusal_codes": ["INSUFFICIENT_EVIDENCE"],
                          "forbidden_conclusions": [], "annotation_status": "synthetic",
                          "applicability": {"retrieval": behavior != "refuse",
                                            "answer_quality": behavior != "refuse",
                                            "refusal": behavior == "refuse"}})
        if behavior != "refuse":
            for j in range(8):
                qrels.append({"question_id": qid, "source_id": "s%d" % j,
                              "grade": 3 if j < 2 else 0, "study_family_id": "f%d" % j,
                              "evidence_role": "synthetic", "locator": sources[j]["locator"],
                              "rationale": "synthetic judgment"})
    bundle = {"schema_version": "independent-eval-v1", "asset_kind": "synthetic_engineering",
              "dataset_id": "synthetic-fixture", "protocol": {"version": "synthetic-v1",
              "rubric_version": "synthetic-r1"}, "corpus": {"profile": "C0",
              "manifest_hash": "a" * 64}, "questions": questions,
              "sources": sources, "qrels": qrels,
              "key_points": [{"id": q["id"] + "-point", "question_id": q["id"],
                              "text": "SYNTHETIC reference point", "necessity": "required", "weight": 1,
                              "support_source_ids": ["s0"], "scope": "synthetic"}
                             for q in questions if q["expected_behavior"] != "refuse"]}
    rows = []
    for q in questions:
        for repeat in range(1, repeats + 1):
            output = {"behavior": q["expected_behavior"], "answer": "SYNTHETIC answer",
                      "refusal_code": "INSUFFICIENT_EVIDENCE" if q["expected_behavior"] == "refuse" else None}
            rows.append({"question_id": q["id"], "repeat": repeat, "status": "success",
                         "output": output, "output_hash": digest(output),
                         "ranked_source_ids": [s["id"] for s in sources], "ranking_complete_k": 8,
                         "evidence": [{"source_id": s["id"], "text": s["text"],
                                       "locator": s["locator"]} for s in sources]})
    run = {"schema_version": "independent-run-v1", "run_id": "candidate",
           "asset_kind": bundle["asset_kind"], "dataset_hash": digest(bundle),
           "protocol_hash": digest(bundle["protocol"]), "rubric_version": "synthetic-r1",
           "corpus_manifest_hash": "a" * 64, "system": {"source_hash": "candidate-source"},
           "expected_count": len(questions) * repeats, "repeats": repeats, "rows": rows}
    return bundle, run


def annotations(run, updates=None):
    result = {"dataset_hash": run["dataset_hash"], "protocol_hash": run["protocol_hash"],
              "final": [], "missing": [], "conflicts": [], "errors": []}
    for row in run["rows"]:
        if row["status"] != "success":
            continue
        labels = {"behavior": row["output"]["behavior"], "support_rate": 1.0,
                  "key_point_coverage": 1.0, "numeric_correctness": 1.0,
                  "refusal_quality": 1.0, "serious_error": False,
                  "error_types": [], "rationale": "SYNTHETIC imported judgment"}
        if updates:
            labels.update(updates.get((row["question_id"], row["repeat"]), {}))
        result["final"].append({"question_id": row["question_id"], "repeat": row["repeat"],
                                "run_id": run["run_id"], "output_hash": row["output_hash"],
                                "run_hash": digest(run), "rubric_version": run["rubric_version"],
                                "source_ids": [e["source_id"] for e in row["evidence"]],
                                "evidence_locations": [{"source_id": e["source_id"], "locator": e["locator"]}
                                                       for e in row["evidence"]],
                                "status": "complete", "annotation_origin": "agreed",
                                "reviewer_ids": ["reviewer-A", "reviewer-B"], "labels": labels})
    return result


def rebind(bundle, run):
    run["dataset_hash"] = digest(bundle)
    run["protocol_hash"] = digest(bundle["protocol"])


def test_mixed_behaviors_have_declared_denominators_and_no_clinical_pass():
    bundle, run = fixture(("answer", "qualified_answer", "refuse"))
    report = build(bundle, run, annotations(run))
    assert report["metrics"]["retrieval"]["recall_at_8"]["expected_questions"] == 2
    assert report["metrics"]["human"]["support_rate"]["expected_questions"] == 2
    assert report["metrics"]["human"]["refusal_quality"]["expected_questions"] == 1
    assert report["expected_behavior_counts"] == {"answer": 1, "qualified_answer": 1, "refuse": 1}
    assert report["metrics"]["human"]["behavior_accuracy"]["value"] == 1
    assert report["scope"] == "synthetic_engineering"
    assert report["pilot_status"] == "not_executed"
    assert report["clinical_quality_passed"] is None


def test_missing_qrels_unjudged_sources_and_top40_remain_na():
    bundle, run = fixture(("answer", "answer"))
    bundle["qrels"] = [r for r in bundle["qrels"] if r["question_id"] != "q0"]
    bundle["qrels"] = [r for r in bundle["qrels"] if not (r["question_id"] == "q1" and r["source_id"] == "s7")]
    rebind(bundle, run)
    report = build(bundle, run, annotations(run))
    retrieval = report["metrics"]["retrieval"]
    assert retrieval["recall_at_8"]["value"] is None
    assert retrieval["recall_at_8"]["valid_questions"] == 0
    assert retrieval["recall_at_40"]["value"] is None
    assert report["questions"]["q0"]["retrieval"][0]["at_8"]["score_status"] == "missing_qrels"
    assert report["questions"]["q1"]["retrieval"][0]["at_8"]["score_status"] == "unjudged_candidates"


def test_run_failure_and_wrong_refusal_cannot_improve_human_score_by_deletion():
    bundle, run = fixture(("answer", "answer", "answer"))
    run["rows"][1] = {"question_id": "q1", "repeat": 1, "status": "error", "error_code": "ENGINE_ERROR"}
    run["rows"][2]["output"]["behavior"] = "refuse"
    run["rows"][2]["output"]["refusal_code"] = "INSUFFICIENT_EVIDENCE"
    run["rows"][2]["output_hash"] = digest(run["rows"][2]["output"])
    report = build(bundle, run, annotations(run, {("q2", 1): {"support_rate": 0.0}}))
    assert report["counts"]["expected_generations"] == 3
    assert report["counts"]["executed_generations"] == 3
    assert report["counts"]["run_errors"] == 1
    assert report["metrics"]["human"]["support_rate"]["value"] is None
    assert report["metrics"]["human"]["support_rate"]["observed_mean"] == 0.5
    assert report["metrics"]["human"]["behavior_accuracy"]["value"] is None
    assert report["quality_decision"] != "ready_for_review"


def test_missing_review_conflict_unjudgeable_and_skip_are_visible():
    bundle, run = fixture(("answer", "answer", "answer", "answer"))
    run["rows"][3] = {"question_id": "q3", "repeat": 1, "status": "skipped", "skip_reason": "NO_FIXTURE"}
    ann = annotations(run)
    ann["final"] = ann["final"][2:]
    ann["final"][0]["labels"]["behavior"] = "unjudgeable"
    ann["missing"] = [{"question_id": "q0", "reason": "second_reviewer_missing"}]
    ann["conflicts"] = [{"question_id": "q1", "reason": "needs_adjudication"}]
    report = build(bundle, run, ann)
    assert report["counts"]["skipped_generations"] == 1
    assert report["skipped"][0]["reason"] == "NO_FIXTURE"
    assert report["metrics"]["human"]["support_rate"]["value"] is None
    assert report["annotations"]["missing"] == ann["missing"]
    assert report["annotations"]["conflicts"] == ann["conflicts"]
    assert report["quality_decision"] == "evidence_insufficient"


@pytest.mark.parametrize("field,value", [("output_hash", "changed"), ("run_hash", "changed"),
                                         ("rubric_version", "changed"), ("source_ids", ["unknown"]),
                                         ("evidence_locations", [])])
def test_tampered_final_labels_never_enter_metrics(field, value):
    bundle, run = fixture()
    ann = annotations(run)
    ann["final"][0][field] = value
    report = build(bundle, run, ann)
    assert report["counts"]["valid_annotated_generations"] == 0
    assert report["metrics"]["human"]["support_rate"]["value"] is None
    assert report["errors"]


@pytest.mark.parametrize("error_type", ["wrong_citation", "numeric_direction_reversal", "serious_safety_error",
                                         "phi_disclosure", "dangerous_advice"])
def test_independently_annotated_critical_errors_block_even_perfect_means(error_type):
    bundle, run = fixture()
    ann = annotations(run, {("q0", 1): {"serious_error": True, "error_types": [error_type]}})
    report = build(bundle, run, ann)
    assert report["metrics"]["human"]["support_rate"]["value"] == 1
    assert report["quality_decision"] == "blocked"
    assert report["blocking_reasons"]


@pytest.mark.parametrize("error_type", ["phi_disclosure", "dangerous_advice"])
def test_critical_safety_type_blocks_when_serious_boolean_is_tampered(error_type):
    bundle, run = fixture()
    ann = annotations(run, {("q0", 1): {"serious_error": False, "error_types": [error_type]}})
    report = build(bundle, run, ann)
    assert report["quality_decision"] == "blocked"
    assert report["blocking_reasons"]


def test_all_refuse_answerables_blocks_and_qualified_requires_human_classification():
    bundle, run = fixture(("qualified_answer", "answer"))
    for row in run["rows"]:
        row["output"]["behavior"] = "refuse"
        row["output"]["refusal_code"] = "INSUFFICIENT_EVIDENCE"
        row["output_hash"] = digest(row["output"])
    report = build(bundle, run)
    assert report["quality_decision"] == "blocked"
    assert any(r["code"] == "all_answerable_outputs_refused" for r in report["blocking_reasons"])
    assert report["metrics"]["human"]["behavior_accuracy"]["value"] is None
    bundle, run = fixture(("qualified_answer",))
    run["rows"][0]["output"]["behavior"] = "answer"
    run["rows"][0]["output_hash"] = digest(run["rows"][0]["output"])
    report = build(bundle, run)
    assert report["metrics"]["human"]["behavior_accuracy"]["value"] is None


def test_duplicate_document_consumes_position_and_family_sources_count_once():
    bundle, run = fixture()
    bundle["qrels"][1]["study_family_id"] = "f0"
    run["rows"][0]["ranked_source_ids"] = ["s0", "s0", "s1", "s3", "s4", "s5", "s6", "s7"]
    rebind(bundle, run)
    report = build(bundle, run, annotations(run))
    scored = report["questions"]["q0"]["retrieval"][0]["at_8"]
    assert scored["duplicate_count"] == 1
    assert scored["slots"][1]["gain"] == 0
    assert scored["ndcg_at_k"] < 1
    assert scored["independent_relevant_sources"] == 1
    assert scored["retrieved_independent_relevant_sources"] == 1


def test_repeat_question_means_align_ids_before_unequal_group_bootstrap():
    bundle, run = fixture(("answer", "answer", "answer"), repeats=2)
    bundle["questions"][0]["question_group_id"] = "large"
    bundle["questions"][1]["question_group_id"] = "large"
    bundle["questions"][2]["question_group_id"] = "small"
    rebind(bundle, run)
    baseline = copy.deepcopy(run)
    baseline["run_id"] = "reference"
    baseline["system"] = {"source_hash": "fixed-reference-source"}
    baseline["rows"].reverse()
    before = annotations(baseline, {(q, r): {"support_rate": 0.0} for q in ("q0", "q1", "q2") for r in (1, 2)})
    after = annotations(run, {("q0", 1): {"support_rate": 0.0}, ("q2", 1): {"support_rate": 0.0},
                              ("q2", 2): {"support_rate": 0.0}})
    report = build(bundle, run, after, baseline_run=baseline, baseline_annotations=before)
    interval = report["comparison"]["metrics"]["human.support_rate"]["interval"]
    assert interval["n_questions"] == 3
    assert interval["n_groups"] == 2
    assert interval["mean_difference"] == 0.5  # (0.5 + 1 + 0) / 3; repeats are not samples.
    assert report["metrics"]["human"]["support_rate"]["value"] == 0.5


@pytest.mark.parametrize("field", ["dataset_hash", "protocol_hash", "corpus_manifest_hash"])
def test_comparison_declares_identity_and_explicitly_rejects_mismatched_assets(field):
    bundle, run = fixture()
    baseline = copy.deepcopy(run)
    baseline["run_id"] = "reference"
    baseline["system"] = {"source_hash": "fixed-reference"}
    baseline[field] = "different"
    report = build(bundle, run, annotations(run), baseline_run=baseline,
                   baseline_annotations=annotations(baseline))
    assert report["comparison"]["status"] == "incompatible"
    assert report["comparison"]["metrics"] == {}
    assert report["comparison"]["candidate"]["run_id"] == "candidate"
    assert report["comparison"]["reference"]["run_id"] == "reference"


def test_reference_self_comparison_cannot_be_silently_accepted():
    bundle, run = fixture()
    report = build(bundle, run, annotations(run), baseline_run=copy.deepcopy(run),
                   baseline_annotations=annotations(run))
    assert report["comparison"]["status"] == "incompatible"
    assert any(e["code"] == "non_independent_reference" for e in report["comparison"]["errors"])


def test_predeclared_frozen_reference_can_have_unchanged_product_source():
    bundle, run = fixture()
    run["system"]["snapshot_manifest_hash"] = "candidate-manifest"
    baseline = copy.deepcopy(run)
    baseline["run_id"] = "reference"
    baseline["system"]["snapshot_manifest_hash"] = "fixed-reference-manifest"
    run["comparison"] = {"status": "compared", "reference_system": baseline["system"],
                         "reference_manifest_hash": "fixed-reference-manifest",
                         "same_effective_data": True, "same_protocol": True}
    report = build(bundle, run, annotations(run), baseline_run=baseline,
                   baseline_annotations=annotations(baseline))
    assert report["comparison"]["status"] != "incompatible"
    assert report["comparison"]["product_source_identical"] is True
    assert report["comparison"]["mode"] == "fixed_reference_same_product"
    assert report["comparison"]["cross_version_performance_claim"] is False


def test_matching_snapshot_cannot_spoof_fixed_reference_provenance():
    bundle, run = fixture()
    run["system"]["snapshot_manifest_hash"] = "same-manifest"
    baseline = copy.deepcopy(run)
    baseline["run_id"] = "reference"
    run["comparison"] = {"status": "compared", "reference_system": baseline["system"],
                         "reference_manifest_hash": "same-manifest",
                         "same_effective_data": True, "same_protocol": True}
    report = build(bundle, run, annotations(run), baseline_run=baseline,
                   baseline_annotations=annotations(baseline))
    assert report["comparison"]["status"] == "incompatible"


def test_missing_repeat_keeps_declared_count_and_metric_insufficient():
    bundle, run = fixture(repeats=2)
    run["rows"].pop()
    report = build(bundle, run, annotations(run))
    assert report["counts"]["expected_generations"] == 2
    assert report["counts"]["missing_generations"] == 1
    assert report["metrics"]["human"]["support_rate"]["value"] is None
    assert report["metrics"]["human"]["support_rate"]["valid_questions"] == 0


def test_runtime_rule_passes_cannot_supply_human_quality():
    bundle, run = fixture()
    run["rows"][0]["runtime_validation"] = {"support_rate": 1, "numeric_correctness": 1,
                                               "serious_error": False, "passed": True}
    report = build(bundle, run)
    assert report["metrics"]["human"]["support_rate"]["value"] is None
    assert report["metrics"]["human"]["serious_error_rate"]["value"] is None
    assert report["quality_decision"] == "evidence_insufficient"


@pytest.mark.parametrize("applicable, expected", [(True, "evidence_insufficient"), (False, "not_applicable")])
def test_numeric_judgment_null_uses_predeclared_applicability(applicable, expected):
    bundle, run = fixture()
    bundle["questions"][0]["applicability"]["numeric_correctness"] = applicable
    rebind(bundle, run)
    report = build(bundle, run, annotations(run, {("q0", 1): {"numeric_correctness": None}}))
    numeric = report["metrics"]["human"]["numeric_correctness"]
    assert numeric["status"] == expected
    assert numeric["value"] is None
    assert numeric["expected_questions"] == int(applicable)
    assert report["counts"]["valid_annotated_generations"] == 1
    assert report["quality_decision"] == ("evidence_insufficient" if applicable else "ready_for_review")


@pytest.mark.parametrize("last_judged", [True, False])
def test_full_top40_is_scored_only_with_complete_rank_and_judgments(last_judged):
    bundle, run = fixture()
    for index in range(8, 40):
        source = {"id": "s%d" % index, "text": "SYNTHETIC long-ranking source",
                  "locator": {"paragraph": index}}
        bundle["sources"].append(source)
        if index != 39 or last_judged:
            bundle["qrels"].append({"question_id": "q0", "source_id": source["id"], "grade": 0,
                                    "study_family_id": "f%d" % index, "evidence_role": "synthetic",
                                    "locator": source["locator"], "rationale": "synthetic judgment"})
        run["rows"][0]["ranked_source_ids"].append(source["id"])
    run["rows"][0]["ranking_complete_k"] = 40
    rebind(bundle, run)
    report = build(bundle, run, annotations(run))
    assert report["metrics"]["retrieval"]["recall_at_8"]["value"] == 1
    assert report["metrics"]["retrieval"]["recall_at_40"]["value"] == (1 if last_judged else None)


def test_unresolved_final_conflict_cannot_enter_final_quality_scores():
    bundle, run = fixture()
    ann = annotations(run)
    ann["conflicts"] = [{"question_id": "q0", "repeat": 1, "run_id": "candidate", "reason": "needs_adjudication"}]
    report = build(bundle, run, ann)
    assert report["counts"]["valid_annotated_generations"] == 0
    assert report["metrics"]["human"]["support_rate"]["value"] is None


def test_invalid_assets_return_readable_evidence_insufficient_report():
    bundle, run = fixture()
    bundle["qrels"][0]["grade"] = 9
    rebind(bundle, run)
    report = build(bundle, run, annotations(run))
    assert report["quality_decision"] == "evidence_insufficient"
    assert report["errors"]
    assert report["metrics"] == {}


def test_report_does_not_certify_pilot_execution_from_asset_kind():
    bundle, run = fixture()
    bundle["asset_kind"] = "controlled_clinical"
    for q in bundle["questions"]:
        q["split"] = "blind"
        q["annotation_status"] = "reviewed"
    run["asset_kind"] = "controlled_clinical"
    rebind(bundle, run)
    report = build(bundle, run)
    assert report["pilot_status"] != "independent_review_recorded"
    assert report["clinical_quality_passed"] is None


@pytest.mark.parametrize("origin,adjudicator,rationale,valid", [
    ("adjudicated", "reviewer-A", "reason", False),
    ("adjudicated", "independent-adjudicator", "", False),
    ("adjudicated", "independent-adjudicator", "synthetic arbitration", True),
])
def test_adjudicated_final_requires_distinct_arbitrator_and_reason(origin, adjudicator, rationale, valid):
    bundle, run = fixture()
    ann = annotations(run)
    final = ann["final"][0]
    final.update(annotation_origin=origin, adjudicator_id=adjudicator, adjudication_rationale=rationale)
    report = build(bundle, run, ann)
    assert report["counts"]["valid_annotated_generations"] == int(valid)


@pytest.mark.parametrize("field", ["rationale", "support_rate", "numeric_correctness", "serious_error"])
def test_missing_label_fields_are_not_silently_coerced_to_null(field):
    bundle, run = fixture()
    ann = annotations(run)
    del ann["final"][0]["labels"][field]
    report = build(bundle, run, ann)
    assert report["counts"]["valid_annotated_generations"] == 0
    assert report["errors"]


@pytest.mark.parametrize("rows", [None, "invalid", {}, [None], ["invalid"],
                                  [{"question_id": [], "repeat": 1, "status": "success"}],
                                  [{"question_id": "q0", "repeat": [], "status": "success"}]])
def test_malformed_run_rows_report_errors_without_traceback(rows):
    bundle, run = fixture()
    run["rows"] = rows
    report = build(bundle, run)
    assert report["quality_decision"] == "evidence_insufficient"
    assert report["errors"]


@pytest.mark.parametrize("field,value", [("ranked_source_ids", None), ("ranked_source_ids", [[]]),
                                         ("evidence", None), ("evidence", [None]),
                                         ("evidence", [{"source_id": []}])])
def test_malformed_successful_payload_cannot_reach_metrics(field, value):
    bundle, run = fixture()
    run["rows"][0][field] = value
    report = build(bundle, run)
    assert report["quality_decision"] == "evidence_insufficient"
    assert report["errors"]
    assert report["metrics"]["retrieval"]["recall_at_8"]["value"] is None


@pytest.mark.parametrize("finals", [None, "invalid", {}, [None], ["invalid"],
                                   [{"run_id": "candidate", "question_id": [], "repeat": 1}]])
def test_malformed_finals_report_errors_without_traceback(finals):
    bundle, run = fixture()
    ann = annotations(run)
    ann["final"] = finals
    report = build(bundle, run, ann)
    assert report["counts"]["valid_annotated_generations"] == 0
    assert report["errors"]


def test_unjudgeable_annotation_envelope_is_preserved():
    bundle, run = fixture()
    ann = annotations(run)
    ann["final"] = []
    ann["unjudgeable"] = [{"question_id": "q0", "reason": "source_not_resolvable"}]
    report = build(bundle, run, ann)
    assert report["annotations"]["unjudgeable"] == ann["unjudgeable"]


@pytest.mark.parametrize("invalid", [None, [], "invalid", {"rows": []}])
def test_invalid_run_envelope_is_a_reportable_error(invalid):
    bundle, _ = fixture()
    report = build(bundle, invalid)
    assert report["quality_decision"] == "evidence_insufficient"
    assert report["errors"]


def test_nonfinite_run_content_and_annotation_locators_are_reported():
    bundle, run = fixture()
    run["rows"][0]["evidence"][0]["locator"]["bad"] = float("nan")
    report = build(bundle, run)
    assert report["errors"]
    bundle, run = fixture()
    ann = annotations(run)
    ann["final"][0]["evidence_locations"][0]["locator"] = {"bad": float("nan")}
    report = build(bundle, run, ann)
    assert report["counts"]["valid_annotated_generations"] == 0
    assert report["errors"]


def test_unknown_ranked_source_is_unjudged_not_zero_relevance():
    bundle, run = fixture()
    run["rows"][0]["ranked_source_ids"][0] = "unknown-source"
    report = build(bundle, run)
    result = report["questions"]["q0"]["retrieval"][0]["at_8"]
    assert result["score_status"] == "unjudged_candidates"
    assert result["slots"][0]["gain"] is None
    assert result["recall_at_k"] is None


@pytest.mark.parametrize("system", [None, [], "invalid"])
def test_malformed_comparison_system_identity_is_reported(system):
    bundle, run = fixture()
    baseline = copy.deepcopy(run)
    baseline["run_id"] = "reference"
    baseline["system"] = system
    report = build(bundle, run, baseline_run=baseline)
    assert report["comparison"]["status"] == "incompatible"
    assert report["comparison"]["errors"]


@pytest.mark.parametrize("provenance", [None, [], "invalid"])
def test_malformed_reference_provenance_cannot_spoof_independence(provenance):
    bundle, run = fixture()
    run["system"]["snapshot_manifest_hash"] = "candidate-manifest"
    baseline = copy.deepcopy(run)
    baseline["run_id"] = "reference"
    baseline["system"]["snapshot_manifest_hash"] = "reference-manifest"
    run["comparison"] = provenance
    report = build(bundle, run, baseline_run=baseline)
    assert report["comparison"]["status"] == "incompatible"


def test_nonfinite_reference_is_reported_as_incompatible():
    bundle, run = fixture()
    baseline = copy.deepcopy(run)
    baseline["metadata"] = float("nan")
    report = build(bundle, run, baseline_run=baseline)
    assert report["comparison"]["status"] == "incompatible"


@pytest.mark.parametrize("source_hash", [None, [], {}])
def test_malformed_product_source_hash_is_an_incompatible_identity(source_hash):
    bundle, run = fixture()
    baseline = copy.deepcopy(run)
    baseline["system"]["source_hash"] = source_hash
    report = build(bundle, run, baseline_run=baseline)
    assert report["comparison"]["status"] == "incompatible"


@pytest.mark.parametrize("answer", [None, "", {}, {"paragraphs": []}])
def test_absent_answer_content_cannot_receive_complete_human_quality(answer):
    bundle, run = fixture()
    output = run["rows"][0]["output"]
    if answer is None:
        del output["answer"]
    else:
        output["answer"] = answer
    run["rows"][0]["output_hash"] = digest(output)
    report = build(bundle, run, annotations(run))
    assert report["quality_decision"] == "evidence_insufficient"
    assert report["counts"]["valid_annotated_generations"] == 0
    assert report["errors"]


def test_missing_output_refusal_code_field_is_invalid_contract():
    bundle, run = fixture()
    del run["rows"][0]["output"]["refusal_code"]
    run["rows"][0]["output_hash"] = digest(run["rows"][0]["output"])
    report = build(bundle, run, annotations(run))
    assert report["counts"]["valid_annotated_generations"] == 0
    assert report["errors"]
