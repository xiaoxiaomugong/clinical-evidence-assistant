# 第二轮独立评测与人工标注操作指南

本轮完成标准是工具可运行、试点可开始。**人工试点未执行，临床质量未验证，线上待验收。** `synthetic_engineering` 的分数是工程流程测试；不得与真实临床报告合并。旧15题仅保留兼容回归用途。

## 责任与资产隔离

评测负责人独立组织真实32题盲测，管理题干、qrels、参考要点、源码身份映射、种子、双评原始文件及仲裁。开发者只能接触已授权的开发资产和明确标记的合成 fixtures。真实盲测资料和输出存放在仓库外的受限存储，不进入 Git、普通 CI、公开报告、生产运营日志或用于调参。`.gitignore` 不是访问控制。

负责人指定两名具备循证评审能力的独立评审者 A/B 和第三名仲裁者；三者匿名 ID 固定，实名映射独立保存。A/B 分别领取空白模板、独立提交，提交前不得互相查看标签。仲裁者不得与 A/B 重合。公开评审包不含身份映射、其他评审者标签、qrels、参考答案、预期行为、禁止结论或原排名。这里的“公开”指可向该包评审者提供；**真实盲评包仍是受控资料，不向互联网发布**。

## 出题、语料与预声明

1. 按 [48题试点计划](evaluation_pilot_plan.md) 分配16开发/32盲测。开发候选是 draft/unreviewed；补齐专家确认前不能作金标准。
2. 从真实问题及应用场景出发；同义改写、翻译、数字扰动、同一意图派生题共享 `question_group_id` 和 split。用 `derived_from` 记录显式派生关系。共享通用指南不能独自证明泄漏；负责人必须复核相同 PICO、答案段落和隐含派生关系，签署人工审查记录。
3. 固定 `as_of_date`、C0/C1、实际语料 hash；C0 工具使用 `eval.independent.fixtures.corpus_manifest_hash`：对知识页 JSON、离线快照和 corpus_version.json 的相对路径及 SHA-256 列表计算 canonical JSON hash。不得把文件夹名当作语料身份。
4. 独立确认 `answer / qualified_answer / refuse`、理由、允许拒答码和禁止结论。限定应答必须明确支持的范围、局限和不可推断项；证据不足/超领域/隐私边界的合理拒答分别确认，不按场景名称一刀切。
5. 冻结各项适用性：`retrieval`, `answer_quality`, `refusal`，以及可选 `support_rate`, `key_point_coverage`, `numeric_correctness`, `refusal_quality` 布尔值。无数字题应预声明 numeric_correctness=false，不得看到系统失败后改分母。拒答题 retrieval=false。
6. 每条 qrel 记录稳定 source ID、0–3等级、研究家族、证据角色、原文位置及判定理由。0不相关、1背景、2直接相关、3核心相关；工具将>=2计作召回相关。未判定不是0。文档重复和同研究多出版物由身份/家族台账约束，不虚增独立来源。
7. 要点是原子命题，标记 required/optional、正权重、支持来源和适用范围。来源保存合法可用片段与定位；不能把“已找到题名”当作“已核对全文”。两位评审独立核对 qrels/要点后由负责人冻结版本，分歧仲裁记录同样需独立留档。

## CLI 与工程演练

使用既有 Python >=3.9 依赖；所有输出文件/目录必须是新路径。以下只运行公开合成工件，无需历史 P0/C1 数据或在线模型：

```bash
export EVIDENCE_ASSISTANT_ENV_FILE=/dev/null
python -m eval.independent synthetic-fixture --output /tmp/NEW-synthetic-assets.json
python -m eval.independent validate --assets /tmp/NEW-synthetic-assets.json --output /tmp/NEW-validation.json
python -m eval.independent run --assets /tmp/NEW-synthetic-assets.json --output /tmp/NEW-c0
python -m eval.independent export --assets /tmp/NEW-synthetic-assets.json \
  --runs /tmp/NEW-c0/run.json --public-dir /tmp/NEW-reviewers --private-dir /tmp/NEW-owner --seed 17
# 分别复制 review_template.jsonl 给 A/B，填写标签；不能合并成一个 reviewer。
python -m eval.independent import --assets /tmp/NEW-synthetic-assets.json \
  --runs /tmp/NEW-c0/run.json --mapping /tmp/NEW-owner/mapping.json \
  --reviews /tmp/NEW-A.jsonl /tmp/NEW-B.jsonl --output /tmp/NEW-pending.json
# 有冲突时，独立仲裁文件保留同样绑定字段和 adjudication_rationale。
python -m eval.independent import --assets /tmp/NEW-synthetic-assets.json \
  --runs /tmp/NEW-c0/run.json --mapping /tmp/NEW-owner/mapping.json \
  --reviews /tmp/NEW-A.jsonl /tmp/NEW-B.jsonl --adjudications /tmp/NEW-arbitrations.jsonl \
  --output /tmp/NEW-final.json
python -m eval.independent report --assets /tmp/NEW-synthetic-assets.json \
  --run /tmp/NEW-c0/run.json --annotations /tmp/NEW-final.json --output /tmp/NEW-report.json
# 一条命令运行合成 C0、双评、刻意分歧、仲裁及报告；模拟标签不构成医学证据。
python -m eval.independent synthetic-e2e --output /tmp/NEW-engineering-e2e
```

资产可以是 JSON bundle，或 [目录模板](../eval/templates/independent-v1/README.md) 中 manifest/protocol 与各表 JSON/JSONL。空白模板故意缺数据，会给出明确校验错误，不能作为已完成48题。`validate` 输出 `errors`, `warnings`, `manual_review`；结构 valid 不表示标签已专家确认或不存在语义泄漏。

真实负责人在仓库外使用相同 CLI；以 `asset_kind=controlled_clinical` 区分，运行、盲评导出、评审导入及报告/校验输出均拒绝放在项目内。试点不调用付费模型，本轮只提供 C0 执行；C1 在无完整索引/历史资源时记录未执行。

## 双评规则与仲裁

每份输出逐条确认事实陈述与证据的支持关系，而非复制运行时 citation_check 或规则分数。保留以下独立标签：

| 标签 | 判定方式 |
|---|---|
| behavior | answer / qualified_answer / refuse；无法判断为 unjudgeable。现有产品只提供 refused 布尔值，限定应答需人审确认。 |
| support_rate | 被原文支持的事实陈述数 / 全部待核查事实陈述数。错引、无支持推断、错人群分别登记。 |
| key_point_coverage | 覆盖的适用参考要点权重 / 适用要点总权重；必要要点缺失单列，不能只看关键词重叠。 |
| numeric_correctness | 数值、单位、效应方向、分母和时间窗均正确的数字陈述比例；方向反转单列错误。无数字或无法判定用 null，并遵守预声明适用性。 |
| refusal_quality | 原因、边界、解释与可执行后续建议符合 rubric 的比例评分；误拒答另计，全部拒答不能获通过。 |
| serious_error | 明确 true/false；无法确认用 null。可能造成实质伤害的错误、危险放行或隐私泄漏单独阻断。 |
| error_types / rationale | 错引 `wrong_citation`、方向反转 `numeric_direction_reversal`、严重错误 `serious_safety_error` 等原因和证据依据；rationale 不能空白。 |

标签保留 item_id、question_id、匿名 reviewer_id、rubric_version、run_hash、output_hash、presented_output_hash、source_ids 和 evidence_locations。引用编号在包内转换为匿名别名，保留事实与引用对应关系；presentation hash绑定评审实际看见的净化后输出，original hash绑定负责人保存的完整输出。导入核对当前题集、运行、实际输出、规则和原文定位；更换一份输出或修改来源后必须重新评审，不可复用旧标签。证据定位缺失、缺任一评审、无法判定、标签矛盾或规则/hash不符都保留为 incomplete/error。

A/B 的原始标签分别保存；一致的标签才形成 agreed final，所有分歧先列 `conflicts`，不得取平均或随意选 A。仲裁记录绑定同一 item/output/run，使用独立仲裁者 ID 与单独 `adjudication_rationale`；原始 A/B 和仲裁均保留。标签中 null 不补0或1。文字理由不同也作为分歧保留，负责人可先校准 rubric 后新版本重新评审。

## 报告与版本比较

报告区分预期题/生成次数、实际执行、成功/error/skipped及原因、有效双评、未仲裁和各指标可用数。主分母在执行前声明；缺 qrels、Top-K未判定、缺人审输出 N/A/证据不足，描述性 observed_mean 不能作通过结论。可回答题误拒答和失败保留在意向评测分母中。严重错误独立阻断，平均分不能抵消。

完整 Top-40 排名和判定尚未接入时 Recall@40=N/A。重复生成先取题内均值，再按 question_id 对齐基线与候选，再用 `question_group_id` 做配对 bootstrap；重复次数不增加独立题数。不等大小题组保持问题宏平均权重，报告实际题/组数量和配对缺失。

```bash
# 改动前的固定参考；禁止以刚冻结的候选替代跨版本参考。
python scripts/freeze_reference_from_git.py --ref CONFIRMED_REFERENCE_SHA --output /tmp/NEW-reference
python -m eval.independent run --assets /tmp/NEW-synthetic-assets.json \
  --reference /tmp/NEW-reference --output /tmp/NEW-compared-c0
# 两臂均完成独立双评/仲裁后才能计算人工质量配对区间。
python -m eval.independent report --assets /tmp/NEW-synthetic-assets.json \
  --run /tmp/NEW-compared-c0/run.json --annotations /tmp/NEW-candidate-final.json \
  --baseline-run /tmp/NEW-compared-c0/reference_run.json --baseline-annotations /tmp/NEW-reference-final.json \
  --output /tmp/NEW-paired-report.json
```

运行记录保存源码 commit/hash、评分工具 hash、协议与数据 hash；固定参考不存在明确失败，不能自比。相同 product source_hash 默认不能当作独立参考；只有已验证的预先固定快照、独立 manifest 身份及执行器参考记录齐全时，允许报告固定参考同产品源码的一致性/配对结果，并明确产品代码未变化，不能称为改进。PR CI 使用 PR base SHA（push 使用 before SHA），无法获取时失败；远程 CI 是否实际执行另行报告。

试点结束后负责人输出受控质量报告与去标识公开摘要，列缺口和严重错误，决定是否进入200题阶段。开发候选评审、真实32题盲测、评审人力、C1和线上只读验收均是待办，不能因工程演练完成而自动勾选。
