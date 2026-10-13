# Paper Research Agent

基于 MCP 的科研论文阅读与推荐助手，面向大学课程作业。支持从论文检索、原文阅读、结构化分析到相关推荐、收藏和历史回顾的完整工作流。

项目使用两个独立 MCP 工具获取真实论文数据，通过 LLM Function Calling 实现自主工具调用，并使用 Codex 辅助编写代码与测试。

## 主要功能

- **论文检索**：通过真实 arXiv API 查询论文，支持相关性、提交时间和日期筛选。
- **论文阅读**：上传本地 PDF 或加载在线 arXiv PDF，按页预览原文。
- **结构化分析**：生成研究问题、背景、方法、贡献、实验、结果、局限和关键词，保留原文证据与页码。
- **长论文处理**：分块分析与分层汇总，明确报告缺页、预算不足等限制。
- **相关研究推荐**：从源论文提取主题，检索并排序真实候选，最多推荐 5 篇。
- **文献管理**：收藏、阅读状态、历史搜索、报告重开和 Markdown 导出，数据保存在 SQLite。
- **交互工作台**：浅色界面、中英语言切换、双栏阅读、内部滚动及收起后的图标导航。

## 技术与架构

| 用途 | 技术 |
| --- | --- |
| 运行环境 | Python 3.11 |
| 工具通信 | 官方 MCP Python SDK / FastMCP，stdio |
| 模型调用 | OpenAI Python SDK，Function Calling / JSON mode |
| 论文检索与解析 | arxiv、PyMuPDF |
| Web 界面 | Streamlit |
| 数据校验与存储 | Pydantic、SQLite、SQLAlchemy 2.0 |
| 配置与测试 | python-dotenv、pytest |

MCP Server 提供两个外部工具：`search_arxiv` 检索论文，`read_pdf` 提取真实 PDF 文本。客户端动态发现工具定义，无需重复维护参数 Schema。

CLI 由 LLM 自主选择工具并完成多轮调用；Web 根据用户点击的明确操作调用已有业务服务。两者复用 MCP Client、分析模块与资源控制，Web 另外接入历史和缓存。

```text
Web 按钮 → 历史/缓存 → WebBackend → MCP Client / ResearchService
CLI 请求 → Function Calling Agent → MCP Client / ResearchService
ResearchService → 分块分析、主题提取、推荐排序 → 模型 API
MCP Client ← stdio → MCP Server → search_arxiv / read_pdf
```

## 项目结构

```text
.
├── app.py                         # Streamlit 启动入口
├── src/paper_research_agent/
│   ├── config.py                  # 环境配置与校验
│   ├── agent/                     # CLI、Agent 循环、MCP Client、预算
│   ├── mcp_server/                # Server 与两个外部工具
│   ├── analysis/                  # 数据模型、分块、证据、分析与推荐
│   ├── database/                  # SQLite、历史、缓存和文献库
│   └── ui/                        # 页面、会话状态、预览与展示
├── tests/                         # 单元、MCP 协议及 UI 测试
├── uploads/                       # 会话 PDF，不提交 Git
├── data/                          # SQLite 数据库，不提交 Git
├── .streamlit/config.toml         # 服务地址与基础主题
├── .env.example                   # 环境变量样例
├── requirements.txt               # 依赖
└── pyproject.toml                 # 包安装与 pytest 配置
```

建议从 `ui/app.py`、`ui/backend.py`、`analysis/service.py` 和 `agent/mcp_client.py` 阅读主流程；自主工具调用见 `agent/loop.py`，数据库操作见 `database/repository.py`。

## 安装与配置

以下命令适用于本项目现有的 Windows Conda 环境。其他机器请将解释器路径替换为自己的 Python 3.11 路径。

**1. 获取项目**（已有工作区可跳过）：

```powershell
git clone https://github.com/Shenjiayi-0823/Paper.git
Set-Location Paper
```

**2. 安装依赖和项目包**：

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pip install --no-user -r requirements.txt
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pip install --no-user --no-deps -e .
```

项目使用 `src/` 布局，需要可编辑安装，以便 CLI 和 MCP 子进程导入代码。当前工作区使用已有 Conda 环境，不需要创建 `.venv`。

**3. 创建配置文件**（保留已有 `.env`）：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

在 `.env` 中填写模型配置：

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TOKEN_PARAMETER=max_completion_tokens
```

使用第三方 OpenAI 兼容平台时，替换为该平台的密钥、模型和 HTTPS API 基础地址；旧式网关可设置 `OPENAI_TOKEN_PARAMETER=max_tokens`。平台需要支持工具调用和 `response_format={"type":"json_object"}`，仅支持普通聊天的接口无法完成全部功能。

检索不需要模型密钥，分析和推荐需要。模型请求会把论文内容发送到配置的平台，并可能产生费用。不要提交 `.env`、数据库或上传论文。

| 常用配置 | 默认值 |
| --- | --- |
| `DATABASE_PATH` | `data/paper_agent.db` |
| `SEARCH_CACHE_SECONDS` | `3600` |
| `PDF_MAX_BYTES` / `PDF_MAX_PAGES` | 20 MiB / 50 页 |
| `REQUEST_TIMEOUT_SECONDS` | 60 秒 |
| `AGENT_TASK_TIMEOUT_SECONDS` | 300 秒 |

配置优先级为进程环境变量 > 项目 `.env` > 默认值。更多参数见 `.env.example` 和 `config.py`；修改配置后重启服务。

## 使用方法

### Web 工作台

在项目根目录运行：

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m streamlit run app.py
```

打开终端显示的地址，默认是 `http://127.0.0.1:8501`。保持终端运行，不能用 `python app.py` 代替此命令。

| 页面 | 功能 |
| --- | --- |
| Dashboard / 研究概览 | 阅读进度、当前论文和最近任务 |
| Discover / 文献发现 | 输入英文关键词或 arXiv 表达式，检索并收藏论文 |
| Paper Reader / 论文阅读 | 上传或加载 PDF、结构化分析、证据页码定位 |
| Related Research / 相关研究 | 复用当前论文，查找相关文献 |
| Library / 我的文献库 | 收藏、待读/阅读中/已读、查看已有分析 |
| History / 研究历史 | 搜索、筛选、打开结果、重新运行和删除 |
| Settings / 设置与诊断 | 模型信息、缓存选项、MCP 检测和工具日志 |

推荐演示流程：**检索论文 → 阅读原文 → 结构化分析 → 核对证据 → 推荐相关研究 → 收藏 → 从历史重新打开报告**。在线原文需点击“加载 PDF 原文”；阅读与推荐共享当前论文，不必在不同页面重复上传。

昂贵操作由按钮触发。切换页面、收藏或查看历史不会自动调用模型。缓存命中会明确显示；需要重新计算时，在 Settings 选择忽略缓存或点击历史详情的重新运行按钮。

### CLI 与 MCP

CLI 展示自然语言请求下的自主工具调用：

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m paper_research_agent.agent.cli --request 'Search for recent papers about reinforcement learning.'
```

本地论文放入 `uploads/` 后，可请求“请结构化分析本地 paper.pdf”。添加 `--json` 输出完整报告及轨迹，`--quiet` 关闭进度提示。CLI 自动启动 MCP Server；CLI 任务目前不自动写入 Web 历史。

也可单独启动 Server：

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m paper_research_agent.mcp_server.server
```

Server 使用 stdio，启动后等待客户端消息，普通日志写入 stderr。协议调用示例见 `tests/test_mcp.py`。

## 测试

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest -q -p no:cacheprovider
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pip check
```

默认测试使用 Mock LLM 和临时数据库，覆盖参数校验、PDF 安全、MCP 工具发现与调用、多轮 Agent、结构化输出、预算、历史、缓存及 UI 交互，不产生模型费用。真实网络和收费测试默认跳过，需通过测试文件中的 `RUN_LIVE_*` 开关显式启用。

离线测试通过不等于真实平台接口或分析质量已验证；真实演示需要可用模型、网络和人工核对。

## 使用范围与常见问题

- 当前为本地单用户模式，历史和收藏由本机会话共享；`session_id` 不提供身份认证。
- 数据库首次使用时自动创建。历史报告长期保留，但上传/预览 PDF 属于会话文件；重启后预览或重新分析本地论文需重新上传相同 PDF。
- 只复用完整成功且结构有效的缓存；模型、平台或提示词变化后重新执行。部分结果、失败和超时会如实标记。
- 不实现 OCR、原文区域自动高亮或复杂图表识别。推荐依据候选标题与摘要；证据存在性校验不能替代对结论的人工审查。

| 问题 | 处理方法 |
| --- | --- |
| 缺少密钥或模型不可用 | 检查 `.env`、平台地址、模型权限及接口兼容性 |
| arXiv 返回 HTTP 429 | 属于限流，等待后重试，不代表没有匹配论文 |
| `invalid_structured_output` | 模型 JSON 不符合结构，查看字段提示；不等同于 PDF 读取失败 |
| 浏览器拒绝连接 | 确认 Streamlit 正在运行，并访问终端显示的端口 |
| 安装出现 WinError 5 | 在有权限写入该 Conda 环境的管理员 PowerShell 中安装 |

若 Windows 策略拦截 SQLAlchemy DLL，可在管理员 PowerShell 安装纯 Python 版本：

```powershell
$env:DISABLE_SQLALCHEMY_CEXT='1'
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pip install --no-user --force-reinstall --no-binary=SQLAlchemy --no-cache-dir 'SQLAlchemy>=2.0,<2.1'
Remove-Item Env:DISABLE_SQLALCHEMY_CEXT
```
