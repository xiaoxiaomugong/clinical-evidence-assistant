# 独立评测负责人空白模板

状态：**空白、未审、不可执行；人工试点未执行。** 这些文件没有真实盲题、已确认 qrels、参考答案或模型输出。空字符串与 null 是需要负责人补齐的字段；运行校验会明确失败，不能将其作为通过样例或临床金标准。

复制本目录到评测负责人管理的独立目录后填写。32 道真实盲题及其原文、qrels、参考要点、输出、评审记录和身份映射不进入 Git、普通 CI、开发者调试目录或公开报告。开发候选另见 `development_candidates.jsonl`；它采用候选草稿格式，不能直接作为执行 bundle 导入。

## 填写与校验

1. 填写 `manifest.json` 的 dataset_id、实际 corpus profile 与冻结语料清单 SHA-256；填写协议和标注规则版本。这里的 manifest_hash 指语料清单，不是本模板目录的哈希。
2. 每题声明固定日期、独立 question_group_id、split、风险和预期行为。预期行为只允许 answer / qualified_answer / refuse，须由负责人根据已核对证据赋值；不要从系统输出反推。预期拒答须声明允许的拒答码，retrieval applicability 为 false。
3. 明确预先声明 retrieval / answer_quality / refusal 的布尔适用性；support_rate、key_point_coverage、numeric_correctness、refusal_quality 可逐指标覆盖默认适用性，若填写必须是布尔值。真实非数字题须在冻结前声明 numeric_correctness=false，不能在结果出炉后删去错误数字题。不得在看到结果后更换分母。缺 qrels、参考要点或人评只表示证据不足。
4. 分配稳定 source_id；来源文本保留可供评审核查的原文片段及 locator。定位可含 section、paragraph、page、quote，或文本 start/end。quote 必须出现在来源文本中；偏移是 Python 字符索引，满足 `0 <= start < end <= len(text)`，区间及 quote 同时提供时须一致。
5. qrels 由人工按 0–3 整数标注，保留研究家族、证据角色与理由。相同来源跨题的研究家族身份一致；同一试验的知识页、论文及重复发表不能增加独立来源数。参考要点的来源不能同时被该题明确标成 grade 0。
6. 参考点填写 required/optional、正数权重、支持来源及适用范围。无已确认参考点时保留空表，不添加猜测标签。
7. `derived_from` 可为父题 ID 或父题 ID 列表；同组、同义、翻译及派生题保留同一 split。没有 semantic_family_id 时删掉该可选字段；不要把 null 当作已知语义家族。
8. 运行校验并处理 errors；逐项签署 manual_review。共享一篇通用指南本身不自动构成泄漏，但结构校验不能确认没有语义泄漏。

```bash
python -m eval.independent validate --assets /path/to/owner-managed/dataset --corpus-hash ACTUAL_SHA256 --output /path/to/new-validation.json
```

目录表可使用 `questions.json` 等 JSON 数组，或目前的 JSONL 每行一个对象；一个表不能同时有两种文件。也可把全部表合入一个 JSON bundle。解析拒绝重复 JSON 键、非有限数值及无效 JSON，记录文件/行及明确错误；校验不会补全缺失标签。

C0 公开语料清单哈希使用 `eval.independent.fixtures.corpus_manifest_hash(root)`：按固定顺序列入 `data/raw/local_corpus.json`、`data/corpus_version.json`，再列入按路径排序的 `data/knowledge_pages/*.json`；每项保存仓库相对 path 和文件字节 SHA-256。对该项列表使用 UTF-8、ensure_ascii=False、sort_keys=True、紧凑 JSON separators 与 allow_nan=False，再做 SHA-256。它只描述当前公开 C0 输入；后续语料配置须另行声明其清单算法和全部有效输入。

## 负责人保存的锁定材料

保存题集与协议内容哈希、实际语料清单、来源身份注册表、题组/派生关系审计、人工语义泄漏复核签名、独立参考源码身份及候选源码身份。所有修订创建新版本和新目录，保留旧版本。真实盲集的这些材料仅由负责人和获授权评审保管。

运行后使用盲评导出命令生成空白评审表；A/B 分开填写，不能互看标签。映射和随机种子只存负责人私有目录。缺一人、无法判定、缺原文定位及未仲裁分歧不会自动成为 final。详见 `docs/evaluation_annotation_guide.md` 和 `docs/evaluation_pilot_plan.md`。
