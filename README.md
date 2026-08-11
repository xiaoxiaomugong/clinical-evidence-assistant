# 循证知问 · 临床证据助手

[![CI](https://github.com/xiaoxiaomugong/clinical-evidence-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaoxiaomugong/clinical-evidence-assistant/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个可离线演示、可接入实时医学检索与在线大模型的循证问答 MVP。项目实现了需求文档中的完整闭环：

```text
临床问题 → 中英文查询改写 → 本地知识页 / 文献快照 + 实时 API
         → 统一候选池 → 跨来源重排 → 前置拒答
         → JSON 结构化生成 → 编号 / 存在性 / 支持性校验 → 后置拒答
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

## 已实现的安全边界

- 引用编号只能来自重排后 Top-K 可引用列表；越界编号立即判失败。
- 知识页 PMID 带核对日期；运行脚本可再次向 NCBI 批量回查。
- 结论和引用逐段做支持性校验；不支持的段落会触发降级或后置拒答。
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

## 测试与评估

```bash
pytest -q
python3 scripts/smoke_test.py
python3 eval/run_eval.py --mode hybrid
```

固定测试集包含 15 题，覆盖事实型、指南型、争议型和 3 个应拒答问题。评估输出写入 `data/eval_results/`：

- 检索层：Recall@8、MRR、nDCG@8
- 生成层：引用准确率、关键点覆盖率、拒答正确率
- 明细：每题 Top-1、分数、延迟、结构化回答

`eval/baseline.py` 提供禁用检索的纯 LLM 基线调用，使用同一模型、温度和 JSON 风格；需要配置 `LLM_API_KEY`。

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
│   └── corpus_version.json
├── src/evidence_assistant/
│   ├── pipeline.py                # 端到端编排
│   ├── query_rewrite.py           # 领域识别与中英文扩展
│   ├── knowledge_base.py          # 知识页召回
│   ├── candidate_pool.py          # 合并、条目级去重
│   ├── rerank.py                  # 跨来源统一评分
│   ├── generate.py                # JSON LLM / 离线抽取式生成
│   ├── citation_check.py          # 三道引用校验
│   ├── refusal.py                 # 前置与后置拒答
│   └── retrievers/                # PubMed / Europe PMC / CT.gov / 本地 RRF
├── eval/                          # 15 题测试集与评估脚本
├── scripts/                       # 采集、PMID 核对、冒烟测试
└── tests/                         # 核心行为单元测试
```

## 关键工程取舍

规范建议的 bge-m3、Chroma 与 bge-reranker-v2-m3 对演示设备资源要求较高。本实现采用无模型下载的 BM25 + TF-IDF 余弦 + RRF，并在统一候选池上使用同一确定性评分器，保证 CPU/离线环境可复现。模块接口已隔离，后续可在不改 UI、校验和评估层的情况下替换为向量库和交叉编码器。

详细架构与替换点见 [docs/architecture.md](docs/architecture.md)，固定测试结果见 [docs/evaluation_report.md](docs/evaluation_report.md)，现场演示流程见 [docs/demo_script.md](docs/demo_script.md)。

## 开源许可与数据边界

源代码以 [MIT License](LICENSE) 发布。仓库不授予任何第三方论文、摘要或数据库内容的再分发权；使用者须自行确认其本地语料及外部 API 数据符合对应来源的许可和使用条款。

请勿提交 `.env`、API Key、可识别患者信息或无权公开的临床资料。该工具仅供教学与研究，不是医疗器械，也不替代专业医疗判断。
