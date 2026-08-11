# 循证知问 · 临床证据助手

[![CI](https://github.com/xiaoxiaomugong/clinical-evidence-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaoxiaomugong/clinical-evidence-assistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个可离线演示、可接入实时医学检索与在线大模型的循证问答 MVP。项目实现了需求文档中的完整闭环：

```text
临床问题 → PHI / 诊疗边界预检 → 中英文查询计划 → 本地知识页 / 文献快照 + 实时 API
         → 跨来源去重 → 统一重排 → 互补证据包 → 证据门控
         → JSON 原子陈述生成 → 编号 / 存在性 / 支持性 / 数字一致性校验
         → 删除无支持陈述与无效引用 → 后置拒答
         → 带证据等级和原始链接的回答
```

项目默认采用“离线优先”：不配置任何密钥也可以运行 UI、完成带引用问答、触发拒答并跑完整测试集。配置实时 API 或 LLM 后会自动增强，失败时降级到本地可信语料。

> 仅供教学与研究，不构成诊断或治疗建议。请勿输入可识别患者隐私信息。

## 立即运行

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

- 引用编号只能来自重排后 Top-K 可引用列表；越界编号立即判失败。
- 知识页 PMID 带核对日期；运行脚本可再次向 NCBI 批量回查。
- 回答按原子陈述生成；数字必须出现在证据正文或元数据中。
- 不支持的陈述和不可用引用会在进入 UI 前被物理移除；净化后无核心陈述则拒答。
- 按 PMID/DOI/NCT 统计独立来源；来源不足、缺预期证据类型或冲突未解释时拒答。
- 疑似 PHI 与个体化剂量、停药、换药问题会在检索和外部调用前阻断。
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

固定测试集包含 15 题，覆盖事实型、指南型、争议型和 3 个应拒答问题。评估输出写入 `data/eval_results/`：

- 检索层：Recall@8、MRR、nDCG@8
- 生成层：引用准确率、受支持陈述率、关键点覆盖率、拒答正确率
- 明细：每题 Top-1、分数、延迟、结构化回答

`eval/run_compare.py` 用锁定配置保存 Arm A 纯 LLM、Arm B 正常 RAG 与 Arm C 劣化 RAG 的全部原始工件。三臂使用同一安全规则、温度和原子陈述 JSON schema；Arm A 需要配置 `LLM_API_KEY`，未配置时会显式记为 skipped，不伪造基线结果。

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
│   ├── query_rewrite.py           # 领域识别与中英文扩展
│   ├── knowledge_base.py          # 知识页召回
│   ├── interfaces.py              # 检索/重排后端协议与状态
│   ├── index_registry.py          # 版本化、不可变稠密索引
│   ├── candidate_pool.py          # 合并、条目级去重
│   ├── rerank.py                  # 跨来源统一评分与互补证据打包
│   ├── rerankers/                 # 确定性/交叉编码器后端
│   ├── generate.py                # JSON LLM / 离线抽取式生成
│   ├── citation_check.py          # 映射/存在/支持/数字校验与输出净化
│   ├── refusal.py                 # 安全、证据与后置解释性拒答
│   └── retrievers/                # 实时源、词法、稠密与混合 RRF
├── eval/                          # 固定题集、回归评估与 A/B/C 比较
├── scripts/                       # 采集、审计、知识页 lint、冒烟测试
└── tests/                         # 核心行为单元测试
```

## 关键工程取舍

默认实现继续采用无模型下载的 BM25 + TF-IDF 余弦 + RRF 与确定性评分器，保证 CPU/离线环境可复现。阶段 2 已加入可选的版本化稠密索引、分语言查询融合、混合 RRF 和交叉编码器适配器；具体模型不写死，由固定开发集在质量、最差主题表现和延迟之间选择。新后端通过配置启用，并保留无损回退路径。

详细架构与替换点见 [docs/architecture.md](docs/architecture.md)，本轮实施状态与后续路线见 [docs/optimization_plan.md](docs/optimization_plan.md)，下一阶段的执行顺序、接口、验收门禁与 PR 拆分见 [docs/next_phase_development_plan.md](docs/next_phase_development_plan.md)，固定测试结果见 [docs/evaluation_report.md](docs/evaluation_report.md)，现场演示流程见 [docs/demo_script.md](docs/demo_script.md)。

## 开源许可与数据边界

源代码以 [MIT License](LICENSE) 发布。仓库不授予任何第三方论文、摘要或数据库内容的再分发权；使用者须自行确认其本地语料及外部 API 数据符合对应来源的许可和使用条款。

请勿提交 `.env`、API Key、可识别患者信息或无权公开的临床资料。该工具仅供教学与研究，不是医疗器械，也不替代专业医疗判断。
