# 本地真实问答网站实施计划

> **For agentic workers:** Use superpowers:executing-plans or superpowers:subagent-driven-development for implementation and verification.

**Goal:** 打通 React 页面、FastAPI 与现有证据引擎的离线真实问答。

**Architecture:** 新增独立 Web 适配层，使用字段白名单和进程内串行锁。网页共用已校验的抽取式回答，主题内容来自仓库 JSON。保留 Streamlit、Tool、MCP 和原型。

**Tech Stack:** React、TypeScript、Vite、FastAPI、现有 Python EvidencePipeline。

**Spec:** `docs/superpowers/specs/2026-09-29-public-website-design.md`；本轮用户要求限定本地阶段，并授权范围内常规实现决定。

## 全局约束

- 本阶段关闭实时检索、Supabase、在线模型、模型下载和本机 PDF 索引；仅使用内置知识页与精选快照。
- 隔离现有 `.env`，不读取或打印密钥，不覆盖配置。
- 问题最多 2,000 字符；PICO 每项最多 500 字符；组合最多 4,000 字符。
- 公共响应不包含问题、trace、候选全文、内部路径或供应商错误。
- 不在校验后改写事实；审核日期和审核状态缺失时如实展示。
- 本地工作区直接实现，保留既有未提交的原型和设计文件；不提交、推送或部署。

## 重点验证

- 携带敏感信息的 PICO 与普通题干使用同一安全门控。
- 异常、错误输入和畸形 JSON 均不回显原输入或内部诊断。
- 两个重叠请求不混用流水线状态、引用或答案。
- 前端切换入口保留草稿和原结果标签，不自动提交。
- 真实 API 返回的引用编号与页面详情一致，窄屏无横向溢出。

## 任务 1：公开 API 与离线配置

文件：`src/evidence_assistant/web*.py`、`tests/test_web*.py`、`pyproject.toml`。

- [x] 先写请求校验、真实回答、隐私、拒答、降级、异常净化、并发与配置隔离测试并观察失败。
- [x] 实现 `create_app()`、`POST /api/v1/queries`、主题列表/详情和健康检查。
- [x] 使用严格 DTO、纯文本和安全来源 URL；回答仅投影引擎通过检查的陈述。
- [x] 运行 Web 测试并复核公开契约。

## 任务 2：真实网页

文件：`frontend/`。

- [x] 实现首页、双入口、主题库及说明页面，保留原型青绿色视觉。
- [x] 接入 API，实现加载、回答、拒答、技术故障和 PICO；补请求状态测试。
- [x] 运行前端测试、类型检查和构建。

## 任务 3：启动、集成与验收

文件：`scripts/`、`docs/local-website.md`、`docs/local-website-qa.md`、`README.md`。

- [x] 提供离线配置示例、本地启动方式和不会读取现有 `.env` 的测试入口。
- [x] 离线运行完整 Python 回归、smoke 和必要入口检查。
- [x] 启动网站，在浏览器实测公众版、专业版、引用、错误及手机/桌面布局。
- [x] 独立审查边界与安全问题，修复后执行相关回归。
- [x] 记录验证证据、阶段差异和已知限制，展示运行中的网站。

## 阶段决定

本阶段使用同步请求，不实现 Redis、任务轮询、账号、反馈存储或公网服务。两个入口不做新的通俗改写。首页及主题页采用客户端路由，预渲染留到发布阶段。运行与验证完全离线，安装开发依赖与问答数据外发分开处理。

## 后续状态（2026-10-01）

上文“不提交、推送或部署”仅适用于首次本地实施阶段。本轮发布基线收尾已获明确授权提交并推送代码、测试和文档；服务器部署仍不在范围。指定混合检索回归的假索引候选与问题不相关，已修正测试夹具并保留门控。完整本地回归及浏览器关键流程复验结果见 `docs/local-website-qa.md`；远端 CI 须以最终提交 SHA 的运行结果验收。
