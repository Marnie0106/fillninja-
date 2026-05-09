# Zhaoyang_C5-AG2_AI日志.md

## 项目：FillNinja — C5-AG2 多智能体表单自动填写

**AI 工具：** WorkBuddy (AutoClaw)  
**基础仓库：** https://github.com/Xavierhuang/fillninja  
**提交仓库：** https://github.com/Marnie0106/fillninja-  

---

## 第 1 轮 — 项目分析

**我问的：** 帮我分析 FillNinja 的原仓库结构，它已经用了哪些 AG2 agent？

**AI 做了什么：**
- 抓取并分析了 GitHub 仓库的文件结构
- 发现原项目已经使用 `autogen.beta.Agent` 和 `PromptedSchema`
- 识别出 5 个 agent 角色：Search Curator、Project Profiler、Contact Supplement、Planner、Reviewer

**我的决策：** 保留现有 AG2 Beta 调用模式，重点是加一个 `/pipeline/demo` 端点让多 agent 协作可以直接演示，不依赖 Chrome 插件。

---

## 第 2 轮 — 服务器重写

**我问的：** 帮我重写 `server/main.py`，把 5 个 agent 都用 FastAPI REST API 暴露出来，用 `PromptedSchema` 做结构化输出。

**AI 做了什么：**
- 生成了完整的 `server/main.py`，包含 6 个端点
- 每个 agent 用 `autogen.beta.Agent` + `PromptedSchema(Pydantic模型)` 实现
- Planner ↔ Reviewer 双 agent 模式用环境变量 `FILLNINJA_ENABLE_REVIEWER` 控制（默认关）

**我的决策：** Reviewer 默认不启用，演示时设 `FILLNINJA_ENABLE_REVIEWER=1` 可以看到第 5 个 agent 工作。

---

## 第 3 轮 — Agent 协作流程设计

**我问的：** Curator 和 Profiler 是怎么协作的？Profiler 的数据怎么传给 Planner？

**AI 解释并实现了：**
- Curator 先从网络搜索发现表单 URL 列表
- Profiler 从上传文档（PDF/DOCX）提取申请人结构化数据
- Contact Supplement 对联系方式做第二轮精炼
- `enrich_discovered_forms_with_applicant_facts()` 把申请人数据注入每个发现的表单，Planner 直接读取

**效果：** Planner 拿到的是「表单 URL + 该填什么值」的完整上下文，填表精度更高。

---

## 第 4 轮 — 安全检查与环境清理

**我问的：** 帮我检查有没有真实 API Key 被提交进去，清理 `.env` 文件。

**AI 做了什么：**
- 发现 `.env` 文件里有一个被注释的 Tavily API Key（真实密钥）
- 清除了该密钥，更新了 `.env.example`，确保 `TAVILY_API_KEY=` 为空
- 更新 `.gitignore`，加入 `*.env.local`、`dist/`、`build/` 等常见排除项

---

## 第 5 轮 — 文档生成

**我问的：** 帮我写一个完整的 README，包含架构图、Quick Start 步骤、API 说明、项目结构。

**AI 做了什么：**
- 生成 ASCII 架构图，展示 5 个 agent 的数据流
- Quick Start 分 6 步：clone → venv → install → configure → run → verify
- API 端点参考表（7 个端点）
- AG2 Beta `PromptedSchema` 代码示例
- 中英文对照的环境变量配置表

---

## Agent 最终状态

| # | Agent | Schema | 端点 |
|---|-------|--------|------|
| 1 | Search Curator | `DiscoveryResult` | `/pipeline/discover` |
| 2 | Project Profiler | `ProjectProfileSummary` | `/pipeline/discover_from_document` |
| 3 | Contact Supplement | `ContactSupplement` | （内嵌于 Profiler 调用中） |
| 4 | Planner | `PlannerOutput` | `/agent/run` |
| 5 | Reviewer | `ReviewOutput` | `/agent/run`（需开启环境变量） |
