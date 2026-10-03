# 服务器运行手册

此手册提供本地基线和服务器核验步骤。用户已确认网站部署到服务器，但尚未提供地址、服务器访问、进程配置或线上运行记录。以下示例尚未在服务器执行，也不构成线上验收。

## 当前事实

2026-10-03 在本轮隔离工作树运行最终管理员诊断，结果为 `ready`，范围是 `local_resources_only`。原始输出为 `/private/tmp/cea-iteration1-final-runtime-20261003-v2.json`；本地交付副本为 [runtime.json](../data/eval_runs/iteration1-20261003-regression-v2/verification/runtime.json)。评测目录被 Git 忽略，不随公开克隆分发；新环境可用下述命令重新生成。

| 本地项目 | 实测结果 |
|---|---|
| HEAD | `2d8be49fa0e79fe737aeb5da77a19ff88c547eb8` |
| 工作树 | `modified`；含本轮未提交改动，HEAD 不能独自标识本轮构建 |
| Python | 3.9.6 |
| 核心/UI 依赖 | requests 2.32.5；python-dotenv 1.2.1；Streamlit 1.50.0 |
| 可选运行时 | PyMuPDF 1.26.5；NumPy 2.0.2；MCP、sentence-transformers 未安装 |
| 实际核心语料 | 5 个知识页、15 个 claim、10 条离线文献快照；结构有效 |
| 知识页 SHA-256 | `51d6be3497ecd91904a9eda34a311511cdc56fd108744fde84e65ddd1ce6a8ee` |
| 离线快照 SHA-256 | `b07fb4add3937beb96eeaff7931061d7ff7235856e8363bc5f19f4b844ee75d5` |
| 版本清单 SHA-256 | `85c1e13fc8ec2e0de8a20b1a94a81fc0bcd993d71ede95a7f005dbf6e70b7142`；与配置一致 |
| PDF / 稠密 / 神经重排 | PDF 缺失但可选；稠密检索与神经重排未启用 |
| 外部依赖 / 推理 | 未探测外部供应商；未加载模型；未执行模型推理 |

版本清单里写有历史 500 篇 PDF 的说明，不能代替当前文件计数。此环境没有该索引，不能将历史 C1 数据算入本轮验收。Python 3.9 可运行核心/UI；现有 MCP 额外依赖要求 Python 3.10+，MCP 推荐使用 3.11。本轮另用既有 Python 3.13.13 / MCP 2.0.0 环境完成 server 与 stdio 两项测试，其中一项验证真实子进程 stdio；这不等于已验证服务器运行时或 CI 的 Python 3.11 环境。

| 服务器项目 | 核验状态 |
|---|---|
| 网站地址、主机、操作系统、访问权限 | 未核验 |
| 部署 SHA、发布目录、构建校验和、Python/依赖 | 未核验 |
| 启动命令、运行用户、进程数、监听地址与端口 | 未核验 |
| 反向代理、TLS、WebSocket、健康检查 | 未核验 |
| 配置/缓存/日志/PDF/稠密索引持久目录及权限 | 未核验 |
| 重启方式、日志轮转与保留期、备份、版本回滚 | 未核验 |
| 线上吞吐、错误率、延迟、实际模型/供应商状态 | 未核验 |

## 管理员诊断

在目标运行环境、应用相同的运行用户及配置下运行，输出文件必须不存在，父目录必须已存在：

```bash
python scripts/runtime_diagnostics.py --output /secure/admin-reports/runtime-UNIQUE-ID.json
```

命令复用 `Settings` 的源码/安装包资源发现和显式环境覆盖，读取配置、核心文件与可选索引。它不调用 `ensure_directories`，不发送医学问题、不探测供应商、不加载/下载模型、不建索引，也不输出环境、凭据、模型名称、URL、文件路径或原始异常。大索引校验和仅由这个显式命令计算。报告只写新文件，已有文件或符号链接均拒绝覆盖。

| 状态 | 解释与退出码 |
|---|---|
| `ready` | 本地核心语料、必需核心/UI 依赖和配置可用；未启用资源缺失不算故障；退出 0 |
| `degraded` | 核心可用，但版本清单未对齐、已挂载 PDF 不可用、启用的稠密资源不可用或模型推理未核验；退出 0，必须查看 `reason_codes` |
| `not_ready` | 核心知识页/快照缺失、为空或结构无效；配置无效；必需核心/UI 包缺失；退出 1 |
| 输出失败 | 目标已存在、父目录缺失或权限不足；退出 2，不覆盖旧报告 |

`ready` 不能证明网络、供应商、浏览器或临床正确性。PDF 检查只覆盖结构、搜索字段、关系、计数及哈希。诊断使用不可写的 SQLite 连接；若发现 `-wal`，状态为 `unverified_wal`，需要管理员生成一致性备份后核验，避免忽略 WAL 的数据。模型目录存在只记为 `present_unverified`；即使稠密索引通过已有 `IndexRegistry` 校验，也不把模型推理标为成功。

## 启动、代理和 WebSocket

下面以 Linux、发布目录 `/srv/cea/current`、虚拟环境 `.venv`、服务名 `clinical-evidence-assistant` 为示例；实际值都仍未核验。安装和发布应使用已审阅的发布工件及固定依赖，保留前一版本。不要在请求路径安装依赖、下载模型或建立索引。

前台启动检查：

```bash
cd /srv/cea/current
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --server.enableCORS true --server.enableXsrfProtection true --browser.gatherUsageStats false
```

生产进程由既有 supervisor 管理。若采用 systemd，记录 `WorkingDirectory=/srv/cea/current`、同一虚拟环境的绝对 `ExecStart`、专用低权限运行用户、受限配置文件和 `Restart=on-failure`；日志送到 stderr/journal。确认配置文件可读取、缓存目录可写、发布代码与索引对运行用户只读，然后先检查 unit，再按授权重启。

Nginx 示例：`map` 放在 `http` 块，`location` 放在已配置 TLS 的站点 `server` 块：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
location / {
    proxy_pass http://127.0.0.1:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 120s;
    proxy_buffering off;
}
```

示例采用根路径；若实际挂载子路径，需核对 Streamlit `server.baseUrlPath` 与代理路由同时一致。保留 CORS/XSRF 保护，确认浏览器的 Origin、Host 和协议转发正确。代理 120 秒超时是示例运维参数，不是问答全链路截止承诺。

在浏览器开发者工具的 Network / WS 查看 `/_stcore/stream` 升级响应 `101`，提交一个公开且不含个人信息的演示问题，确认成功/拒答能显示、重新连接正常。单独的 HTTP 200 或页面 HTML 不能证明 WebSocket 工作。

## 健康、只读核验和日志

在服务器读取既有状态，不修改配置或语料：

```bash
git -C /srv/cea/current rev-parse HEAD
git --no-optional-locks -C /srv/cea/current status --short
systemctl status clinical-evidence-assistant --no-pager
curl --fail --max-time 5 http://127.0.0.1:8501/_stcore/health
curl --fail --max-time 5 https://YOUR-CONFIRMED-HOST/_stcore/health
journalctl -u clinical-evidence-assistant --since '30 minutes ago' --no-pager
```

进程状态、直连健康、代理健康、WebSocket 和实际问答分别记录结果。`/_stcore/health` 只说明 Streamlit 服务响应；核心语料通过管理员 JSON 报告另行检查。需要问答级离线检查时，可额外在受控环境执行 `clinical-evidence-ui --check` 或 `python scripts/smoke_test.py`；这些会执行内置公开问题并创建运行缓存，不能描述为只读诊断。

运营事件仅保留 request_id、时间、版本、mode、状态码、阶段耗时、实际后端、枚举回退原因和计数。不得记录问题、检索词、候选/回答正文、PHI、密钥或原始异常。不得把保存证据正文的评测 recorder 接到生产请求。MCP stdout 只用于协议，日志使用 stderr。

核对 Nginx、supervisor 和应用日志配置，避免记录 request body、完整 URL/query string、认证头或配置。访问日志可限定为时间、状态和耗时。对既有错误日志核对其字段是否包含输入；轮转和保留期必须在服务器库存中确认。若使用 journal，可由管理员按容量和保留期配置 `SystemMaxUse`、`MaxRetentionSec`；若使用文件，配置 logrotate 和受限读取权限。实际策略目前未核验。

当前请求保护为同一进程内共享 pipeline 的互斥：默认等待最多 5 秒、至多 8 个等待请求。它不能跨多个 worker/主机限流。LLM 单次调用默认超时 45 秒，API 重试每次等待默认上限 5 秒；排队、单次调用和重试等待分别统计。尚无问答全链路硬截止，也没有线上延迟或容量结论。

## 发布前本地回归

先在受控运行环境隔离 `.env`、实时源、云端及模型，使用唯一输出目录。以下目录名仅为新一次运行的示例；命令拒绝覆盖已有基线或结果：

```bash
export EVIDENCE_ASSISTANT_ENV_FILE=/dev/null
export ENABLE_LIVE_APIS=false ENABLE_SUPABASE=false
export LLM_API_KEY='' PUBMED_API_KEY='' NCBI_EMAIL=''
export SUPABASE_URL='' SUPABASE_PUBLISHABLE_KEY='' SUPABASE_SECRET_KEY=''
export MODEL_LOCAL_FILES_ONLY=true HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python -m pytest -q -rs
python scripts/smoke_test.py
python scripts/lint_knowledge_pages.py --strict
python scripts/freeze_current_baseline.py --output data/eval_runs/NEW-current-c0
python -m eval.run_p0 --baseline-source current --baseline data/eval_runs/NEW-current-c0 --output data/eval_runs/NEW-regression --profiles C0 --arms G1
```

运行器验证输入哈希，在隔离子进程运行冻结参考代码与候选代码；候选两次语义结果必须一致，并通过适用的旧题行为及工程质量回归门禁。当前来源只能运行 C0/G1，不能作为历史实验或 C1。若比较两个代码版本，先在改动前冻结参考，再对候选运行；刚冻结同一候选的比较主要检验可复现性与既有标签/门禁，不能替代跨版本对照。正式临床安全评审始终单列，缺少人评时为 N/A。

需要受控并发测量时，在回归命令增加 `--performance --shared-pipeline --trials 120`。分别报告服务锁等待、执行、线程池调度等待；按真实进程数解释共享锁成本。当前本地结果与实际执行/跳过项见 [第一轮交付报告](post_deployment_iteration1_report.md)。CI 已配置 Python 3.9/3.11 离线回归和 Python 3.11 必测 MCP，但本轮未执行远程 Actions。

## 备份、重启与版本回滚

每次授权发布前，保存当前代码/依赖锁定、管理员报告及语料哈希。保留当前和前一发布目录、各自虚拟环境和对应语料。配置与凭据只进入受限的既有密钥/备份设施，不进入公开发布包或诊断报告。缓存可重建；核心知识页、离线快照、PDF/稠密索引及其版本清单应单独保留。

SQLite 正在写入时使用一致性备份，不能只复制主数据库并丢弃 WAL。例如，在新建且受限的唯一备份目录内执行：

```bash
sqlite3 /srv/cea/data/pdf_collection.sqlite3 ".backup '/secure/backup/UNIQUE-ID/pdf_collection.sqlite3'"
```

对备份重新计算哈希并进行管理员诊断；稠密索引是不可变目录，保留 metadata、records 和 embeddings 的完整版本及校验和。禁止覆盖当前索引、历史冻结基线或评测结果。恢复演练使用独立临时目录，验证计数、哈希、离线问答后再考虑发布。

按授权重启的示例命令是 `systemctl restart clinical-evidence-assistant`。重启后检查上述直连、代理、WebSocket、日志与公开问题，并将新管理员报告与发布工件的 SHA/语料哈希对齐。缺少线上证据时保留“未核验”。

回滚需选择库存中已验证的前一发布版本及其配置/语料组合。以下是 Linux 原子切换已有 `current` 符号链接的示例，前一版本仍需管理员确认：

```bash
ln -s /srv/cea/releases/CONFIRMED-PREVIOUS-RELEASE /srv/cea/current.rollback
mv -Tf /srv/cea/current.rollback /srv/cea/current
systemctl restart clinical-evidence-assistant
```

切换后重新核对部署 SHA、依赖、语料哈希、健康与公开问题，记录触发原因和结果。若回滚仅涉及实验策略，可将候选池恢复为 `legacy`；常规基线保持 `source_preserving / legacy / legacy / deterministic`，Top-8、生成 Top-5、独立来源最少 3、阈值 0.18/0.5。所有回滚均保留 PHI 阻断、实际生成包引用校验、无支持陈述删除和后置拒答。

目前没有执行服务器重启、备份、代理修改、索引替换或版本回滚。
