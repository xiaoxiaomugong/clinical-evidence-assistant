"""Import and validate versioned independent evaluation assets.

This module validates structure and explicit leakage relationships. It never
generates labels, reads a hidden blind set, or certifies clinical quality.
"""

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path


SCHEMA_VERSION = "independent-eval-v1"
TABLES = ("questions", "sources", "qrels", "key_points")
BEHAVIORS = ("answer", "qualified_answer", "refuse")
ASSET_KINDS = ("synthetic_engineering", "draft_development", "controlled_clinical")


class AssetValidationError(ValueError):
    """A readable validation failure with machine-readable error entries."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join("{path}: {message} [{code}]".format(**row) for row in errors))


def _issue(code, path, message):
    return {"code": code, "path": path, "message": message}


def content_hash(value):
    """SHA-256 of canonical finite JSON; insertion order is insignificant."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise AssetValidationError([_issue("not_json_serializable", "$", "Value must be finite, serializable JSON")]) from exc
    return hashlib.sha256(encoded).hexdigest()


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("Repeated object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _parse_json(text, path):
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        # A syntactically valid exponent such as 1e999 can overflow to infinity
        # without invoking parse_constant. Apply the same canonical contract as
        # hashes before an imported value can be presented as valid JSON.
        content_hash(value)
        return value
    except _DuplicateKey as exc:
        raise AssetValidationError([_issue("duplicate_json_key", str(path), "JSON object contains a repeated key")]) from exc
    except (ValueError, RecursionError) as exc:
        message = "Invalid JSON"
        if isinstance(exc, json.JSONDecodeError):
            message += " at line {}, column {}".format(exc.lineno, exc.colno)
        raise AssetValidationError([_issue("invalid_json", str(path), message)]) from exc


def _read_json(path):
    try:
        return _parse_json(path.read_text(encoding="utf-8"), path)
    except (OSError, UnicodeError) as exc:
        raise AssetValidationError([_issue("read_error", str(path), "Cannot read UTF-8 asset file")]) from exc


def _read_table(path, table):
    if path.suffix == ".jsonl":
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise AssetValidationError([_issue("read_error", str(path), "Cannot read UTF-8 asset file")]) from exc
        result = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            record_path = "{}:{}".format(path, line_number)
            row = _parse_json(line, record_path)
            if not isinstance(row, dict):
                raise AssetValidationError([_issue("invalid_type", record_path, "JSONL records must be objects")])
            result.append(row)
        return result
    result = _read_json(path)
    if isinstance(result, dict) and set(result) == {table}:
        result = result[table]
    if not isinstance(result, list):
        raise AssetValidationError([_issue("invalid_type", str(path), "Table must be a JSON array")])
    return result


def load_bundle(path):
    """Read a JSON bundle or directory of manifest/protocol and JSON(L) tables.

    Import does not silently repair data or grant validation. Call
    ``require_valid`` before running a bundle.
    """
    try:
        path = Path(path)
    except TypeError as exc:
        raise AssetValidationError([_issue("invalid_path", "$", "Asset path must be a filesystem path")]) from exc
    if not path.is_dir():
        bundle = _read_json(path)
        if not isinstance(bundle, dict):
            raise AssetValidationError([_issue("invalid_type", str(path), "Bundle must be a JSON object")])
        return bundle
    bundle = _read_json(path / "manifest.json")
    if not isinstance(bundle, dict):
        raise AssetValidationError([_issue("invalid_type", str(path / "manifest.json"), "Manifest must be a JSON object")])
    protocol_path = path / "protocol.json"
    if protocol_path.exists():
        protocol = _read_json(protocol_path)
        if "protocol" in bundle and bundle["protocol"] != protocol:
            raise AssetValidationError([_issue("conflicting_label", str(protocol_path), "Protocol conflicts with manifest protocol")])
        bundle["protocol"] = protocol
    for table in TABLES:
        candidates = [candidate for candidate in (path / (table + ".json"), path / (table + ".jsonl")) if candidate.exists()]
        if len(candidates) > 1:
            raise AssetValidationError([_issue("ambiguous_table", str(path / table), "Both JSON and JSONL table files exist")])
        if candidates:
            value = _read_table(candidates[0], table)
            if table in bundle and bundle[table] != value:
                raise AssetValidationError([_issue("conflicting_label", str(candidates[0]), "Table conflicts with manifest table")])
            bundle[table] = value
    return bundle


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class _Validator:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.manual_review = []

    def error(self, code, path, message):
        self.errors.append(_issue(code, path, message))

    def string(self, record, field, path):
        value = record.get(field)
        if not _nonempty(value):
            code = "missing_field" if value is None or value == "" else "invalid_type"
            self.error(code, path + "." + field, "Required nonempty string")
            return None
        if (field == "id" or field.endswith("_id")) and any(character.isspace() for character in value):
            self.error("invalid_id", path + "." + field, "Stable IDs must not contain whitespace")
            return None
        return value

    def string_list(self, record, field, path):
        value = record.get(field)
        if not isinstance(value, list):
            self.error("invalid_type", path + "." + field, "Required list of nonempty strings")
            return []
        result = []
        for index, item in enumerate(value):
            if not _nonempty(item):
                self.error("invalid_type", "{}.{}[{}]".format(path, field, index), "Expected nonempty string")
            else:
                result.append(item)
        if len(result) != len(set(result)):
            self.error("duplicate_id", path + "." + field, "List contains repeated values")
        return result

    def mapping(self, record, field, path):
        value = record.get(field)
        if not isinstance(value, dict):
            self.error("invalid_type", path + "." + field, "Required JSON object")
            return {}
        return value

    def records(self, bundle, table):
        values = bundle.get(table)
        if not isinstance(values, list):
            self.error("invalid_type", table, "Required list of objects")
            return []
        result = []
        for index, value in enumerate(values):
            path = "{}[{}]".format(table, index)
            if not isinstance(value, dict):
                self.error("invalid_type", path, "Expected JSON object")
            else:
                result.append((path, value))
        return result

    def locator(self, value, path, text=None):
        if not isinstance(value, dict) or not value:
            self.error("missing_locator", path, "A nonempty original-text locator is required")
            return
        for key, part in value.items():
            if not _nonempty(key) or not (_nonempty(part) or _finite_number(part)):
                self.error("invalid_locator", path, "Locator keys and values must identify an original-text position")
        if "quote" in value:
            quote = value["quote"]
            if not _nonempty(quote) or (isinstance(text, str) and quote not in text):
                self.error("locator_mismatch", path, "Locator quote is absent from the referenced source text")
        if "start" in value or "end" in value:
            start, end = value.get("start"), value.get("end")
            valid = type(start) is int and type(end) is int and 0 <= start < end
            if isinstance(text, str):
                valid = valid and end <= len(text)
            if not valid:
                self.error("locator_mismatch", path, "Locator offsets must be a valid source-text interval")
            elif "quote" in value and isinstance(text, str) and text[start:end] != value["quote"]:
                self.error("locator_mismatch", path, "Locator quote does not match its source-text interval")

    def result(self):
        return {"valid": not self.errors, "errors": self.errors, "warnings": self.warnings, "manual_review": self.manual_review}


def _hash_field(validator, value, path):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        validator.error("invalid_hash", path, "Expected lowercase SHA-256 hex digest")
        return False
    return True


def _index_records(validator, records):
    result = {}
    for path, row in records:
        identifier = validator.string(row, "id", path)
        if identifier is None:
            continue
        if identifier in result:
            validator.error("duplicate_id", path + ".id", "ID is already present in this table")
        else:
            result[identifier] = row
    return result


def _check_ref(validator, value, known, path):
    if _nonempty(value) and value not in known:
        validator.error("unknown_id", path, "ID does not exist in the referenced table")


def _check_leakage(validator, questions):
    groups = {}
    semantics = {}
    texts = {}
    parents = {}
    for identifier, question in questions.items():
        split = question.get("split")
        group = question.get("question_group_id")
        if _nonempty(group) and _nonempty(split):
            groups.setdefault(group, []).append((identifier, split))
        family = question.get("semantic_family_id")
        if family is not None and not _nonempty(family):
            validator.error("invalid_type", "questions.{}.semantic_family_id".format(identifier), "Expected nonempty string")
        if _nonempty(family) and _nonempty(split):
            semantics.setdefault(family, []).append((identifier, split))
        text = question.get("question")
        if _nonempty(text) and _nonempty(split):
            normalized = " ".join(text.casefold().split())
            texts.setdefault(normalized, []).append((identifier, split))
        raw = question.get("derived_from", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            validator.error("invalid_type", "questions.{}.derived_from".format(identifier), "Expected parent ID or list of parent IDs")
            raw = []
        parents[identifier] = []
        for parent in raw:
            path = "questions.{}.derived_from".format(identifier)
            if not _nonempty(parent):
                validator.error("invalid_type", path, "Expected nonempty parent question ID")
            elif parent not in questions:
                validator.error("unknown_id", path, "Parent question ID does not exist")
            else:
                parents[identifier].append(parent)
    for group, members in groups.items():
        if len({split for _, split in members}) > 1:
            validator.error("cross_split_group_leakage", "question_groups." + group, "One question group occurs across different splits")
    for members in texts.values():
        if len({split for _, split in members}) > 1:
            validator.error("cross_split_duplicate_question", "questions", "Identical normalized question text occurs across different splits")
        elif len({questions[identifier].get("question_group_id") for identifier, _ in members
                  if _nonempty(questions[identifier].get("question_group_id"))}) > 1:
            validator.error("conflicting_question_groups", "questions", "Identical normalized question text in one split must share one question group; independent groups would inflate the sample")
    for family, members in semantics.items():
        if len({split for _, split in members}) > 1:
            validator.manual_review.append(_issue("semantic_leakage_review", "semantic_families." + family, "Declared semantic family crosses splits; independent owner must review question IDs " + ", ".join(identifier for identifier, _ in members)))
    splits = {question.get("split") for question in questions.values() if _nonempty(question.get("split"))}
    if "dev" in splits and "blind" in splits:
        validator.manual_review.append(_issue("semantic_leakage_audit_required", "questions", "Independent owner must review semantic overlap between development and blind questions; ID and derivation checks cannot certify absence of semantic leakage. Shared guideline citations alone do not establish leakage."))
    # Iterative ancestor traversal also handles malformed cycles and long chains
    # without turning a validation request into a Python recursion error.
    cycles = set()
    for identifier in parents:
        stack = [(identifier, iter(parents[identifier]))]
        active = {identifier}
        visited = set()
        ancestors = set()
        while stack:
            node, remaining = stack[-1]
            try:
                parent = next(remaining)
            except StopIteration:
                stack.pop()
                active.remove(node)
                visited.add(node)
                continue
            ancestors.add(parent)
            if parent in active:
                cycle_key = tuple(sorted(active))
                if cycle_key not in cycles:
                    validator.error("derived_cycle", "questions.{}.derived_from".format(identifier), "Derived-question graph contains a cycle")
                    cycles.add(cycle_key)
            elif parent not in visited:
                active.add(parent)
                stack.append((parent, iter(parents[parent])))
        if any(questions[ancestor].get("split") != questions[identifier].get("split") for ancestor in ancestors):
            validator.error("derived_leakage", "questions.{}.derived_from".format(identifier), "Question and a direct or transitive parent occur in different splits")


def validate_bundle(bundle, corpus_manifest_hash=None):
    """Return explicit errors, evidence-gap warnings and manual review items."""
    validator = _Validator()
    if not isinstance(bundle, dict):
        validator.error("invalid_type", "$", "Bundle must be a JSON object")
        return validator.result()
    try:
        content_hash(bundle)
    except AssetValidationError as exc:
        validator.errors.extend(exc.errors)
    if bundle.get("schema_version") != SCHEMA_VERSION:
        validator.error("schema_version", "schema_version", "Unsupported independent evaluation schema")
    if bundle.get("asset_kind") not in ASSET_KINDS:
        validator.error("asset_kind", "asset_kind", "Expected synthetic_engineering, draft_development or controlled_clinical")
    validator.string(bundle, "dataset_id", "$")
    protocol = validator.mapping(bundle, "protocol", "$")
    validator.string(protocol, "version", "protocol")
    validator.string(protocol, "rubric_version", "protocol")
    corpus = validator.mapping(bundle, "corpus", "$")
    profile = validator.string(corpus, "profile", "corpus")
    manifest_hash = corpus.get("manifest_hash")
    _hash_field(validator, manifest_hash, "corpus.manifest_hash")
    if corpus_manifest_hash is not None:
        _hash_field(validator, corpus_manifest_hash, "expected_corpus_manifest_hash")
        if manifest_hash != corpus_manifest_hash:
            validator.error("corpus_hash_mismatch", "corpus.manifest_hash", "Bundle does not match the supplied corpus manifest hash")

    tables = {table: validator.records(bundle, table) for table in TABLES}
    questions = _index_records(validator, tables["questions"])
    sources = _index_records(validator, tables["sources"])
    _index_records(validator, tables["key_points"])
    if not tables["questions"]:
        validator.error("empty_questions", "questions", "At least one question is required")

    for path, source in tables["sources"]:
        text = validator.string(source, "text", path)
        validator.locator(source.get("locator"), path + ".locator", text)
    for path, question in tables["questions"]:
        for field in ("question_group_id", "question", "topic", "language", "scenario", "risk", "as_of_date", "corpus_profile", "expected_reason", "annotation_status"):
            validator.string(question, field, path)
        if question.get("split") not in ("dev", "blind", "synthetic"):
            validator.error("invalid_split", path + ".split", "Expected dev, blind or synthetic")
        behavior = question.get("expected_behavior")
        if behavior not in BEHAVIORS:
            validator.error("invalid_behavior", path + ".expected_behavior", "Expected answer, qualified_answer or refuse")
        raw_date = question.get("as_of_date")
        if isinstance(raw_date, str):
            try:
                parsed = date.fromisoformat(raw_date)
                if parsed.isoformat() != raw_date:
                    raise ValueError("Non-canonical date")
            except ValueError:
                validator.error("invalid_date", path + ".as_of_date", "Expected a valid YYYY-MM-DD date")
        question_hash = question.get("corpus_manifest_hash")
        _hash_field(validator, question_hash, path + ".corpus_manifest_hash")
        if question_hash != manifest_hash:
            validator.error("corpus_hash_mismatch", path + ".corpus_manifest_hash", "Question corpus hash differs from bundle corpus hash")
        if question.get("corpus_profile") != profile:
            validator.error("corpus_profile_mismatch", path + ".corpus_profile", "Question corpus profile differs from bundle corpus profile")
        allowed = validator.string_list(question, "allowed_refusal_codes", path)
        validator.string_list(question, "forbidden_conclusions", path)
        applicability = validator.mapping(question, "applicability", path)
        for field in ("retrieval", "answer_quality", "refusal"):
            if type(applicability.get(field)) is not bool:
                validator.error("invalid_type", path + ".applicability." + field, "Applicability must be explicitly boolean")
        for field, value in applicability.items():
            if field not in ("retrieval", "answer_quality", "refusal") and type(value) is not bool:
                validator.error("invalid_type", path + ".applicability." + str(field), "Optional metric applicability must be explicitly boolean")
        if behavior == "refuse" and applicability.get("retrieval") is True:
            validator.error("conflicting_label", path + ".applicability.retrieval", "Expected-refusal questions cannot enter the retrieval denominator")
        if behavior == "refuse" and not allowed:
            validator.error("conflicting_label", path + ".allowed_refusal_codes", "Expected refusal requires at least one allowed refusal code")
        status = question.get("annotation_status")
        if isinstance(status, str) and ("draft" in status or "unreviewed" in status):
            validator.warnings.append(_issue("unreviewed_asset", path + ".annotation_status", "Question is draft/unreviewed; no confirmed clinical label is implied"))

    seen_qrels = {}
    qrels_by_question = {}
    source_families = {}
    for path, qrel in tables["qrels"]:
        question_id = validator.string(qrel, "question_id", path)
        source_id = validator.string(qrel, "source_id", path)
        _check_ref(validator, question_id, questions, path + ".question_id")
        _check_ref(validator, source_id, sources, path + ".source_id")
        grade = qrel.get("grade")
        if type(grade) is not int or not 0 <= grade <= 3:
            validator.error("invalid_grade", path + ".grade", "Relevance grade must be an integer from 0 to 3")
        for field in ("study_family_id", "evidence_role", "rationale"):
            validator.string(qrel, field, path)
        family = qrel.get("study_family_id")
        if source_id is not None and _nonempty(family):
            if source_id in source_families and source_families[source_id] != family:
                validator.error("conflicting_label", path + ".study_family_id", "One source must retain the same study-family identity across questions")
            else:
                source_families[source_id] = family
        source = sources.get(source_id, {}) if source_id is not None else {}
        validator.locator(qrel.get("locator"), path + ".locator", source.get("text"))
        if question_id is not None and source_id is not None:
            pair = (question_id, source_id)
            if pair in seen_qrels:
                code = "duplicate_id" if seen_qrels[pair] == qrel else "conflicting_label"
                validator.error(code, path, "Question/source pair has repeated or conflicting qrels")
            else:
                seen_qrels[pair] = qrel
            qrels_by_question.setdefault(question_id, []).append(qrel)

    points_by_question = {}
    for path, point in tables["key_points"]:
        question_id = validator.string(point, "question_id", path)
        _check_ref(validator, question_id, questions, path + ".question_id")
        validator.string(point, "text", path)
        if point.get("necessity") not in ("required", "optional"):
            validator.error("invalid_necessity", path + ".necessity", "Expected required or optional")
        weight = point.get("weight")
        if not _finite_number(weight) or weight <= 0:
            validator.error("invalid_weight", path + ".weight", "Weight must be a finite positive number")
        supporting = validator.string_list(point, "support_source_ids", path)
        if not supporting:
            validator.error("missing_support", path + ".support_source_ids", "Reference key point requires at least one supporting source")
        for source_id in supporting:
            _check_ref(validator, source_id, sources, path + ".support_source_ids")
            qrel = seen_qrels.get((question_id, source_id)) if question_id is not None else None
            if qrel is not None and type(qrel.get("grade")) is int and qrel["grade"] == 0:
                validator.error("conflicting_label", path + ".support_source_ids", "Reference key point cites a source explicitly judged irrelevant to this question")
        scope = point.get("scope")
        if not (_nonempty(scope) or isinstance(scope, dict) and bool(scope)):
            validator.error("missing_field", path + ".scope", "Applicable scope must be a nonempty string or object")
        if question_id is not None:
            points_by_question.setdefault(question_id, []).append(point)

    _check_leakage(validator, questions)
    for identifier, question in questions.items():
        applicability = question.get("applicability")
        if not isinstance(applicability, dict):
            continue
        if applicability.get("retrieval") is True and not qrels_by_question.get(identifier):
            validator.warnings.append(_issue("missing_qrels", "questions." + identifier, "Retrieval is applicable but qrels are absent; retrieval scoring is evidence-insufficient"))
        if applicability.get("answer_quality") is True and not points_by_question.get(identifier):
            validator.warnings.append(_issue("missing_key_points", "questions." + identifier, "Answer quality is applicable but reference key points are absent"))
    return validator.result()


def require_valid(bundle, corpus_manifest_hash=None):
    """Reject structural/explicit leakage errors; retain visible evidence gaps."""
    report = validate_bundle(bundle, corpus_manifest_hash=corpus_manifest_hash)
    if not report["valid"]:
        raise AssetValidationError(report["errors"])
    return bundle
