# Paper Research Agent

基于 MCP 的智能科研论文阅读与推荐助手，Python 3.11 课程项目。

## 当前进度

阶段 1–5 已完成：包含 MCP 检索与 PDF 解析、自主 Function Calling Agent、CLI、结构化分析、长论文汇总、相关推荐及 Streamlit Web 界面。尚未进入阶段 6 部署与最终演示验收。

## 项目结构

```text
.
├── src/paper_research_agent/
│   ├── config.py           # 环境变量读取、参数验证与密钥保护
│   ├── mcp_server/         # 阶段 2：search_arxiv 与 read_pdf
│   ├── agent/              # 阶段 3：MCP Client 与 LLM 工具调用循环
│   ├── analysis/           # 阶段 4：论文分析报告、主题提取与推荐
│   └── ui/                 # 阶段 5：Streamlit 前端
├── tests/                  # 配置、工具、MCP 协议与 Agent 测试
├── data/                   # 后续存放上传与下载的 PDF（不提交）
├── reports/                # 后续存放生成的报告（不提交）
├── requirements.txt        # 依赖及版本范围
├── pyproject.toml          # 包安装信息、Python 版本约束、pytest 配置
├── .env.example            # 配置样例，无真实密钥
└── .gitignore              # 排除密钥、虚拟环境、缓存与用户数据
```

`mcp_server/server.py` 负责 MCP 注册；`mcp_server/tools/arxiv_tool.py`、`pdf_tool.py` 为可复用实现，`models.py` 定义工具输出。`agent/` 包含 Client、Agent 循环、统一 LLM 预算、提示和 CLI；`analysis/` 包含结构化模型、分块、分析与推荐服务；`ui/` 包含 Web 页面、会话状态、后台任务、格式化与上传隔离；根目录 `app.py` 是 Streamlit 入口。`uploads/` 不提交到 Git。

## 使用现有 Python 3.11 环境并安装依赖

本项目统一使用已有 Conda 环境 `D:\anaconda3\envs\paper-agent\python.exe`（Python 3.11.16）。后续开发、安装和测试都使用该解释器，不创建项目内 `.venv`，不使用默认 Python 3.14。

在当前工作区的 PowerShell 中执行：

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' --version
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pip install --no-user -r requirements.txt
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pip install --no-user --no-deps -e .
```

项目采用 `src/` 布局，可编辑安装使普通 Python 命令和后续 MCP 子进程能直接导入项目包；修改源代码后无需重新安装。pytest 自身配置了 `pythonpath`，因此仅测试通过不能证明项目已安装。

`.vscode/settings.json` 已指定上述解释器并启用 pytest。若 VS Code 曾缓存另一解释器，执行 `Python: Select Interpreter` → `Enter interpreter path`，选择上述路径。`defaultInterpreterPath` 不会覆盖已有的解释器选择。无需激活环境或修改 PowerShell 执行策略。

依赖包括 MCP Python SDK（使用其 1.x 内置 FastMCP）、OpenAI SDK、arxiv、PyMuPDF、Streamlit、Pydantic、pytest 和 python-dotenv。当前使用版本范围，尚未生成经过 Python 3.11 集成验证的依赖锁文件。

## 配置

第三方 OpenAI 兼容平台可在 `.env` 中配置以下字段，保留现有 MCP 和多轮工具调用机制：

```dotenv
OPENAI_API_KEY=第三方平台提供的密钥
OPENAI_BASE_URL=https://你的平台域名/v1
OPENAI_MODEL=平台支持的模型名称
OPENAI_TOKEN_PARAMETER=max_tokens
```

地址必须以平台文档为准，路径不一定为 `/v1`。如果平台给的是完整 `https://域名/v1/chat/completions`，程序会移除末尾 `/chat/completions` 后交给 SDK，避免路径重复。密钥需与配置的平台匹配，程序不会自动切回官方平台。只填写 `GPT_URL` 或 `GPT_API_KEY` 不会生效，请使用上述字段。

`OPENAI_TOKEN_PARAMETER` 默认 `max_completion_tokens`；旧式网关可改为 `max_tokens`。平台还必须支持 `tools`、`tool_choice`、`tool_calls` 和 `role=tool` 消息；结构化分析需要 `response_format={"type":"json_object"}`。仅支持普通聊天的接口不能满足 Agent 课程要求。保留 HTTPS 证书验证，不使用 `verify=False`；证书问题应通过平台证书或可信 CA 配置解决。

SDK 接入会将预算内论文文本发送给配置的平台；是否支持上述功能及计费规则以平台文档和实测为准。本次仅通过 httpx MockTransport 验证自定义地址、Bearer 认证、工具参数和输出上限，没有调用真实第三方平台。

```powershell
Copy-Item .env.example .env
```

编辑 `.env` 的 `OPENAI_API_KEY`，填入自己的密钥；`OPENAI_MODEL` 应为账号可用且支持工具调用的模型。阶段 1 不调用 API，可以暂时留空密钥。不要在代码或报告中写入密钥，也不要提交 `.env`。

| 配置项 | 默认值 | 用途 |
| --- | --- | --- |
| OPENAI_API_KEY | 空 | 后续 LLM 调用凭据 |
| OPENAI_MODEL | gpt-4.1-mini | 后续使用的模型，可修改 |
| ARXIV_MAX_RESULTS | 5 | Agent 建议默认检索数量，1–20 |
| PDF_MAX_PAGES | 50 | 后续 PDF 页数上限，正整数 |
| REQUEST_TIMEOUT_SECONDS | 60 | 后续请求超时秒数，必须大于 0 |
| AGENT_MAX_TOOL_ROUNDS | 8 | 后续工具调用轮数上限，1–50 |
| DATA_DIR | data | PDF 数据目录，相对路径以项目根目录解析 |

配置优先级：进程环境变量 > 项目根目录 `.env` > 默认值。`load_settings()` 不修改进程环境、不创建目录、不启动服务。非法参数立即报错，密钥在配置对象表示和 JSON 中被遮蔽；后续真正调用模型时使用 `require_openai_api_key()` 检查密钥。

## 阶段 1 验证

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest -q
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pip check
& 'D:\anaconda3\envs\paper-agent\python.exe' -c "from paper_research_agent.config import load_settings; print(load_settings())"
```

测试无需密钥或网络，检查默认配置、环境变量覆盖、非法参数和密钥遮蔽。测试通过仅代表基础配置正常，不代表论文检索、PDF 解析或 LLM 已验证。真实 API 连通性将在后续阶段验证。

最新环境验证（2026-10-09）：使用指定 Conda Python **3.11.16** 完成全部依赖和项目可编辑安装；pytest **9 passed**，`pip check` 无冲突，源码编译、配置加载、全部直接依赖和 `mcp.server.fastmcp.FastMCP` 导入通过。可编辑安装元数据确认指向当前工作区。未调用外部 API。

已安装版本：MCP 1.30.0、OpenAI 2.54.0、arxiv 2.4.1、PyMuPDF 1.28.2、Streamlit 1.65.0、Pydantic 2.14.0、pytest 8.4.2、python-dotenv 1.2.4。

该 Conda 环境目录仅管理员可写，本次通过 Windows UAC 管理员权限完成安装，未修改目录权限或重建环境。以后安装依赖若出现 WinError 5，可在管理员 PowerShell 中执行上述安装命令。环境的 `Scripts` 未加入 PATH，因此继续使用完整解释器路径与 `-m` 执行命令即可。详细安装日志位于 `dependency-install.log`，已被 Git 忽略。

依赖参考：[MCP SDK 发布页](https://pypi.org/project/mcp/)、[OpenAI SDK 发布页](https://pypi.org/project/openai/)、[arxiv 发布页](https://pypi.org/project/arxiv/)。阶段 2 使用 MCP 1.x 的接口，依赖中通过 `<2` 排除主版本迁移。

## 后续阶段

1. 阶段 2：已实现两个独立 MCP 工具 `search_arxiv` 和 `read_pdf`，支持在线 arXiv PDF 与本地 PDF，并提供工具及 stdio 协议测试。
2. 阶段 3：已实现 MCP Client 和基于 LLM Function Calling 的多轮工具调用循环及 CLI。
3. 阶段 4：已实现基于 PDF 的结构化分析、长论文分块汇总、主题提取与相关论文推荐；真实 LLM 行为尚待配置密钥后验证。
4. 阶段 5：实现 Streamlit 上传、检索和报告展示页面。
5. 阶段 6：完成集成测试、使用文档和课程演示。

## 阶段 2：MCP 工具使用

启动命令（不需要 OpenAI API Key）：

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m paper_research_agent.mcp_server.server
```

这是 stdio Server，启动后等待 MCP 客户端通过 stdin 发送 JSON-RPC；终端没有页面或普通输出是正常现象。工具日志写入 stderr。客户端启动子进程时应指定上述解释器，参数为 `['-m', 'paper_research_agent.mcp_server.server']`。实现依据 [MCP Python SDK 1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)。

### search_arxiv

参数：`query: str`（去除首尾空格后 1–1000 字符）、`max_results: int = 5`（1–20）、`sort_by: str = 'submittedDate'`（或 `relevance`）。工具显式默认值为 5；`ARXIV_MAX_RESULTS` 是留给阶段 3 使用的默认配置。英文关键词或 arXiv 表达式均可，例如 `cat:cs.CL AND all:attention`。

返回：`{success, query, papers, warnings, error}`。`papers` 每项包含 `arxiv_id, title, authors, abstract, published, updated, pdf_url, entry_url`；日期为 ISO 8601 字符串。空结果返回 `success=true`、空列表和提示，不伪造数据。失败返回空列表及 `{code, message}` 错误对象；成功时 `error=null`。

使用 arxiv SDK 的 3 秒请求间隔、最多 2 次重试和配置的请求超时；共享客户端与锁保持跨调用间隔。SDK 2.x 无公开 timeout 参数，因此使用带超时的 requests Session 替换其 `_session`，对应兼容性测试已覆盖超时转换。参考 [arxiv 官方库文档](https://lukasschwab.me/arxiv.py/)。

### read_pdf

参数：`source_type: str`（`local` 或 `arxiv`）、`file_path: str | None = None`、`arxiv_id: str | None = None`。

- 本地：将论文放入项目 `uploads/`，调用 `{"source_type":"local","file_path":"paper.pdf"}`。相对路径以 `uploads/` 为根；目录内绝对路径也允许。拒绝 `..`、目录外路径、目录外符号链接、非 `.pdf` 文件。
- 在线：调用 `{"source_type":"arxiv","arxiv_id":"1706.03762"}`。接受新版、旧版和带版本号 ID，拒绝 URL。仅构造官方 HTTPS PDF 地址，逐跳验证重定向，不接受任意主机、用户凭据或非标准端口。最多 5 次跳转、2 次网络重试，不继承环境代理和 netrc 凭据。
- 两种模式的参数不能混用。ID 语法合法不保证论文存在，HTTP 404 会报告下载失败。

统一返回：`{success, source_type, document_id, total_pages, pages, full_text, warnings, error}`。`pages` 为 `[{page_number: 1, text: '...'}]`，页码从 1 开始；`full_text` 按页顺序用双换行连接。成功时 `error=null`，失败时为 `{code, message}`。

限制配置：`PDF_MAX_BYTES=20971520`（20 MiB）、`PDF_MAX_PAGES=50`、`PDF_MAX_TEXT_CHARS=500000`。大小限制同时检查响应头和流式读取实际字节数；超过任何限制均失败，不返回截断的成功报告。下载在内存中解析，不保存缓存文件。`REQUEST_TIMEOUT_SECONDS` 为每个网络请求的连接/读取超时，不是整个工具调用的总时限。

损坏、需结构修复或密码保护 PDF 会报告错误。全无文本的扫描 PDF 返回 `no_text`；部分页无文本时保留可提取内容并明确标记缺页和不完整。没有 OCR，也不保证恢复公式、图表或多栏排版的阅读顺序。

常见错误码：`invalid_input`、`api_error`、`invalid_arxiv_id`、`file_not_found`、`path_not_allowed`、`not_pdf`、`corrupt_pdf`、`encrypted_pdf`、`download_failed`、`unsafe_redirect`、`size_limit`、`page_limit`、`text_limit`、`no_text`、`file_error`、`internal_error`。业务错误在稳定结果中的 `error` 返回；MCP 层参数结构错误由 SDK 返回 `isError=true`，Server 继续服务。

### MCP Client 与测试

```powershell
# 全部离线测试：无真实网络调用
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest -q -p no:cacheprovider
# 实际启动 stdio 子进程，验证 initialize/list_tools/call_tool 和异常恢复
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest tests/test_mcp.py -v -p no:cacheprovider
# 可选真实 arXiv 检索及 PDF 下载，需联网
$env:RUN_LIVE_ARXIV='1'
$env:RUN_LIVE_PDF='1'
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest tests/test_arxiv.py tests/test_pdf.py -m live -v -p no:cacheprovider
Remove-Item Env:RUN_LIVE_ARXIV
Remove-Item Env:RUN_LIVE_PDF
```

`tests/test_mcp.py` 是可运行的官方 SDK Client 示例：使用 `stdio_client` 与 `ClientSession`，先 `initialize()`，再 `list_tools()` 和 `call_tool()`，检查 `structuredContent`。生产 Server 的协议测试不访问网络；测试子进程 `mcp_fixture_server.py` 复用相同 Server 注册，只替换 arXiv 后端为 Mock，PDF 则使用临时目录的真实生成文件。该测试入口不用于生产。

阶段 2 实际验收（2026-10-09，Python 3.11.16）：离线 **51 passed, 2 skipped**；单独授权联网运行真实冒烟测试 **2 passed**，分别验证 `id:1706.03762` 的检索结果和官方 PDF 下载、文本解析。`pip check` 无冲突，源码编译通过。沙箱内网络请求曾因 WinError 10013 被拒绝，授权后的请求成功，因此此前失败属于网络权限限制。联网测试使用 `-p no:cacheprovider` 避免不同 Windows 执行身份间的缓存写入权限警告。

尚未验证：真实网络请求经生产 MCP 子进程完成的完整链路、全部 arXiv 学科/编号、所有复杂 PDF 排版及部署环境。正常结果的 MCP 检索测试使用 Mock；真实接口成功来自上述单独冒烟测试。现有 requests/urllib3 版本已满足新增直接依赖范围，无需再次安装。

## 阶段 3：自主 Agent 与 CLI

新增 `agent/mcp_client.py`、`agent/loop.py`、`agent/prompts.py`、`agent/cli.py`。Agent 不直接导入阶段 2 工具函数。实现使用已安装的 OpenAI 与 MCP SDK；新增声明直接使用的 `jsonschema` 依赖，当前环境版本已满足要求。

### 运行

在已有 `.env` 中填写 `OPENAI_API_KEY`，将 `OPENAI_MODEL` 设置为账号可用且支持 Chat Completions Function Calling 的模型。不要覆盖已有 `.env` 或在命令行输入密钥。真实运行会消耗 OpenAI API 额度，并把用户请求及预算内的论文内容发送到 OpenAI。

```powershell
# 交互模式，每条请求是独立任务；输入 exit 退出
& 'D:\anaconda3\envs\paper-agent\python.exe' -m paper_research_agent.agent.cli
# 单次请求
& 'D:\anaconda3\envs\paper-agent\python.exe' -m paper_research_agent.agent.cli --request 'Search for recent papers about reinforcement learning.'
```

也可输入 `Find papers about data center energy management.`。读取在线论文时提供实际 arXiv ID；读取本地论文前将文件放入 `uploads/`，例如输入“读取本地 paper.pdf，告诉我它的研究主题”。CLI 没有硬编码论文编号，没有预设搜索→阅读流程。无需手动启动 Server，Client 会用运行 CLI 的同一个解释器启动生产 Server 子进程。

### 调用机制

Client 使用官方 `stdio_client` 和 `ClientSession`，在异步上下文中初始化、分页 `list_tools()`，按 `name`、`description`、`inputSchema` 构造 OpenAI 的 `tools`。Schema 直接复制，保留可选参数、默认值和 nullable 类型，使用 `strict=false`，避免擅自将 MCP 可选参数改成 OpenAI 严格模式的必填参数。执行前按发现的 JSON Schema 校验参数，并拒绝额外字段和未声明工具。

Agent 使用 `AsyncOpenAI.chat.completions.create`，初始 `tool_choice='auto'`。模型决定直接回答或返回多个 `tool_calls`。Agent 保存原始 assistant 调用记录，逐个通过 MCP 执行，将工具结果作为带对应 `tool_call_id` 的 `role='tool'` 消息追加，再次请求模型。多个工具可以在同轮或不同轮请求；最终回答仍由模型生成。参考 [官方 OpenAI Function Calling 文档](https://developers.openai.com/api/docs/guides/function-calling)。

每次任务的 `AgentResult` 保留 `messages` 和不含完整 PDF 的 `tool_trace`，方便课程展示；CLI 默认只打印最终回答或经过脱敏的错误。交互模式各任务独立，不自动把上一任务带入下一任务。

Client 优先读取 `structuredContent`；旧式纯文本 JSON 会解析，普通文本保留在 `content` 字段。`isError` 和业务结果中的 `success=false/error` 都会传回模型。SDK 或连接异常不会向用户暴露原始错误字符串、请求头或 API Key。退出与取消均关闭 ClientSession 和 stdio 子进程；超时或断线的连接标为不可用，下一任务重建连接，业务错误则允许模型在预算内重试。

### 资源与证据限制

| 环境变量 | 默认值 | 限制 |
| --- | --- | --- |
| AGENT_MAX_TOOL_ROUNDS | 8 | 工具调用轮数；每轮允许多个调用 |
| AGENT_TOOL_TIMEOUT_SECONDS | 90 | 单次 MCP 请求超时，也用于初始化 |
| AGENT_TASK_TIMEOUT_SECONDS | 300 | 单任务总时限，包含连接和模型请求 |
| AGENT_MAX_RESULT_CHARS | 16000 | 单条发送给模型的工具结果字符上限 |
| AGENT_MAX_TASK_RESULT_CHARS | 64000 | 单任务发送给模型的工具结果累计字符上限 |
| AGENT_MAX_REPEATED_CALLS | 2 | 同名工具及规范化相同参数的执行次数 |
| AGENT_MAX_CALLS_PER_ROUND | 4 | 同轮调用数量，超出则拒绝该响应 |

达到工具轮数或结果预算后，最多再请求一次 `tool_choice='none'` 的最终回答；模型仍请求工具则终止报错。OpenAI SDK 自动重试关闭，避免总时限内隐式重复请求。重复调用以解析后的 JSON 参数统计，不受参数键顺序影响。

结果以有效 JSON 信封传给模型：`untrusted_tool_data=true`。超长内容变成带 `truncated=true`、`original_chars`、警告与 `excerpt` 的节选，保留 JSON 有效性，不冒充摘要或完整论文。累计预算为后续同轮结果预留空间，接近耗尽时停止新的工具轮次。这里限制的是字符数，不是精确 Token 数；上下文还包含提示、用户消息和调用参数。

系统提示要求真实检索必须调用搜索工具、阅读全文必须调用 PDF 工具，禁止从摘要假装已阅读全文，报告错误及截断，默认用用户语言回答；论文和工具文本仅为不可信数据，不是系统指令。提示不能保证模型永远遵守所有证据约束，实际回答仍应结合 `tool_trace` 和内容审阅。

### 测试与真实验证

```powershell
# 默认无网络费用，Mock LLM + 实际 MCP 子进程
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest -q -p no:cacheprovider
# 本阶段测试
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest tests/test_agent.py tests/test_agent_mcp.py -v -p no:cacheprovider
```

可选生产 MCP 真实网络测试（无 LLM 费用）：设置 `RUN_LIVE_MCP=1` 和 `LIVE_ARXIV_ID` 为实际合法编号，运行 `tests/test_agent_mcp.py::test_live_mcp_network`。

可选真实 LLM→MCP→arXiv→PDF 端到端测试（会产生 API 费用）：

```powershell
$env:RUN_LIVE_AGENT='1'
# 修改为明确要求搜索和阅读 PDF 的自然语言请求，不要使用占位编号
$env:LIVE_AGENT_REQUEST='Search arXiv for a paper about data center energy management, then read its PDF and summarize the main idea. Use one search result and report failures honestly.'
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest tests/test_agent_mcp.py::test_live_agent_end_to_end -v -p no:cacheprovider
Remove-Item Env:RUN_LIVE_AGENT
Remove-Item Env:LIVE_AGENT_REQUEST
```

付费测试不强迫工具选择，检查自主决策最终是否成功执行搜索和 PDF 阅读；模型选择不执行、账号不可用或网络失败都会使测试失败。默认测试中该测试被跳过，不能把 Mock 通过描述为真实 LLM 已验证。

阶段 3 实际验收（2026-10-09，指定 Python 3.11.16）：**78 passed, 4 skipped**，包括生产 MCP 工具发现、Mock LLM + 实际 stdio 工具调用、子进程异常退出及总任务超时。CLI `--help`、源码编译、`pip check` 和全部 requirements 版本范围检查通过。当前未配置 OpenAI API Key，因此未运行真实付费 LLM 或完整端到端测试；新增的生产 MCP 网络测试也未启用。阶段 2 的两个真实 arXiv 冒烟测试已通过，这是历史验证结果，不代表本阶段真实 LLM 通过。

## 阶段 4：结构化分析与相关推荐

长论文上下文修复（2026-10-11）：中间摘要使用 `SummarySelection`，每字段最多 3 条、每条最多 180 字符和 2 个引用 ID；每轮仅携带摘要及引用 ID/页码，不反复携带全部原文证据。原始块笔记和引文完整保存，详细结论只在最终 artifact 补回，按内容和来源标签去重，不能因共用引用 ID 丢弃不同结论。报告新增精简 `summary`，推荐主题提取使用它而不是完整详细列表。路由请求过大时只压缩工具消息副本，标记 `truncated=true`，保留全部调用 ID、完整原始记录和 artifacts。上下文/预算失败缓存，避免推荐操作重启同来源分析。最新离线 **157 passed, 5 skipped**，含长中文论文、调用 ID 保留与失败缓存测试；未增加预算或调用收费 API。换成本地 PDF 对应的 arXiv 源不解决汇总输入累积问题。

长论文超时修复：`ANALYSIS_OUTPUT_TOKENS=6000` 单独控制 JSON 分析/主题/排序请求的最大输出，普通 Agent 对话仍使用 `AGENT_OUTPUT_TOKENS`；两类请求都按实际配置预留预算。`finish_reason=length` 现在返回 `structured_output_limit`，异常工具请求与其他结束状态分别报告。此类失败在同一任务缓存，不让推荐操作重启整篇分析。后续 `task_timeout` 不覆盖已有研究错误，而是保存在 `secondary_error`。当前本地 `.env` 的总时限已改为 900 秒，40 次调用和 320000 Token 预算不变；单次请求超时不变。输出上限提高可能增加实际消耗，不保证平台支持该上限。仅运行离线测试，未重新调用收费模型。

CLI 默认实时显示 MCP、模型请求、分块分析与分层汇总进度，每 15 秒显示等待提示；进度在 stderr，最终 JSON 在 stdout。`--quiet` 可关闭进度，Ctrl+C 可取消。默认单次模型请求 60 秒、单任务总时限 300 秒；22 页长论文的多轮处理可能持续数分钟。旧版只在任务结束时显示结果，不能用静默输出判断是否卡死。进度只记录阶段和计数，不显示密钥、论文正文或用户提示。本次进度修复离线测试 **149 passed, 5 skipped**，未发起收费模型请求。

最新修复验收：**147 passed, 5 skipped**。标题在完整 PDF 内核对，不能核对的模型标题改为 `Not specified` 并记录警告，不编造标题、不阻断其他有证据的分析。分块提示用证据目录承载原文，spans 仅发送页码/位置/章节元数据；汇总笔记不再重复携带引文，目录保留原文。Token 预算在请求前仍保守预留；若平台返回有效的正整数 `usage.total_tokens`，请求后以该用量替换预留，否则保持估算。CLI 的 `usage` 显示调用次数、已计预算、使用平台计量的次数及估算次数，不是账单金额。后续预算错误不会覆盖已发生的研究错误，预算错误记录在 `secondary_error`。本次未调用收费模型、未提高预算上限。

新增模块：

- `analysis/models.py`：PaperAnalysis、Claim、Evidence、TopicPlan、RelatedPaper 等 Pydantic 模型。
- `analysis/chunking.py`：不重叠、可重组的原文分块，保留页码、字符起止位置和章节线索。
- `analysis/structured.py`：JSON mode 输出解析与 Pydantic 校验，不进行无限格式修复。
- `analysis/analyzer.py`：完整页数据读取、分块分析、两两分层汇总、证据校验与覆盖记录。
- `analysis/recommender.py`：主题提取、英文查询生成、真实候选过滤及 LLM 相关性排序。
- `analysis/service.py`：应用层操作、单任务分析缓存和内部 MCP 调用记录。
- `agent/budget.py`：路由、分块、汇总、主题和排序共享的 LLM 预算。

### 自主选择与 MCP 集成

阶段 3 的自主 Tool Calling Loop 保留。LLM 仍可直接选择 `search_arxiv` 或 `read_pdf`，另可选择注册的应用层操作 `analyze_paper` 或 `recommend_related`。两个应用操作由 `SourceRequest` 生成参数 Schema：`source_type`、对应的 `file_path` 或 `arxiv_id`，以及 `language`（默认中文）。它们不是新增 MCP Server 工具；MCP Server 仍只暴露原来的两个独立外部工具。

操作内部复用同一个已连接 MCP Client，绝不直接导入检索/PDF 工具函数。`analyze_paper` 通过 MCP 读取页数据再分析；`recommend_related` 先分析源论文，再提取主题、检索候选和排序。由模型自主选择何时执行这些业务操作；代码不通过关键词路由或固定入口替代模型决策。相同来源与语言在单次任务内复用已验证的分析结果。

### 结构化报告与证据

`PaperAnalysis` 包含 `title`、`research_problem`、`background`、`methodology`、`contributions`、`experiments`、`results`、`limitations`、`keywords` 和 `evidence`。标题保留论文原始语言，其他内容默认中文，保留必要的英文术语。

各结论字段是 Claim 列表，每项包含 `text`、`provenance`（`author_stated`、`inference` 或 `not_specified`）、`evidence_ids`。缺失结论使用 `Not specified`，不以猜测补齐。Evidence 包含 `id`、`page_number` 和原文 `quote`。代码检查引文是否实际出现在对应分块和页内，拒绝未知引用 ID；汇总不能修改原引文、页码或 ID，标题也必须存在于原文。

报告另含 `document_id`、`total_pages`、`analyzed_pages`、`missing_pages`、`complete`、`warnings`、`sections`、`chunk_count`、`chunk_analyses`。`complete` 表示所有页均有可提取内容且工具未报告警告，不保证模型的所有科学判断正确。引文存在性校验无法自动证明引文支持结论，也不能完全防止 LLM 误标作者陈述与推断；重要结论仍需人工核对。

### 长论文如何避免提前截断

分析服务收到的 MCP 页数据不会经过 `bounded_result()`。先按 UTF-8 字节预算分块，对每个可提取字符保留原文和页内偏移，无重叠、无主动省略；单页也可拆成多个连续片段。章节标记使用启发式标题识别，是辅助线索，不保证准确恢复所有 PDF 章节结构。

每块分别生成经过验证的分析；随后两两合并形成分层归约树。归约不能静默丢弃相应结论字段的输入引用，缺失引用的原始结论会补回；精确相同文本与来源标记的结论合并引用。原始块笔记和全部验证过的证据仍保存在最终报告，便于检查遗漏。语义相近而措辞不同的重复主要由 LLM 合并，不保证完全消除。

分块上限会同时考虑配置的文本块大小、上下文预算、Schema/提示和输出预留。预算不足、块数过多或单请求过长时明确失败，不截掉后半篇并声称成功。分析缺页会设置 `complete=false` 并列出页码，没有 OCR。阶段 2 的 PDF 大小/页数/文本硬限制仍有效，超过其限制的文档无法进入分析。

完整报告保存在 `AgentResult.artifacts`；向路由 LLM 回传的报告副本仍受阶段 3 长度限制，超长时带 `truncated=true`。这不会删除已保留的报告，但最后的自然语言回答可能只依据报告节选，因此完整报告请使用 CLI `--json` 查看。

### 推荐的真实性与范围

LLM 从已验证的源论文分析提取主题、方法和英文关键词。代码将最多 8 个英语短语构造成最多两条 `all:"..." OR ...` 查询，每条通过 MCP 检索最多 10 项。

候选按去版本号后的 arXiv ID 和规范化标题去重，排除原 arXiv ID 或原论文标题。若本地源论文既无可识别标题也无 ID，返回 `source_identity_unknown`，不冒险推荐原论文。

LLM 只返回候选 ID、相关性分数、推荐理由、研究联系和差异。未知或重复的选择会报错；排序后的最终标题、作者、摘要、PDF URL、entry URL 和 ID 全部回填自 MCP 候选，最多 5 篇。`evidence_basis='title_and_abstract'` 明确说明未阅读候选全文。候选方法只依据摘要描述；没有明确差异时应为 Not specified。搜索为空时返回空推荐和提示，不补造论文。LLM 的相关性理由仍需人工判断。

### 统一资源配置

在 `.env` 中可设置：

| 新配置项 | 默认值 | 用途 |
| --- | --- | --- |
| AGENT_MAX_LLM_CALLS | 40 | 单任务全部 LLM 调用总数 |
| AGENT_TOKEN_BUDGET | 320000 | 单任务保守 Token 预算 |
| AGENT_CONTEXT_BUDGET | 64000 | 单请求上下文与输出预留预算 |
| AGENT_OUTPUT_TOKENS | 3000 | 每次 LLM 请求的最大输出 Token 数 |
| ANALYSIS_CHUNK_BYTES | 12000 | 原文块 UTF-8 字节上限 |
| ANALYSIS_MAX_CHUNKS | 24 | 单篇最大原文块数 |

Token 预算使用请求 JSON 的 UTF-8 字节数，加协议余量与最大输出预留进行保守估算，并非精确模型 Token 计数或费用承诺。所有调用共享计数器，格式校验失败也占用已发出的调用预算。n 块需要约 `2n−1` 次分析与归约调用，另加 Agent 路由、最终回答、主题提取与候选排序；配置块数上限并不意味着调用预算必然足够。

第三方模型的 JSON 格式兼容处理：只去除一层外围 Markdown JSON 代码块，不把字符串自动转换成结论，也不补造证据。`ANALYSIS_FORMAT_RETRIES=1` 默认允许最多一次格式修复请求，可设为 0 关闭（最大 2）；额外请求仍计入统一调用、Token 和时间预算，真实运行可能增加平台费用。失败错误列出字段路径与 Pydantic 错误类型，不输出原文、模型原始错误内容或密钥。模型必须正确返回 Claim 对象数组及引用 ID，格式修复后仍执行证据校验。

同一任务内成功的 PDF 结果会缓存并复用；同来源/语言的结构化分析在修复后仍失败时，不再通过重复读取来解决 JSON 问题。`read_pdf success=true` 与 `invalid_structured_output` 分别表示读取成功和模型输出失败，不能据此称文件不存在。若应用层分析/推荐全部失败且没有生成任何报告，任务 `success=false` 并保留最初业务错误，即使模型已给出一段最终说明。

原来的总任务时限、单次 MCP 超时、轮数、重复调用限制仍生效；内部 MCP 请求也计数并记入 `tool_trace`。单次 LLM 超时为 `llm_timeout`，总任务超时为 `task_timeout`。不存在无限修复或自动无限重试。

### CLI 与测试

已有 `.env` 配置 API Key 后，在 VS Code 终端运行：

```powershell
# 把实际论文放进 uploads/paper.pdf
& 'D:\anaconda3\envs\paper-agent\python.exe' -m paper_research_agent.agent.cli --request '请结构化分析本地 paper.pdf，提供研究问题、方法、实验结果、局限与页码证据。' --json
& 'D:\anaconda3\envs\paper-agent\python.exe' -m paper_research_agent.agent.cli --request '根据本地 paper.pdf 的研究主题，检索并推荐最多 5 篇相关 arXiv 论文，解释联系与差异。' --json
# 全部离线测试，无付费请求
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest -q -p no:cacheprovider
# 本阶段新增测试
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest tests/test_analysis.py tests/test_research_agent.py -v -p no:cacheprovider
```

`--json` 输出最终回答、完整 artifacts、错误和工具记录，不输出内部 messages。CLI 自动管理 Server，直接读取在线论文时在自然语言请求中提供实际合法 ID。与此前一样，每条交互请求是独立任务。

可选真实收费端到端测试，仅在用户授权且已配置密钥后显式启用：

```powershell
$env:RUN_LIVE_RESEARCH='1'
$env:LIVE_RESEARCH_REQUEST='请结构化分析本地 paper.pdf，然后检索推荐相关 arXiv 论文，提供依据和差异。'
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest tests/test_research_agent.py::test_live_research_end_to_end -v -p no:cacheprovider
Remove-Item Env:RUN_LIVE_RESEARCH
Remove-Item Env:LIVE_RESEARCH_REQUEST
```

使用前应提供真实 `uploads/paper.pdf`，或将请求替换为实际 arXiv ID。该测试使用真实 LLM、生产 stdio MCP 和真实检索；若选择在线源，也包含真实 PDF 下载。默认不启用，不在缺少密钥或授权时运行。

阶段 4 实际验收（2026-10-09，指定 Python 3.11）：**109 passed, 5 skipped**；`pip check`、源码编译、CLI 帮助通过。本阶段新增 31 项离线测试，包括真实 MCP 子进程读取生成的本地 PDF，再由 Mock LLM 完成结构化分析。没有运行收费 API，也没有重新运行 arXiv 联网测试；真实模型的中文分析、长论文归约质量、主题提取及推荐效果尚未验证。阶段 2 的真实检索/PDF 冒烟测试为历史通过结果。

后续兼容性修复验证：**136 passed, 5 skipped**。包含第三方 SDK 地址与认证 Mock 测试、错误脱敏与 MCP 异常组、JSON 格式修复上限、PDF 缓存，以及研究失败时的任务状态。未执行收费模型请求；当前第三方模型的实际结构化输出兼容性仍需用户运行确认。

证据兼容性修复验证：**140 passed, 5 skipped**。引文提示明确要求短的连续原文（建议 30–150 字符，硬上限仍为 350），保留原语言、实际 PDF 页码、原标点和断词，不翻译或拼接远隔句子。分块 JSON 校验与原文证据校验共享 `ANALYSIS_FORMAT_RETRIES` 上限，不叠加无限纠正。错误只报告引用序号、页码和不匹配类型，不回显引文。修复后仍失败的分析在本任务内缓存原因，不通过推荐操作重新付费分析同一来源；最终失败说明依据真实工具记录生成，避免模型将证据错误误说成文件缺失。未发起真实模型请求，离线成功不代表第三方模型的引用输出已验证。

当前证据方案改为代码回填：新增 `analysis/evidence.py` 和不含 `evidence` 字段的 `AnalysisSelection` Schema。代码从 MCP 原文逐段生成不超过 180 字符的连续片段，每项携带 ID、原语言引文和真实页码。分块分析与分层汇总均让模型只选择 `evidence_ids`，不生成引文或页码；代码解析已知 ID 后回填 `AnalysisContent`，最终报告接口保持原样。未知 ID 仍拒绝，兼容旧式完整证据 JSON 时也必须通过原文严格匹配。这样可防止新模式的引文被模型翻译、改写或超长复制，但不能自动证明引用与结论之间的逻辑支持关系。

新增候选目录会占用输入预算，分块为目录预留空间；超出统一上下文/调用预算仍明确失败。最新离线验证：**144 passed, 5 skipped**。另通过生产 MCP 读取当前本地 `uploads/paper.pdf`，验证 22 页、10 块、371 个证据片段均在对应页真实存在，且不超过 180 字符。此检查未发送论文给 LLM，不产生模型费用；实际第三方模型的分析与 ID 选择仍需运行验证。


## ?? 5?Streamlit Web ??

???????? PowerShell????? Conda ?????

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m streamlit run app.py
```

???? `http://127.0.0.1:8501`????????????? 8511??? `http://127.0.0.1:8511`?????????????????????????????? `.env` ??????????????????????????????? MCP????????????? Streamlit 1.65.0 ????????????????

### ?? Tab

- **Paper Search**??????????? 5??????? Agent ?? MCP Client ?????????????????????PDF ??????????? 4 ResearchService ????????????????????
- **PDF Analysis**??? PDF????????????? MCP ??????????????????????????/???????????? PDF ????????????????? Markdown ???
- **Related Papers**????? PDF ??????????????????????????????????????? 5 ?????????????????????????????????????????????????????

??????????????????????? LLM ?????CLI ??? Function Calling Loop ?????Web ??????? MCP Client?ResearchService?BudgetedLLM ????????????? PDF/??????? `ResearchService.seed_analysis()` ??????????? Pydantic ???????????

### ??????

?????????Web ????? `success`?`error`????? `data`????????????

| Web ?? | ???? |
| --- | --- |
| success | ?? success=true????????? |
| partial | ???????????/?????????? PDF ?? complete=false |
| failed | ??????????? |
| timeout | task/tool/LLM ????? secondary_error ?????????????????? timeout |

??????????????????????? partial ??????? success=true???????????????????????????????????????????? JSON???????????????????

### ??????????

????????????? `st.session_state`??????? `st.cache_data`/`st.cache_resource`???????????????????? Tab ???? SHA-256 ????????????????????????? Tab?????? rerun ??????????????????

???????????? `asyncio.run`?????? Streamlit?????? `st.fragment` ???????MCP ????????????????????????? MCP ?????? Client?????????UI ???????????????????? .env?????????????????????????????????????????????????

?????????????????????????????????????????????????????????????????????????????????????????????????? Windows ?????? Pandas DLL???????? Pandas ? dataframe ???

### ???????

?????? `.pdf` ???? `%PDF-` ??????? PyMuPDF ?????????????????/?????????? 20 MiB / 50 ?????????????????????????????

???????? `uploads/web_<session UUID>/`????????? UUID ??????? 5 ??Web ??????????????????????????????WebBackend ??????????? `uploads/paper.pdf` ???????Web ?????????????????uploads ?? .gitignore ????

???????????????????????????????????? Python ????????????????/???????????????????????????????????????? `web_*` ?????????????????????????????????????????????????? 6 ???

### ?????

?????? `app.py`?`.streamlit/config.toml`??? `ui/app.py`?`backend.py`?`state.py`?`uploads.py`?`formatters.py`?`components.py`?`search_page.py`?`analysis_page.py`?`recommend_page.py`??? `tests/test_ui.py`??? ResearchService ????????????ui ????requirements?Streamlit >=1.65??AGENTS ?? README?

```powershell
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest tests/test_ui.py -q -p no:cacheprovider
& 'D:\anaconda3\envs\paper-agent\python.exe' -m pytest -q -p no:cacheprovider
```

?????2026-10-11???? **191 passed, 5 skipped**????? 34 ? Web ???Streamlit AppTest ????????????rerun ??????????????? Tab ??/???????????? partial ???Web ???????? stdio MCP ??????? PDF??? Mock LLM ????? Client ?????????????????????pip check ????????????? Streamlit ?????`/_stcore/health` ?? HTTP 200 / ok?

??? Web ???? LLM ?????????????????????????????? CLI ?????????????????????????? Web ?? API ?????????????????? 4??????????????? 5 ??????????????????????????????????????????????????????? Web ??????????????????????????? 5?
