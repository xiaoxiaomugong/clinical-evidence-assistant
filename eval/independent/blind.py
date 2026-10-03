"""Whitelisted blind packages and independently retained double annotation.

Only synthetic fixtures belong in the repository. Real review packages, mappings,
original labels and adjudications are controlled assets of the evaluation lead.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import random
import re
import shutil

from .assets import content_hash, require_valid
from .contracts import ANSWER_LIST_FIELDS, ensure_artifact_location, validate_output


_QUESTION_FIELDS = ("id", "question", "topic", "language", "scenario", "risk", "as_of_date")
_OUTPUT_FIELDS = ("behavior", "answer", "refusal_code")
_EVIDENCE_FIELDS = ("source_id", "text", "locator", "citation_number")
_METRICS = ("support_rate", "key_point_coverage", "numeric_correctness", "refusal_quality")
_LABEL_FIELDS = ("behavior",) + _METRICS + ("serious_error", "error_types", "rationale")
_CRITICAL_ERRORS = {"wrong_citation", "numeric_direction_reversal", "serious_safety_error", "phi_disclosure", "dangerous_advice"}
_LOCATOR_FIELDS = {"file", "document_id", "field", "entry_id", "section", "page", "paragraph", "chapter",
                   "start", "end", "quote", "url", "title", "table", "figure", "doi", "pmid", "line", "lines"}
_CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def _whitelist(value, fields):
    return {field: copy.deepcopy(value[field]) for field in fields if field in value}


def _sanitize_locator(value):
    if isinstance(value, dict):
        return {key: _sanitize_locator(item) for key, item in value.items() if key in _LOCATOR_FIELDS}
    if isinstance(value, list):
        return [_sanitize_locator(item) for item in value if isinstance(item, (str, int, float, dict)) and not isinstance(item, bool)]
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return value
    return None


def _sanitize_output(output):
    if output is None:
        return None
    validate_output(output)
    result = _whitelist(output, _OUTPUT_FIELDS)
    answer = result.get("answer")
    if isinstance(answer, dict):
        clean = {}
        if "paragraphs" in answer:
            if not isinstance(answer["paragraphs"], list):
                raise ValueError("Output answer paragraphs must be a list")
            clean["paragraphs"] = []
            for paragraph in answer["paragraphs"]:
                if not isinstance(paragraph, dict) or not isinstance(paragraph.get("text"), str):
                    raise ValueError("Output paragraph requires authored text")
                citations = paragraph.get("citation_ids", [])
                if not isinstance(citations, list) or any(type(c) is not int and not (isinstance(c, str) and c.isdigit()) for c in citations):
                    raise ValueError("Output citation_ids must be integer citation references")
                clean["paragraphs"].append(_whitelist(paragraph, ('text', 'citation_ids', 'claim_type', 'certainty')))
        for field in ANSWER_LIST_FIELDS:
            if field in answer:
                clean[field] = copy.deepcopy(answer[field])
        if "refusal_reason" in answer:
            if not isinstance(answer["refusal_reason"], str):
                raise ValueError("Output refusal_reason must be authored text")
            clean["refusal_reason"] = answer["refusal_reason"]
        result["answer"] = clean
    elif answer is not None and not isinstance(answer, str):
        raise ValueError("Output answer must be text or a supported paragraph object")
    for field in ("behavior", "refusal_code"):
        if result.get(field) is not None and not isinstance(result[field], str):
            raise ValueError("Output %s must be a string or null" % field)
    return result


def _authored_texts(output):
    if output is None:
        return []
    answer = output.get("answer")
    if isinstance(answer, str):
        return [answer]
    if isinstance(answer, dict):
        return ([p["text"] for p in answer.get("paragraphs", [])] + [answer.get("refusal_reason", "")]
                + [text for field in ANSWER_LIST_FIELDS for text in answer.get(field, [])])
    return []


def _blind_records(records, seed):
    """Reproducible presentation derived only from a separately held seed."""
    rng = random.Random(seed)
    items, mapping_items = [], {}
    for record in records:
        item_id = "item-" + format(rng.getrandbits(128), "032x")
        while item_id in mapping_items:
            item_id = "item-" + format(rng.getrandbits(128), "032x")
        evidence, output = copy.deepcopy(record["evidence"]), copy.deepcopy(record["output"])
        original_ids = {str(item["citation_number"]) for item in evidence if "citation_number" in item}
        for authored_text in _authored_texts(output):
            for match in _CITATION_PATTERN.finditer(authored_text):
                original_ids.update(re.split(r"\s*[,;]\s*", match.group(1)))
        if output is not None and isinstance(output.get("answer"), dict):
            for paragraph in output["answer"].get("paragraphs", []):
                original_ids.update(str(c) for c in paragraph["citation_ids"])
        aliases = {}
        for original in sorted(original_ids):
            alias = "cite-" + format(rng.getrandbits(64), "016x")
            while alias in aliases.values():
                alias = "cite-" + format(rng.getrandbits(64), "016x")
            aliases[original] = alias

        def remap(text):
            return _CITATION_PATTERN.sub(lambda match: "[" + ", ".join(aliases[c] for c in re.split(r"\s*[,;]\s*", match.group(1))) + "]", text)

        if output is not None:
            if isinstance(output.get("answer"), str):
                output["answer"] = remap(output["answer"])
            elif isinstance(output.get("answer"), dict):
                for paragraph in output["answer"].get("paragraphs", []):
                    paragraph["text"] = remap(paragraph["text"])
                    paragraph["citation_ids"] = [aliases[str(c)] for c in paragraph["citation_ids"]]
                if "refusal_reason" in output["answer"]:
                    output["answer"]["refusal_reason"] = remap(output["answer"]["refusal_reason"])
                for field in ANSWER_LIST_FIELDS:
                    if field in output['answer']:
                        output['answer'][field] = [remap(text) for text in output['answer'][field]]
        for item in evidence:
            if "citation_number" in item:
                item["citation_number"] = aliases[str(item["citation_number"])]
        rng.shuffle(evidence)
        presented_hash = content_hash(output)
        mapped = copy.deepcopy(record)
        mapped.update({"original_to_public": aliases, "presented_output": output,
                       "presented_output_hash": presented_hash, "presented_evidence_locations": _locations(evidence)})
        mapping_items[item_id] = mapped
        items.append({"item_id": item_id, "question_id": record["question_id"], "question": record["question"],
                      "output": output, "output_hash": record["output_hash"], "presented_output_hash": presented_hash,
                      "run_hash": record["run_hash"], "execution_status": record["status"], "evidence": evidence})
    rng.shuffle(items)
    return items, mapping_items


def _source_ids(evidence):
    return sorted({item["source_id"] for item in evidence})


def _locations(evidence):
    unique = {}
    for item in evidence:
        location = {"source_id": item["source_id"], "locator": copy.deepcopy(item.get("locator"))}
        unique[content_hash(location)] = location
    return [unique[key] for key in sorted(unique)]


def _run_records(bundle, runs):
    """Check bindings before releasing a package or accepting an annotation."""
    require_valid(bundle)
    if isinstance(runs, dict):
        runs = [runs]
    if not isinstance(runs, (list, tuple)) or not runs:
        raise ValueError("At least one run is required")
    questions = {q["id"]: q for q in bundle["questions"]}
    sources = {source["id"]: source for source in bundle["sources"]}
    expected = {"dataset_hash": content_hash(bundle), "protocol_hash": content_hash(bundle["protocol"]),
                "rubric_version": bundle["protocol"]["rubric_version"],
                "corpus_manifest_hash": bundle["corpus"]["manifest_hash"]}
    records, run_ids, keys = [], set(), set()
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str) or not run["run_id"].strip():
            raise ValueError("Run must have a nonempty run_id")
        if run["run_id"] in run_ids:
            raise ValueError("Duplicate run_id: " + run["run_id"])
        run_ids.add(run["run_id"])
        for field, value in expected.items():
            if run.get(field) != value:
                raise ValueError("Run %s %s mismatch" % (run["run_id"], field))
        run_hash = content_hash(run)
        rows = run.get("rows")
        if not isinstance(rows, list):
            raise ValueError("Run rows must be a list")
        repeats = run.get('repeats')
        if type(repeats) is not int or repeats < 1 or run.get('expected_count') != len(questions) * repeats:
            raise ValueError('Run declared question/repeat denominator mismatch')
        required_positions = {(qid, repeat) for qid in questions for repeat in range(1, repeats + 1)}
        positions = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Run row must be an object")
            qid = row.get("question_id")
            if not isinstance(qid, str) or qid not in questions:
                raise ValueError("Unknown question_id: " + str(qid))
            repeat = row.get("repeat")
            if type(repeat) is not int or not 1 <= repeat <= repeats:
                raise ValueError("Row repeat must be in declared 1..repeats")
            positions.add((qid, repeat))
            key = (run["run_id"], qid, repeat)
            if key in keys:
                raise ValueError("Duplicate question/repeat in run: " + str(key))
            keys.add(key)
            if row.get("status") not in {"success", "error", "skipped"}:
                raise ValueError("Unknown execution status")
            output = row.get("output")
            if row["status"] == "success" and not isinstance(output, dict):
                raise ValueError("Successful row must contain an output")
            if output is not None and row.get("output_hash") != content_hash(output):
                raise ValueError("Row output_hash mismatch")
            if output is None and row.get("output_hash") is not None:
                raise ValueError("Null output must have null output_hash")
            evidence = row.get("evidence", [])
            if not isinstance(evidence, list):
                raise ValueError("Row evidence must be a list")
            for item in evidence:
                if not isinstance(item, dict) or not isinstance(item.get('source_id'), str) or item['source_id'] not in sources:
                    raise ValueError("Unknown evidence source_id")
                source = sources[item['source_id']]
                text, locator = item.get('text'), item.get('locator')
                if not isinstance(text, str) or not text.strip() or text not in source['text']:
                    raise ValueError("Evidence text does not match frozen original source text")
                if not isinstance(locator, dict) or not locator:
                    raise ValueError('Evidence original locator is missing')
                if any(locator.get(field) != value for field, value in source['locator'].items()):
                    raise ValueError('Evidence locator differs from frozen source identity')
                if 'start' in locator or 'end' in locator:
                    start, end = locator.get('start'), locator.get('end')
                    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source['text']) or source['text'][start:end] != text:
                        raise ValueError('Evidence original source offsets mismatch')
                if 'quote' in locator and locator['quote'] != text:
                    raise ValueError('Evidence original source quote mismatch')
            records.append({"run_id": run["run_id"], "question_id": qid, "repeat": repeat,
                            "status": row["status"], "output_hash": row.get("output_hash"),
                            "run_hash": run_hash, "system": copy.deepcopy(run.get("system")),
                            "rubric_version": expected["rubric_version"],
                            "source_ids": _source_ids(evidence), "evidence_locations": _locations(evidence),
                            "question": _whitelist(questions[qid], _QUESTION_FIELDS),
                            "output": _sanitize_output(output),
                            "evidence": [{**_whitelist(item, _EVIDENCE_FIELDS), "locator": _sanitize_locator(item.get("locator"))} for item in evidence]})
        if positions != required_positions:
            raise ValueError('Run omits declared question/repeat positions; report missing executions before export')
    return records, expected


def _write_private(path, value):
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def export_blind(bundle, runs, public_dir, private_dir, seed=0):
    """Write a reviewer package and a separate private mapping without overwrite.

    The public package contains neither reference labels nor identities. All
    identifiers and evidence order are shuffled reproducibly by the private seed.
    Hashes bind a returned annotation to the original complete output and run.
    """
    ensure_artifact_location(bundle, public_dir, private_dir)
    public_dir, private_dir = Path(public_dir).resolve(), Path(private_dir).resolve()
    if public_dir == private_dir or public_dir in private_dir.parents or private_dir in public_dir.parents:
        raise ValueError("Public and private destination directories overlap")
    if public_dir.exists() or private_dir.exists():
        raise FileExistsError("Blind export destination already exists; use new directories")
    if type(seed) is not int:
        raise ValueError("Seed must be an integer")
    records, expected = _run_records(bundle, runs)
    items, mapping_items = _blind_records(records, seed)
    package_id = content_hash({"dataset_hash": expected["dataset_hash"], "items": items})
    package = {"schema_version": "independent-review-package-v1", "package_id": package_id,
               "asset_kind": bundle["asset_kind"], "dataset_hash": expected["dataset_hash"],
               "protocol_version": bundle["protocol"]["version"], "rubric_version": expected["rubric_version"],
               "notice": "SYNTHETIC engineering acceptance only; no clinical quality claim" if bundle["asset_kind"] == "synthetic_engineering" else "Controlled independent review; reference assets held by evaluation lead",
               "items": items}
    mapping = {"schema_version": "independent-private-mapping-v1", "package_id": package_id,
               "seed": seed, **expected, "items": mapping_items}
    template = []
    for item in items:
        template.append({"item_id": item["item_id"], "question_id": item["question_id"], "reviewer_id": "",
                         "rubric_version": expected["rubric_version"], "output_hash": item["output_hash"],
                         "run_hash": item["run_hash"], "presented_output_hash": item["presented_output_hash"],
                         "source_ids": _source_ids(item["evidence"]),
                         "evidence_locations": _locations(item["evidence"]),
                         "labels": {"behavior": None, **{metric: None for metric in _METRICS},
                                    "serious_error": None, "error_types": [], "rationale": ""}})
    created = []
    try:
        private_dir.mkdir(parents=True, mode=0o700)
        os.chmod(str(private_dir), 0o700)
        created.append(private_dir)
        _write_private(private_dir / "mapping.json", mapping)
        public_dir.mkdir(parents=True)
        created.append(public_dir)
        with (public_dir / "review_package.json").open("x", encoding="utf-8") as handle:
            json.dump(package, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        with (public_dir / "review_template.jsonl").open("x", encoding="utf-8") as handle:
            for record in template:
                handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    except Exception:
        for directory in reversed(created):
            shutil.rmtree(directory)
        raise
    return {"public_package": str(public_dir / "review_package.json"),
            "review_template": str(public_dir / "review_template.jsonl"),
            "private_mapping": str(private_dir / "mapping.json"), "item_count": len(items), "package_id": package_id}


def _parse_json(text):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key: " + key)
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Non-finite JSON number: " + value)

    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def _read_json(path):
    return _parse_json(Path(path).read_text(encoding="utf-8"))


def _read_reviews(path):
    if path is None:
        return []
    if isinstance(path, list):
        return copy.deepcopy(path)
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        result = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    result.append(_parse_json(line))
                except ValueError as exc:
                    raise ValueError("%s line %d: %s" % (path.name, number, exc))
        return result
    value = _read_json(path)
    if isinstance(value, dict):
        value = value.get("reviews", value.get("adjudications"))
    if not isinstance(value, list):
        raise ValueError("Annotation JSON must be a list or contain a reviews/adjudications list")
    return value


def import_reviews(bundle, runs, private_mapping, review_paths, adjudication_path=None):
    """Preserve A/B originals, exposing missing/invalid/unresolved annotations.

    Invalid bindings never yield finals. Agreement compares all independent
    labels, including rationale; differing labels require a third person and an
    explicit adjudication rationale. Explicit null measurements stay null.
    """
    result = {"schema_version": "independent-annotations-v1", "dataset_hash": content_hash(bundle),
              "protocol_hash": content_hash(bundle["protocol"]), "rubric_version": bundle["protocol"]["rubric_version"],
              "original_reviews": {"A": [], "B": []}, "original_adjudications": [],
              "final": [], "missing": [], "conflicts": [], "unjudgeable": [], "errors": [], "status": "incomplete"}

    def error(code, message, item_id=None, role=None):
        value = {"code": code, "message": message}
        if item_id is not None:
            value["item_id"] = item_id
        if role is not None:
            value["reviewer_role"] = role
        result["errors"].append(value)

    try:
        records, expected = _run_records(bundle, runs)
        mapping = copy.deepcopy(private_mapping) if isinstance(private_mapping, dict) else _read_json(private_mapping)
        if not isinstance(mapping, dict):
            raise ValueError("Private mapping must be an object")
        if mapping.get("schema_version") != "independent-private-mapping-v1":
            raise ValueError("Unknown private mapping schema")
        for field, value in expected.items():
            if mapping.get(field) != value:
                raise ValueError("Private mapping %s mismatch" % field)
        mapped = mapping.get("items")
        if not isinstance(mapped, dict):
            raise ValueError("Private mapping must contain items")
        if type(mapping.get("seed")) is not int:
            raise ValueError("Private mapping requires its original seed")
        presented_items, expected_mapped = _blind_records(records, mapping["seed"])
        if mapped != expected_mapped:
            raise ValueError("Private mapping does not match current run/output/evidence or original presentation")
        if mapping.get("package_id") != content_hash({"dataset_hash": expected["dataset_hash"], "items": presented_items}):
            raise ValueError("Private mapping package hash mismatch")
    except (ValueError, TypeError, KeyError, OSError, UnicodeError) as exc:
        error("mapping_run_mismatch", str(exc))
        return result

    if isinstance(review_paths, dict):
        paths = {"A": review_paths.get("A"), "B": review_paths.get("B")}
        if set(review_paths) - {"A", "B"}:
            error("invalid_review_roles", "Only independent A/B files are accepted")
            return result
    elif isinstance(review_paths, (list, tuple)) and len(review_paths) <= 2:
        paths = {"A": review_paths[0] if review_paths else None,
                 "B": review_paths[1] if len(review_paths) == 2 else None}
    else:
        error("invalid_review_roles", "Provide A/B paths or a list of up to two independent files")
        return result
    for role, path in paths.items():
        try:
            result["original_reviews"][role] = _read_reviews(path)
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            error("invalid_review_file", str(exc), role=role)
    try:
        result["original_adjudications"] = _read_reviews(adjudication_path)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        error("invalid_adjudication_file", str(exc))

    reviewers = {role: {row.get("reviewer_id") for row in rows if isinstance(row, dict) and isinstance(row.get("reviewer_id"), str) and row["reviewer_id"].strip()}
                 for role, rows in result["original_reviews"].items()}
    overlapping = reviewers["A"] & reviewers["B"]
    if overlapping:
        error("reviewer_not_independent", "Reviewer IDs overlap across A/B roles for the package")

    def validate(record, role):
        if not isinstance(record, dict):
            error("invalid_review", "Annotation must be an object", role=role)
            return False
        item_id = record.get("item_id")
        item = mapped.get(item_id) if isinstance(item_id, str) else None
        if item is None:
            error("unknown_item", "Annotation refers to an unknown item", item_id, role)
            return False
        before = len(result["errors"])
        for field, code in (("question_id", "question_mismatch"), ("output_hash", "output_hash_mismatch"),
                            ("run_hash", "run_hash_mismatch"), ("rubric_version", "rubric_mismatch"),
                            ("presented_output_hash", "presented_output_hash_mismatch")):
            if record.get(field) != item[field]:
                error(code, "Annotation %s does not match the exported item" % field, item_id, role)
        reviewer = record.get("reviewer_id")
        if not isinstance(reviewer, str) or not reviewer.strip():
            error("missing_reviewer_id", "Nonempty anonymous reviewer ID required", item_id, role)
        source_ids = record.get("source_ids")
        if not isinstance(source_ids, list) or any(not isinstance(s, str) for s in source_ids) or sorted(set(source_ids)) != item["source_ids"]:
            error("source_mismatch", "Annotation source IDs differ from exported evidence", item_id, role)
        locations = record.get("evidence_locations")
        if item["source_ids"] and not locations:
            error("missing_evidence_locations", "Evidence locations are required", item_id, role)
        elif not isinstance(locations, list) or any(not isinstance(loc, dict) or not isinstance(loc.get("locator"), dict) or not loc["locator"] for loc in locations) or sorted(content_hash(loc) for loc in locations) != sorted(content_hash(loc) for loc in item["presented_evidence_locations"]):
            error("evidence_location_mismatch", "Annotation locations differ or original evidence lacks a locator", item_id, role)
        if "status" in record and record["status"] not in {"complete", "unjudgeable"}:
            error("invalid_review_status", "Only complete or unjudgeable annotation status is accepted", item_id, role)
        labels = record.get("labels")
        invalid = not isinstance(labels, dict) or set(labels) != set(_LABEL_FIELDS)
        if not invalid:
            invalid = not isinstance(labels["behavior"], str) or labels["behavior"] not in {"answer", "qualified_answer", "refuse", "unjudgeable"}
            for metric in _METRICS:
                value = labels[metric]
                if value is not None and (type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value)):
                    invalid = True
            invalid = invalid or (labels["serious_error"] is not None and type(labels["serious_error"]) is not bool)
            invalid = invalid or not isinstance(labels["error_types"], list) or any(not isinstance(t, str) or not t.strip() for t in labels["error_types"])
            invalid = invalid or not isinstance(labels["rationale"], str) or not labels["rationale"].strip()
        if invalid:
            error("invalid_labels", "Labels require explicit behavior, bounded/null metrics, serious error, types and rationale", item_id, role)
        elif _CRITICAL_ERRORS.intersection(labels["error_types"]) and labels["serious_error"] is not True:
            error("critical_error_conflict", "Critical error type cannot be annotated as no serious error", item_id, role)
        if role == "adjudicator":
            if reviewer in reviewers["A"] | reviewers["B"]:
                error("adjudicator_not_independent", "Adjudicator must be distinct from every A/B reviewer in this package", item_id, role)
            if not isinstance(record.get("adjudication_rationale"), str) or not record["adjudication_rationale"].strip():
                error("missing_adjudication_rationale", "Adjudication needs a separate resolution rationale", item_id, role)
        if len(result["errors"]) != before:
            return False
        if labels["behavior"] == "unjudgeable" or labels["serious_error"] is None or record.get("status") == "unjudgeable":
            result["unjudgeable"].append({"item_id": item_id, "reviewer_role": role, "reason": "Reviewer could not make a complete safety/behavior judgment"})
            return False
        return True

    indexed, valid = {}, {}
    for role, rows in list(result["original_reviews"].items()) + [("adjudicator", result["original_adjudications"])]:
        indexed[role], valid[role] = {}, {}
        duplicate = set()
        for record in rows:
            item_id = record.get("item_id") if isinstance(record, dict) else None
            accepted = validate(record, role)
            if isinstance(item_id, str) and item_id in indexed[role]:
                duplicate.add(item_id)
                error("duplicate_review", "Multiple annotations for the same item in one role", item_id, role)
            elif isinstance(item_id, str):
                indexed[role][item_id] = record
                valid[role][item_id] = accepted
        for item_id in duplicate:
            valid[role][item_id] = False

    for item_id, item in mapped.items():
        missing_roles = [role for role in ("A", "B") if item_id not in indexed[role]]
        if missing_roles:
            result["missing"].append({"item_id": item_id, "reviewer_roles": missing_roles})
        if item["status"] != "success":
            result["unjudgeable"].append({"item_id": item_id, "reason": "execution_" + item["status"]})
            continue
        if overlapping or missing_roles or not all(valid[role].get(item_id) for role in ("A", "B")):
            continue
        a, b = indexed["A"][item_id], indexed["B"][item_id]
        origin, chosen = "agreed", a
        if a["labels"] != b["labels"]:
            if not valid["adjudicator"].get(item_id):
                result["conflicts"].append({"item_id": item_id, "reviewer_ids": [a["reviewer_id"], b["reviewer_id"]],
                                            "labels_A": copy.deepcopy(a["labels"]), "labels_B": copy.deepcopy(b["labels"]),
                                            "status": "awaiting_adjudication"})
                continue
            origin, chosen = "adjudicated", indexed["adjudicator"][item_id]
        elif item_id in indexed["adjudicator"]:
            error("unexpected_adjudication", "No disagreement exists for this item", item_id, "adjudicator")
        final = {key: copy.deepcopy(item[key]) for key in ("run_id", "question_id", "repeat", "output_hash", "presented_output_hash", "run_hash", "rubric_version", "source_ids", "evidence_locations")}
        final.update({"item_id": item_id, "status": "complete", "annotation_origin": origin,
                      "reviewer_ids": [a["reviewer_id"], b["reviewer_id"]], "labels": copy.deepcopy(chosen["labels"])})
        if origin == "adjudicated":
            final.update({"adjudicator_id": chosen["reviewer_id"], "adjudication_rationale": chosen["adjudication_rationale"]})
        result["final"].append(final)
    if not any(result[key] for key in ("missing", "conflicts", "unjudgeable", "errors")) and len(result["final"]) == len(mapped):
        result["status"] = "complete"
    return result
