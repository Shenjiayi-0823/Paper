import asyncio

from paper_research_agent.agent import cli
from paper_research_agent.agent.loop import AgentResult, PaperAgent
from paper_research_agent.config import Settings
from test_agent import FakeMCP
from test_research_agent import llm
from test_agent import response


def test_agent_progress_without_sensitive_content():
    messages = []
    result = asyncio.run(PaperAgent(Settings(),llm([response()]),FakeMCP(),progress=messages.append).run("private-paper-request"))
    assert result.success and any("模型请求 1" in text for text in messages)
    assert any("已收到响应" in text for text in messages)
    assert all("private-paper-request" not in text for text in messages)


def test_cli_progress_uses_stderr_and_cleans_timer(monkeypatch,capsys):
    class Agent:
        def __init__(self,settings,progress=None):
            self.progress = progress
        async def run(self,request):
            if self.progress:
                self.progress("测试阶段")
            return AgentResult(success=True,answer="done")
    monkeypatch.setattr(cli,"PaperAgent",Agent)
    async def check():
        result = await cli.run_task(Settings(),"request")
        assert result.success
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    asyncio.run(check())
    output = capsys.readouterr()
    assert "测试阶段" in output.err and not output.out
    asyncio.run(cli.run_task(Settings(),"request",quiet=True))
    assert not capsys.readouterr().err
