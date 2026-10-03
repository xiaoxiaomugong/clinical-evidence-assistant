"""Synthetic assets only; no real clinical blind-set data is read here."""

import copy
import json

import pytest

from eval.independent.assets import (
    AssetValidationError,
    content_hash,
    load_bundle,
    require_valid,
    validate_bundle,
)


def synthetic_bundle():
    return {
        "schema_version": "independent-eval-v1",
        "asset_kind": "synthetic_engineering",
        "dataset_id": "synthetic-contract-v1",
        "protocol": {"version": "synthetic-v1", "rubric_version": "synthetic-rubric-v1"},
        "corpus": {"profile": "C0", "manifest_hash": "a" * 64},
        "questions": [{
            "id": "q1", "question_group_id": "g1", "split": "synthetic",
            "question": "Synthetic evidence question?", "topic": "synthetic",
            "language": "en", "scenario": "engineering", "risk": "low",
            "as_of_date": "2026-10-03", "corpus_profile": "C0",
            "corpus_manifest_hash": "a" * 64,
            "expected_behavior": "qualified_answer", "expected_reason": "Engineering fixture",
            "allowed_refusal_codes": [], "forbidden_conclusions": ["Clinical quality passed"],
            "applicability": {"retrieval": True, "answer_quality": True, "refusal": False},
            "annotation_status": "synthetic",
        }],
        "sources": [{"id": "s1", "text": "Synthetic source text for testing only.",
                     "locator": {"document": "synthetic source", "section": "fixture"}}],
        "qrels": [{"question_id": "q1", "source_id": "s1", "grade": 3,
                   "study_family_id": "family1", "evidence_role": "support",
                   "locator": {"quote": "Synthetic source text"}, "rationale": "Synthetic support"}],
        "key_points": [{"id": "kp1", "question_id": "q1", "text": "Synthetic qualification",
                        "necessity": "required", "weight": 1,
                        "support_source_ids": ["s1"], "scope": "Synthetic engineering only"}],
    }


def codes(report, key="errors"):
    return {row["code"] for row in report[key]}


def test_valid_synthetic_bundle_preserves_declared_behavior_and_canonical_hash():
    bundle = synthetic_bundle()
    assert validate_bundle(bundle)["valid"] is True
    assert require_valid(bundle) is bundle
    assert bundle["questions"][0]["expected_behavior"] == "qualified_answer"
    assert content_hash({"b": 2, "a": 1}) == "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_import_single_json_and_directory_jsonl_without_changing_contents(tmp_path):
    bundle = synthetic_bundle()
    single = tmp_path / "bundle.json"
    single.write_text(json.dumps(bundle), encoding="utf-8")
    assert load_bundle(single) == bundle
    directory = tmp_path / "tables"
    directory.mkdir()
    metadata = {key: value for key, value in bundle.items() if key not in ("protocol", "questions", "sources", "qrels", "key_points")}
    (directory / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    (directory / "protocol.json").write_text(json.dumps(bundle["protocol"]), encoding="utf-8")
    for table in ("questions", "sources", "qrels", "key_points"):
        (directory / (table + ".jsonl")).write_text("\n".join(json.dumps(row) for row in bundle[table]) + "\n", encoding="utf-8")
    assert load_bundle(directory) == bundle


@pytest.mark.parametrize("text,code", [('{"schema_version":', "invalid_json"), ('{"x":1,"x":2}', "duplicate_json_key"), ('{"x":NaN}', "invalid_json")])
def test_import_reports_invalid_or_ambiguous_json(tmp_path, text, code):
    path = tmp_path / "broken.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(AssetValidationError) as exc:
        load_bundle(path)
    assert exc.value.errors[0]["code"] == code
    assert exc.value.errors[0]["path"]


def test_jsonl_invalid_record_reports_exact_table_line(tmp_path):
    bundle = synthetic_bundle()
    (tmp_path / "manifest.json").write_text(json.dumps({k: v for k, v in bundle.items() if k not in ("questions", "sources", "qrels", "key_points")}), encoding="utf-8")
    (tmp_path / "questions.jsonl").write_text(json.dumps(bundle["questions"][0]) + "\nnot json\n", encoding="utf-8")
    with pytest.raises(AssetValidationError) as exc:
        load_bundle(tmp_path)
    assert exc.value.errors[0]["code"] == "invalid_json"
    assert "questions.jsonl:2" in exc.value.errors[0]["path"]


@pytest.mark.parametrize("field,value,code", [
    ("id", "", "missing_field"), ("split", "test", "invalid_split"),
    ("expected_behavior", "maybe", "invalid_behavior"),
    ("as_of_date", "2026-02-30", "invalid_date"),
    ("corpus_manifest_hash", "b" * 64, "corpus_hash_mismatch"),
    ("corpus_profile", "C1", "corpus_profile_mismatch"),
    ("allowed_refusal_codes", "REFUSE", "invalid_type"),
    ("applicability", {"retrieval": "yes", "answer_quality": True, "refusal": False}, "invalid_type"),
])
def test_question_contract_reports_invalid_fields(field, value, code):
    bundle = synthetic_bundle()
    bundle["questions"][0][field] = value
    report = validate_bundle(bundle)
    assert report["valid"] is False
    assert code in codes(report)


def test_duplicate_unknown_ids_and_conflicting_qrels_are_visible():
    bundle = synthetic_bundle()
    bundle["questions"].append(copy.deepcopy(bundle["questions"][0]))
    bundle["qrels"].append(dict(bundle["qrels"][0], grade=0))
    bundle["key_points"][0]["support_source_ids"] = ["unknown"]
    report = validate_bundle(bundle)
    assert {"duplicate_id", "conflicting_label", "unknown_id"} <= codes(report)


@pytest.mark.parametrize("grade", [-1, 4, 2.5, True, "3", None])
def test_relevance_grades_are_strict_integers_zero_to_three(grade):
    bundle = synthetic_bundle()
    bundle["qrels"][0]["grade"] = grade
    assert "invalid_grade" in codes(validate_bundle(bundle))


def test_original_text_locator_and_source_references_are_required():
    bundle = synthetic_bundle()
    bundle["qrels"][0]["source_id"] = "unknown"
    bundle["qrels"][0]["locator"] = {}
    bundle["qrels"][0]["rationale"] = ""
    bundle["key_points"][0]["scope"] = ""
    report = validate_bundle(bundle)
    assert {"unknown_id", "missing_locator", "missing_field"} <= codes(report)


@pytest.mark.parametrize("locator", [{"quote": "Text never present"}, {"start": 0, "end": 999}, {"start": True, "end": 4}, {"start": 0, "end": 9, "quote": "incorrect"}])
def test_locator_must_match_the_referenced_source_text(locator):
    bundle = synthetic_bundle()
    bundle["qrels"][0]["locator"] = locator
    assert "locator_mismatch" in codes(validate_bundle(bundle))


def test_refusal_cannot_be_declared_retrieval_applicable():
    bundle = synthetic_bundle()
    question = bundle["questions"][0]
    question.update(expected_behavior="refuse", allowed_refusal_codes=["INSUFFICIENT_EVIDENCE"])
    assert "conflicting_label" in codes(validate_bundle(bundle))


def test_corpus_expected_hash_is_verified_independently():
    report = validate_bundle(synthetic_bundle(), corpus_manifest_hash="b" * 64)
    assert "corpus_hash_mismatch" in codes(report)


def add_question(bundle, identifier, group, split, text, **extra):
    question = copy.deepcopy(bundle["questions"][0])
    question.update(id=identifier, question_group_id=group, split=split, question=text, **extra)
    bundle["questions"].append(question)


def test_cross_split_question_group_and_transitive_derived_leakage_are_rejected():
    bundle = synthetic_bundle()
    bundle["questions"][0]["split"] = "dev"
    add_question(bundle, "q2", "g1", "blind", "Another synthetic question")
    add_question(bundle, "q3", "g3", "dev", "Derived synthetic question", derived_from="q1")
    add_question(bundle, "q4", "g4", "blind", "Further derivative", derived_from=["q3"])
    report = validate_bundle(bundle)
    assert {"cross_split_group_leakage", "derived_leakage"} <= codes(report)


def test_derived_cycles_and_unknown_parents_are_rejected_without_recursion_failure():
    bundle = synthetic_bundle()
    bundle["questions"][0]["derived_from"] = ["q2", "unknown"]
    add_question(bundle, "q2", "g2", "synthetic", "Another question", derived_from="q1")
    report = validate_bundle(bundle)
    assert {"derived_cycle", "unknown_id"} <= codes(report)


def test_shared_guideline_alone_is_allowed_but_semantic_family_needs_manual_review():
    bundle = synthetic_bundle()
    bundle["questions"][0].update(split="dev", semantic_family_id="semantic1")
    add_question(bundle, "q2", "g2", "blind", "Distinct synthetic question", semantic_family_id="semantic1")
    bundle["qrels"].append(dict(bundle["qrels"][0], question_id="q2"))
    report = validate_bundle(bundle)
    assert report["valid"] is True
    assert "semantic_leakage_review" in codes(report, "manual_review")
    assert "shared_source_leakage" not in codes(report)


def test_missing_draft_labels_are_visible_evidence_gaps_not_fabricated():
    bundle = synthetic_bundle()
    bundle["asset_kind"] = "draft_development"
    bundle["questions"][0].update(split="dev", annotation_status="draft/unreviewed")
    bundle["qrels"] = []
    bundle["key_points"] = []
    report = validate_bundle(bundle)
    assert report["valid"] is True
    assert {"missing_qrels", "missing_key_points", "unreviewed_asset"} <= codes(report, "warnings")
    assert bundle["qrels"] == []
    assert bundle["key_points"] == []


@pytest.mark.parametrize("bundle", [None, [], {"questions": None}, {"questions": [None, [], 5], "sources": "oops", "qrels": [{"question_id": []}], "key_points": [None]}])
def test_malformed_nested_types_produce_validation_errors_not_tracebacks(bundle):
    report = validate_bundle(bundle)
    assert report["valid"] is False
    assert report["errors"]
    with pytest.raises(AssetValidationError):
        require_valid(bundle)


def test_nonfinite_weights_and_hash_values_are_rejected():
    bundle = synthetic_bundle()
    bundle["key_points"][0]["weight"] = float("nan")
    assert "invalid_weight" in codes(validate_bundle(bundle))
    with pytest.raises(AssetValidationError):
        content_hash({"value": float("nan")})


def test_extreme_numeric_weights_and_nonfinite_locators_return_errors():
    bundle = synthetic_bundle()
    bundle["key_points"][0]["weight"] = 10 ** 1000
    bundle["sources"][0]["locator"] = {"page": float("inf"), "section": False}
    report = validate_bundle(bundle)
    assert {"invalid_weight", "invalid_locator"} <= codes(report)


def test_source_study_family_is_stable_across_question_labels():
    bundle = synthetic_bundle()
    add_question(bundle, "q2", "g2", "synthetic", "Another synthetic question")
    bundle["qrels"].append(dict(bundle["qrels"][0], question_id="q2", study_family_id="different_family"))
    assert "conflicting_label" in codes(validate_bundle(bundle))


def test_keypoint_support_cannot_use_an_explicitly_irrelevant_source():
    bundle = synthetic_bundle()
    bundle["qrels"][0]["grade"] = 0
    assert "conflicting_label" in codes(validate_bundle(bundle))


def test_cross_split_semantic_audit_remains_required_without_explicit_family_tags():
    bundle = synthetic_bundle()
    bundle["questions"][0]["split"] = "dev"
    add_question(bundle, "q2", "g2", "blind", "A superficially different synthetic question")
    report = validate_bundle(bundle)
    assert report["valid"] is True
    assert "semantic_leakage_audit_required" in codes(report, "manual_review")


def test_ambiguous_table_files_do_not_silently_select_one(tmp_path):
    bundle = synthetic_bundle()
    (tmp_path / "manifest.json").write_text(json.dumps(bundle), encoding="utf-8")
    (tmp_path / "questions.json").write_text("[]", encoding="utf-8")
    (tmp_path / "questions.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(AssetValidationError) as exc:
        load_bundle(tmp_path)
    assert exc.value.errors[0]["code"] == "ambiguous_table"


@pytest.mark.parametrize("metric", ["support_rate", "key_point_coverage", "numeric_correctness", "refusal_quality"])
def test_optional_metric_applicability_requires_declared_boolean(metric):
    bundle = synthetic_bundle()
    bundle["questions"][0]["applicability"][metric] = None
    assert "invalid_type" in codes(validate_bundle(bundle))
    bundle["questions"][0]["applicability"][metric] = False
    assert validate_bundle(bundle)["valid"] is True


def test_unknown_boolean_applicability_is_preserved_for_versioned_extensions():
    bundle = synthetic_bundle()
    bundle["questions"][0]["applicability"]["readability"] = True
    assert require_valid(bundle)["questions"][0]["applicability"]["readability"] is True


@pytest.mark.parametrize("table,field,value", [("questions", "id", " q1 "), ("questions", "question_group_id", "g 1"), ("sources", "id", "source\n1"), ("qrels", "study_family_id", "family 1")])
def test_stable_ids_cannot_hide_duplicates_behind_whitespace(table, field, value):
    bundle = synthetic_bundle()
    bundle[table][0][field] = value
    assert "invalid_id" in codes(validate_bundle(bundle))


def test_json_numeric_overflow_is_rejected_at_import_boundary(tmp_path):
    path = tmp_path / "overflow.json"
    path.write_text('{"untrusted": 1e999}', encoding="utf-8")
    with pytest.raises(AssetValidationError) as exc:
        load_bundle(path)
    assert exc.value.errors[0]["code"] == "invalid_json"
    assert exc.value.errors[0]["path"] == str(path)


@pytest.mark.parametrize("location,value", [("extra", object()), ("protocol", float("inf")), ("scope", float("nan"))])
def test_whole_bundle_must_be_finite_canonical_json(location, value):
    bundle = synthetic_bundle()
    if location == "extra":
        bundle["extra"] = value
    elif location == "protocol":
        bundle["protocol"]["extension"] = value
    else:
        bundle["key_points"][0]["scope"] = {"population": value}
    report = validate_bundle(bundle)
    assert report["valid"] is False
    assert "not_json_serializable" in codes(report)
    with pytest.raises(AssetValidationError):
        require_valid(bundle)


def test_exact_same_split_question_cannot_claim_different_independent_groups():
    bundle = synthetic_bundle()
    add_question(bundle, "q2", "g2", "synthetic", "  SYNTHETIC  evidence question?  ")
    report = validate_bundle(bundle)
    assert report["valid"] is False
    assert "conflicting_question_groups" in codes(report)


def test_exact_same_split_question_in_one_group_is_explicitly_clustered():
    bundle = synthetic_bundle()
    add_question(bundle, "q2", "g1", "synthetic", "  SYNTHETIC  evidence question?  ")
    assert validate_bundle(bundle)["valid"] is True
