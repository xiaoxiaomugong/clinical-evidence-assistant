# 第二轮实施契约与计划

用户已明确授权实施完整 A–D；沿用所给范围，当前工作树承接 `07d3be39`，不用 8890 作开发目录。预改动参考为 `data/eval_runs/iteration2-reference-07d3be3-20261003`，不可覆盖。该轮验收为合成工程验收，真实试点未执行。

## 模块接口（Python 3.9，标准库，无新增产品依赖）

- `eval/independent/assets.py`: `load_bundle(path) -> dict`, `validate_bundle(bundle, corpus_manifest_hash=None) -> dict`（`valid`, `errors`, `manual_review`）, `require_valid(bundle, corpus_manifest_hash=None)`, `content_hash(value) -> str`。JSON 单文件 bundle 或目录中的 manifest.json/protocol.json 与 questions/qrels/key_points/sources.json[l]；不要读取真实盲集。
- bundle: `schema_version='independent-eval-v1'`, `asset_kind='synthetic_engineering'|'draft_development'|'controlled_clinical'`, `dataset_id`, `protocol`（`version`, `rubric_version`）, `corpus`（`profile`, `manifest_hash`）, `questions`, `sources`, `qrels`, `key_points`。
- question: `id`, `question_group_id`, `split`（dev/blind/synthetic）, `question`, `topic`, `language`, `scenario`, `risk`, `as_of_date`, `corpus_profile`, `corpus_manifest_hash`, `expected_behavior`（answer/qualified_answer/refuse）, `expected_reason`, `allowed_refusal_codes`, `forbidden_conclusions`, `applicability`（retrieval/answer_quality/refusal），可选 `derived_from`, `semantic_family_id`；`annotation_status` 标记 synthetic 或 draft/unreviewed。
- source: `id`, `text`, `locator`（非空对象，原文定位）；qrel: `question_id`, `source_id`, `grade`（严格整数0–3）, `study_family_id`, `evidence_role`, `locator`, `rationale`；key point: `id`, `question_id`, `text`, `necessity`（required/optional）, `weight`, `support_source_ids`, `scope`。
- run: `schema_version`, `run_id`, `asset_kind`, `dataset_hash`, `protocol_hash`, `rubric_version`, `corpus_manifest_hash`, `system`（源码身份）, `expected_count`, `repeats`, `rows`。row: `question_id`, `repeat`, `status`（success/error/skipped）, `error_code`/`skip_reason`, `output`（`behavior`, `answer`, `refusal_code`）, `output_hash`, `ranked_source_ids`, `ranking_complete_k`, `evidence`（`source_id`, `text`, `locator`）。正文哈希严格 canonical JSON；无关时间不进入输出哈希。
- `eval/independent/blind.py`: `export_blind(bundle, runs, public_dir, private_dir, seed=0) -> dict`, `import_reviews(bundle, runs, private_mapping, review_paths, adjudication_path=None) -> dict`。两个目录不可相含且不可覆盖；公开包按白名单构造，隐藏参考/原排名/身份；每题输出匿名 item_id。标签包含 item_id, reviewer_id, rubric_version, question_id, output_hash, run_hash, source_ids, evidence_locations, labels。labels: `behavior`, `support_rate`, `key_point_coverage`, `numeric_correctness`, `refusal_quality`（0..1 或 null）, `serious_error`（bool/null）, `error_types`（列表，如 wrong_citation/numeric_direction_reversal）, `rationale`。原始 A/B 分别保留，完全一致才自动 final，冲突必须独立仲裁；unjudgeable/missing 明确 incomplete。
- `eval/independent/scoring.py`: `build_report(bundle, run, annotations=None, baseline_run=None, baseline_annotations=None) -> dict`。annotations 含 `final` 列表，各项 question_id/repeat/run_id/output_hash/labels/status，及 missing/conflicts/errors。适用性分母预先声明；answer/qualified/refuse 分开；重复先题内汇总，question_id 对齐后题组配对。人工指标不读取运行时校验器，缺标注 N/A；错误/误拒答不得删除。严重错误阻断；完整人评缺失不得 pass；Recall@40 未完整排名保持 N/A。
- root: `eval/independent/runner.py`, `worker.py`, `__main__.py` 接冻结、干净环境、网络 guard 和 RunRecorder，无旧 P0 专有门禁；不修改产品设置。提供 validate/run/export/import/report/synthetic-e2e 命令。

## 执行顺序与验收

1. 资产模块先失败测试后最小实现，检查 ID/等级/哈希/split/派生泄漏；通用指南共享不自动泄漏。
2. 盲评模块先测试身份/参考隐藏、双评/冲突/哈希/定位，再实现。
3. 评分模块先测试混合分母/N/A/严重错误/重复家族/不等题组，再实现，复用 metrics_v2。
4. root 接隔离执行与独立源码参考、合成 fixtures/CLI，运行真实 C0，不要求 C1 或历史工件。
5. CI 保留同版一致性，同时从 PR base/固定提交 freeze 独立参考；不可用明确失败，禁止自比。
6. 16 开发 draft/unreviewed 候选与核对清单，32 盲测仅配额及空白模板；独立负责人管理真实数据。
7. 全套适用 pytest、MCP、原 C0 两次与独立参考、合成 E2E、独立代码审查；修复发现后重新验证受影响检查。
8. 写交付报告/标注指南与待办。明确工程工具、待审候选、试点未执行、线上待验收；线上资料缺失集中列出，禁止生产发布或付费调用。
