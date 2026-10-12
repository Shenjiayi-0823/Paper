import asyncio
import json
from types import SimpleNamespace as NS

from paper_research_agent.analysis.analyzer import PaperAnalyzer
from paper_research_agent.analysis.models import CLAIM_FIELDS
from paper_research_agent.analysis.service import ResearchService
from paper_research_agent.agent.budget import BudgetedLLM
from paper_research_agent.agent.loop import PaperAgent
from paper_research_agent.config import Settings
from test_analysis import MCP, document, llm_for
from test_agent import response, call, FakeMCP
from test_research_agent import llm


def test_long_chinese_notes_do_not_accumulate_in_reduction_inputs():
    settings = Settings(analysis_chunk_bytes=1200)
    sizes = []
    async def create(**kwargs):
        sizes.append(len(json.dumps(kwargs,ensure_ascii=False).encode('utf-8')))
        payload = json.loads(kwargs['messages'][-1]['content'])
        if 'chunk_id' in payload:
            ident = payload['evidence_catalog'][0]['id']
            output = {field:[{'text':f'块{payload["chunk_id"]}结论{i}'+('中文' * 75), 'provenance':'inference','evidence_ids':[ident]} for i in range(3)] for field in CLAIM_FIELDS}
        else:
            assert all(len(note[field]) <= 3 for note in payload['notes'] for field in CLAIM_FIELDS)
            assert all('quote' not in e for e in payload['evidence_catalog'])
            output = {field:payload['notes'][0][field] for field in CLAIM_FIELDS}
        reply = response(text=json.dumps(output,ensure_ascii=False))
        reply.usage = NS(total_tokens=1000)
        return reply
    raw = NS(chat=NS(completions=NS(create=create)))
    pdf = document('中文论文测试。' * 60,page_count=18)
    report = asyncio.run(PaperAnalyzer(MCP(pdf),BudgetedLLM(raw,settings),settings).analyze('local','source.pdf'))
    assert report.chunk_count > 10
    assert len(report.methodology) == report.chunk_count * 3
    assert len(report.summary.methodology) <= 3
    assert len(report.chunk_analyses) == report.chunk_count
    assert max(sizes) < settings.agent_context_budget


def test_routing_excerpts_fit_context_without_losing_call_ids():
    settings = Settings(agent_context_budget=18000)
    raw = llm([response([call('read_pdf','{"source_type":"arxiv","arxiv_id":"first"}'),call('read_pdf','{"source_type":"arxiv","arxiv_id":"second"}','second')]),response()])
    mcp = FakeMCP({'success':True,'full_text':'中文论文' * 10000})
    result = asyncio.run(PaperAgent(settings,raw,mcp).run('Read papers'))
    assert result.success
    sent = raw.chat.completions.create.call_args.kwargs
    assert len(json.dumps(sent,ensure_ascii=False).encode('utf-8')) < settings.agent_context_budget
    messages = [m for m in sent['messages'] if m['role'] == 'tool']
    assert [m['tool_call_id'] for m in messages] == ['call1','second']
    assert all(json.loads(m['content'])['truncated'] for m in messages)


def test_context_failure_does_not_restart_analysis():
    async def check():
        settings = Settings(agent_context_budget=1000)
        mcp = MCP()
        service = ResearchService(mcp,BudgetedLLM(llm_for([{}]),settings),settings,[])
        args = {'source_type':'local','file_path':'source.pdf'}
        first = await service.execute('analyze_paper',args)
        second = await service.execute('recommend_related',args)
        assert first['error']['code'] == second['error']['code'] == 'context_budget'
        assert len(mcp.calls) == 1
    asyncio.run(check())
