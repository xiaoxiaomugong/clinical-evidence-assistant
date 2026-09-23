"""Freeze inputs and evaluate P0 arms in clean, network-denied child processes.

Example: python -m eval.run_p0 --output data/eval_runs/NEW --profiles C0 C1
Dataset format: JSON list (or {"questions": [...]}) with unique id/question fields.
Optional graded qrels: {"version": "...", "qrels": {"question_id": {"doc_id": 0..3}}}.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

from eval.run_record import NONDETERMINISTIC_FIELDS, semantic_digest, summarize_results, write_json

ROOT = Path(__file__).resolve().parents[1]
BASELINE_ID = "20260919T092741Z-p0-1cc225b"
BASELINE_COMMIT = "1cc225b3e606e516df289daff96883e92b49a57f"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_run_directory(output: Path) -> Path:
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    return output


def clean_environment(code_root: Path, cache: Path, source_root: Path = None) -> dict:
    """Allowlist constructed from constants and paths, never inherited credentials."""
    source_root = source_root or code_root
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(cache / "home"),
        "TMPDIR": str(cache / "tmp"), "LANG": "en_US.UTF-8",
        "PYTHONPATH": os.pathsep.join(map(str, (source_root / "src", code_root))),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "EVIDENCE_ASSISTANT_ENV_FILE": os.devnull,
        "CLINICAL_EVIDENCE_ROOT": str(code_root), "ENABLE_LIVE_APIS": "false",
        "ENABLE_SUPABASE": "false", "LLM_API_KEY": "", "PUBMED_API_KEY": "",
        "NCBI_EMAIL": "", "SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": "",
        "SUPABASE_SECRET_KEY": "", "MODEL_LOCAL_FILES_ONLY": "true",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "HF_HOME": str(cache / "models"), "XDG_CACHE_HOME": str(cache),
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false", "CEA_ISOLATED_WORKER": "1",
    }


def _copy(source: Path, destination: Path, manifest: list) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = sha256(source)
    shutil.copy2(source, destination)
    after = sha256(source)
    if before != after or sha256(destination) != before:
        raise ValueError("Input changed while freezing: " + str(source))
    manifest.append({"source": str(source), "path": str(destination), "sha256": before,
                     "bytes": destination.stat().st_size})


def freeze_inputs(run: Path, baseline: Path, dataset: Path, qrels: Path = None,
                  index: Path = None, include_pdf: bool = True, include_b0: bool = True) -> dict:
    files = []
    for name in ("local_corpus.json",):
        _copy(baseline / "frozen/data/raw" / name, run / "frozen/data/raw" / name, files)
    for source in sorted((baseline / "frozen/data/knowledge_pages").glob("*.json")):
        _copy(source, run / "frozen/data/knowledge_pages" / source.name, files)
    _copy(baseline / "frozen/data/corpus_version.json", run / "frozen/data/corpus_version.json", files)
    _copy(dataset, run / "frozen/eval/dataset.json", files)
    if qrels:
        _copy(qrels, run / "frozen/eval/qrels.json", files)
    if include_pdf:
        _copy(baseline / "frozen/data/raw/pdf_collection.sqlite3", run / "frozen/data/raw/pdf_collection.sqlite3", files)
    if index:
        _copy(index, run / "frozen/data/raw/pdf_collection_vnext.sqlite3", files)
    for source in sorted((run / "frozen/data/raw").glob("*.sqlite3")):
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("Frozen SQLite integrity check failed")
    # Snapshot current source too: a developer edit during a long run cannot mix implementations.
    current = run / "code/current"
    for directory in ("src", "eval"):
        for source in sorted((ROOT / directory).rglob("*.py")):
            _copy(source, current / source.relative_to(ROOT), files)
    for name in ("config.py", "pyproject.toml"):
        _copy(ROOT / name, current / name, files)
    if include_b0:
        archive = subprocess.check_output(["git", "archive", BASELINE_COMMIT, "src", "config.py"], cwd=ROOT)
        historical = run / "code/B0"
        historical.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            for member in bundle.getmembers():
                target = historical / member.name
                if Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                    raise ValueError("Unsafe archive path")
                if member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.extractfile(member).read())
                    files.append({"source": "git:" + BASELINE_COMMIT + ":" + member.name,
                                  "path": str(target), "sha256": sha256(target), "bytes": target.stat().st_size})
    write_json(run / "input_manifest.json", files)
    return {"files": files, "snapshot_scope": "evaluation dataset, knowledge, local corpus, index, source; PDF binaries not copied"}


def verify_frozen(files: list) -> dict:
    changed = [record["path"] for record in files if sha256(Path(record["path"])) != record["sha256"]]
    source_changed = [record["source"] for record in files if not record["source"].startswith("git:")
                      and sha256(Path(record["source"])) != record["sha256"]]
    return {"frozen_unchanged": not changed, "changed_frozen_paths": changed,
            "source_unchanged": not source_changed, "changed_source_paths": source_changed}


def read_rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _semantic_result(row):
    return {key: row.get(key) for key in ("run_status", "answer_status", "legacy", "pipeline", "graded")}


def engineering_gates(baseline: dict, candidate: dict, original_pairs_retained=None) -> dict:
    def compare(metric):
        before, after = baseline["quality"][metric]["value"], candidate["quality"][metric]["value"]
        return {"passed": after >= before if before is not None and after is not None else None,
                "baseline": before, "candidate": after}
    recall = candidate["quality"]["recall_at_8"]["value"]
    previous, outcomes = baseline.get("question_outcomes", {}), candidate.get("question_outcomes", {})
    mismatched, evaluated = [], 0
    for qid in sorted(set(previous) | set(outcomes)):
        outcome = outcomes.get(qid, {})
        expected = previous.get(qid, {}).get("expected_answer_status") or outcome.get("expected_answer_status")
        if expected is not None:
            evaluated += 1
        if outcome.get("run_status") != "success" or (expected is not None and outcome.get("answer_status") != expected):
            mismatched.append(qid)
    return {"recall_regression": compare("recall_at_8"), "ndcg_regression": compare("ndcg_at_8"),
            "coverage_regression": compare("key_point_coverage"),
            "retrieval_benefit": {"passed": recall >= .875 if recall is not None else None, "target": .875, "value": recall},
            "original_retention": {"passed": original_pairs_retained == 5 if original_pairs_retained is not None else None,
                                    "numerator": original_pairs_retained, "denominator": 5},
            "answer_behavior": {"passed": not mismatched if evaluated or mismatched else None,
                                "evaluated_count": evaluated, "mismatched_ids": mismatched,
                                "counts_equal_diagnostic": candidate["answer_counts"] == baseline["answer_counts"]},
            "run_errors": {"passed": candidate["status_counts"]["error"] == 0},
            "independent_safety_review": {"passed": None, "reason": "Not evaluated by this runner"}}


def build_summary(run: Path, profiles: list, arms: list, commands: list, frozen_check: dict) -> dict:
    configurations, stability, baseline_alignment, gates, performance = {}, {}, {}, {}, {}
    for profile in profiles:
        for arm in arms:
            key = profile + "/" + arm
            repeats = [read_rows(run / profile / arm / ("repeat_%d/results.jsonl" % repeat)) for repeat in (1, 2)]
            configurations[key] = summarize_results(repeats[0])
            left, right = ({row["question_id"]: semantic_digest(_semantic_result(row)) for row in rows} for rows in repeats)
            stability[key] = {"stable": bool(left) and left == right,
                              "mismatched_ids": sorted(qid for qid in set(left) | set(right) if left.get(qid) != right.get(qid)),
                              "ignored_fields": sorted(NONDETERMINISTIC_FIELDS), "independent_repetitions": False}
            performance_path = run / profile / arm / "performance/performance.json"
            if performance_path.exists():
                measured = json.loads(performance_path.read_text())
                performance[key] = {**measured, "profiles": [{k: v for k, v in group.items() if k not in {"samples", "refusal_fast_path"}}
                                                               for group in measured.get("profiles", [])]}
        if "B0" in arms and "B1" in arms:
            old = {row["question_id"]: row for row in read_rows(run / profile / "B0/repeat_1/results.jsonl")}
            current = {row["question_id"]: row for row in read_rows(run / profile / "B1/repeat_1/results.jsonl")}
            differences = [qid for qid in set(old) | set(current) if
                           semantic_digest(_semantic_result(old.get(qid, {}))) != semantic_digest(_semantic_result(current.get(qid, {})))]
            baseline_alignment[profile] = {"aligned": bool(old) and not differences, "mismatched_ids": sorted(differences)}
    diagnostics = {}
    known_pairs = {"q002": "31132793", "q003": "31132793", "q004": "39651989", "q014": "39651989", "q013": "34024117"}
    for profile in profiles:
        for arm in arms:
            candidates = read_rows(run / profile / arm / "repeat_1/candidates.jsonl")
            matches = {}
            for qid, pmid in known_pairs.items():
                matches[qid] = any(row.get("question_id") == qid and row.get("stage") == "pool_after"
                                   and row.get("phase") == "final" and pmid in str(row.get("doc_id", ""))
                                   and row.get("source") != "knowledge_page" for row in candidates)
            diagnostics[profile + "/" + arm] = {"known_original_pairs": matches if arm != "B0" else None,
                "retained_count": sum(matches.values()) if arm != "B0" else None, "expected_count": 5,
                "q008": [row for row in candidates if row.get("question_id") == "q008" and
                         row.get("stage") in {"reranked", "top8"} and "29507099" in str(row.get("doc_id", ""))]}
    for profile in profiles:
        baseline = configurations.get(profile + "/B0") or configurations.get(profile + "/B1")
        if baseline:
            for arm in arms:
                key = profile + "/" + arm
                gates[key] = engineering_gates(baseline, configurations[key], diagnostics[key]["retained_count"])
        baseline_perf = next((p for p in performance.get(profile + "/B1", {}).get("profiles", []) if p["concurrency"] == 1), None)
        if baseline_perf:
            before = baseline_perf["all_requests"]["p95_ms"]
            for arm in arms:
                key = profile + "/" + arm
                candidate_perf = next((p for p in performance.get(key, {}).get("profiles", []) if p["concurrency"] == 1), None)
                if candidate_perf:
                    after = candidate_perf["all_requests"]["p95_ms"]
                    performance[key]["relative_to_B1_p95"] = {"ratio": after / before if before else None,
                                                                "review_alarm": after > before * 1.2 if before else None}
    return {"scope": "P0 engineering regression; not independent clinical validation",
            "configurations": configurations, "repeat_stability": stability,
            "baseline_alignment": baseline_alignment, "candidate_diagnostics": diagnostics,
            "engineering_gates": gates, "performance": performance,
            "commands": commands, "artifact_integrity": frozen_check,
            "failed_commands": [command for command in commands if command["exit_code"]],
            "formal_quality": {"status": "N/A", "reason": "Independent labels, reviewer judgments and blind sets unavailable"}}


def write_report(run: Path, summary: dict) -> None:
    lines = ["# P0 isolated offline evaluation", "", summary["scope"], "",
             "| Configuration | success/error/skipped | Recall@8 (hits/qrels) | nDCG@8 | legacy lexical coverage | answered/refused |", "|---|---|---|---|---|---|"]
    def display(value):
        return "N/A" if value is None else "%.6f" % value
    for key, value in summary["configurations"].items():
        counts, quality, answers = value["status_counts"], value["quality"], value["answer_counts"]
        hits = value["legacy_relevant_source_hits"]
        lines.append("| %s | %d/%d/%d | %s (%d/%d) | %s | %s | %d/%d |" % (
            key, counts["success"], counts["error"], counts["skipped"], display(quality["recall_at_8"]["value"]), hits["numerator"], hits["denominator"],
            display(quality["ndcg_at_8"]["value"]), display(quality["key_point_coverage"]["value"]), answers["answered"], answers["refused"]))
    lines += ["", "All metric values and denominators are computed from the first repeat in summary.json. The second repeat only checks determinism.",
              "", "Baseline alignment: " + json.dumps(summary["baseline_alignment"], ensure_ascii=False),
              "", "Repeat stability: " + json.dumps({key: value["stable"] for key, value in summary["repeat_stability"].items()}),
              "", "Artifact integrity: " + json.dumps(summary["artifact_integrity"], ensure_ascii=False),
              "", "Network audit covers Python socket/process audit events. It does not prove absence of OS-level packets.",
              "", "Legacy Top-40, formal clinical quality, independent review, blind-set intervals and unmeasured GPU performance: N/A.",
              "", "B0 is archived historical code and cannot expose historical raw generation or internal stages. B1 is the recorder equivalence arm."]
    for key, gates in summary["engineering_gates"].items():
        failed = [name for name, gate in gates.items() if gate["passed"] is False]
        if failed:
            lines.append("\n%s failed engineering gates: %s." % (key, ", ".join(failed)))
    lines.append("\nCoverage/citation/support metrics are legacy engineering rule proxies. Error-inclusive behavior/coverage denominators are in intention_to_evaluate; they do not count skips.")
    (run / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True, type=Path, help="New output directory; must not exist")
    parser.add_argument("--profiles", nargs="+", choices=("C0", "C1"), default=["C0", "C1"])
    parser.add_argument("--arms", nargs="+", choices=("B0", "B1", "R1", "I1", "G1", "R2", "D1", "RD"), default=["B0", "B1", "R1", "I1", "G1", "R2"])
    parser.add_argument("--baseline", type=Path, default=ROOT / "data/eval_runs" / BASELINE_ID)
    parser.add_argument("--dataset", type=Path, help="Explicit controlled dataset; default frozen historical 15 questions")
    parser.add_argument("--qrels", type=Path, help="Optional independent graded qrels; never rewrites legacy qrels")
    parser.add_argument("--index", type=Path, help="Candidate corpus SQLite for D1/RD only")
    parser.add_argument("--performance", action="store_true", help="Also run concurrency 1/4, 10 warmups and >=100 trials")
    parser.add_argument("--trials", type=int, default=120)
    parser.add_argument("--save-questions", action="store_true", help="Persist controlled deidentified dataset text in recorder")
    args = parser.parse_args(argv)
    if args.performance and args.trials < 100:
        parser.error("--trials must be at least 100")
    if any(arm in {"D1", "RD"} for arm in args.arms) and (args.index is None or args.profiles != ["C1"]):
        parser.error("D1/RD require --index and --profiles C1")
    if len(set(args.profiles)) != len(args.profiles) or len(set(args.arms)) != len(args.arms):
        parser.error("Duplicate profiles/arms are not allowed")
    if args.output.resolve() == args.baseline.resolve() or args.baseline.resolve() in args.output.resolve().parents:
        parser.error("Output must be outside the historical baseline directory")
    from eval.offline_runner import load_dataset
    dataset = (args.dataset or args.baseline / "frozen/eval/test_set.json").resolve()
    load_dataset(dataset)
    run = create_run_directory(args.output)
    baseline_hashes = {str(path.relative_to(args.baseline)): sha256(path)
                       for path in sorted(args.baseline.rglob("*")) if path.is_file()}
    write_json(run / "baseline_artifact_hashes.json", baseline_hashes)
    frozen = freeze_inputs(run, args.baseline.resolve(), dataset, args.qrels, args.index,
                           include_pdf="C1" in args.profiles, include_b0="B0" in args.arms)
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD", "--", "src", "eval", "tests", "scripts", ".github", "pyproject.toml"], cwd=ROOT)
    (run / "workspace.patch").write_bytes(diff)
    manifest = {"run_id": run.name, "baseline_run_id": args.baseline.name,
                "baseline_commit": BASELINE_COMMIT, "created_at": datetime.now(timezone.utc).isoformat(),
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "workspace_diff_sha256": hashlib.sha256(diff).hexdigest(),
                "input_manifest_sha256": sha256(run / "input_manifest.json"),
                "baseline_artifact_hashes_sha256": sha256(run / "baseline_artifact_hashes.json"),
                "dataset_sha256": sha256(run / "frozen/eval/dataset.json"),
                "qrels_version": "explicit graded qrels" if args.qrels else "frozen embedded binary legacy labels",
                "qrels_sha256": sha256(run / "frozen/eval/qrels.json") if args.qrels else None,
                "scorers": {name: sha256(run / "code/current/eval" / name) for name in ("metrics.py", "metrics_v2.py") if (run / "code/current/eval" / name).exists()},
                "python": sys.version, "dependencies": dict(sorted((dist.metadata["Name"], dist.version) for dist in importlib.metadata.distributions())),
                "hardware": {"platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor() or None,
                             "cpu_count": os.cpu_count(), "power_mode": None, "gpu": "not_evaluated"},
                "seed": 0, "repeats": 2, "mode": "hybrid", "profiles": args.profiles, "arms": args.arms,
                "settings_protocol": "All Settings fields explicitly assigned and schema-checked in each worker; secret fields excluded from settings.json",
                "historical_gate_bypass": "B1/R1/D1 use the frozen legacy source-count rule and bypass Top5 recheck; I1 uses current source-count safety but bypasses Top5; worker instances only; B0 runs archived code",
                "diagnostic_arm_I1": "R1 + hardened source identity; G1 = I1 + actual Top5 gate. Added to isolate the safety correction found during review.",
                "input_scope": frozen["snapshot_scope"]}
    write_json(run / "manifest.json", manifest)
    commands = []
    for profile in args.profiles:
        for arm in args.arms:
            actions = [(repeat, 0) for repeat in (1, 2)]
            if args.performance and arm != "B0":
                actions.append((0, args.trials))
            for repeat, trials in actions:
                label = "performance" if trials else "repeat_%d" % repeat
                cache = run / "runtime_cache" / profile / arm / label
                for directory in (cache / "home", cache / "tmp"):
                    directory.mkdir(parents=True)
                code = run / "code/current"
                env = clean_environment(code, cache, run / "code/B0" if arm == "B0" else code)
                command = [sys.executable, "-m", "eval.offline_runner", "--run", str(run), "--profile", profile,
                           "--arm", arm, "--repeat", str(repeat)]
                if trials:
                    command += ["--performance", str(trials)]
                if args.save_questions:
                    command += ["--save-questions"]
                log = run / "logs" / (profile + "_" + arm + "_" + label + ".log")
                log.parent.mkdir(exist_ok=True)
                print("RUN %s %s %s" % (profile, arm, label), flush=True)
                with log.open("w", encoding="utf-8") as handle:
                    completed = subprocess.run(command, env=env, cwd=code, stdout=handle, stderr=subprocess.STDOUT)
                commands.append({"profile": profile, "arm": arm, "repeat": repeat, "action": label,
                                 "exit_code": completed.returncode, "log": str(log.relative_to(run))})
                write_json(run / "commands.json", commands)
    integrity = verify_frozen(frozen["files"])
    changed_baseline = [path for path, expected in baseline_hashes.items()
                        if not (args.baseline / path).exists() or sha256(args.baseline / path) != expected]
    integrity.update({"baseline_artifacts_unchanged": not changed_baseline, "changed_baseline_paths": changed_baseline})
    summary = build_summary(run, args.profiles, args.arms, commands, integrity)
    write_json(run / "summary.json", summary)
    write_report(run, summary)
    manifest["settings"] = {str(path.relative_to(run)): json.loads(path.read_text()) for path in run.glob("*/*/*/settings.json")}
    write_json(run / "manifest.json", manifest)
    print(str(run / "report.md"), flush=True)
    return 1 if summary["failed_commands"] or not integrity["frozen_unchanged"] or changed_baseline else 0


if __name__ == "__main__":
    raise SystemExit(main())
