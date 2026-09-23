# 循证知问 · 临床证据助手

[![CI](https://github.com/xiaoxiaomugong/clinical-evidence-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaoxiaomugong/clinical-evidence-assistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个可离线演示、可作为 MCP/Agent Tool、也可接入实时医学检索与在线大模型的循证问答 MVP。当前问答流程：

```text
临床问题 → PHI / 诊疗边界预检 → 中英文查询计划 → 本地语料 / Supabase + 实时 API
         → 保留不同原文与段落、文档内去重 → 统一重排 → Top-8 证据门控
         → 互补 Top-5 生成证据包 → 独立来源 / 必要类型复核
         → JSON 原子陈述生成 → 实际生成包引用 / 支持性 / 数字与单位 / 字面否定校验
         → 删除无支持陈述与无效引用 → 后置拒答
         → 带证据等级和原始链接的回答
```

项目默认采用“离线优先”：不配置任何密钥也可以运行 Web UI 或 MCP tool、完成带引用问答、触发拒答并跑完整测试集。配置实时 API 或 LLM 后会自动增强，失败时降级到本地可信语料。

> 仅供教学与研究，不构成诊断或治疗建议。请勿输入可识别患者隐私信息。

## P0 优化进展（2026-09-23）

原文候选保留、生成证据包复核、输出安全及隔离评测工具已落地。**P0 尚未整体完成：Top-8 多样性实验、新语料和独立临床评审仍有未通过或未完成的门禁。**

- **默认策略已更新**：候选池使用 `source_preserving`，按文档身份与完整文本哈希去重，移除旧的池内研究家族截断，减少原文被知识页条目挤出的情况。Top-8 选择仍为 `legacy`。
- **安全复核已启用**：实际用于生成的 Top-5 再次检查独立来源和必要证据类型；引用校验限定在该证据包内，增加单位与字面否定检查，并阻止 PHI 阻断响应回显原始题干。
- **旧题回归有改善**：当前默认策略在内置语料 C0 / 挂载原本地 PDF 索引 C1 上，旧 Recall@8 分别从 75.00% 提升至 95.83% / 91.67%。这来自同一套 15 题的工程回归，不代表独立临床验证。
- **工具与数据状态分开记录**：隔离 runner、阶段追踪、分级评分和语料候选审计工具已实现；实验策略与候选语料未替换默认 Top-8 策略或原索引。

详见下文 [P0 优化与隔离回归](#p0-优化与隔离回归)及 [P0 实施报告](docs/optimization_p0_implementation_report.md)。

## 当前能力

| 能力 | 默认行为 | 可选增强 |
|---|---|---|
| 使用入口 | Streamlit Web UI、Python Tool API、MCP stdio 服务 | 接入任意支持 MCP 的 agent host |
| 证据来源 | 5 个知识页、10 条精选文献快照，可完全离线运行 | 本地 PDF 全文、Supabase 云端证据库、PubMed / Europe PMC / ClinicalTrials.gov 实时检索 |
| 检索与重排 | BM25、TF-IDF、RRF 和确定性重排 | 版本化稠密索引、混合召回、交叉编码器 |
| 候选与证据包 | 原文候选保留、来源身份归并、实际 Top-5 复核 | Top-8 文档多样性实验（未默认启用） |
| 回答生成 | 从证据中抽取原子陈述并逐条校验 | OpenAI-compatible JSON 生成 |
| 质量与安全 | PHI/诊疗边界预检、证据门控、引用/数字/单位校验、后置拒答 | 语料门禁、隔离回归、本地阶段追踪、三臂对比评估 |

所有在线能力都采用显式配置并保留本地回退路径；不配置任何密钥时，核心问答、测试和评估仍可运行。

## 从 GitHub Releases 安装

每个正式版本提供轻量离线桌面安装包和 Python 分发包：

| 平台 | Release 文件 | 安装方式 |
|---|---|---|
| Windows x64 | `Clinical-Evidence-Assistant-*-windows-x64-setup.exe` | 双击安装，无需预装 Python |
| macOS Apple Silicon | `Clinical-Evidence-Assistant-*-macos-arm64.dmg` | 拖入 Applications |
| macOS Intel | `Clinical-Evidence-Assistant-*-macos-x86_64.dmg` | 拖入 Applications |
| Ubuntu/Debian x64 | `clinical-evidence-assistant_*_amd64.deb` | `sudo apt install ./clinical-evidence-assistant_*_amd64.deb` |
| Python/MCP | `.whl` | 适合开发者和 agent host |

桌面版内置 Python、Web UI、核心问答和小型离线语料，首次运行不需要 API key。它只监听本机
`127.0.0.1`，并自动在浏览器打开界面。大型 PDF 全文、生成的 SQLite 索引、稠密模型和密钥不进入
安装包；高级用户仍可通过 `PDF_INDEX_PATH`、模型路径及用户配置文件挂载。

Release 同时提供 `SHA256SUMS.txt`。在项目尚未配置正式签名证书时，macOS 或 Windows 可能显示
“未知开发者”提示；用于公开分发前应配置代码签名和 macOS notarization，详见
[发布手册](docs/releasing.md)。

也可从 wheel 安装 UI：

```bash
python3 -m pip install 'clinical-evidence-assistant[ui]'
clinical-evidence-ui
```

只验证安装资源和离线问答而不启动服务：

```bash
clinical-evidence-ui --check
```

## 立即运行 Web UI

推荐 Python 3.11；代码兼容 Python 3.9+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

浏览器会打开 `http://localhost:8501`。默认配置下无需网络和 API key。

也可用 Makefile：

```bash
make install
make run
```

## 作为 Agent Tool 使用（MCP）

项目同时提供一个标准 MCP stdio 服务，原 Streamlit UI 和 `EvidencePipeline` 调用方式保持不变。
MCP 运行时要求 Python 3.10+，推荐继续使用 Python 3.11：

```bash
python3 -m venv .venv
source .venv/bin/activate
make install-tool
# 等价于：python3 -m pip install -e '.[mcp]'
```

安装后，任何支持 MCP 的 agent host 都可以用下面的配置启动本地工具。`command` 建议填写
虚拟环境中可执行文件的绝对路径，因此不依赖 host 的工作目录：

```json
{
  "mcpServers": {
    "clinical-evidence": {
      "command": "/absolute/path/to/.venv/bin/clinical-evidence-mcp"
    }
  }
}
```

也可以直接从源码启动服务，便于本地调试：

```bash
make run-tool
```

服务暴露一个 `query_clinical_evidence` tool：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `question` | string | 必填 | 去标识化的临床学习或科研问题，最长 4000 字符 |
| `mode` | string | `hybrid` | `hybrid`、`knowledge` 或 `rag` |
| `enable_live_apis` | boolean / null | `null` | `null` 使用服务端配置；`true` 显式启用三个实时检索源 |

返回值是可直接供 agent 推理的结构化 JSON，包含 `status`、原子陈述、编号引用、完整证据条目、
证据门控、引用校验、实际检索/重排后端、降级原因与检索轨迹。`status=refused` 时，agent 应保留
拒答边界，不应自行补写临床结论。MCP 使用 stdio，stdout 专用于协议消息。

也可在不依赖 MCP 框架时直接复用同一个 Tool API：

```python
from evidence_assistant import query_clinical_evidence

result = query_clinical_evidence(
    "降压药应早上服用还是睡前服用？",
    mode="hybrid",
    enable_live_apis=False,
)
```

已安装的包会携带知识页和精选文献快照，所以不依赖仓库工作目录也能离线运行。大型 PDF 索引
不会打入安装包；如需挂载现有索引，可设置 `PDF_INDEX_PATH=/absolute/path/to/index.sqlite3`。
安装态默认使用系统临时缓存；生产环境可用 `EVIDENCE_ASSISTANT_CACHE_DIR` 指定持久目录。

如需从 PDF 新建索引，再安装 PDF 可选依赖：

```bash
python3 -m pip install 'clinical-evidence-assistant[pdf]'
```

## 三种检索模式

| 模式 | 行为 | 适用场景 |
|---|---|---|
| 混合模式 | 知识页 + 本地文献优先；相关性不足时才调用实时 API | 默认演示 |
| 知识页优先 | 只使用人工审阅、绑定已核对来源的知识页 claim | 最稳定、最可解释 |
| RAG 优先 | 本地文献快照；开启实时 API 后同时检索三类在线源 | 长尾与最新研究 |

界面中的“启用实时 API”控制 PubMed、Europe PMC 与 ClinicalTrials.gov API v2。三者均可免费、免密钥检索；配置 `PUBMED_API_KEY` 可提高 NCBI 限流额度。在线结果默认缓存 1 小时，并对各来源独立节流；遇到 429、临时服务错误或超时时有限重试，单源失败不会中断其余检索与本地兜底。

## 配置在线生成

复制环境变量模板：

```bash
cp .env.example .env
```

最少配置：

```dotenv
LLM_API_KEY=your_key
LLM_MODEL=gpt-4.1-mini
LLM_BASE_URL=https://api.openai.com/v1
```

接口按 OpenAI-compatible Chat Completions JSON mode 调用。未配置或调用失败时使用抽取式生成器：它直接输出候选证据中的 claim/摘要，因此仍可校验、不会凭空补全。

## 启用阶段 2 混合语义检索

默认仍使用 `legacy + deterministic`，不会加载或下载模型。需要评估稠密召回和交叉编码器时，先安装可选依赖并在请求路径之外构建不可变索引：

```bash
pip install -e '.[retrieval]'
export EMBEDDING_MODEL=/absolute/path/to/local-embedding-model
export EMBEDDING_MODEL_REVISION=your-pinned-revision
python3 scripts/build_dense_index.py
```

然后启用混合后端：

```dotenv
RETRIEVAL_BACKEND=hybrid
RERANK_BACKEND=cross_encoder
RERANK_MODEL=/absolute/path/to/local-rerank-model
RERANK_MODEL_REVISION=your-pinned-revision
MODEL_LOCAL_FILES_ONLY=true
RETRIEVE_K=40
RERANK_K=8
GENERATION_K=5
```

应用不会在请求主路径自动建索引或下载模型。索引缺失、版本不匹配、模型加载失败或推理异常时会回退到 legacy/确定性重排，并在 UI、流水线结果和评估工件中标记实际后端与降级原因。对比不同后端：

```bash
python3 scripts/benchmark_retrieval.py \
  --profile legacy:deterministic \
  --profile hybrid:deterministic \
  --profile hybrid:cross_encoder
```

## 已实现的安全边界

- 生成证据包再次检查独立来源和必要类型；引用编号只能来自实际传入生成器的证据包。
- 知识页 PMID 带核对日期；运行脚本可再次向 NCBI 批量回查。
- 回答按原子陈述生成；数字及显式单位必须与证据一致，并检查字面否定反转。这些规则不能代替医学语义审查。
- 不支持的陈述和不可用引用会在进入 UI 前被物理移除；净化后无核心陈述则拒答。
- 按 PMID/DOI/NCT 统计独立来源；来源不足、缺预期证据类型或冲突未解释时拒答。
- 页面身份与研究身份分开处理；重复论文表示和已知研究别名归并，身份不明的条目不虚增来源数。自动规则不能替代人工研究家族核验。
- 疑似 PHI 与个体化剂量、停药、换药问题会在检索和外部调用前阻断。
- 模型生成的无引用辅助字段使用应用固定文案；PHI 阻断响应不回传原始题干。
- 明显超领域、虚构疗法、空候选或低相关问题在生成前拒答。
- ClinicalTrials.gov 条目固定标为 `ClinicalTrial`，并保留 `status`，不会冒充已发表 RCT。
- Europe PMC 预印本默认过滤；关闭过滤时明确标为 `preprint`。
- 默认不持久化用户问题；缓存只存公开检索结果。

## 数据与可复现性

仓库内置语料包括 5 个主题知识页、15 个 claim 和 10 条精选 PubMed 文献快照；项目另支持挂载本地 PMID PDF 集合并建立磁盘型全文索引：

- 成人高血压起始药物与服药时间
- 血脂风险分层、他汀与肌肉症状
- 2 型糖尿病的 GLP-1 / SGLT2 / 胰岛素选择
- 脑卒中/TIA 二级预防
- 地中海饮食与钠摄入

语料版本记录在 `data/corpus_version.json`。离线文献摘要是对 PubMed 元数据/摘要的中文概述；原始来源链接保留在每个条目中。

论文 PDF、PubMed 批量元数据和生成的 SQLite 索引不随仓库分发，以避免版权和仓库体积问题。没有这些文件时，应用会自动跳过 PDF 支路，内置知识页与精选快照仍可离线运行。

如需使用你有权处理的本地 PDF，请在 `500-collection/` 放置 500 份以 PMID 命名的 PDF 和 `selected_manifest.csv`。清单字段为 `pmid,title,pub_year,nlm_unique_id,if_value,q_value,source_pdf,dest_pdf`。构建脚本使用 PyMuPDF 提取文本块并建立 SQLite FTS 索引：

```bash
python3 scripts/index_pdf_collection.py
```

本项目开发时的本地基准索引包含 500 篇文献、18,002 个 chunk，其中 480 篇成功提取全文，20 篇使用 PubMed 摘要兜底。该结果仅记录工程测试条件，不代表仓库附带或授权分发相关论文。

重新核对知识页 PMID：

```bash
python3 scripts/verify_pmids.py --strict
```

采集一个独立的多源快照（默认目标 200 条，不覆盖内置演示语料）：

```bash
python3 scripts/collect_corpus.py --target 200
```

## Supabase 云端证据库

仓库包含可直接部署的 Supabase 迁移、显式 Data API 授权、RLS 只读策略、全文检索 RPC，
以及按来源原子替换的同步工具。应用读取时只需要 publishable key；写入、发布和中止同步仅允许
后端 secret/service-role key。`anon` 与普通已登录用户不能访问暂存表或发布 RPC。

每次推送先把文档和 chunk 分批写入后端暂存表，再由单个 PostgreSQL 事务发布：

```text
本地来源 → staging（批量上传）→ publish RPC（校验并原子替换）→ 可检索证据表
                                  └─ 失败：事务回滚，原有可见版本不变
```

新版本发布时会停用该来源中已删除的文档，并删除其旧 chunk；中途失败则清理暂存数据并把
本次 ingestion 标为失败。应用仍保持离线优先：启用云端后会把 Supabase 词法候选并入统一
重排池，连接失败则自动回退知识页、JSON 快照和 SQLite PDF 索引。

先部署迁移并配置环境变量：

```bash
npx --yes supabase@2.109.1 link --project-ref YOUR_PROJECT_REF
npx --yes supabase@2.109.1 db push --dry-run
npx --yes supabase@2.109.1 db push

cp .env.example .env
# 填写 SUPABASE_URL、SUPABASE_PUBLISHABLE_KEY、SUPABASE_SECRET_KEY
```

然后预览或执行同步：

```bash
# 不联网检查将要同步的数据量
python3 scripts/sync_supabase.py push --source snapshot --dry-run

# 使用 SUPABASE_SECRET_KEY 执行按来源原子替换
python3 scripts/sync_supabase.py push --source snapshot

# 从云端生成新的离线快照
python3 scripts/sync_supabase.py pull
```

本地 PDF 默认仅同步题录/摘要；只有确认拥有相应权利时才可显式加入全文。完整建库、
密钥轮换、安全边界和故障恢复说明见 [docs/supabase.md](docs/supabase.md)。

生成语料质量报告，并检查知识页可追溯字段：

```bash
python3 scripts/audit_corpus.py
python3 scripts/lint_knowledge_pages.py --strict
```

当前质量报告写在 `data/corpus_quality.json`。它会明确报告领域分布、证据等级、全文/摘要兜底、重复主键和未通过的质量门禁，避免只用“500 篇”代表语料质量。

## 测试与评估

```bash
pytest -q
python3 scripts/smoke_test.py
python3 eval/run_eval.py --mode hybrid
python3 eval/run_compare.py
```

GitHub Actions 在 Python 3.9 和 3.11 上验证核心离线流程，并在 Python 3.11 任务中额外安装
`mcp` extra、通过真实 stdio 子进程发现并调用 MCP tool，检查 stdout 协议及拒答行为。该 CI 步骤用
`CLINICAL_REQUIRE_MCP=1` 将运行时缺失视为失败；未安装 MCP 的普通本地环境则跳过相关测试。

2026-09-23 本地验证记录：核心测试 **179 通过、2 跳过**（Python 3.9.6），另在 Python 3.13.13 / MCP 2.0.0
环境完成 **2 项 MCP 测试**；离线 smoke、桌面入口 `--check` 与知识页 lint 通过。核心测试有 5 条既有
SWIG 弃用警告；该记录不代表远端 CI、真实浏览器交互或多平台安装包均已验证。

若本机已安装 Docker 与 Supabase CLI，还可以在隔离的本地数据库中验证迁移、RLS、原子替换、
回滚和暂存清理：

```bash
supabase start
supabase db reset --local --no-seed
supabase test db --local supabase/tests/atomic_evidence_publish_test.sql
supabase db lint --local --schema public --fail-on error
```

固定测试集包含 15 题，覆盖事实型、指南型、争议型和 3 个应拒答问题。评估输出写入 `data/eval_results/`：

- 检索层：Recall@8、MRR、nDCG@8
- 生成层：引用与陈述支持规则通过率、词项覆盖率、旧应答/拒答标签一致率（工程代理指标）
- 明细：每题 Top-1、分数、延迟、结构化回答

`eval/run_compare.py` 对 Arm A 纯 LLM、Arm B 正常 RAG 与 Arm C 劣化 RAG 统一执行输入预检，分别记录执行状态和应答行为。Arm A 需要配置 `LLM_API_KEY`，未配置时记为 skipped，质量指标为 N/A。C 仅标为 `legacy_degraded_smoke`，不代表已完成指定证据扰动实验。净化前输出由显式启用的本地 recorder 保存，不加入公开 Tool/MCP 响应。

### P0 优化与隔离回归

#### 默认配置与回滚

```dotenv
CANDIDATE_POOL_POLICY=source_preserving
TOP8_SELECTION_POLICY=legacy
RETRIEVAL_BACKEND=legacy
RERANK_BACKEND=deterministic
```

上述为代码默认值；已有环境变量的显式配置仍优先。候选保留与 Top-8 选择可独立配置：将
`CANDIDATE_POOL_POLICY` 设为 `legacy` 可回滚候选策略，不会关闭来源身份安全、实际生成包复核或输出安全规则。
`TOP8_SELECTION_POLICY=document_diverse` 仅用于实验，其覆盖回归尚未通过，不建议作为默认配置。

#### 旧题集上的变化

以下摘自 2026-09-23 冻结运行 `p0-final-20260923-v3`。B1 为隔离 worker 中的历史行为基线，G1 为当前默认策略对应配置；代码默认值已在 C0/C1 共 30 个题目—配置组合上与 G1 核对一致。

| 语料配置 | 旧 Recall@8：B1 → G1 | 旧 nDCG@8：B1 → G1 | 词项覆盖：B1 → G1 | 应答 / 拒答：B1 → G1 |
|---|---|---|---|---|
| C0：5 个知识页 + 10 条快照 | 75.00% → 95.83%（18/24 → 23/24） | 77.56% → 89.85% | 81.67% → 83.75% | 12/3 → 12/3 |
| C1：C0 + 原 500 篇本地 PDF 索引 | 75.00% → 91.67%（18/24 → 22/24） | 75.47% → 85.63% | 80.00% → 82.08% | 12/3 → 12/3 |

每个配置仍只有 15 道旧题：12 道应答题、3 道应拒答题。Recall 分母为 24 个来源标签，不能解释为
24 项独立研究；重复运行也不增加独立样本量。旧标签、`eval/metrics.py` 和安全阈值均保持不变。
词项覆盖及规则通过率不能作为医学正确率，独立分级指标和正式置信区间仍为 N/A。

同轮离线抽取式性能测试中，G1 并发 1 的全链路 P95 为 C0 **7.62 ms**、C1 **68.45 ms**，对应 B1 为
6.89 / 66.63 ms；每档预热 10 次、180 次请求且均实际应答。计时不含全文诊断落盘开销，电源模式、系统争用
和 OS 缓存未受控，不作为在线 LLM 或生产服务延迟承诺。完整并发 1/4 数据与测量限制见 [实施报告](docs/optimization_p0_implementation_report.md)。

#### 隔离复现与实验臂

普通克隆可运行上方测试与内置 15 题评估。**完整 P0 对比另需本机保留的历史冻结工件**，包括原始语料快照，
C1 还需要冻结 PDF 索引；它们和原始评测记录均不随 GitHub 仓库分发。输出目录必须不存在，且不能位于基线目录内：

```bash
python3 -m eval.run_p0 \
  --baseline /absolute/path/to/historical-p0-run \
  --output data/eval_runs/p0-new-run \
  --profiles C0 C1 --arms B0 B1 R1 I1 G1 R2 --performance --trials 180
```

runner 在干净子进程中禁用 live、云端和 LLM，冻结代码/数据，执行两次确定性回归及网络拒绝自检；报告包含阶段候选、原始与净化后陈述映射、逐题状态、耗时和哈希。历史 B0 无完整阶段 recorder。并发性能使用轻量计时，不把保存全文的诊断开销混入主性能结果。

| 实验臂 | 用途 |
|---|---|
| B0 / B1 | 冻结历史代码 / 历史行为加新 recorder，用于核对基线一致性 |
| R1 | B1 加原文候选保留 |
| I1 | R1 加来源身份修复，用于单独分析身份计数影响 |
| G1 | I1 加实际 Top-5 门控，对应当前默认策略 |
| R2 | G1 加 Top-8 文档多样性，仅实验启用 |
| D1 / RD | 分别在 B1 / G1 上更换独立候选语料；须指定 `--profiles C1 --index ...` |

历史身份规则和生成包旁路只在隔离 worker 中复现，产品配置没有安全旁路。性能报告同时列出请求数与实际应答数，
不以拒答快路径代替应答性能。网络拒绝自检覆盖 Python socket/DNS 和子进程审计，不等同于 OS 抓包。

新评分器 `eval/metrics_v2.py` 支持 0–3 分级、完整 IDCG、重复条目零增益、未标注候选 N/A 和题组 bootstrap；
通过 `--dataset`、`--qrels` 接入独立标注。旧题未具备独立分级 qrels，不能仅切换评分器就宣称正式质量达标。

#### 语料治理与剩余工作

`scripts/prepare_corpus_candidate.py` 在独立目录生成候选索引与来源台账；`scripts/audit_corpus.py --check`
会在质量门禁失败时返回非零退出码，默认报告模式允许检查未达标语料。候选 manifest 和索引应使用独立路径，不覆盖原 P0 索引。

- **Top-8 实验未默认启用**：R2 的 C1 词项覆盖从 B1 的 80.00% 降至 77.92%；C0 并发 1 P95 另触发超过 20% 的性能警报，尚待复核。q008 的原文排序问题仍需在独立开发集诊断。
- **新语料未替换原库**：v2 候选保留 500 条原始记录，其中 468 篇可用（368 全文、100 实质摘要），其余 32 条仅有可确认标题；文献量、全文率、核心主题覆盖和 Other 比例四项门禁失败，132 个 PDF 仍待严格题名核验。
- **独立临床评审未完成**：需明确评测负责人、两名独立循证评审及仲裁者，建立 48 题（16 开发 / 32 盲测），再扩至 200 题。当前没有正式临床质量或严重安全错误门禁通过的结论。

完整决策、失败项和工件索引见 [P0 实施报告](docs/optimization_p0_implementation_report.md)；其原始工件链接指向被 Git 忽略的本地 `data/eval_runs/`，公开克隆中不可访问。

## 目录

```text
.
├── app.py                         # Streamlit UI
├── config.py                      # 环境配置与阈值
├── data/
│   ├── knowledge_pages/           # 5 个结构化知识页
│   ├── raw/local_corpus.json      # 离线文献快照
│   ├── raw/                        # 演示快照；本地 PDF 索引不入库
│   ├── cache/                     # 实时检索缓存
│   ├── corpus_version.json
│   └── corpus_quality.json        # 机器可读的语料质量门禁
├── src/evidence_assistant/
│   ├── pipeline.py                # 端到端编排
│   ├── tool.py                    # 框架无关的 Agent Tool 适配层
│   ├── mcp_server.py              # MCP stdio 服务入口
│   ├── config.py                  # 源码/安装包均可用的运行配置
│   ├── query_rewrite.py           # 领域识别与中英文扩展
│   ├── knowledge_base.py          # 知识页召回
│   ├── interfaces.py              # 检索/重排后端协议与状态
│   ├── index_registry.py          # 版本化、不可变稠密索引
│   ├── candidate_pool.py          # 原文保留、文档去重与来源身份
│   ├── rerank.py                  # 跨来源统一评分与互补证据打包
│   ├── rerankers/                 # 确定性/交叉编码器后端
│   ├── generate.py                # JSON LLM / 离线抽取式生成
│   ├── citation_check.py          # 映射/存在/支持/数字校验与输出净化
│   ├── observability.py           # 可选的阶段耗时与候选追踪
│   ├── output_policy.py           # 生成器辅助字段净化与固定文案
│   ├── refusal.py                 # 安全、证据与后置解释性拒答
│   └── retrievers/                # 实时源、Supabase、词法、稠密与混合 RRF
├── docs/
│   ├── optimization_p0_implementation_report.md # P0 交付、实测结果与剩余门禁
│   ├── optimization_p0_plan.md    # P0 优化方案
│   ├── evaluation_p0_report.md    # 优化前的冻结基线报告
│   ├── evaluation_plan.md         # 独立评测与验收方案
│   └── supabase.md                # 云端建库、同步、安全与恢复手册
├── eval/
│   ├── run_p0.py                  # P0 冻结运行、实验臂及性能编排
│   ├── offline_runner.py          # 隔离 worker 与网络拒绝自检
│   ├── run_record.py              # 本地诊断、陈述映射与工件记录
│   ├── metrics_v2.py              # 独立分级指标与 N/A 语义
│   └── run_compare.py             # A/B/C 比较与执行状态记录
├── scripts/
│   ├── prepare_corpus_candidate.py # 独立候选语料、来源台账与索引
│   ├── audit_corpus.py            # 语料审计与可失败的质量门禁
│   └── sync_supabase.py           # 云端来源 dry-run、原子推送与离线拉取
├── supabase/
│   ├── migrations/                # 表、索引、RLS、检索与发布 RPC
│   └── tests/                     # pgTAP 数据库集成测试
└── tests/                         # 核心行为单元测试
```

## 关键工程取舍

默认实现继续采用无模型下载的 BM25 + TF-IDF 余弦 + RRF 与确定性评分器，保证 CPU/离线环境可复现。阶段 2 已加入可选的版本化稠密索引、分语言查询融合、混合 RRF 和交叉编码器适配器；具体模型不写死，由固定开发集在质量、最差主题表现和延迟之间选择。新后端通过配置启用，并保留无损回退路径。

当前交付状态以 [P0 实施报告](docs/optimization_p0_implementation_report.md)为准，设计依据见
[P0 优化方案](docs/optimization_p0_plan.md)，独立评测要求见 [评测方案](docs/evaluation_plan.md)。
详细架构与替换点见 [架构说明](docs/architecture.md)，现场演示见 [演示流程](docs/demo_script.md)。
早期 [优化路线](docs/optimization_plan.md)、[阶段 2 开发计划](docs/next_phase_development_plan.md)及
[历史评估报告](docs/evaluation_report.md)保留用于追溯，不能替代最新 P0 验证结果。

## 开源许可与数据边界

源代码以 [MIT License](LICENSE) 发布。仓库不授予任何第三方论文、摘要或数据库内容的再分发权；使用者须自行确认其本地语料及外部 API 数据符合对应来源的许可和使用条款。

请勿提交 `.env`、API Key、可识别患者信息或无权公开的临床资料。`SUPABASE_SECRET_KEY`
只能在可信后端或本地同步环境中使用，不能放入浏览器、移动端包或公开日志。该工具仅供教学与研究，
不是医疗器械，也不替代专业医疗判断。
