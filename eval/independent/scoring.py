"""Independent quality reports with explicit evidence gaps and question-level pairing.

Human quality numbers only consume provenance-bound imported final judgments.
No clinical pass threshold is inferred from a fixture or the legacy P0 protocol.
"""

from __future__ import annotations

from collections import Counter
import math

from eval.metrics_v2 import paired_group_bootstrap, score_retrieval
from .assets import AssetValidationError, content_hash, validate_bundle
from .contracts import validate_output


REPORT_VERSION = "independent-quality-report-v1"
BEHAVIORS = ("answer", "qualified_answer", "refuse")
HUMAN_FIELDS = ("support_rate", "key_point_coverage", "numeric_correctness", "refusal_quality")
CRITICAL_ERRORS = {"wrong_citation", "numeric_direction_reversal", "serious_safety_error",
                   "phi_disclosure", "dangerous_advice"}
RETRIEVAL_FIELDS = {"recall_at_8": (8, "recall_at_k"), "ndcg_at_8": (8, "ndcg_at_k"),
                    "mrr_at_8": (8, "mrr_at_k"), "recall_at_40": (40, "recall_at_k")}


def _error(code, question_id=None, repeat=None, **details):
    result = {"code": code}
    if question_id is not None:
        result["question_id"] = question_id
    if repeat is not None:
        result["repeat"] = repeat
    result.update(details)
    return result


def _identity(run):
    return {"run_id": run.get("run_id"), "run_hash": content_hash(run),
            "system": run.get("system"), "dataset_hash": run.get("dataset_hash"),
            "protocol_hash": run.get("protocol_hash"),
            "corpus_manifest_hash": run.get("corpus_manifest_hash"),
            "rubric_version": run.get("rubric_version")}


def _run_rows(bundle, run):
    """Return trusted unique positions; invalid or duplicate positions stay gaps."""
    errors = []
    repeats = run.get("repeats")
    if type(repeats) is not int or repeats < 1:
        errors.append(_error("invalid_repeats"))
        repeats = 1
    expected = {q["id"] for q in bundle["questions"]}
    bindings = {"dataset_hash": content_hash(bundle), "protocol_hash": content_hash(bundle["protocol"]),
                "corpus_manifest_hash": bundle["corpus"]["manifest_hash"],
                "rubric_version": bundle["protocol"]["rubric_version"],
                "expected_count": len(expected) * repeats}
    identity_valid = True
    for field, value in bindings.items():
        if run.get(field) != value:
            errors.append(_error("run_%s_mismatch" % field, expected=value, actual=run.get(field)))
            identity_valid = False
    if not run.get("run_id") or not isinstance(run.get("system"), dict) or not run["system"]:
        errors.append(_error("missing_run_identity"))
        identity_valid = False
    rows, duplicate_keys = {}, set()
    raw_rows = run.get("rows")
    if not isinstance(raw_rows, list):
        errors.append(_error("invalid_run_rows", reason="rows must be a list"))
        raw_rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            errors.append(_error("invalid_run_row", reason="each row must be an object"))
            continue
        qid, repeat = row.get("question_id"), row.get("repeat")
        if not isinstance(qid, str) or qid not in expected:
            errors.append(_error("unknown_question_id", qid, repeat))
            continue
        if type(repeat) is not int or not 1 <= repeat <= repeats:
            errors.append(_error("invalid_repeat_position", qid, repeat))
            continue
        key = qid, repeat
        if key in rows or key in duplicate_keys:
            rows.pop(key, None)
            duplicate_keys.add(key)
            errors.append(_error("duplicate_run_position", qid, repeat))
            continue
        if row.get("status") not in ("success", "error", "skipped"):
            errors.append(_error("invalid_run_status", qid, repeat))
            continue
        if row["status"] == "success":
            output = row.get("output")
            if not isinstance(output, dict) or row.get("output_hash") != content_hash(output):
                errors.append(_error("run_output_hash_mismatch", qid, repeat))
                continue
            try:
                validate_output(output)
            except ValueError as exc:
                errors.append(_error("invalid_output_contract", qid, repeat, reason=str(exc)))
                continue
            ranking, evidence = row.get("ranked_source_ids"), row.get("evidence")
            if not isinstance(ranking, list) or not all(isinstance(s, str) and s for s in ranking):
                errors.append(_error("invalid_ranked_source_ids", qid, repeat))
                continue
            if not isinstance(evidence, list) or not all(
                isinstance(entry, dict) and isinstance(entry.get("source_id"), str) and entry["source_id"]
                and isinstance(entry.get("text"), str) and isinstance(entry.get("locator"), dict)
                for entry in evidence
            ):
                errors.append(_error("invalid_run_evidence", qid, repeat))
                continue
        rows[key] = row
    return rows, repeats, identity_valid, errors


def _location_pairs(evidence):
    return {(entry.get("source_id"), content_hash(entry.get("locator"))) for entry in evidence
            if isinstance(entry, dict) and isinstance(entry.get("source_id"), str)
            and isinstance(entry.get("locator"), dict) and entry["locator"]}


def _final_labels(bundle, run, rows, annotations, identity_valid):
    labels_by_key, errors, duplicate_keys = {}, [], set()
    summary = {field: [] for field in ("missing", "conflicts", "unjudgeable", "errors")}
    if annotations is None:
        return labels_by_key, errors, summary
    if not isinstance(annotations, dict):
        errors.append(_error("invalid_annotation_envelope"))
        return labels_by_key, errors, summary
    if not annotations:
        return labels_by_key, errors, summary
    try:
        content_hash(annotations)
    except AssetValidationError:
        errors.append(_error("annotation_not_finite_serializable_json"))
        return labels_by_key, errors, summary
    for field in summary:
        value = annotations.get(field, [])
        if isinstance(value, list):
            summary[field] = value
        else:
            errors.append(_error("invalid_annotation_summary", field=field))
    envelope_valid = identity_valid
    for field in ("dataset_hash", "protocol_hash"):
        if annotations.get(field) != run.get(field):
            errors.append(_error("annotation_%s_mismatch" % field))
            envelope_valid = False
    source_ids = {s["id"] for s in bundle["sources"]}
    run_hash = content_hash(run)
    finals = annotations.get("final")
    if not isinstance(finals, list):
        errors.append(_error("invalid_final_annotations"))
        return labels_by_key, errors, summary
    for final in finals:
        if not isinstance(final, dict):
            errors.append(_error("invalid_final_annotation"))
            continue
        # A shared import envelope can contain finals for several runs.
        if final.get("run_id") != run.get("run_id"):
            continue
        key = final.get("question_id"), final.get("repeat")
        qid, repeat = key
        if not isinstance(qid, str) or type(repeat) is not int:
            errors.append(_error("invalid_annotation_position", qid, repeat))
            continue
        row = rows.get(key)
        if key in labels_by_key or key in duplicate_keys:
            labels_by_key.pop(key, None)
            duplicate_keys.add(key)
            errors.append(_error("duplicate_final_annotation", qid, repeat))
            continue
        if not row or row["status"] != "success":
            errors.append(_error("annotation_unknown_output", qid, repeat))
            continue
        issues = []
        for unresolved in summary["missing"] + summary["conflicts"] + summary["unjudgeable"]:
            if not isinstance(unresolved, dict):
                continue
            if unresolved.get("run_id", run.get("run_id")) != run.get("run_id"):
                continue
            same_item = final.get("item_id") and unresolved.get("item_id") == final["item_id"]
            same_position = (unresolved.get("question_id") == qid and
                             unresolved.get("repeat", repeat) == repeat)
            if same_item or same_position:
                issues.append("annotation_resolution_incomplete")
                break
        for field, value in (("run_hash", run_hash), ("output_hash", row["output_hash"]),
                             ("rubric_version", bundle["protocol"]["rubric_version"])):
            if final.get(field) != value:
                issues.append("annotation_%s_mismatch" % field)
        if final.get("status") != "complete":
            issues.append("annotation_incomplete")
        reviewers = final.get("reviewer_ids", [])
        if (not isinstance(reviewers, list) or len(reviewers) != 2 or
                not all(isinstance(r, str) and r for r in reviewers) or len(set(reviewers)) != 2):
            issues.append("independent_double_review_missing")
        if final.get("annotation_origin") not in ("agreed", "adjudicated"):
            issues.append("annotation_resolution_missing")
        elif final["annotation_origin"] == "adjudicated":
            adjudicator = final.get("adjudicator_id")
            if (not isinstance(adjudicator, str) or not adjudicator.strip()
                    or (isinstance(reviewers, list) and adjudicator in reviewers)):
                issues.append("adjudicator_not_independent_or_missing")
            rationale = final.get("adjudication_rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                issues.append("adjudication_rationale_missing")
        evidence = row.get("evidence", [])
        expected_sources = {e.get("source_id") for e in evidence if isinstance(e, dict)}
        final_sources = final.get("source_ids")
        if (not isinstance(final_sources, list) or not all(isinstance(s, str) for s in final_sources)
                or set(final_sources) != expected_sources or not set(final_sources) <= source_ids):
            issues.append("annotation_source_mismatch")
        locations = final.get("evidence_locations")
        if (not isinstance(locations, list) or _location_pairs(locations) != _location_pairs(evidence)
                or len(_location_pairs(evidence)) < len(expected_sources)
                or (expected_sources and not _location_pairs(locations))):
            issues.append("annotation_evidence_location_missing_or_mismatch")
        labels = final.get("labels")
        if not isinstance(labels, dict):
            issues.append("annotation_labels_missing")
            labels = {}
        required_fields = set(HUMAN_FIELDS) | {"behavior", "serious_error", "error_types", "rationale"}
        if not required_fields <= set(labels):
            issues.append("annotation_label_fields_missing")
        rationale = labels.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            issues.append("annotation_rationale_missing")
        if labels.get("behavior") not in BEHAVIORS:
            issues.append("annotation_behavior_unjudgeable")
        for field in HUMAN_FIELDS:
            value = labels.get(field)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                                      or not 0 <= value <= 1):
                issues.append("annotation_%s_invalid" % field)
        serious = labels.get("serious_error")
        if serious is not None and type(serious) is not bool:
            issues.append("annotation_serious_error_invalid")
        error_types = labels.get("error_types")
        if not isinstance(error_types, list) or not all(isinstance(e, str) for e in error_types):
            issues.append("annotation_error_types_invalid")
        if issues or not envelope_valid:
            errors.extend(_error(issue, qid, repeat) for issue in issues)
            continue
        labels_by_key[key] = labels
    return labels_by_key, errors, summary


def _retrieval(row, qrels, family_ids, k, identity_valid):
    reason = None
    if not identity_valid:
        reason = "run_identity_invalid"
    elif row is None:
        reason = "missing_generation"
    elif row["status"] != "success":
        reason = "run_%s" % row["status"]
    elif not qrels:
        reason = "missing_qrels"
    elif (type(row.get("ranking_complete_k")) is not int or row["ranking_complete_k"] < k
          or (k == 40 and len(row.get("ranked_source_ids", [])) < 40)):
        reason = "ranking_incomplete"
    if reason:
        return {"k": k, "score_status": reason, "ranking_comparable": False,
                "recall_at_k": None, "ndcg_at_k": None, "mrr_at_k": None}
    scored = score_retrieval(row.get("ranked_source_ids", []), qrels, k=k)
    relevant_families = {family_ids[s] for s, grade in qrels.items() if grade >= 2}
    retrieved = {family_ids[slot["doc_id"]] for slot in scored["slots"]
                 if slot["status"] == "judged" and slot["relevance"] >= 2}
    scored.update(independent_relevant_sources=len(relevant_families),
                  retrieved_independent_relevant_sources=len(retrieved),
                  family_recall_at_k=len(retrieved) / len(relevant_families)
                  if relevant_families and scored["ranking_comparable"] else None)
    return scored


def _applicable(question, metric):
    declared = question["applicability"]
    behavior = question["expected_behavior"]
    if metric.startswith("retrieval."):
        # Refusal targets never enter a retrieval denominator, even if a malformed
        # configuration declares retrieval applicable.
        return behavior != "refuse" and declared.get("retrieval") is True
    field = metric.split(".", 1)[1]
    if field in ("behavior_accuracy", "serious_error_rate"):
        return True
    if field == "refusal_quality":
        return declared.get("refusal_quality", declared.get("refusal")) is True
    return behavior != "refuse" and declared.get(field, declared.get("answer_quality")) is True


def _aggregate(values, questions, repeats, metric):
    selected = [q for q in questions if _applicable(q, metric)]
    means, observed, excluded, valid_generations = {}, [], [], 0
    for question in selected:
        qid = question["id"]
        samples = values[metric][qid]
        available = [value for value in samples if value is not None]
        valid_generations += len(available)
        if available:
            observed.append(sum(available) / len(available))
        if len(available) == repeats:
            means[qid] = sum(available) / repeats
        else:
            excluded.append({"question_id": qid, "reason": "incomplete_evidence",
                             "expected_generations": repeats, "valid_generations": len(available)})
    complete = bool(selected) and not excluded
    return {"value": sum(means.values()) / len(means) if complete else None,
            "status": "scored" if complete else "not_applicable" if not selected else "evidence_insufficient",
            "expected_questions": len(selected), "valid_questions": len(means),
            "expected_generations": len(selected) * repeats, "valid_generations": valid_generations,
            "observed_mean": sum(observed) / len(observed) if observed else None,
            "observed_mean_scope": "descriptive_available_evidence_only",
            "question_means": means, "excluded": excluded}


def _build_single(bundle, run, annotations):
    rows, repeats, identity_valid, errors = _run_rows(bundle, run)
    labels, annotation_errors, summary = _final_labels(bundle, run, rows, annotations, identity_valid)
    errors.extend(annotation_errors)
    questions = bundle["questions"]
    qrels, families = {}, {}
    for qrel in bundle.get("qrels", []):
        qrels.setdefault(qrel["question_id"], {})[qrel["source_id"]] = qrel["grade"]
        families.setdefault(qrel["question_id"], {})[qrel["source_id"]] = qrel["study_family_id"]
    point_questions = {point["question_id"] for point in bundle.get("key_points", [])}
    metric_names = ["retrieval." + name for name in RETRIEVAL_FIELDS]
    metric_names += ["human." + name for name in HUMAN_FIELDS + ("behavior_accuracy", "serious_error_rate")]
    values = {name: {} for name in metric_names}
    details, blockers, skipped, insufficiency = {}, [], [], []
    for question in questions:
        qid = question["id"]
        detail = {"expected_behavior": question["expected_behavior"],
                  "question_group_id": question["question_group_id"], "topic": question["topic"],
                  "risk": question["risk"], "expected_generations": repeats,
                  "execution": [], "retrieval": [], "human": []}
        for name in metric_names:
            values[name][qid] = []
        for repeat in range(1, repeats + 1):
            key = qid, repeat
            row, judgment = rows.get(key), labels.get(key)
            status = row["status"] if row else "missing"
            reason = row.get("error_code") if status == "error" else row.get("skip_reason") if status == "skipped" else None
            detail["execution"].append({"repeat": repeat, "status": status, "reason": reason})
            if status == "skipped":
                skipped.append({"question_id": qid, "repeat": repeat,
                                "reason": reason or "unspecified_skip_reason"})
            if status != "success":
                insufficiency.append(_error("run_%s" % status, qid, repeat, reason=reason))
            scored = {"repeat": repeat}
            for k in (8, 40):
                scored["at_%d" % k] = _retrieval(row, qrels.get(qid, {}), families.get(qid, {}), k, identity_valid)
            detail["retrieval"].append(scored)
            for name, (k, field) in RETRIEVAL_FIELDS.items():
                values["retrieval." + name][qid].append(scored["at_%d" % k][field])
            human = {"repeat": repeat, "status": "complete" if judgment else "evidence_insufficient"}
            if not judgment:
                insufficiency.append(_error("missing_valid_independent_annotation", qid, repeat))
            for field in HUMAN_FIELDS:
                value = judgment.get(field) if judgment else None
                if field == "key_point_coverage" and qid not in point_questions:
                    value = None
                values["human." + field][qid].append(value)
                human[field] = value
            behavior = judgment.get("behavior") if judgment else None
            behavior_accuracy = float(behavior == question["expected_behavior"]) if behavior else None
            # A product-classified refusal cannot receive correct answer behavior
            # credit merely because a final label claims answer/qualified_answer.
            if row and status == "success" and row["output"]["behavior"] == "refuse" and question["expected_behavior"] != "refuse":
                behavior_accuracy = 0.0 if judgment else None
            values["human.behavior_accuracy"][qid].append(behavior_accuracy)
            serious = judgment.get("serious_error") if judgment else None
            values["human.serious_error_rate"][qid].append(float(serious) if serious is not None else None)
            human.update(behavior=behavior, behavior_accuracy=behavior_accuracy, serious_error=serious)
            detail["human"].append(human)
            if judgment:
                critical = sorted(set(judgment["error_types"]) & CRITICAL_ERRORS)
                if serious is True or critical:
                    blockers.append(_error("independently_annotated_critical_error", qid, repeat,
                                           error_types=critical, serious_error=serious))
        details[qid] = detail
    answerable_keys = [(q["id"], r) for q in questions if q["expected_behavior"] != "refuse"
                       for r in range(1, repeats + 1)]
    if answerable_keys and all(key in rows and rows[key]["status"] == "success" and
                              rows[key]["output"]["behavior"] == "refuse" for key in answerable_keys):
        blockers.append(_error("all_answerable_outputs_refused"))
    metrics = {"retrieval": {}, "human": {}}
    for name in metric_names:
        section, field = name.split(".")
        metrics[section][field] = _aggregate(values, questions, repeats, name)
    # Optional Recall@40 insufficiency remains visible, without turning an
    # explicitly Top-8 protocol into an implicit Top-40 gate.
    required = [metric for field, metric in metrics["human"].items() if metric["expected_questions"]]
    required += [metrics["retrieval"]["recall_at_8"]] if metrics["retrieval"]["recall_at_8"]["expected_questions"] else []
    incomplete = (not identity_valid or bool(errors) or bool(insufficiency) or
                  any(summary.values()) or any(m["status"] != "scored" for m in required))
    statuses = Counter(row["status"] for row in rows.values())
    executed = {qid for (qid, _), row in rows.items() if row["status"] in ("success", "error")}
    counts = {"expected_questions": len(questions), "independent_questions": len(questions),
              "expected_generations": len(questions) * repeats,
              "received_rows": len(run["rows"]) if isinstance(run.get("rows"), list) else 0,
              "executed_questions": len(executed),
              "executed_generations": statuses["success"] + statuses["error"],
              "successful_generations": statuses["success"], "run_errors": statuses["error"],
              "skipped_generations": statuses["skipped"],
              "missing_generations": len(questions) * repeats - len(rows),
              "valid_annotated_generations": len(labels),
              "valid_annotated_questions": sum(all((q["id"], r) in labels for r in range(1, repeats + 1)) for q in questions)}
    slices = {}
    for dimension in ("topic", "risk"):
        slices[dimension] = {}
        for label in sorted({q[dimension] for q in questions}):
            subset = [q for q in questions if q[dimension] == label]
            slices[dimension][label] = {name: _aggregate(values, subset, repeats, name) for name in metric_names}
    return {"schema_version": REPORT_VERSION, "scope": bundle["asset_kind"],
            "pilot_status": "not_executed" if bundle["asset_kind"] != "controlled_clinical" else "execution_not_certified",
            "clinical_quality_passed": None,
            "quality_decision": "blocked" if blockers else "evidence_insufficient" if incomplete else "ready_for_review",
            "decision_meaning": "Report readiness only; no clinical acceptance criterion or pass is inferred.",
            "identity": _identity(run), "expected_behavior_counts": {b: sum(q["expected_behavior"] == b for q in questions) for b in BEHAVIORS},
            "counts": counts, "metrics": metrics, "slices": slices, "questions": details,
            "errors": errors, "skipped": skipped, "evidence_insufficient": insufficiency,
            "annotations": summary, "blocking_reasons": blockers}, values


def _comparison(bundle, baseline, candidate, baseline_report, candidate_report):
    result = {"reference": _identity(baseline), "candidate": _identity(candidate),
              "status": "compared", "errors": [], "metrics": {}}
    for field in ("dataset_hash", "protocol_hash", "rubric_version", "corpus_manifest_hash"):
        if baseline.get(field) != candidate.get(field):
            result["errors"].append(_error("comparison_%s_mismatch" % field))
    before_system = baseline.get("system") if isinstance(baseline.get("system"), dict) else {}
    after_system = candidate.get("system") if isinstance(candidate.get("system"), dict) else {}
    before_source = before_system.get("source_hash")
    after_source = after_system.get("source_hash")
    result["product_source_identical"] = bool(before_source and before_source == after_source)
    result["mode"] = "different_product_source"
    result["cross_version_performance_claim"] = False
    if (not isinstance(before_source, str) or not before_source.strip()
            or not isinstance(after_source, str) or not after_source.strip()):
        result["errors"].append(_error("reference_source_identity_unavailable"))
    elif before_source == after_source:
        provenance = candidate.get("comparison") if isinstance(candidate.get("comparison"), dict) else {}
        reference_manifest = before_system.get("snapshot_manifest_hash")
        candidate_manifest = after_system.get("snapshot_manifest_hash")
        fixed_reference = (isinstance(reference_manifest, str) and reference_manifest.strip()
                           and isinstance(candidate_manifest, str) and candidate_manifest.strip()
                           and reference_manifest != candidate_manifest
                           and provenance.get("status") == "compared"
                           and provenance.get("reference_manifest_hash") == reference_manifest
                           and provenance.get("reference_system") == baseline.get("system")
                           and provenance.get("same_effective_data") is True
                           and provenance.get("same_protocol") is True)
        if fixed_reference:
            result["mode"] = "fixed_reference_same_product"
        else:
            result["errors"].append(_error("non_independent_reference"))
    if baseline_report["errors"] or candidate_report["errors"]:
        result["errors"].append(_error("comparison_invalid_run_or_annotations"))
    if result["errors"]:
        result["status"] = "incompatible"
        return result
    question_groups = {q["id"]: q["question_group_id"] for q in bundle["questions"]}
    for section in ("retrieval", "human"):
        for field, right_metric in candidate_report["metrics"][section].items():
            left_metric = baseline_report["metrics"][section][field]
            paired_ids = sorted(set(left_metric["question_means"]) & set(right_metric["question_means"]))
            expected_ids = {q["id"] for q in bundle["questions"] if _applicable(q, section + "." + field)}
            before, after = {}, {}
            for qid in paired_ids:
                group = question_groups[qid]
                before.setdefault(group, []).append(left_metric["question_means"][qid])
                after.setdefault(group, []).append(right_metric["question_means"][qid])
            interval = paired_group_bootstrap(before, after)
            missing = sorted(expected_ids - set(paired_ids))
            result["metrics"][section + "." + field] = {
                "status": "compared" if expected_ids and not missing else "not_applicable" if not expected_ids else "evidence_insufficient",
                "expected_questions": len(expected_ids), "paired_questions": len(paired_ids),
                "paired_question_ids": paired_ids, "excluded_question_ids": missing,
                "interval": interval, "interval_scope": "available_paired_question_means"}
            if missing:
                result["status"] = "evidence_insufficient"
    return result


def build_report(bundle, run, annotations=None, baseline_run=None, baseline_annotations=None):
    """Build a report without replacing missing judgments or deleting failures.

    ``annotations`` is the importer's resolution envelope, not runtime checks.
    Each repeat is averaged within its question before question-macro aggregation
    and paired group resampling. Imported labels with mismatched provenance are
    explicitly rejected. A reference with identical source identity is not an
    independent regression reference.
    """
    validation = validate_bundle(bundle)
    if not validation["valid"]:
        questions = bundle.get("questions", []) if isinstance(bundle, dict) else []
        expected_count = len(questions) if isinstance(questions, list) else 0
        return {"schema_version": REPORT_VERSION, "scope": bundle.get("asset_kind") if isinstance(bundle, dict) else None,
                "pilot_status": "not_executed", "clinical_quality_passed": None,
                "quality_decision": "evidence_insufficient", "asset_validation": validation,
                "counts": {"expected_questions": expected_count, "valid_annotated_generations": 0},
                "metrics": {}, "questions": {}, "errors": validation["errors"],
                "blocking_reasons": [], "annotations": {}, "skipped": [],
                "comparison": {"status": "incompatible", "errors": [_error("invalid_evaluation_assets")], "metrics": {}}}
    run_input_errors = []
    if not isinstance(run, dict):
        run_input_errors.append(_error("invalid_run_envelope", reason="run must be an object"))
    else:
        try:
            content_hash(run)
        except AssetValidationError:
            run_input_errors.append(_error("run_not_finite_serializable_json"))
    if run_input_errors:
        return {"schema_version": REPORT_VERSION, "scope": bundle["asset_kind"],
                "pilot_status": "not_executed", "clinical_quality_passed": None,
                "quality_decision": "evidence_insufficient", "asset_validation": validation,
                "counts": {"expected_questions": len(bundle["questions"]), "valid_annotated_generations": 0},
                "metrics": {}, "questions": {}, "errors": run_input_errors,
                "blocking_reasons": [], "annotations": {}, "skipped": [],
                "comparison": {"status": "incompatible", "errors": run_input_errors, "metrics": {}}}
    report, _ = _build_single(bundle, run, annotations)
    report["asset_validation"] = validation
    if baseline_run is None:
        report["comparison"] = {"status": "reference_unavailable", "errors": [], "metrics": {},
                                "reason": "No independently frozen reference run was supplied."}
    else:
        if not isinstance(baseline_run, dict):
            report["comparison"] = {"status": "incompatible", "errors": [_error("invalid_reference_run")], "metrics": {}}
            return report
        try:
            content_hash(baseline_run)
        except AssetValidationError:
            report["comparison"] = {"status": "incompatible", "errors": [_error("reference_not_finite_serializable_json")], "metrics": {}}
            return report
        baseline_report, _ = _build_single(bundle, baseline_run, baseline_annotations)
        report["comparison"] = _comparison(bundle, baseline_run, run, baseline_report, report)
        report["comparison"]["reference_counts"] = baseline_report["counts"]
        report["comparison"]["reference_quality_decision"] = baseline_report["quality_decision"]
    return report
