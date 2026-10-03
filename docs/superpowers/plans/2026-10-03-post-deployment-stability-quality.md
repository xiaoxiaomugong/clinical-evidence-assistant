# 上线后稳定性与回答质量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先让已部署网站的故障可定位、请求有保护、回退可辨认，再用独立评测与合格语料提升回答质量。

**Architecture:** 延续 Streamlit、EvidencePipeline、Python Tool/MCP 与离线兜底。第一轮在现有链路补运行诊断、请求保护、结构化依赖状态和可复现回归；后续用独立开发集选择数据与检索候选，通过门禁再发布。

**Tech Stack:** Python 3.9+ 核心、Streamlit、requests、pytest；MCP 依赖保持现有 Python 版本约束。

**Spec:** 用户于 2026-10-03 明确选择“稳定运行与回答质量”；质量边界沿用 [P0 实施报告](../../optimization_p0_implementation_report.md) 与 [评测方案](../../evaluation_plan.md)。本文是下一阶段提案，当前请求仅交付规划与执行 prompt。

## 事实与范围

- 用户确认网站已经部署到服务器。本次没有网站地址、服务器配置和运行数据，没有验证线上健康、部署 SHA 或实际挂载语料。
- 本次只读核对了本地仓库 `2d8be49`，未运行应用测试或重新评测。历史结果均标明出处。
- 最新 P0 报告显示，候选保留、Top-5 门控、输出校验和评测工具已实现；Top-8 多样性实验、新语料和独立人评尚未通过完整验收。
- 2026-09-23 报告的旧 15 题 Recall@8：C0/G1 为 95.83%，C1/G1 为 91.67%。这是旧题工程回归，不能作为临床正确率。
- 当前工作树未见服务器部署清单、`.venv`、历史 `data/eval_runs/` 或本地 PDF 索引。它们可能存在于其他工作区或服务器，不能据此判断线上缺失。
- 旧 `docs/next_phase_development_plan.md` 包含已经完成的接口、混合检索和记录工具，执行时逐项对照代码，不按旧清单重做。
- `data/corpus_quality.json` 是 2026-08-11 的旧审计，不能代表当前线上数据；`docs/evaluation_plan.md` 中部分“尚未实现”的工程状态也已过时，保留其评审规范，并以代码核对实现进度。

## Global Constraints

- 保持 `CANDIDATE_POOL_POLICY=source_preserving`、`TOP8_SELECTION_POLICY=legacy`、`RETRIEVAL_BACKEND=legacy`、`RERANK_BACKEND=deterministic` 的默认值。
- 保持 Top-8、生成 Top-5、最少独立来源 3、安全阈值 0.18/0.5。实验失败不能通过降低门槛掩盖。
- 保留 PHI 前置阻断、实际生成包引用校验、无支持陈述删除和后置拒答；新入口不得绕过它们。
- 默认不持久化问题、生成正文、检索词、PHI、密钥或完整异常文本。运营记录使用字段白名单，不复用保存证据正文的评测 recorder。
- 保持无密钥离线运行；请求路径不下载模型、不建索引。
- Python、MCP 既有调用与返回字段保持兼容；新增字段有默认值。修改 Settings 时同步 `eval/offline_runner.py` 的显式字段清单。
- 先完成本地可验证改动和发布包。生产配置、数据库写入、索引替换与部署须依据当时明确授权；缺服务器访问只阻塞线上验收，不阻塞本地工作。
- 不覆盖历史评测、题集、qrels、旧索引或用户未提交改动。新工件写入唯一目录。

## Review Focus

1. 多用户并发：共享检索器状态和 recorder 不能把甲请求的诊断归到乙请求；由任务 2 验证。
2. 正常离线与故障回退：无密钥抽取式回答、成功空检索、未尝试、调用失败必须分开；由任务 3 验证。
3. 隐私与错误：异常字符串、来源 URL 或 trace 可能夹带输入和配置；最终日志和错误提示不能泄漏；由任务 2、3 验证。
4. 缺失可选资源：没有 PDF、模型、线上凭据或历史工件时，应准确报告适用范围，不能产生虚假成功；由任务 1、4 验证。
5. 版本错配：本地代码、已部署代码和语料哈希未对齐时，不能把本地结果算作线上验收；由任务 1、4 验证。

## 路线与投入

以下是工作量估算，不是上线日期承诺；人工评审和服务器访问单独影响日历时间。

| 顺序 | 目标 | 主要交付 | 进入下一步的条件 |
|---|---|---|---|
| 第一轮，约 3–5 工程日 | 稳定运行与可定位故障 | 下述任务 1–4；部署基线、请求保护、脱敏记录、真实回退状态、回归与运行手册 | 工程验收通过；缺线上证据则明确列为待验收 |
| 第二轮，约 2–3 工程日搭建流程，人工另计 | 建立可信的质量判断 | 48 题试点，16 开发/32 盲测；分级 qrels、要点和拒答标签；双评与仲裁流程 | 独立标注可用，评分流程可复现 |
| 与第二轮并行，工期取决于资料与人审 | 修复真实语料缺口 | 补齐弱主题，核验题名/类型/全文状态，生成独立候选索引及审计报告 | 数据门禁通过，原索引可回滚 |
| 第三轮，约 2–4 工程日实验 | 改善回答与检索 | 误拒答、缺要点、错引和排序失败分类；固定变量比较候选 | 安全、覆盖、最差主题与性能共同达标 |
| 后续按证据推进 | 扩大验证并发布 | 必要时扩到 200 题；小范围发布、运行观察和回滚演练 | 满足既有正式门禁，不能用试点高分替代 |

推荐先完成运行保障，再并行准备评测与语料。直接调排序会继续受旧题偏差影响；同时铺开账户、聊天历史和 UI 重构会分散当前目标。

## 第一轮：交给 GPT-6.1-sol 的执行范围

### Task 1：记录部署与运行基线

**Files**

- Create: `scripts/runtime_diagnostics.py`
- Create: `tests/test_runtime_diagnostics.py`
- Create: `docs/server_operations.md`
- Read/reuse: `src/evidence_assistant/config.py`、`data/corpus_version.json`、`src/evidence_assistant/desktop.py`

**Interfaces**

- 新命令：`python scripts/runtime_diagnostics.py --output <new-file.json>`。
- 输出 `schema_version`、构建/提交标识、Python/包版本、配置白名单、语料计数和哈希、可选资源状态；无 Git 元数据时提交标识为 unknown。
- 结果区分 `ready`、`degraded`、`not_ready`。缺少本就未启用的 PDF/模型不算失败；必需离线数据不可用算 not_ready。
- 默认只检查本地配置和资源，不发送医学查询或探测外部供应商。命令用于管理员核验，不新增公开诊断页。

- [ ] 先测试：无 Git、无 PDF、核心语料缺失、未知配置字段、配置里含合成密钥时，输出状态正确且敏感值不出现。
- [ ] 实现白名单输出与不可覆盖的报告文件。复用已有资源发现逻辑，索引大文件哈希只在显式诊断时计算。
- [ ] 在 `docs/server_operations.md` 填写本地基线；服务器版本、启动方式、反向代理、持久目录、重启及回滚方式缺证据时写“未核验”。
- [ ] 验证：`python -m pytest -q tests/test_runtime_diagnostics.py`；在唯一临时输出位置运行诊断，人工核对字段和资源状态。

### Task 2：统一 Web 请求保护并增加脱敏运行记录

**Files**

- Modify: `app.py`、`src/evidence_assistant/tool.py`、`src/evidence_assistant/pipeline.py`、`src/evidence_assistant/observability.py`
- Create: `src/evidence_assistant/query_service.py`、`src/evidence_assistant/runtime_logging.py`
- Create: `tests/test_query_service.py`、`tests/test_runtime_logging.py`、`tests/test_web_app.py`
- Extend: `tests/test_tool.py`，仅在确实需要配置时修改 `src/evidence_assistant/config.py` 和 `eval/offline_runner.py`

**Interfaces**

- `query_service.py` 提供 Web 与 Tool 可共享的输入校验及安全执行入口；返回现有 `PipelineResult`，Tool 继续负责原 JSON 序列化。
- 统一 strip 后的非空和最大 4000 字符规则、mode 及布尔参数校验。Web 也设置输入长度提示。
- 对同一个共享 pipeline 的调用互斥，默认最多等待 5 秒取得执行权，超时返回明确的“服务繁忙”状态；所有异常路径释放执行权。这个限制是单进程保护，不能宣称为分布式限流。
- 每次调用创建随机 request_id，统计排队和执行时间。请求上下文不得保存在共享 recorder 的可变字段中。
- 生产记录限定为 request_id、时间、版本、mode、状态码、阶段耗时、实际后端、枚举错误/回退原因和计数；`capture_content=False`。
- 运营日志接既有服务器日志设施或标准 logging 的 stderr，MCP stdout 保持协议专用。文件落盘需要轮转和保留期；不接第三方分析服务。

- [ ] 测试空输入、4000/4001 字符、非法 mode；失败时 pipeline 调用次数为 0。
- [ ] 用可控 barrier/fake pipeline 测试并发调用、排队超时、异常后解锁、请求 ID 与诊断不串；不用偶然 sleep 证明并发正确。
- [ ] 用合成 PHI、包含假密钥的异常和带输入的 trace 测试日志字段白名单；候选、答案、题干均不得落盘。
- [ ] 将 Web 改为调用共享服务；异常用固定文案与 request_id 提示，不展示完整异常。新提交失败时清理或明确区分上次答案，避免旧答案被误当作本次结果。
- [ ] 运行上述新增测试与 `tests/test_tool.py`、`tests/test_mcp_server.py`；Web 用 Streamlit AppTest 或实际浏览器检查成功、拒答、繁忙及异常恢复。

### Task 3：如实记录外部依赖与生成器回退

**Files**

- Modify: `src/evidence_assistant/schemas.py`、`src/evidence_assistant/pipeline.py`、`src/evidence_assistant/generate.py`、`app.py`
- Modify as needed: `src/evidence_assistant/retrievers/common.py`、`src/evidence_assistant/config.py`、`eval/offline_runner.py`
- Extend: `tests/test_generate.py`、`tests/test_pipeline.py`、`tests/test_live_api_common.py`、`tests/test_web_app.py`

**Interfaces**

- 各依赖用结构化状态区分 disabled、not_attempted、success、empty、error、fallback，记录稳定原因码与耗时。
- 保留已有 `used_live_api` 字段的兼容语义；新增状态供 UI 区分“已尝试”和“成功获取证据”。成功返回空结果不能记为网络故障。
- 顶层降级信息覆盖启用后的实时源失败、云检索失败及 LLM 回退。未配置 LLM 的正常 extractive 模式不算降级。
- 不通过解析 trace 文本推导状态；错误原因使用枚举，不把原异常直接塞进公共字段或日志。
- LLM 单次超时改为可配置，兼容默认 45 秒；重试等待设置明确上限，建议默认 5 秒，并处理 NaN、Infinity、负值和超大 Retry-After。
- 单次超时、重试等待上限、排队等待分别报告。第一轮不宣称已实现全链路硬截止；若线上实测显示积压，后续单独设计请求总预算和进程级取消。

- [ ] 先补 fake 响应测试：单源/全源失败、空结果、429、超时、坏 JSON、缺字段；确保降级信息真实，既有抽取式兜底仍经过门控和引用校验。
- [ ] 测试无 LLM key 正常离线；证据门控提前拒答时生成器为 not_attempted；PHI 阻断后所有外部适配器调用次数为 0。
- [ ] 以模拟时钟验证重试等待有界；不在测试中实际长时间等待或调用付费模型。
- [ ] 更新 UI 的固定状态文案和运行日志；必要时清理现有含原异常内容的 trace。
- [ ] 运行受影响测试，检查 Tool/MCP 序列化兼容性。纯离线默认回答、引用和拒答决策应与本轮开始时一致。

### Task 4：补齐新环境回归、CI 与发布验收

**Files**

- Create: `scripts/freeze_current_baseline.py`
- Modify/reuse: `eval/run_p0.py`、`eval/offline_runner.py`、`.github/workflows/ci.yml`
- Extend: `tests/test_eval_runner.py`
- Update: `docs/server_operations.md`、`README.md`
- Create on execution: `docs/post_deployment_iteration1_report.md`

**Interfaces**

- 新命令：`python scripts/freeze_current_baseline.py --output <new-directory>`，显式冻结当前 C0 数据、代码、旧 15 题、配置和依赖；复用现有哈希/隔离代码。
- 当前基线使用独立身份，不能写成 2026-09-23 历史基线。运行器接受其来源并准确记录当前提交，不能继续无条件标注固定 `BASELINE_COMMIT`。
- 如取得历史冻结工件，先核对校验和再复现原实验。未取得时，只比较本轮冻结前后的工程结果；C1、历史臂或人评缺资源时明确标注未执行及原因。
- 回归仍为显式 Settings、隔离环境、禁止外网、唯一输出目录、两次语义一致；复用已有 runner，不另造评分体系。

- [ ] 测试干净克隆无历史目录可创建新 C0 基线、拒绝覆盖既有目录、错误来源不可伪装成历史臂、配置和输入哈希可验证。
- [ ] 修改 CI，让离线测试、smoke 和安装检查均显式隔离 `.env`、云端/实时源及模型密钥；接入轻量 C0 回归，保留 Python 3.11 的真实 MCP stdio 必测。
- [ ] 在可用隔离环境运行全套 pytest、smoke、桌面 `--check` 与 C0 回归；依赖缺失明确记录，不能把 skip 算通过。
- [ ] 在测试环境以并发 1/4、预热 10 次、每档至少 100 次受控请求记录 P50/P95/P99、排队、错误和峰值内存。沿用固定输入，说明共享锁的吞吐成本；没有硬截止时超时指标记 N/A。
- [ ] 对网页执行真实问答冒烟，核对答案、引用、拒答、刷新和故障恢复。HTTP 健康探测与问答验收分开记录。
- [ ] 运行手册包含启动/自启、代理与 WebSocket、健康探测、日志轮转、数据备份、完整版本回滚及只读上线核验步骤；针对实际部署方式填写，不同时引入 Docker、Kubernetes 等无依据设施。
- [ ] 若用户另行授权部署：核对代码与语料版本，先小范围验证，再观察错误率/降级率/延迟；回滚同时恢复代码、配置与对应索引。没有服务器访问则交付具体步骤和待验收表。
- [ ] 报告区分本次实测、历史记录、未执行和失败项；写明默认算法/安全门禁是否改变及回滚办法。最后做一次代码审查，只修复本轮相关问题。

## 第二轮以后：质量工作包

### Q1：48 题独立试点

沿用 `docs/evaluation_plan.md`：16 开发题用于调试，32 盲测由评测负责人独立管理。两名具备循证背景的评审独立标注，第三人仲裁；AI 可协助整理模板和证据，不能充当已完成的独立临床评审。

交付题集版本、文档级 0–3 qrels、参考要点、应答/拒答标签、证据日期及一致性报告。工程侧补 split、问题家族泄漏、语料哈希和标注完整性校验，以及盲评导出、仲裁导入、适用分母与按问题组的配对区间。未标注为 N/A；报告分子/分母和区间。现有 `metrics_v2.py` 可复用，但当前汇总仍把正式评审、区间和 Recall@40 记为 N/A，不能仅传 qrels 就宣称正式评分已接通。旧 15 题保持冻结。

### Q2：修复语料，而后发布候选

先确认服务器实际使用 C0、PDF 索引、云端库或组合，再对那份数据审计。最新报告的候选仍有文献量、全文率、核心主题覆盖、Other 比例四项失败；132 个 PDF 待严格题名核验。历史缺口不能直接当作线上现状。

优先补高血压与脑卒中等弱主题；核验主标识、文献类型、全文状态和可使用范围，不能批量强改 Other。先产出有来源账本与哈希的独立候选索引，跑现有审计与开发集，再安排版本化发布。缺资料或人工复核时列清单，不造数据。

PDF 候选沿用现有严格门禁：真实可用文献至少 500、已核验全文率至少 90%、各核心主题至少 20、Other 比例小于 50%，并通过 SQLite/FTS/主标识/台账校验。这些是该候选库的验收要求，不是内置 C0 网站正常启动的前置条件。

### Q3：按失败类型改回答质量

使用开发集将错误分为语料缺失、召回失败、Top-8/Top-5 选择、生成失真、校验漏检和误拒答。每次只改一层，固定其余条件；优先诊断 q008 所代表的通用排序问题和 R2 的覆盖退化，不针对题号/PMID 特判。

Top-8 多样性、稠密检索、交叉编码器和独立语义校验均作为可选候选。除 Recall/nDCG 外，还看有效回答覆盖、独立引用支持、数字、人群与否定、最差主题、延迟和成本。旧题提升或少答导致的高支持率不能作为切换依据。

### Q4：发布决策

复用评测方案第 9 节的正式门禁与适用样本条件。严重安全错误出现任何一例即阻断；候选必须具有明确收益且通过非劣与最差主题检查。48 题主要验证流程，样本不足时保留实验配置，扩大独立评测后再决定默认切换。

## 第一轮完成的定义

- 本地基线可复现，运行版本、资源范围和待核验线上信息明确。
- Web 的输入、并发、异常和上次答案状态可预测；生产记录不保存内容或凭据。
- 外部源及 LLM 回退如实呈现；正常离线工作不报故障。
- 工程测试和离线回归有新证据，原有安全门禁不退化。
- 有针对实际部署的核验/回滚手册。未取得线上证据时，结论是“本地交付完成，线上待验收”。
- 不把第一轮完成写成“P0 全部完成”或“临床质量已验证”。
