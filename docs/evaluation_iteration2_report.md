# 第二轮：独立质量评测工程闭环与人工试点准备

日期：2026-10-03。**工程工具完成；16道开发候选待审；人工试点未执行；线上待验收。** 本轮本地全套 **528 passed / 3 skipped**，另 **2项 MCP passed**；旧 C0 回归、固定参考对照、合成单臂/双臂闭环及独立代码审查通过。合成分数只验证工具，不构成临床质量通过。没有发布生产、重启服务、替换索引、调用付费模型或改模型/阈值。

交付分支为 `codex/iteration2-evaluation`，以本地 Git 提交保存第二轮源码、公开模板及文档；未推送、未合并。被测版本以本报告链接的冻结源码/工具hash为准：冻结时commit指向第一轮且working_tree_dirty=true，不能只用该HEAD代表第二轮。最终提交与被测Python/配置源码逐项哈希一致，后续报告/说明更新不改变被测实现。工件目录继续本地保留，不进入Git。

## 基线核对与不可覆盖参考

- 实际初始目录为 `/Users/yangxuesong/.codex/worktrees/bda0/Clinical Evidence Assistant`；初始 HEAD 是旧 `2d8be49` 的 detached HEAD，diff 和未跟踪文件为空。它没有第一轮源码与交付文件，不能直接继续第二轮。
- 本地 `codex/iteration1-stability` 为完成提交 `07d3be39c1c4f4c925f8e9cd977634806f7884f4`，8890 工作树干净。只读检查该提交和交付报告后，**在当前目录**建立 `codex/iteration2-evaluation` 承接此提交；未切回8890修改。
- 第一轮报告、server_operations、evaluation_plan、P0实施报告、freeze脚本/相关测试及 `run_p0/offline_runner/run_record/metrics_v2` 已阅读；未发现当前目录、适用父目录或子目录中的 AGENTS.md。已有诊断、请求保护和运营日志系统未重建；产品 `src/` 未改动。
- 校验8890的第一轮冻结工件成功：input manifest hash `06add2cabf1456adc521ccc66f33fdf903bc5b6970bc624f65c099970e974044`。这是历史工件校验，**不是重跑第一轮测试**。
- 在第二轮任何源码改动前另冻结 [固定第一轮参考](../data/eval_runs/iteration2-reference-07d3be3-20261003/manifest.json)，input manifest hash `726d6bf5a9dfaa8cce9ce59c69522603da60c902925ad0e3cb7b17bcffbb0fb7`。保存实际公开源码、C0数据、旧题、显式配置及依赖；源码扫描包含相关未跟踪 `.py`，排除 `.env`、密钥、私有配置和可选私有索引。改动前没有未跟踪源码。参考不被候选覆盖，验收后重新校验通过。
- **第一轮334通过、3跳过，另2项MCP；两次C0一致及15题前后兼容是已有记录。** 下文528/3、MCP2和本轮回归来自本轮实际命令，分别留有日志。

## A：版本化资产与题集校验

[独立资产模块](../eval/independent/assets.py) 与旧15题/P0完全分离，支持 JSON bundle 和目录式 JSON/JSONL 表；`schema_version=independent-eval-v1`。题目包含题组、split、题干、主题/语言/场景/风险、截止日期、语料配置/hash、三类预期行为、理由、允许拒答码、禁止结论及预声明适用性。qrels包含稳定来源、严格0–3等级、研究家族、角色、原文位置及依据；要点包含必要性、权重、支持来源和范围。

校验输出机器可读 `errors/warnings/manual_review`：重复/未知/空白ID、重复JSON key、非法等级/非有限值、冲突标签、来源家族不一致、原文quote/offset、语料hash、跨split同题组/同文题、派生链/循环均可见。同split完全重复题干若给不同题组也失败，不能增加独立样本量。共享指南本身不自动算泄漏；无法自动证明的语义重叠列为负责人复核项。缺 qrels/要点不补标签，保留证据不足提示。结构valid不等于专家确认。

可直接使用 [合成JSON示例](../eval/examples/independent-synthetic-v1.json)、[空白模板与说明](../eval/templates/independent-v1/README.md)和 `synthetic-fixture` 生成命令。空白负责人模板故意不可作为完整题集，校验失败为预期；没有伪造确认标签。

## B：盲评双评与仲裁

[盲评模块](../eval/independent/blind.py) 打乱输出和证据顺序，按白名单导出题目、完整可评审回答、限定/拒答理由、found/missing/next_steps及原文定位。系统/模型/后端、原排名、运行时诊断、参考答案/qrels/预期标签和其他评审标签不导出。引用编号转换成匿名别名，避免编号泄漏原排序；正文引用、结构化引用及证据别名对应。嵌套元数据同样净化。

负责人独立保存 seed 与映射（目录0700、文件0600），公开评审包不含它们。真实包只是评审者可见的受控资产，不用于互联网公开。import绑定题目、来源、原文、run/output/presented-output hash及rubric版本；伪造来源正文、位置或更换输出均失败。评审A/B原件分别保留；缺评审/无法判定/空标签/冲突状态可见，不能静默通过。分歧必须由独立仲裁者及单独理由形成final；原始标签不被覆盖。

真实 `controlled_clinical` 的运行、导出、导入及报告/校验输出均禁止写入仓库。负责人仍须采用仓库外受限存储、权限和审计；工具不替代组织访问控制。实现、CI及验收仅使用明确标记的合成fixtures，没有读取真实32题盲测。

## C：独立评分、隔离与参考对照

[独立执行器](../eval/independent/runner.py) 复用现有冻结、Settings白名单、干净子进程、网络audit guard及RunRecorder；[worker](../eval/independent/worker.py) 不调用旧P0评分/指定题目/五个原文对/旧Recall门槛。C0设置维持 `source_preserving / legacy / legacy / deterministic`、Top8/生成Top5、独立来源至少3及0.18/0.5，PHI、引用验证、净化、后置拒答保留。

[独立评分器](../eval/independent/scoring.py) 复用未改动的 `score_retrieval` 和 `paired_group_bootstrap`：

- 检索适用性预声明，拒答题不入检索分母；错误、skipped、缺失和原因单列，预期题/次数及有效双评数分开报告。错误/误拒答不能删除后提高通过成绩。
- 缺qrels、未判定Top-K、缺人评、未仲裁或无法判定输出N/A/证据不足；不把未知记成不相关，也不记成100%通过。`observed_mean`明确只是可用证据描述。
- 重复文档消耗位置但零增益；研究家族独立来源计数与文档指标分别保留。answer/qualified_answer/refuse分别评审；现有产品只给refused布尔值，限定应答由独立标签确认。
- 人工支持率、加权要点覆盖、数字正确性、拒答质量及严重错误仅来自有绑定的双评/仲裁标签，不使用运行时规则分数。错引、方向反转、PHI泄露、危险建议及其他严重错误独立阻断；全部误拒答也不能通过。
- 生成重复先题内均值，再按question_id对齐，再按题组配对bootstrap；不等大小题组保留问题宏平均，重复不增加独立题数。缺完整Top40排名与判定时Recall@40=N/A。
- 报告的 `ready_for_review` 仅表示可供评估负责人复核的工程报告；**不是临床通过**，`clinical_quality_passed=null`。正式阈值和决策由负责人预声明，本轮未自行选择临床门槛。

[固定Git参考冻结器](../scripts/freeze_reference_from_git.py) 从明确ref提取源码/公开数据；参考不存在失败，禁止回退候选自比。CI保留同版两次一致性，再增加PR base SHA（push before SHA）独立冻结回归；本地另实测 `2d8be49` 独立archive参考，证明旧Git基点流程可用。远程Actions尚未执行。

执行器记录双方源码、快照manifest、评分工具、有效数据与协议身份。第一轮固定参考和本轮候选产品源码相同（本轮仅新增评测工程）；报告明确 `fixed_reference_same_product / cross_version_performance_claim=false`。该对照证明固定参考回归一致，不声称回答能力提升。

## D：试点与端到端验收

[48题试点计划](evaluation_pilot_plan.md) 提供16开发/32盲测的场景、语言、预期行为和风险出题配额，及[16条开发候选](../eval/templates/independent-v1/development_candidates.jsonl)。候选为 `draft/unreviewed / label_status=not_assigned`，没有已确认预期标签、来源匹配或PMID；来源核查清单待负责人执行。32题真实题干、qrels、参考答案和输出不在仓库；本轮只提供配额、空白模板和管理流程。

合成单臂C0流程在无历史工件/C1依赖时完成：导入→校验→隔离运行→盲评导出→A/B合成标签导入→保留1项分歧→独立合成仲裁→报告。双臂流程另用改动前参考；每臂3题×2次=6输出，总12份输出/双评结果。配对指标先汇总题内重复，检索区间独立样本为2题/2组，行为/安全为3题/3组；不是12个独立样本。模拟标签不可混入真实质量报告。

## 实际命令与结果

主运行时为既有 Python3.9.6；MCP为既有 Python3.13.13/MCP2.0.0。未安装产品新依赖。实际隔离环境包含下列变量；runner另独立构造全部Settings及环境白名单：

```bash
CEA_PY='/Users/yangxuesong/Clinical Evidence Assistant/.venv/bin/python'
CEA_MCP_PY='/Users/yangxuesong/Clinical Evidence Assistant/.venv-mcp/bin/python'
export EVIDENCE_ASSISTANT_ENV_FILE=/dev/null ENABLE_LIVE_APIS=false ENABLE_SUPABASE=false
export LLM_API_KEY='' PUBMED_API_KEY='' NCBI_EMAIL=''
export SUPABASE_URL='' SUPABASE_PUBLISHABLE_KEY='' SUPABASE_SECRET_KEY=''
export MODEL_LOCAL_FILES_ONLY=true HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

"$CEA_PY" -m pytest -q -rs
PYTHONPATH='/private/tmp/cea-iteration1-mcp-test-deps:src:.' CLINICAL_REQUIRE_MCP=1 "$CEA_MCP_PY" -m pytest -q tests/test_mcp_server.py tests/test_mcp_stdio.py
"$CEA_PY" scripts/smoke_test.py
EVIDENCE_ASSISTANT_CACHE_DIR=/private/tmp/cea-iteration2-desktop-cache PYTHONPATH=src "$CEA_PY" -m evidence_assistant.desktop --check
"$CEA_PY" scripts/lint_knowledge_pages.py --strict
"$CEA_PY" scripts/runtime_diagnostics.py --output data/eval_runs/iteration2-20261003-acceptance-v1/verification/runtime.json
"$CEA_PY" -m eval.independent validate --assets eval/examples/independent-synthetic-v1.json --output data/eval_runs/iteration2-20261003-acceptance-v1/verification/example_validation.json
"$CEA_PY" -m eval.run_p0 --baseline-source current --baseline data/eval_runs/iteration2-reference-07d3be3-20261003 --output data/eval_runs/iteration2-20261003-acceptance-v1/legacy-c0 --profiles C0 --arms G1
"$CEA_PY" scripts/freeze_reference_from_git.py --ref 2d8be49fa0e79fe737aeb5da77a19ff88c547eb8 --output data/eval_runs/iteration2-20261003-acceptance-v1/pr-base-reference
"$CEA_PY" -m eval.run_p0 --baseline-source current --baseline data/eval_runs/iteration2-20261003-acceptance-v1/pr-base-reference --output data/eval_runs/iteration2-20261003-acceptance-v1/pr-base-c0 --profiles C0 --arms G1
"$CEA_PY" -m eval.independent synthetic-e2e --output data/eval_runs/iteration2-20261003-acceptance-v1/synthetic-clean-c0
"$CEA_PY" -m eval.independent synthetic-e2e --reference data/eval_runs/iteration2-reference-07d3be3-20261003 --output data/eval_runs/iteration2-20261003-acceptance-v1/synthetic-paired-c0
git diff --check
```

上述目录是实际已完成工件；复跑必须改为唯一新目录，禁止原样覆盖。MCP依赖路径是既有本地测试适配目录；CI通过安装声明的MCP extra及自身Python3.11环境运行，不依赖这个临时路径。

| 本轮检查 | 实际结果/工件 |
|---|---|
| 全套适用pytest | [日志](../data/eval_runs/iteration2-20261003-acceptance-v1/verification/pytest.log)：528通过、3跳过、5条既有SWIG弃用警告，11.73s |
| 跳过原因 | 当前主环境无可选MCP runtime（2项），仓库未分发可选PDF索引（1项）；不算通过 |
| MCP另验 | [日志](../data/eval_runs/iteration2-20261003-acceptance-v1/verification/mcp.log)：2通过，1.11s，含真实子进程stdio |
| 新模块专项/独立复核 | 194通过；含混合分母、缺标注/缺评审/仲裁、无法判定、泄漏/哈希、重复文档/重复题与不等题组、错引/数字反转/全拒答/严重错误、身份/参考隐藏及干净C0 |
| 原15题C0 | [汇总](../data/eval_runs/iteration2-20261003-acceptance-v1/legacy-c0/summary.json)：两次一致；15success、0error、0skipped，12应答/3拒答；固定第一轮参考15/15答案/引用/拒答兼容 |
| 旧Git基点对照 | [汇总](../data/eval_runs/iteration2-20261003-acceptance-v1/pr-base-c0/summary.json)：退出0，`2d8be49`参考同数据；15/15答案/引用/拒答兼容 |
| C0旧工程代理 | Recall@8=23/24（95.83%），nDCG@8=89.85%，词项覆盖83.75%，旧citation/support规则100%；均不代表医学正确率 |
| 合成单臂 | [acceptance](../data/eval_runs/iteration2-20261003-acceptance-v1/synthetic-clean-c0/acceptance.json)：engineering_complete=true，分歧1→0，无C1/历史依赖 |
| 合成固定参考双臂 | [acceptance](../data/eval_runs/iteration2-20261003-acceptance-v1/synthetic-paired-c0/acceptance.json)、[独立报告JSON](../data/eval_runs/iteration2-20261003-acceptance-v1/synthetic-paired-c0/report.json)：每臂6运行/6有效模拟标注，1分歧完成仲裁；真实试点not_executed，临床通过null，Recall@40=N/A |
| 隔离及工件 | 旧回归每组3个worker、新双臂4个worker自检通过，意外网络事件0；frozen/source/参考未改写。Python audit范围，不是OS抓包 |
| 其他工程检查 | smoke PASS（pdf_docs=0,answer_entries=8,checked=4）；desktop通过；strict lint 0问题；管理员诊断ready；示例valid；diff检查通过 |

主要机器证据汇总见 [delivery_evidence.json](../data/eval_runs/iteration2-20261003-acceptance-v1/verification/delivery_evidence.json)。这些本地评测工件被Git忽略；源码、模板、公开合成示例与指南可随仓库交付，干净环境可重新生成新工件。

| 身份 | SHA-256 |
|---|---|
| 固定第一轮input manifest | `726d6bf5a9dfaa8cce9ce59c69522603da60c902925ad0e3cb7b17bcffbb0fb7` |
| 新合成candidate snapshot manifest | `2c5b340bbf9a6aea060a23377f8310bf6fcf8c4e39dbb64a9cea251d90c091fe` |
| 新合成运行评分/执行harness | `0a157c91bead666fc7149af25ce7b671cf97aafdda7f1a359188fa2829c9c494` |
| 新合成dataset | `fec40e9c4308f563f094a96750a7d9f37e23552d00b317956082bc31f566a0ac` |
| 新协议 | `99fd685329b246f164a3b6b08bb04d1aeec4716d102e673e3ba61d32c61dc2d6` |
| C0语料清单 | `dcd596c9dd12c3cf59338ceae2862d839e5890da53cb57e553c1785fce058f81` |

## 独立审查、失败记录与限制

任务模块由不同代理实现，另由非作者交叉做只读审查，先看测试，再查正确性、安全、结构、可读性与性能。发现6项P2并修复：原文/定位绑定、controlled输出位置、比较身份类型防御、成功输出缺正文、安全错误类别一致性、实际可见限定/拒答辅助字段保留。引用别名、递归白名单、非有限JSON和重复题组也有反例覆盖。修复后独立复核194项通过，无未解决的高信度阻断项；**没有合并或生产发布**。

测试优先的缺模块红测、review反例及模块并行未完成时的临时失败均保留为开发过程，不当作最终验收。原文绑定首次失败根因是既有分块在句间插空白；改为仅允许空白变化的精确原文映射，实际检索文本另保存在本地记录，没有放宽语义或更改产品。最终上述命令均退出0；空白模板/缺参考/恶意样例的失败是必要负向测试。报告写入命令成功只说明报告生成成功，不是临床门禁通过。

未执行：真实双评/仲裁试点、真实32题盲测、C1（本工作树无完整索引/配套工件）、完整Top40、在线供应商/付费模型、线上HTTP/TLS/WebSocket/版本/实际语料、远程CI、生产发布/重启、索引替换、OS抓包和临床有效性验证。

线上只读核验缺少信息：网站URL；允许的只读访问方式；部署SHA、实际资源/语料manifest及索引状态；既有管理员诊断与运行记录位置；直连/代理健康和WebSocket证据。已集中向用户请求，本轮未得到可用资料，保留“线上待验收”，不猜测健康或部署版本。

## 人工待办与下一轮语料治理

1. 指定独立评测负责人、A/B评审及仲裁者，按 [标注指南](evaluation_annotation_guide.md) 校准rubric、定位规范、必要要点和严重错误口径，预声明适用性与决策规则。
2. 复核16开发候选并获取合法原文；确认三类行为/qrels/参考要点，记录来源研究家族、日期、范围与许可。自动泄漏项清零，语义人工审查签署后冻结版本。
3. 独立负责人组织32题盲测，在仓库外存题集/金标准/输出/映射；完成双评与仲裁、测真实人审耗时后再决定扩200题。当前没有人评完成记录。
4. 继续第一轮/P0遗留语料治理：缺文献/主题覆盖、132个未确认PDF、泛Other分类、HTML冒充PDF/缺正文、全文可用性/原文身份/许可、知识页到原文映射与研究家族。历史数量只作治理起点，不当作本轮重新审计；详见 [P0报告](optimization_p0_implementation_report.md) 和试点核查清单。
5. C1资料齐全后冻结独立索引manifest再接新协议；完整Top40排序/判定未接入前保持N/A。不得以未达数据门禁的候选索引替换原库。
6. 补齐线上只读证据及远程CI，发布/重启/更换语料仍须另行授权。工具完成不能替代这些验收项。
