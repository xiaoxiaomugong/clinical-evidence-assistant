# 上线后稳定性与回答质量：第一轮交付报告

日期：2026-10-03。结论：**Task 1–4 本地交付完成，线上版本与健康未核验，生产发布待另行确认。** 最终本地全套测试 334 通过、3 跳过；另在可用环境完成 2 项 MCP 测试，其中 1 项验证真实子进程 stdio。离线 smoke、资源检查、当前 C0 回归和独立代码审查通过。本轮没有执行生产发布、重启、语料切换或索引替换；这些工程证据不能证明临床质量已验证。

## 起点、范围与保留项

- 起始工作树干净，HEAD 为 `2d8be49fa0e79fe737aeb5da77a19ff88c547eb8`，与规划基点一致。没有发现仓库及适用父目录的 `AGENTS.md`。先读取 README、最新 [P0 实施报告](optimization_p0_implementation_report.md)、[评测方案](evaluation_plan.md)及两份执行计划。
- 两份计划起初不在当前工作树，在同仓库的 8148 工作树找到后原样复制到 [计划目录](superpowers/plans/2026-10-03-post-deployment-stability-quality.md)，并读取 [执行提示](superpowers/plans/2026-10-03-gpt-6.1-sol-prompt.md)。没有覆盖现有用户改动。
- 复用现有资源发现、`RunObserver`、抽取式生成、隔离评测 runner、网络审计及旧评分器。请求服务覆盖 Web/Tool/MCP 入口；直接 Python pipeline 的既有调用接口保留。
- 默认仍为 `source_preserving / legacy / legacy / deterministic`，Top-8、生成 Top-5、最少 3 个独立来源、前置阈值 0.18、后置阈值 0.5。PHI 前置阻断、实际生成包引用校验、无支持陈述净化和后置拒答保留。
- 旧 `eval/test_set.json`、`metrics.py`、`metrics_v2.py`、历史报告与评测方案的内容哈希核对起始 HEAD 一致；核心语料没有改写，旧题集、旧工件和原索引没有覆盖。没有新增依赖或改动既有虚拟环境。
- 首次交付验收时改动尚未提交，当时 HEAD 独自不能标识新增代码；最终冻结工件保存实际源码、配置、依赖与哈希。后续按用户授权，将第一轮文件整理到 `codex/iteration1-stability` 作本地提交，提交身份以该分支 Git 历史为准；不推送或发布生产，被忽略评测工件保留本地。48 题独立评测和语料治理交给下一轮。

## Task 1：运行基线

新增管理员命令 `python scripts/runtime_diagnostics.py --output NEW_FILE.json`。只读本地资源，输出代码/构建身份、Python/包版本、枚举/布尔/有限数值配置白名单、语料计数和哈希、可选资源状态。无 Git 时明确 `unknown`；输出文件已存在或为符号链接时拒绝覆盖。不输出密钥、完整环境变量、配置 URL/路径、模型名称或原异常；不探测供应商、不加载模型、不建索引。

诊断区分 `ready / degraded / not_ready`。PDF 缺失且可选不算启动故障；挂载后损坏会降级。PDF 检查包含真实 FTS5/MATCH、双向 chunk/doc 关系和重复身份；SQLite 使用不可写连接，存在 WAL 时标为待一致性核验。稠密资源复用索引注册校验，模型推理仍未核验，损坏数组不会逃逸成原始 traceback。

最终本地结果 `ready / local_resources_only`：5 个知识页、15 个 claim、10 条离线快照；PDF 未提供，稠密检索和神经重排未启用。主要环境为 Python 3.9.6、requests 2.32.5、python-dotenv 1.2.1、Streamlit 1.50.0、PyMuPDF 1.26.5、NumPy 2.0.2。详细白名单见 [最终诊断副本](../data/eval_runs/iteration1-20261003-regression-v2/verification/runtime.json)。服务器部署 SHA、Python/依赖、资源、进程、代理、持久目录和健康均为 **未核验**。

主要文件：[诊断脚本](../scripts/runtime_diagnostics.py)、[诊断测试](../tests/test_runtime_diagnostics.py)、[服务器手册](server_operations.md)。诊断最终专项测试 34 通过。

## Task 2：请求保护与脱敏记录

Web 与 Tool 接入同一个 `QueryService` 校验入口：strip 后非空、最多 4000 字符，验证 mode 和严格 bool/null 参数；保留原 mode 别名和 Tool JSON 接口。无效输入不调用 pipeline。

同一 pipeline 的各服务适配器共享执行权，默认最多等 5 秒、最多 8 名等待者；队满/超时固定繁忙状态，异常后用 finally 释放执行权。等待者被唤醒后重新检查截止时间，超时不会进入 pipeline 或释放其他请求的执行权。每次请求独立 UUID、时间和诊断 recorder，不改写共享 `pipeline.recorder`。这是单进程保护，不提供跨主机限流、FIFO 或全链路硬截止。

新提交先清理上次结果；验证失败、繁忙或执行失败显示固定提示与 request_id，不展示异常正文。运营记录 `capture_content=False`，仅白名单版本、状态/错误码、时间、耗时、计数、实际后端及枚举原因。题干、答案、候选正文、PHI、凭据、trace 和完整异常均不进入运营日志。专用 logging handler 写 stderr 并关闭 root 传播，MCP stdout 继续专用于协议。内容评测 recorder 仍仅用于显式离线评测。

主要文件：[服务](../src/evidence_assistant/query_service.py)、[日志](../src/evidence_assistant/runtime_logging.py)、[Web](../app.py)、[Tool](../src/evidence_assistant/tool.py)、[服务测试](../tests/test_query_service.py)、[日志测试](../tests/test_runtime_logging.py)、[Web 测试](../tests/test_web_app.py)。既有 observer 已支持需要的接口，无需重复改写。最终 Web/Tool/并发/日志专项 46 通过、1 个可选 MCP 跳过；运输层在后述另一环境单独验证。

## Task 3：真实依赖状态与回退

为 PubMed、Europe PMC、ClinicalTrials、Supabase、generator 提供请求级结构化状态：`disabled / not_attempted / success / empty / error / fallback`，带固定 reason_code、耗时、结果数、实际后端。`used_live_api` 保留“尝试过”的兼容语义；UI 直接消费状态，区分尝试与成功获取，不解析 trace。

启用源失败、云检索失败、LLM 回退进入顶层降级信息；空结果是正常空结果，无 LLM key 的抽取式生成是 `success/offline_extractive`，不算故障。安全阻断后适配器调用为零；证据门控提前拒答时生成器为 `not_attempted`。超时、429、坏 JSON、缺字段、空 claims 和非有限 citation ID 等模拟故障可安全回退，随后继续引用验证、净化与后置门控。

新增 `LLM_REQUEST_TIMEOUT`，默认 45 秒，仅界定一次 LLM HTTP 调用；新增 `API_RETRY_SLEEP_CAP_SECONDS`，默认 5 秒，对实时 GET 的每次退避/Retry-After 等待封顶，处理日期、负值、NaN、Infinity 和极大值。仍使用现有 GET 重试次数，不另加 LLM 重试；服务排队、HTTP 单次超时、重试等待各自独立，**不描述为全链路硬截止**。

主要文件：[状态模型](../src/evidence_assistant/schemas.py)、[pipeline](../src/evidence_assistant/pipeline.py)、[生成器](../src/evidence_assistant/generate.py)、[配置](../src/evidence_assistant/config.py)、[重试公共代码](../src/evidence_assistant/retrievers/common.py)、三个实时适配器、[环境示例](../.env.example)、[依赖测试](../tests/test_dependency_states.py)。显式离线 Settings 同步两项新配置。最终生成/依赖/安全专项 107 通过；未调用真实付费模型或外部供应商。

## Task 4：可复现 C0、CI 与验收

新增 [当前基线冻结脚本](../scripts/freeze_current_baseline.py)，来源明确 `current_c0`；冻结真实源码、C0 数据、旧 15 题、显式配置及依赖，不读取私有 `.env`。输入清单使用可迁移相对路径和哈希；基线及输出必须新建，不覆盖历史工件。`eval.run_p0 --baseline-source current` 只允许当前 C0/G1，拒绝冒充历史臂或 C1。

候选在既有隔离子进程中运行两次；另在独立 reference 子树运行经过校验的冻结参考代码，使用相同有效数据和题集。汇总验证语义稳定、源码/数据/基线未改写、网络审计和适用工程门禁。稳定但全拒答、缺参考或 recall/nDCG/coverage/citation/support 退化不能通过验收。旧评分器复用，正式临床安全评审保持 N/A。

[CI](../.github/workflows/ci.yml)统一隔离 `.env`、实时源/云端密钥及模型下载，增加轻量当前 C0 冻结/回归；保留 Python 3.9/3.11 和 Python 3.11 必测真实 MCP stdio。远程 Actions 尚未执行。README 更新复现入口和范围。评测专项最终 39 通过，包括真实冻结参考运行和验收失败反例。

### 本次实测 C0

最终工件为 [当前冻结基线](../data/eval_runs/iteration1-20261003-current-c0-v2/manifest.json)和[回归汇总](../data/eval_runs/iteration1-20261003-regression-v2/summary.json)。旧 15 题两次语义一致，12 应答、3 拒答；15 次成功、0 错误、0 跳过。适用工程门禁全部通过；4 个子进程网络审计自检通过，非自检网络尝试为 0。范围是 Python audit hooks，未进行操作系统抓包。

| 旧题工程指标 | 本次结果 |
|---|---|
| Relevant-source Recall@8 | 23/24，95.83% |
| nDCG@8 | 89.85%，12 个应答题 |
| 词项要点覆盖代理 | 83.75%，12 个应答题 |
| 旧规则 citation accuracy / support | 均 100%，12 个应答题 |
| 应答/拒答标签一致 | 15/15 |
| 独立 qrels、临床评审、区间、Recall@40 | N/A；旧标签不支持正式结论 |

另从起始 `2d8be49` 的 Git archive 生成一份独立当前 C0 参考，用最终候选对照。比较答案/拒答、claims/citations、有序条目、引用校验、证据门控、生成条目及旧指标：**15/15 一致**，新增请求/依赖诊断和时间字段不参与兼容比较，见 [对照证据](../data/eval_runs/iteration1-20261003-before-after/before_after_compatibility.json)。这只是本轮开始前后工程对照；archive 无 Git 时 commit 为 unknown，另记录源 archive SHA，不能称为历史 P0 实验复现。

| 输入 | SHA-256 |
|---|---|
| 当前基线输入清单 | `06add2cabf1456adc521ccc66f33fdf903bc5b6970bc624f65c099970e974044` |
| 最终回归输入清单（含参考代码） | `92d99d683fdab005f752e190b1981640589bc160abd280d5b1d1dcc68ca1f24e` |
| 旧 15 题 | `3bb0e81eced9c2e667c358e5ed5ae520049eb54b3d651b5ef542fd9f24427368` |
| 知识页集合 | `51d6be3497ecd91904a9eda34a311511cdc56fd108744fde84e65ddd1ce6a8ee` |
| 离线快照 | `b07fb4add3937beb96eeaff7931061d7ff7235856e8363bc5f19f4b844ee75d5` |
| 语料版本清单 | `85c1e13fc8ec2e0de8a20b1a94a81fc0bcd993d71ede95a7f005dbf6e70b7142` |
| metrics.py | `1b2746cea6aced772a2811b9017ad6aa3dbfc527ca26bec3c2cc04510680d777` |
| metrics_v2.py | `5c33895b2ad620018e063d8f73f675c17766bcb0a3c485f3a5bfb771fd140da2` |

评测工件含公开题目与答案，仅作为显式离线工程记录；`data/eval_runs/` 被 Git 忽略，当前机器可查看，公开克隆无需这些历史私有工件即可用新目录重新执行。最终源码在上述工件中冻结；本报告及手册的后续文字更新不改变被测代码。

### 共享 pipeline 受控并发

macOS ARM 本地离线 C0，每档 1 个 pipeline，预热 10 次，使用固定可回答旧题，120 次/档，nearest-rank 分位数。两档均 120 应答、0 错误、0 busy；总链路超时率 N/A。

| 并发 | 请求 P50/P95/P99 ms | 锁等待 P50/P95/P99 ms | 执行 P50/P95/P99 ms | 线程池调度等待 P50/P95/P99 ms | RSS 高水位 |
|---|---|---|---|---|---|
| 1 | 7.09 / 8.11 / 8.72 | 0.001 / 0.002 / 0.004 | 7.00 / 8.01 / 8.61 | 423.83 / 817.39 / 852.97 | 34,177,024 B |
| 4 | 22.02 / 70.81 / 144.96 | 8.65 / 56.83 / 134.79 | 7.12 / 7.94 / 9.10 | 400.50 / 787.36 / 823.17 | 34,422,784 B |

请求耗时从线程开始执行计算，锁等待不包含线程池调度等待，后者单列。一次提交 120 项形成调度积压，不能当作真实线上到达分布。互斥使并发 4 的等待增加，不能假定四倍吞吐。CPU 电源/争用、系统缓存未控制，无 GPU/外部调用；RSS 为进程高水位，后一档包含前一档分配。详细数据见 [performance.json](../data/eval_runs/iteration1-20261003-regression-v2/C0/G1/performance/performance.json)。

### Web 与健康实测

本地临时 Streamlit 监听 `127.0.0.1:18501`，明确关闭实时源、云端、LLM 和可选索引。真实浏览器完成公开问题应答与引用、领域外拒答、空白输入错误及旧结果清理、刷新后再次成功问答。无 key 显示正常离线抽取，各外部源为未启用，request_id 可见。繁忙、执行异常、故障恢复与各种依赖失败状态通过 AppTest/受控 pipeline 验证，未在真实浏览器注入供应商故障。临时服务器验证后已停止。

HTTP `/_stcore/health` 返回 `ok`，只计作本地 HTTP 健康；实际交互另计作本地 Web 问答证据，没有验证线上反向代理、TLS 或 WS 101 状态。截图：[本地 Web 冒烟](assets/iteration1-web-smoke.png)。

## 实际验证命令与结果

主要运行时：`/Users/yangxuesong/Clinical Evidence Assistant/.venv/bin/python`（Python 3.9.6）。下文用 `CEA_PY` 表示该绝对路径，`CEA_MCP_PY` 表示既有 `.venv-mcp/bin/python`（Python 3.13.13 / MCP 2.0.0）。没有使用缺 pytest 的默认 Python 3.14。

全套测试实际显式环境：`EVIDENCE_ASSISTANT_ENV_FILE=/dev/null`，实时源/云端关闭，LLM/PubMed/NCBI/Supabase 凭据清空，`MODEL_LOCAL_FILES_ONLY=true HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`。本地 C0 runner 另有自身环境白名单与显式 Settings。命令的 `v2` 目录是本次实测工件；复跑必须替换为新目录。

```bash
CEA_PY='/Users/yangxuesong/Clinical Evidence Assistant/.venv/bin/python'
CEA_MCP_PY='/Users/yangxuesong/Clinical Evidence Assistant/.venv-mcp/bin/python'

# 在上述隔离环境运行
"$CEA_PY" -m pytest -q -rs
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null PYTHONPATH='/private/tmp/cea-iteration1-mcp-test-deps:src:.' CLINICAL_REQUIRE_MCP=1 "$CEA_MCP_PY" -m pytest -q tests/test_mcp_server.py tests/test_mcp_stdio.py
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null ENABLE_LIVE_APIS=false ENABLE_SUPABASE=false LLM_API_KEY='' "$CEA_PY" scripts/smoke_test.py
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null EVIDENCE_ASSISTANT_CACHE_DIR=/private/tmp/cea-iteration1-desktop-cache ENABLE_LIVE_APIS=false ENABLE_SUPABASE=false LLM_API_KEY='' PYTHONPATH=src "$CEA_PY" -m evidence_assistant.desktop --check
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null "$CEA_PY" scripts/runtime_diagnostics.py --output /private/tmp/cea-iteration1-final-runtime-20261003-v2.json
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null "$CEA_PY" scripts/lint_knowledge_pages.py --strict
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null "$CEA_PY" scripts/freeze_current_baseline.py --output data/eval_runs/iteration1-20261003-current-c0-v2
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null "$CEA_PY" -m eval.run_p0 --baseline-source current --baseline data/eval_runs/iteration1-20261003-current-c0-v2 --output data/eval_runs/iteration1-20261003-regression-v2 --profiles C0 --arms G1 --performance --shared-pipeline --trials 120
EVIDENCE_ASSISTANT_ENV_FILE=/dev/null "$CEA_PY" -m eval.run_p0 --baseline-source current --baseline data/eval_runs/iteration1-20261003-before-v2 --output data/eval_runs/iteration1-20261003-before-after --profiles C0 --arms G1
curl --silent --show-error --fail --max-time 5 http://127.0.0.1:18501/_stcore/health
git diff --check
```

| 检查 | 最终实际结果 |
|---|---|
| 全套 pytest | **334 passed, 3 skipped, 5 warnings，6.20s**；[日志](../data/eval_runs/iteration1-20261003-regression-v2/verification/final_pytest_after_review.log) |
| MCP server 与 stdio | **2 passed，0.88s**；包含 1 项真实子进程 stdio、1 项进程内 server 测试；[日志](../data/eval_runs/iteration1-20261003-regression-v2/verification/final_mcp_after_review.log) |
| 离线 smoke | PASS，pdf_docs=0，answer_entries=8，checked=4 |
| desktop `--check` | Offline check passed；显式使用可写临时缓存目录 |
| 管理员诊断 | ready，仅本地资源 |
| 知识页 strict lint | 0 issues |
| 当前冻结与 C0 回归 | 退出 0；两次语义一致、参考对照/适用门禁/输入完整性通过 |
| 起始代码对照 | 退出 0；15/15 语义兼容 |
| 本地 HTTP / Web | `ok` / 实际交互通过，范围如上 |
| `git diff --check` | 退出 0 |

MCP 环境缺 pytest；把主环境已有纯 Python pytest 及其测试依赖复制到独立 `/private/tmp/cea-iteration1-mcp-test-deps` 后，用 PYTHONPATH 执行，没有安装或修改两份已有环境。这是本机测试支架；新环境应按 CI 安装项目测试依赖和 MCP extra，不依赖该临时目录。

## 失败、修复与未执行项

各任务先补反例测试再作最小实现：Task 1 测缺资源/脱敏/写入保护；Task 2 初始缺服务模块及 UI 错误状态；Task 3 初始缺结构化状态与有界等待；Task 4 初始缺当前冻结/共享性能/验收入口。这些 RED 失败用于验证测试有效，后续 GREEN 及上述最终集成结果替代中间状态。

独立审查发现 5 项 Important，均先复现再修复：稳定全拒答仍能通过当前 C0 CI；超时等待者取得已释放执行权；非有限 citation ID 逃逸回退；等数量却错误关联的 FTS 被判有效；损坏标量 dense 数组导致诊断 traceback。补齐参考/行为及质量门禁、唤醒后截止检查、citation 类型校验、双向 FTS 关系和诊断错误边界后，独立复查结论为 **Approve，0 个剩余 Critical/Important**。原始问题和修复附录保留在 [独立审查记录](../data/eval_runs/iteration1-20261003-regression-v2/verification/final_review.md)；未把旧审查失败改写为从未发生。

| 项目 | 状态及处理 |
|---|---|
| 主环境 2 个 MCP 测试 skip | Python 3.9 环境没有 MCP；另用 Python 3.13.13 实测 server 与 stdio 共 2 项通过，skip 本身不计通过 |
| PDF 500 篇索引测试 skip | C1 索引未提供，未执行；没有新建伪索引补数字 |
| 5 条 SWIG 警告 | 既有 PyMuPDF DeprecationWarning；无本轮新增失败 |
| 起始 archive 第一次回归 | 因缺 `dataset.json` alias 失败；保留 `iteration1-20261003-before` 失败工件，补齐冻结输入 alias 后新建 `before-v2` 成功，不覆盖旧结果 |
| 默认 desktop 缓存位置 | 沙箱无默认用户缓存目录写权限；改为显式可写 `/private/tmp` 后通过 |
| 临时本地服务/HTTP | 首次 bind 和 curl 受沙箱限制；允许本地测试的自动审批后启动/探测成功。没有生产操作 |
| 历史 P0 工件 / C1 | 未取得，经核验历史工件复现和 C1 回归均未执行；起始代码 archive 不冒充历史实验 |
| 真实供应商、云端、LLM、神经模型推理 | 未执行；故障/回退以 fake 响应验证 |
| 远程 CI / Python 3.11 矩阵 / 新包安装检查 | CI 已完善但本轮未执行远程 Actions、全新安装或 3.11 环境；本地 desktop 使用源码入口 |
| 临床金标准、盲评、双评、仲裁、48 题 | 未执行，N/A；未伪造人工评审或质量提升结论 |
| 生产健康、容量、发布、备份恢复、回滚演练 | 未执行且未核验；用户本轮授权限本地交付 |

## 部署验收与回滚交接

具体管理员命令、启动/自启、代理/WebSocket、日志轮转、SQLite 一致性备份和原子版本回滚见 [服务器运行手册](server_operations.md)。手册以 Linux/systemd/Nginx 作明确标识的示例；实际系统与托管方式仍未提供，不能把示例写成已部署配置。

生产发布待用户另行确认。获准后依次执行：

1. 只读核对现网 SHA、脏工作树、运行 Python/依赖、启动用户/进程数、配置和数据目录；运行管理员诊断，将代码与语料哈希对齐。保存现有版本、受限配置及对应索引的一致性备份。
2. 将本轮审阅代码形成有唯一提交/构建校验和的发布工件，保留旧发布目录和依赖环境；使用现网确认的 supervisor/平台，先在隔离测试或小范围实例完成离线、Web、代理/WS 核验。本轮不更换默认算法或生产语料。
3. 按已批准的启动方式切换并重启；分别检查进程、直连 HTTP、代理 HTTP、实际 WS/问答、脱敏日志及版本哈希。观察错误/降级率、队满/队时限率和延迟，记录观察窗口、基数和结果；尚无线上阈值数据可作为本地推断。
4. 若出现发布新增故障、语料版本不符或安全门禁异常，恢复已验证前一版本的**代码、配置、依赖及对应索引组合**，再重启并重复版本/健康/公开问答核验；保留新旧工件和失败证据，不用旧缓存代替回滚验收。

当前仅完成本地交付，没有执行以上服务器步骤。

## 所需用户信息与下一轮任务

线上验收需要：网站 URL、服务器系统及访问方式、现有启动/托管方式与进程数、发布/配置/缓存/日志/语料/索引目录、实际使用的 C0/C1/云端资源、现网 SHA 和依赖环境、代理及重启命令、日志保留策略、已验证的回滚版本与备份位置。只需说明密钥是否配置和保存方式，不在聊天或报告中提供密钥值。

下一轮按计划推进：

1. 48 题独立试点（16 开发、32 盲测），版本化文档级 0–3 qrels、要点和应答/拒答标签；两名循证评审独立标注，第三人仲裁，补齐泄漏检查、适用分母和配对区间。旧 15 题继续冻结。
2. 核验现网实际语料，再审计弱主题、题名/主标识、文献类型与全文状态；用独立候选索引及来源账本，不覆盖原索引。历史候选缺口不能直接推定现网现状。
3. 基于独立开发集分类缺资料、召回、Top-8/Top-5 选择、生成、校验和误拒答问题；诊断 q008/R2 所代表的通用失败，固定其他变量逐层实验，避免题号特判或直接切换默认后端。
4. 在获准发布后做线上观察和回滚演练；若真实积压需要请求总预算或进程取消，再单独设计，保留单次超时与全链路截止的边界。
