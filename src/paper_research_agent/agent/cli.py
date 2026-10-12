"""One task per CLI prompt; MCP subprocess is managed automatically."""

import argparse
import asyncio
import sys
import json
from contextlib import suppress
import time

from paper_research_agent.config import load_settings
from .loop import PaperAgent


async def run_task(settings, request, quiet=False):
    started = time.monotonic()
    def progress(message):
        print(f"[{time.monotonic() - started:.0f}s] {message}", file=sys.stderr, flush=True)
    async def heartbeat():
        while True:
            await asyncio.sleep(15)
            progress("仍在处理中；可按 Ctrl+C 取消")
    if quiet:
        return await PaperAgent(settings).run(request)
    timer = asyncio.create_task(heartbeat())
    try:
        # Run the Agent in this task, so MCP cancel scopes keep their ownership.
        return await PaperAgent(settings, progress=progress).run(request)
    finally:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper Research Agent (MCP + OpenAI)")
    parser.add_argument("--request", help="Run one natural-language task and exit")
    parser.add_argument("--json", action="store_true", help="Print final answer, full structured artifacts and tool trace as JSON")
    parser.add_argument("--quiet", action="store_true", help="Disable progress and waiting messages on stderr")
    args = parser.parse_args()
    try:
        settings = load_settings()
        settings.require_openai_api_key()
    except Exception:
        print("配置无效或缺少 OPENAI_API_KEY。请检查项目 .env 和 README。", file=sys.stderr)
        return 1
    while True:
        try:
            request = args.request if args.request is not None else input("请求（输入 exit 退出）：")
            if request.strip().lower() in ("exit", "quit"):
                return 0
            result = asyncio.run(run_task(settings, request, args.quiet))
            if args.json:
                print(json.dumps(result.model_dump(exclude={"messages"}), ensure_ascii=False, indent=2))
            elif result.success:
                print(result.answer)
            else:
                print(f"任务失败：{result.error['code']} — {result.error['message']}", file=sys.stderr)
            if args.request is not None:
                return 0 if result.success else 1
        except (EOFError, KeyboardInterrupt):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
