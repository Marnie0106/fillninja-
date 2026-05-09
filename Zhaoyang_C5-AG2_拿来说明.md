# Zhaoyang_C5-AG2_拿来说明.md

## Fork 来源

| 项目 | 链接 |
|------|------|
| **Base repo (直接 Fork)** | https://github.com/Xavierhuang/fillninja |
| **我的 Fork** | https://github.com/Marnie0106/fillninja- |

---

## 借鉴了什么

### 保留的部分（原 repo 已有）

| 文件 | 来源 | 说明 |
|------|------|------|
| `server/discovery.py` | 原 repo 改写 | Search Curator agent 的核心逻辑；保留了 DuckDuckGo + Tavily 双后端搜索架构 |
| `server/project_profile.py` | 原 repo 改写 | Project Profiler + Contact Supplement 的 Pydantic schema 设计 |
| `server/document_extract.py` | 原 repo 保留 | PDF / DOCX / PPTX 文本提取逻辑 |
| `server/web_fetch.py` | 原 repo 保留 | 异步 HTTP 抓取工具 |
| `server/smart_source_url.py` | 原 repo 保留 | URL 内容智能抓取 |
| AG2 Beta 调用模式 | 原 repo 参考 | `autogen.beta.Agent` + `PromptedSchema` 组合方式 |

### 新增 / 重写的部分

| 文件 | 说明 |
|------|------|
| `server/main.py` | 重写 — 把所有 5 个 agent 以干净的 FastAPI REST API 形式暴露出来 |
| `/pipeline/demo` 端点 | 新增 — 无需 Chrome 插件即可演示多智能体协作 |
| `README.md` | 全新 — 含架构图、Quick Start、API 表格 |
| `AI_LOG.md` | 新增 — 记录 5 轮 AI 迭代过程 |
| `ATTRIBUTION.md` | 新增 — 完整列出 fork 来源和依赖库 |
| `.env.example` | 更新 — 清除残留密钥，添加详细注释 |

---

## 参考的同学仓库格式

| 同学仓库 | 参考内容 |
|----------|----------|
| https://github.com/dark-077/AG2-multiagent | README 结构、ATTRIBUTION 格式、提交文件命名规范 |
| https://github.com/Usernames686/RefereeOS | AI_LOG 迭代记录方式、多 agent 架构图写法 |

---

## 删除的内容

- 视频转录模块（`video_transcribe.py`）— 需要额外环境，与核心 multi-agent 演示无关  
- Daytona 沙盒依赖 — 简化为本地直接运行  
- `.env` 中注释的真实 Tavily API Key — 安全清理  
