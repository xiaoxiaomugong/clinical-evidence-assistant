# 本地真实问答网站

本地开发版本使用 React + TypeScript + Vite、FastAPI 和现有 `EvidencePipeline`。每次提交都会执行检索、证据门控、抽取式生成与引用校验；页面没有固定示例答案。示例按钮只填写题干。

## 安装与启动

建议 Python 3.11+、Node.js 22.12+。后端保留 Python 3.9 兼容性。首次安装依赖需要访问包仓库；安装完成后的问答、测试与构建不需要访问外部服务。

在项目根目录执行（已有 `.venv` 时跳过创建步骤）：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web,dev,pdf,ui]'
npm --prefix frontend ci
```

终端一，启动 API：

```sh
.venv/bin/python scripts/run_web.py
```

终端二，启动网页：

```sh
npm --prefix frontend run dev
```

打开 <http://127.0.0.1:5173>。API 监听 `127.0.0.1:8766`，Vite 将 `/api`、`/health` 转发到 API；使用同一浏览器来源，无需开放跨域。按 Ctrl+C 分别停止两个进程。

网页入口：`/` 首页、`/ask` 公众版、`/professional` 专业版、`/topics` 主题库，以及方法、隐私、使用说明页面。

### 配置示例

本阶段无需任何密钥，也无需创建或复制 `.env`。启动脚本清除继承的服务配置与凭据；Web factory 自身也显式构造离线配置，忽略现有 `.env`、检索后端、模型、云端和私有 PDF 配置。Vite 设置 `envDir: false`。

```sh
# 默认配置：本机地址，API 8766，网页 5173，离线抽取式回答
.venv/bin/python scripts/run_web.py --port 8766

# 仅检查语料、API 和真实回答，不启动监听
.venv/bin/python scripts/run_web.py --check
```

若修改 API 端口，同步修改 `frontend/vite.config.ts` 中两个代理目标。页面端口可用 `npm --prefix frontend run dev -- --port 5174` 修改。不要将本阶段服务绑定到公网地址。

固定服务策略：实时 API 关闭、Supabase 关闭、在线模型关闭、模型下载关闭；确定性检索与重排，仅使用 `data/knowledge_pages/*.json` 和 `data/raw/local_corpus.json`。本机 PDF 索引不进入此入口。原 Streamlit、Python Tool 和 MCP 独立启动时仍使用各自原有配置行为。

请将 Web 服务与旧入口分进程运行。在同一个 Python 进程中先导入 Web，配置模块会固定为离线默认值，后续创建的默认 Tool 也会沿用这些值；本阶段不支持在一个进程内混合离线网站与在线 Tool 配置。

`scripts/run_web.py` 另安装 Python 审计钩子，仅允许本机 socket/DNS。该约束只作用于当前 Python 进程，不是操作系统防火墙。网页没有第三方脚本或远程字体；点击文献原始链接会离开本地站点。

## 使用与结果含义

1. 公众版输入一般健康知识问题，例如“降压药应早上服用还是睡前服用？”。
2. 专业版可以填写 PICO 人群、干预、对照、结局。条件与题干合并后进入同一安全和证据链；这不是患者病例表。
3. 查看回答后点击正文编号，核对对应来源、标识与摘录。引用编号保留引擎分配值，可能不连续。
4. 切换入口保留当前草稿、PICO 与原回答标签；再次点击提交才发起新请求。刷新页面清除这些状态。

| 状态 | 含义 |
|---|---|
| `answered`，`degraded=false` | 正常完成本地抽取与引用检查；离线模式本身不算故障降级 |
| `answered`，`degraded=true` | 处理发生降级，仍有通过检查的回答；页面说明实际生成方式 |
| `refused` | 隐私或诊疗边界阻断，或者证据不足；没有对问题形成答案 |
| `error` | 技术处理失败；不能把故障解释为没有证据 |

两个入口的事实陈述完全沿用引擎校验结果。公众版没有再调用模型润色。现有知识页未记录独立临床评审时显示“未记录”，不把更新时间称作审核时间。语料版本日期来自 `corpus_version.json`，不是本次联网日期。

## 公开 API

完整机器可读结构：`GET /openapi.json`。未启用需要远程资源的 Swagger/Redoc 页面。

| 方法与路径 | 输入 / 输出 |
|---|---|
| `POST /api/v1/queries` | 同步提交，返回最终公开回答；不保存服务端问答历史 |
| `GET /api/v1/topics` | 实际知识页列表及语料版本 |
| `GET /api/v1/topics/{topic_id}` | 主题原有内容、适用范围、局限、来源及审核记录 |
| `GET /health/live` | 进程存活；仅返回状态 |
| `GET /health/ready` | 语料与流水线已就绪时 200，否则 503 |

请求示例：

```json
{
  "question": "降压药应早上服用还是睡前服用？",
  "audience": "professional",
  "pico": {
    "population": "成人高血压",
    "intervention": "晚间服药",
    "comparison": "早晨服药",
    "outcome": "心血管结局"
  }
}
```

`audience` 只接受 `public`、`professional`。问题最多 2,000 字符，PICO 各项最多 500 字符，最终组合输入最多 4,000 字符。额外字段、错误类型、空白问题被拒绝。请求体最多 64 KiB，包括分块传输。超长返回 413 或 422；其他输入错误返回 422；技术不可用返回 503。正常回答及证据拒答均返回 200。

回答的字段白名单：`request_id`、`audience`、`status`、`degraded`、`generation_method`、`message`、`answer`、`sources`、`corpus`、`online_search`。`answer` 包含说明、带编号的陈述、局限与用途提示；`sources` 包含对应编号、题名、年份、来源类型、研究类型、证据类型、发表状态、公开标识、安全链接和最多 800 字符的必要摘录。证据类型不等同于证据确定性评级。

不返回原题、查询计划、候选全文列表、检索分数、内部 trace、私有路径、供应商错误或凭据。响应禁止缓存；输入错误也不回显输入。页面按普通文本显示证据，不执行 HTML。启动命令关闭访问日志，异常仅转换为固定文案，不记录题干和堆栈。

共享流水线由进程内锁串行使用，锁覆盖调用与公开结果构造。当前部署只运行一个 API worker，不提供持久任务或查询任务接口。

## 离线验证

```sh
# 清理继承配置并限制当前进程网络，运行完整 Python 回归
.venv/bin/python scripts/test_offline.py -q

# 本地 API 端到端自检
.venv/bin/python scripts/run_web.py --check

# 前端：控制替身模拟边界/故障，真实链路另在浏览器验证
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

只有测试依赖安装步骤联网；故障和降级由测试替身产生，不接触真实供应商。普通核心环境未安装可选 Web 或 MCP 依赖时，相应测试会跳过。完整网站回归需安装 `.[web,dev,pdf,ui]`：完整 Python 测试集包含 PDF 模块与原 Streamlit 桌面入口测试，尽管 Web 运行本身不读取本机 PDF 索引或启动 Streamlit。

## 与初步设计的阶段差异

- 使用同步 HTTP 请求，暂不引入 Redis、队列、轮询、幂等任务存储或分布式 worker。
- 浏览器超时只停止等待，不代表服务器中断已开始的计算。当前离线流水线耗时短，但没有硬执行期限或面向公网的容量保障。
- 首页和主题页使用客户端路由；预渲染、SEO、TLS、防刷与部署监控留到发布阶段。
- 公众版仅调整信息层次，保持原有已校验陈述；未来通俗改写须重新进行引用和支持性校验。
- 不增加账号、收藏、支付、上传、反馈存储、在线模型或云资源。原型保留在 `docs/prototypes/public-website/`。

当前语料仅五个主题、十条精选快照。2026-09-30 首次验收发现的服药时间和饮食回答跨主题陈述，已通过问题覆盖筛选及生成后陈述过滤修复；同日发布基线复验中，这两题不再显示糖尿病治疗等无关陈述。修复没有改变至少三组独立来源的门控、引用校验与证据不足拒答。混合检索回归曾因 fake index 提供糖尿病候选而失败，现改用真实相关且来源独立的证据夹具，并核对稠密召回和交叉重排确实参与结果。

发布基线本地命令：`.venv/bin/python scripts/test_offline.py -q`（218 passed、2 skipped）、`.venv/bin/python scripts/run_web.py --check`、`npm --prefix frontend test`（11 passed）、`npm --prefix frontend run typecheck`、`npm --prefix frontend run build` 和 `git diff --check`，于 2026-09-30 至 2026-10-01 在 macOS / Python 3.9.6 / Node.js 26.5.0 环境通过。两项 MCP 用例因该 Python 环境未安装可选 MCP 而跳过，远端 Python 3.11 CI 任务要求执行真实 stdio 测试。浏览器已复验公众版、专业版 PICO、引用详情及证据不足拒答；完整响应式、故障注入和并发浏览器矩阵沿用首次验收记录，未在本轮重复。远端 CI 以最终提交 SHA 的 Actions 运行结果验收，本段写于提交前，不预先声称通过。

相关性规则仍需独立题集与临床评审；三来源门控可计入同领域背景资料，最终回答可能只引用一个直接研究家族。规则校验不能替代独立临床评审，也不能证明医学正确率或资料最新。下一阶段优先补语料质量、相关性评测与临床评审，再讨论经授权的通俗改写、在线来源状态与正式部署。

本轮实测结果、修复记录和限制见 [验收记录](local-website-qa.md)。
