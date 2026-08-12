# Supabase 云端证据库

本项目把 Supabase 作为公开临床证据的云端权威数据源，同时保留 JSON/SQLite
本地缓存作为离线兜底。云端不可用不会阻断现有问答流程。

## 数据模型

| 表 / RPC | 用途 | Data API 权限 |
|---|---|---|
| `source_catalog` | PubMed、Europe PMC、ClinicalTrials.gov、快照和 PDF 集合登记 | 仅后端 secret key |
| `evidence_documents` | 文献规范主键、摘要、来源标识、证据等级、更新时间和内容哈希 | 匿名/登录用户只读活动记录 |
| `evidence_chunks` | 摘要或有授权全文的可检索 chunk | 匿名/登录用户只读活动文档的 chunk |
| `ingestion_runs` | 每次同步的状态、数量、错误和审计元数据 | 仅后端 secret key |
| `evidence_*_staging` | 分批上传中的文献/chunk 暂存区 | 仅后端 secret key |
| `publish_evidence_ingestion` | 在一个数据库事务中替换指定来源并清理旧数据 | 仅后端 secret key |
| `search_evidence_chunks` | PostgreSQL FTS 云端检索，最多返回 100 条 | 匿名/登录用户可执行，受 RLS 约束 |

迁移文件位于 `supabase/migrations/`。所有 `public` 表都显式启用 RLS；
`anon` 和 `authenticated` 没有写权限。`SUPABASE_SECRET_KEY` 会绕过 RLS，
因此只能放在后端任务的密钥管理中。

## 创建或关联项目

使用仓库固定验证过的 CLI 版本：

```bash
npx --yes supabase@2.109.1 link --project-ref YOUR_PROJECT_REF
npx --yes supabase@2.109.1 db push --linked --dry-run
npx --yes supabase@2.109.1 db push --linked
```

也可以通过已连接的 Supabase 管理工具应用同一迁移。迁移后应运行 Security
Advisor 和 Performance Advisor，并分别用 publishable key 验证只读检索、用
secret key 验证同步写入。

本地安装 Docker Desktop 或 Podman 后，可用仓库内的 pgTAP 用例验证原子替换、
失败回滚和权限边界：

```bash
supabase start
supabase db reset --local --no-seed
supabase test db --local supabase/tests/atomic_evidence_publish_test.sql
supabase db lint --local --schema public --fail-on error
supabase db advisors --local --type all --fail-on error
```

## 应用配置

复制 `.env.example` 后填写：

```dotenv
ENABLE_SUPABASE=true
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
SUPABASE_TIMEOUT=15
```

- 应用请求路径只读取 `SUPABASE_PUBLISHABLE_KEY`。
- `scripts/sync_supabase.py push` 才读取 `SUPABASE_SECRET_KEY`。
- 不要把 secret key 放进浏览器、日志、Git、截图或公开部署配置。

## 数据同步

先验证要上传的数量，不发出网络请求：

```bash
python3 scripts/sync_supabase.py push --source snapshot --dry-run
```

上传内置文献快照；脚本先分批写入不可公开读取的暂存表，再由单次 RPC 原子替换
`pubmed_snapshot` 来源：

```bash
python3 scripts/sync_supabase.py push --source snapshot
```

PDF 集合默认只上传题录和摘要，不上传本地论文正文：

```bash
python3 scripts/sync_supabase.py push --source pdf
```

只有在确认拥有对应处理和分发权时，才显式上传 PDF 全文 chunk：

```bash
python3 scripts/sync_supabase.py push --source pdf --include-pdf-full-text
```

每次成功发布都会删除该来源中本次快照未包含的旧 chunk，并把本次快照未包含的旧文献
标记为 `is_active=false`。因此从全文模式切回默认 PDF 同步会原子删除旧全文 chunk；
任一暂存批次或发布步骤失败时，当前公开版本保持不变。

下载云端活动文档，生成可离线使用的 JSON 快照：

```bash
python3 scripts/sync_supabase.py pull
```

然后可设置 `LOCAL_CORPUS_PATH=data/raw/supabase_corpus.json`。直接云端检索失败时，
流水线会自动保留原有知识页、本地快照和 SQLite PDF 索引。

## 数据边界

该数据库只用于公开或已有合法处理依据的证据资料，不存储用户问题、患者信息或
可识别健康数据。若未来要处理 PHI，需要单独完成 BAA、HIPAA 项目标记、MFA、
PITR、SSL 强制、网络限制、密钥轮换和完整访问审计，不能沿用当前公开只读策略。
