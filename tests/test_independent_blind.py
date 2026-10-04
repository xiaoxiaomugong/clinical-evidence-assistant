"""Synthetic engineering fixtures only; never real blind questions or labels."""
import copy
import hashlib
import json
from pathlib import Path

import pytest


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@pytest.fixture
def bundle():
    return {
        "schema_version": "independent-eval-v1", "asset_kind": "synthetic_engineering",
        "dataset_id": "synthetic-blind-test", "protocol": {"version": "test-v1", "rubric_version": "rubric-v1"},
        "corpus": {"profile": "C0", "manifest_hash": "a" * 64},
        "questions": [{"id": "q-synthetic", "question_group_id": "g-synthetic", "split": "synthetic",
            "question": "SYNTHETIC: what does the fictional source say?", "topic": "engineering",
            "language": "en", "scenario": "synthetic only", "risk": "synthetic", "as_of_date": "2026-10-03",
            "corpus_profile": "C0", "corpus_manifest_hash": "a" * 64,
            "expected_behavior": "answer", "expected_reason": "SECRET REFERENCE REASON",
            "allowed_refusal_codes": [], "forbidden_conclusions": ["SECRET FORBIDDEN"],
            "applicability": {"retrieval": True, "answer_quality": True, "refusal": False},
            "annotation_status": "synthetic"}],
        "sources": [{"id": "source-1", "text": "SYNTHETIC excerpt one.", "locator": {"section": "1"}},
                    {"id": "source-2", "text": "SYNTHETIC excerpt two.", "locator": {"section": "2"}}],
        "qrels": [{"question_id": "q-synthetic", "source_id": "source-1", "grade": 3,
                   "study_family_id": "family-1", "evidence_role": "synthetic", "locator": {"section": "1"}, "rationale": "SECRET QREL"}],
        "key_points": [{"id": "kp-1", "question_id": "q-synthetic", "text": "SECRET REFERENCE ANSWER",
                        "necessity": "required", "weight": 1, "support_source_ids": ["source-1"], "scope": "synthetic"}],
    }


@pytest.fixture
def runs(bundle):
    def run(name, repeat=1):
        output = {"behavior": "answer", "answer": "SYNTHETIC answer [1].", "refusal_code": None,
                  "model": "SECRET MODEL", "raw_runtime": "SECRET RUNTIME"}
        return {"schema_version": "independent-run-v1", "run_id": name, "asset_kind": "synthetic_engineering",
                "dataset_hash": digest(bundle), "protocol_hash": digest(bundle["protocol"]), "rubric_version": "rubric-v1",
                "corpus_manifest_hash": "a" * 64, "system": {"model": "SECRET MODEL", "backend": "SECRET BACKEND", "source": name},
                "expected_count": 1, "repeats": 1, "rows": [{"question_id": "q-synthetic", "repeat": repeat, "status": "success",
                  "output": output, "output_hash": digest(output), "ranked_source_ids": ["source-1", "source-2"], "ranking_complete_k": 2,
                  "evidence": [{"source_id": "source-1", "text": "SYNTHETIC excerpt one.", "locator": {"section": "1"}, "rank": 1, "citation_number": 1},
                               {"source_id": "source-2", "text": "SYNTHETIC excerpt two.", "locator": {"section": "2"}, "rank": 2, "citation_number": 2}]}]}
    return [run("SECRET BASELINE"), run("SECRET CANDIDATE")]


def exported(tmp_path, bundle, runs, seed=17):
    from eval.independent.blind import export_blind
    result = export_blind(bundle, runs, tmp_path / "public", tmp_path / "private", seed=seed)
    package = json.loads(Path(result["public_package"]).read_text())
    mapping = json.loads(Path(result["private_mapping"]).read_text())
    return result, package, mapping


def review_rows(package, reviewer):
    labels = {"behavior": "answer", "support_rate": 1.0, "key_point_coverage": 1.0,
              "numeric_correctness": None, "refusal_quality": None, "serious_error": False,
              "error_types": [], "rationale": "SYNTHETIC engineering judgement."}
    return [{"item_id": item["item_id"], "question_id": item["question_id"], "reviewer_id": reviewer,
             "rubric_version": package["rubric_version"], "output_hash": item["output_hash"], "run_hash": item["run_hash"],
             "presented_output_hash": item.get("presented_output_hash"),
             "source_ids": [e["source_id"] for e in item["evidence"]],
             "evidence_locations": [{"source_id": e["source_id"], "locator": e["locator"]} for e in item["evidence"]],
             "labels": copy.deepcopy(labels)} for item in package["items"]]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    return path


def import_pair(tmp_path, bundle, runs, mapping, a, b, adjudications=None):
    from eval.independent.blind import import_reviews
    paths = {"A": write_jsonl(tmp_path / "A.jsonl", a), "B": write_jsonl(tmp_path / "B.jsonl", b)}
    adjudication_path = write_jsonl(tmp_path / "adjudication.jsonl", adjudications) if adjudications is not None else None
    return import_reviews(bundle, runs, mapping, paths, adjudication_path)


def test_public_package_whitelist_hides_identity_references_and_rank(tmp_path, bundle, runs):
    result, package, mapping = exported(tmp_path, bundle, runs)
    public_text = " ".join(p.read_text() for p in Path(result["public_package"]).parent.iterdir())
    for forbidden in ("SECRET", '"system"', '"model"', '"backend"', '"rank"', '"ranked_source_ids"',
                      '"expected_behavior"', '"key_points"', '"qrels"', '"seed"', '"reviewer_id": "A"'):
        assert forbidden not in public_text
    assert len(package["items"]) == 2
    assert len({item["item_id"] for item in package["items"]}) == 2
    assert all(set(item["output"]) == {"behavior", "answer", "refusal_code"} for item in package["items"])
    assert mapping["seed"] == 17
    assert {item["run_id"] for item in mapping["items"].values()} == {r["run_id"] for r in runs}
    assert {item["run_hash"] for item in mapping["items"].values()} == {digest(r) for r in runs}
    assert Path(result["private_mapping"]).stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("relative", ["same", "inside-public", "inside-private"])
def test_export_rejects_overlapping_destinations(tmp_path, bundle, runs, relative):
    from eval.independent.blind import export_blind
    public = tmp_path / "package"
    private = public if relative == "same" else public / "private" if relative == "inside-public" else tmp_path
    with pytest.raises(ValueError, match="overlap"):
        export_blind(bundle, runs, public, private)
    assert not public.exists()


def test_export_never_overwrites_and_seed_reproduces_blinding(tmp_path, bundle, runs):
    from eval.independent.blind import export_blind
    _, first, _ = exported(tmp_path / "first", bundle, runs, seed=42)
    _, second, _ = exported(tmp_path / "second", bundle, runs, seed=42)
    assert first == second
    with pytest.raises(FileExistsError):
        export_blind(bundle, runs, tmp_path / "first/public", tmp_path / "new-private", seed=42)
    assert not (tmp_path / "new-private").exists()


def test_export_rejects_symlink_overlap(tmp_path, bundle, runs):
    from eval.independent.blind import export_blind
    public = tmp_path / "public"
    public.mkdir()
    (tmp_path / "alias").symlink_to(public, target_is_directory=True)
    with pytest.raises(ValueError, match="overlap"):
        export_blind(bundle, runs, public / "new", tmp_path / "alias/new/private")


def test_two_independent_reviews_are_retained_and_agreement_finalized(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert result["original_reviews"] == {"A": a, "B": b}
    assert result["errors"] == result["missing"] == result["conflicts"] == []
    assert result["status"] == "complete"
    assert result["dataset_hash"] == digest(bundle)
    assert len(result["final"]) == 2
    for final in result["final"]:
        assert final["status"] == "complete"
        assert final["annotation_origin"] == "agreed"
        assert final["rubric_version"] == "rubric-v1"
        assert final["run_hash"] == digest(next(r for r in runs if r["run_id"] == final["run_id"]))
        assert final["labels"]["numeric_correctness"] is None


def test_missing_second_reviewer_never_becomes_pass(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    result = import_pair(tmp_path, bundle, runs, mapping, review_rows(package, "anon-A"), [])
    assert result["final"] == []
    assert len(result["missing"]) == 2
    assert result["status"] == "incomplete"


def test_conflict_requires_independent_adjudication_and_rationale(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    b[0]["labels"]["support_rate"] = 0.0
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert len(result["final"]) == 1
    assert len(result["conflicts"]) == 1
    adjudication = copy.deepcopy(b[0])
    adjudication["reviewer_id"] = "anon-arbiter"
    adjudication["adjudication_rationale"] = "SYNTHETIC: inspected fictional locator and resolved disagreement."
    result = import_pair(tmp_path, bundle, runs, mapping, a, b, [adjudication])
    assert result["conflicts"] == []
    assert len(result["final"]) == 2
    final = next(f for f in result["final"] if f["item_id"] == b[0]["item_id"])
    assert final["annotation_origin"] == "adjudicated"
    assert final["labels"]["support_rate"] == 0.0
    assert result["original_reviews"]["A"] == a
    assert result["original_reviews"]["B"] == b


@pytest.mark.parametrize("field,value,code", [
    ("question_id", "unknown", "question_mismatch"), ("output_hash", "bad", "output_hash_mismatch"),
    ("run_hash", "bad", "run_hash_mismatch"), ("rubric_version", "old", "rubric_mismatch"),
    ("source_ids", ["unknown"], "source_mismatch"), ("evidence_locations", [], "missing_evidence_locations"),
    ("evidence_locations", [{"source_id": "source-1", "locator": {"section": "WRONG"}}], "evidence_location_mismatch"),
])
def test_invalid_binding_is_visible_and_cannot_finalize(tmp_path, bundle, runs, field, value, code):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    a[0][field] = value
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert any(error["code"] == code for error in result["errors"])
    assert all(f["item_id"] != a[0]["item_id"] for f in result["final"])


def test_mapping_and_run_tampering_are_detected(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    runs[0]["system"]["source"] = "DIFFERENT VERSION"
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert any(e["code"] == "mapping_run_mismatch" for e in result["errors"])
    assert result["final"] == []


def test_reviewer_independence_is_global_not_per_item(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    a[1]["reviewer_id"], b[1]["reviewer_id"] = "anon-B", "anon-A"
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert any(e["code"] == "reviewer_not_independent" for e in result["errors"])
    assert result["final"] == []


@pytest.mark.parametrize("change,code", [("same-reviewer", "adjudicator_not_independent"), ("no-rationale", "missing_adjudication_rationale")])
def test_adjudication_rejects_reviewer_self_resolution_and_missing_rationale(tmp_path, bundle, runs, change, code):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    b[0]["labels"]["support_rate"] = 0.0
    arb = copy.deepcopy(b[0])
    arb["reviewer_id"] = "anon-A" if change == "same-reviewer" else "anon-arbiter"
    if change != "no-rationale":
        arb["adjudication_rationale"] = "SYNTHETIC resolution."
    result = import_pair(tmp_path, bundle, runs, mapping, a, b, [arb])
    assert any(e["code"] == code for e in result["errors"])
    assert len(result["conflicts"]) == 1


def test_unknown_duplicate_and_unjudgeable_reviews_are_visible(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    a[0]["labels"]["behavior"] = "unjudgeable"
    unknown = copy.deepcopy(a[1])
    unknown["item_id"] = "unknown-item"
    a.extend([copy.deepcopy(a[1]), unknown])
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert {"unknown_item", "duplicate_review"} <= {e["code"] for e in result["errors"]}
    assert len(result["unjudgeable"]) == 1
    assert result["final"] == []


@pytest.mark.parametrize("change,code", [("out-of-range", "invalid_labels"), ("critical-passed", "critical_error_conflict"), ("bool-metric", "invalid_labels")])
def test_invalid_labels_cannot_silently_pass(tmp_path, bundle, runs, change, code):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    if change == "out-of-range":
        a[0]["labels"]["support_rate"] = 2
    elif change == "bool-metric":
        a[0]["labels"]["support_rate"] = True
    else:
        a[0]["labels"]["error_types"] = ["numeric_direction_reversal"]
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert any(e["code"] == code for e in result["errors"])
    assert all(f["item_id"] != a[0]["item_id"] for f in result["final"])


def test_agreed_serious_error_stays_blocking_label(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    for review in (a[0], b[0]):
        review["labels"]["serious_error"] = True
        review["labels"]["error_types"] = ["wrong_citation"]
        review["labels"]["support_rate"] = 0
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert next(f for f in result["final"] if f["item_id"] == a[0]["item_id"])["labels"]["serious_error"] is True


def test_citation_aliases_hide_original_ranking_in_text_and_structure(tmp_path, bundle, runs):
    for run in runs:
        row = run["rows"][0]
        row["output"]["answer"] = {"paragraphs": [{"text": "SYNTHETIC claim [1] and second claim [2].", "citation_ids": [1, 2]}], "refusal_reason": ""}
        row["output_hash"] = digest(row["output"])
    _, package, mapping = exported(tmp_path, bundle, runs)
    for item in package["items"]:
        aliases = {e["source_id"]: e["citation_number"] for e in item["evidence"]}
        paragraph = item["output"]["answer"]["paragraphs"][0]
        assert aliases["source-1"].startswith("cite-")
        assert aliases["source-2"].startswith("cite-")
        assert paragraph["citation_ids"] == [aliases["source-1"], aliases["source-2"]]
        assert "[1]" not in paragraph["text"] and "[2]" not in paragraph["text"]
        assert "[" + aliases["source-1"] + "]" in paragraph["text"]
        assert item["presented_output_hash"] == digest(item["output"])
        assert mapping["items"][item["item_id"]]["original_to_public"] == {"1": aliases["source-1"], "2": aliases["source-2"]}
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert result["status"] == "complete"


def test_nested_identity_and_reference_metadata_cannot_escape_whitelist(tmp_path, bundle, runs):
    for run in runs:
        row = run["rows"][0]
        row["output"]["answer"] = {"model": "SECRET NESTED MODEL", "paragraphs": [{"text": "SYNTHETIC authored answer [1].", "citation_ids": [1], "backend": "SECRET NESTED BACKEND", "labels": {"reference_answer": "SECRET LABEL"}}], "refusal_reason": "", "raw_runtime": "SECRET RAW"}
        row["output_hash"] = digest(row["output"])
        row["evidence"][0]["locator"]["model"] = "SECRET LOCATOR MODEL"
        row["evidence"][0]["locator"]["table"] = {"title": "visible subsection", "backend": "SECRET LOCATOR BACKEND"}
    result, package, mapping = exported(tmp_path, bundle, runs)
    assert "SECRET" not in Path(result["public_package"]).read_text()
    assert all("model" not in evidence["locator"] for item in package["items"] for evidence in item["evidence"])
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    imported = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert imported["status"] == "complete"
    assert all(any(location["locator"].get("model") == "SECRET LOCATOR MODEL" for location in final["evidence_locations"]) for final in imported["final"])


def test_presented_output_hash_tamper_is_visible(tmp_path, bundle, runs):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    a[0]["presented_output_hash"] = digest({"behavior": "answer", "answer": "SYNTHETIC different answer"})
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert any(error["code"] == "presented_output_hash_mismatch" for error in result["errors"])
    assert all(final["item_id"] != a[0]["item_id"] for final in result["final"])


@pytest.mark.parametrize("kind", ["mapping-list", "mapping-item-list", "review-list", "pending-review"])
def test_malformed_annotations_remain_visible_instead_of_crashing(tmp_path, bundle, runs, kind):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    if kind == "mapping-list":
        mapping = []
    elif kind == "mapping-item-list":
        mapping["items"][next(iter(mapping["items"]))] = []
    elif kind == "review-list":
        a[0] = []
    else:
        a[0]["status"] = "pending"
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert result["status"] == "incomplete"
    assert result["errors"]


def test_duplicate_json_label_key_is_rejected_instead_of_last_value_winning(tmp_path, bundle, runs):
    from eval.independent.blind import import_reviews
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    text = "\n".join(json.dumps(row) for row in a)
    text = text.replace('"serious_error": false', '"serious_error": true, "serious_error": false', 1)
    path_a = tmp_path / "A.jsonl"
    path_a.write_text(text)
    result = import_reviews(bundle, runs, mapping, {"A": path_a, "B": write_jsonl(tmp_path / "B.jsonl", b)})
    assert any(error["code"] == "invalid_review_file" for error in result["errors"])
    assert result["final"] == []


@pytest.mark.parametrize("field,value", [("behavior", []), ("support_rate", 10 ** 400), ("error_types", {}), ("rationale", None)])
def test_malformed_label_values_are_reported_without_crashing(tmp_path, bundle, runs, field, value):
    _, package, mapping = exported(tmp_path, bundle, runs)
    a, b = review_rows(package, "anon-A"), review_rows(package, "anon-B")
    a[0]["labels"][field] = value
    result = import_pair(tmp_path, bundle, runs, mapping, a, b)
    assert result["status"] == "incomplete"
    assert result["errors"]
    assert all(f["item_id"] != a[0]["item_id"] for f in result["final"])


def test_nontext_evidence_cannot_leak_nested_identity(tmp_path, bundle, runs):
    from eval.independent.blind import export_blind
    runs[0]["rows"][0]["evidence"][0]["text"] = {"backend": "SECRET BACKEND"}
    with pytest.raises(ValueError, match="text"):
        export_blind(bundle, runs, tmp_path / "public", tmp_path / "private")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize('kind', ['forged-text', 'wrong-location'])
def test_export_rejects_known_source_with_forged_original_evidence(tmp_path, bundle, runs, kind):
    from eval.independent.blind import export_blind
    if kind == 'forged-text':
        runs[0]['rows'][0]['evidence'][0]['text'] = 'SYNTHETIC altered original finding.'
    else:
        runs[0]['rows'][0]['evidence'][0]['locator']['section'] = 'different-section'
    with pytest.raises(ValueError, match='source|locator|original'):
        export_blind(bundle, runs, tmp_path / 'public', tmp_path / 'private')
    assert not (tmp_path / 'public').exists()


def test_controlled_export_refuses_repository_destination(bundle, runs, tmp_path):
    from eval.independent.blind import export_blind
    from eval.run_p0 import ROOT
    bundle['asset_kind'] = 'controlled_clinical'
    for run in runs:
        run['asset_kind'] = bundle['asset_kind']
        run['dataset_hash'] = digest(bundle)
    with pytest.raises(ValueError, match='outside'):
        export_blind(bundle, runs, ROOT / 'data/eval_runs/unsafe-private-package', tmp_path / 'private')


def test_empty_or_partial_run_cannot_finalize_zero_reviews(tmp_path, bundle, runs):
    from eval.independent.blind import export_blind
    runs[0]['rows'] = []
    with pytest.raises(ValueError, match='omits'):
        export_blind(bundle, runs, tmp_path / 'public', tmp_path / 'private')


def test_output_without_answer_is_not_a_reviewable_success(tmp_path, bundle, runs):
    from eval.independent.blind import export_blind
    runs[0]['rows'][0]['output'].pop('answer')
    runs[0]['rows'][0]['output_hash'] = digest(runs[0]['rows'][0]['output'])
    with pytest.raises(ValueError, match='answer'):
        export_blind(bundle, runs, tmp_path / 'public', tmp_path / 'private')


def test_blind_output_preserves_visible_boundaries_and_refusal_next_steps(tmp_path, bundle, runs):
    for run in runs:
        row = run['rows'][0]
        row['output']['answer'] = {'paragraphs': [{'text': 'SYNTHETIC claim [1]', 'citation_ids': [1],
                                                   'claim_type': 'effect', 'certainty': 'low'}],
                                  'refusal_reason': '', 'limitations': ['SYNTHETIC boundary [1]'],
                                  'found': ['SYNTHETIC found'], 'missing': ['SYNTHETIC missing'],
                                  'next_steps': ['SYNTHETIC next step [2]'], 'model': 'SECRET MODEL'}
        row['output_hash'] = digest(row['output'])
    result, package, _ = exported(tmp_path, bundle, runs)
    answer = package['items'][0]['output']['answer']
    assert answer['limitations'][0].startswith('SYNTHETIC boundary [cite-')
    assert answer['next_steps'][0].startswith('SYNTHETIC next step [cite-')
    assert answer['found'] == ['SYNTHETIC found']
    assert answer['missing'] == ['SYNTHETIC missing']
    assert answer['paragraphs'][0]['claim_type'] == 'effect'
    assert answer['paragraphs'][0]['certainty'] == 'low'
    assert 'SECRET' not in Path(result['public_package']).read_text()
