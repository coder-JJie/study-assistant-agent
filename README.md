# 学习资料助理 Agent（Study Assistant Agent）

一个**单一用途**的 AI 智能体：总结本地 PDF、抓取网页提炼要点、查询课程表 CSV。
外部能力以 **MCP（Model Context Protocol）** 技能服务器形式暴露，大脑（LLM）通过
**function calling** 决定何时调用哪个技能——完全依赖外部工具和上下文，而不是模型记忆。

> 本项目是"软件开发实验"课程的 vibe coding 作业实现：
> **样板代码**（MCP 服务器搭建、Pydantic 参数模型、API 请求逻辑）按"氛围编程"
> 的思路由 AI 生成；**系统提示词（prompt.py）与编排循环（agent.py）**是手工
> 打磨的核心部分。

---

## 三个技术要求（Must-Haves）的落点

| 必须项 | 本项目的实现 | 如何验证 |
|---|---|---|
| ① 至少两个技能 | `summarize_pdf`（本地 PDF）、`fetch_webpage`（外部网页）、`query_csv`（本地表格）——共 **3 个** | `python tests/test_cases.py` 的 A/B/C 组 |
| ② 上下文集成（MCP / function calling） | `mcp_server.py` 是 MCP 技能服务器；`mcp_client.py` 用 **stdio 协议**连接，并把 MCP 工具 schema **桥接成 OpenAI 兼容 function calling** | B 组测试走真实 MCP 管道调用工具；`agent.py` 用 tools 数组喂给 LLM |
| ③ vibe coding（AI 写样板） | `mcp_server.py` / `mcp_client.py` / `app.py` / 依赖清单等是 AI 生成的样板；`prompt.py` + `agent.py` 的循环逻辑是核心手工部分 | 对照代码注释区分两部分即可 |

---

## 架构

```
用户输入（问题 / 文件路径 / URL）
        │
        ▼
┌─────────────────────────────────────────────────┐
│ agent.py —— 编排循环（自己写的核心）               │
│   messages = [system(user/assistant/tool)…]      │
│   tools    = mcp_client 桥接出的 function schema │
│   循环：LLM(messages, tools)                      │
│        → 有 tool_call? 执行工具回填 : 输出最终答案  │
└──────────────────────┬──────────────────────────┘
                       │ MCP stdio 协议
                       ▼
┌─────────────────────────────────────────────────┐
│ mcp_server.py —— MCP 技能服务器（AI 生成的样板）   │
│   summarize_pdf / fetch_webpage / query_csv      │
│   （参数为 Pydantic 模型，SDK 自动生成 JSON Schema）│
└─────────────────────────────────────────────────┘
```

## 目录结构

```
study-assistant-agent/
├── mcp_server.py          # MCP 技能服务器（样板：AI 生成）
├── mcp_client.py          # MCP 客户端 + function calling schema 桥接（样板：AI 生成）
├── agent.py               # 编排循环 + CLI（核心：自己写）
├── prompt.py              # 系统提示词（核心：自己写）
├── app.py                 # Streamlit 演示界面（样板：AI 生成）
├── requirements.txt       # 依赖清单（样板：AI 生成）
├── .env.example           # 环境变量示例
├── data/
│   ├── sample_reading.pdf # 演示 PDF（tools/make_sample_data.py 生成）
│   └── courses.csv        # 演示课表
├── tools/
│   └── make_sample_data.py# 演示数据生成脚本
└── tests/
    └── test_cases.py      # 端到端自测（工具级/协议级/循环级）
```

---

## 快速开始

### 1. 环境准备（Windows / macOS / Linux 均可）

```bash
cd study-assistant-agent
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
python tools/make_sample_data.py     # 生成演示 PDF 和课表 CSV
```

### 2. 配置 LLM API Key（可选，不配也能跑）

项目根目录的 `.env` 已生成，直接打开把 `LLM_API_KEY=` 后面填上你的 Key
（任何 OpenAI 兼容接口都行，DeepSeek 示例）：

```ini
LLM_API_KEY=sk-xxxx
LLM_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

> **改 Key 不用重启**：streamlit 每次运行都会自动重读 `.env`（非空值覆盖），
> 填好保存后，在网页里点一次"运行"即生效。网页侧边栏里填的 Key 优先级最高。
> （`.env.example` 只是示例，不要直接编辑它。）

> **没有 Key 也可以全流程演示**：agent 会自动退回 `mock` 后端，用规则模拟
> 模型"决定调用哪个工具"，编排循环照样完整跑通。

### 3. 运行

```bash
# 交互式问答（Ctrl+D / q 退出）
python agent.py

# 单次问答
python agent.py --once "请总结 data/sample_reading.pdf"
python agent.py --once "data/courses.csv 里周一有哪些课？"
python agent.py --once "请抓取 https://example.com 并提炼要点"

# 强制 mock 后端演示
python agent.py --backend mock

# 网页演示界面
streamlit run app.py

# 端到端自测（10 项）
python tests/test_cases.py
```

CLI 使用的示例问题（mock 后端会自动识别关键词并调用对应技能）：

- 含 `.pdf` / "pdf" → 调 `summarize_pdf`
- 含 `http` → 调 `fetch_webpage`
- 含 `csv` / "课表" / "课程表" / "成绩" → 调 `query_csv`

---

## 自测输出（一份通过的示例）

```
[A] 工具级                                  → 3/3 ✅（三个技能直接可用）
[B] 协议级（真实 MCP stdio 链路）            → 5/5 ✅（发现 3 工具、schema 桥接、
                                                   三个技能均经 MCP 协议调用成功）
[C] 循环级（mock 编排循环）                  → 2/2 ✅（模型决策→工具调用→结果回填→最终回答）
结果: 10/10 通过
```

---

## 常见问题

- **网页侧边栏填了 API Key，却仍提示"未检测到 LLM_API_KEY"**：早期版本在模块
  导入时把 Key 读死，现已改为每次调用动态读取；侧边栏填 Key 即时生效。
  另外请确认后端选择器是 `auto`/`openai` 而不是 `mock`（mock 是为了离线演示，
  即使有 Key 也会走 mock）。`.env` 必须放在项目根目录
  `study-assistant-agent/.env`（文件已生成，直接填）——填好后不用重启，
  每次运行自动重读。
- **控制台打印中文/emoji 乱码或报 `UnicodeEncodeError`**：Windows 默认 GBK，
  脚本已自动把 stdout/stderr 切换为 UTF-8；若仍异常，请在终端执行
  `chcp 65001`。
- **PDF 报"文字只有几个字符"**：那是扫描版/图片型 PDF，没有文字层，需 OCR，
  属正常提示（工具会如实说明）。
- **网页抓取失败**：多为网络、反爬或动态渲染页面；工具会返回错误原因。
- **模型不调用工具**：把 `prompt.py` 里的"工具使用铁律"再强调几遍，并把
  `temperature` 调低（agent.py 已设 0.2）。
- **要更多技能**：在 `mcp_server.py` 里照葫芦画瓢再注册一个工具即可，
  客户端与循环无需改动（工具列表是动态发现的）。
