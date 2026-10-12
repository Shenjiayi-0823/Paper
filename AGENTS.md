# 项目开发环境

- 所有 Python、pip、pytest 和后续 MCP 子进程统一使用 `D:\anaconda3\envs\paper-agent\python.exe`（现有 Conda Python 3.11 环境）。PowerShell 调用方式为 `& 'D:\anaconda3\envs\paper-agent\python.exe' ...`。
- 不创建项目内 `.venv`，不使用系统默认 Python 3.14，不重建或删除已有 Conda 环境。
- 允许按用户要求向该环境安装项目依赖；涉及沙箱外写入或联网时遵守工具的授权要求。
- 按课程阶段开发；当前已实现阶段 1–5。不要自动进入阶段 6，不执行部署或收费测试，除非用户另行要求。
