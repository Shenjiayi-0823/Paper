"""Explicit Web actions reuse the Agent's MCP client and research service."""

import asyncio
from dataclasses import dataclass, field
import time
import logging

from openai import AsyncOpenAI
from paper_research_agent.agent.budget import BudgetedLLM, ResourceError, find_resource_error
from paper_research_agent.agent.mcp_client import MCPClient
from paper_research_agent.analysis.models import PaperAnalysis, Recommendations
from paper_research_agent.analysis.service import ResearchService

logger = logging.getLogger(__name__)


@dataclass
class TaskOutcome:
    success: bool = False
    data: dict = field(default_factory=dict)
    error: dict | None = None
    trace: list[dict] = field(default_factory=list)
    elapsed: float = 0
    usage: dict = field(default_factory=dict)
    connected: bool = False


def is_timeout(error):
    return bool(error and (error.get('code') in {'task_timeout','tool_timeout','llm_timeout','llm_connect_timeout'} or is_timeout(error.get('secondary_error'))))


def task_status(outcome):
    if is_timeout(outcome.error):
        return 'timeout'
    if outcome.success and not outcome.error:
        return 'partial' if outcome.data.get('analysis',{}).get('complete') is False else 'success'
    if outcome.data.get('analysis') or outcome.data.get('recommendations') or outcome.data.get('papers'):
        return 'partial'
    return 'failed'


class WebBackend:
    def __init__(self,settings,uploads,mcp_factory=None,llm_factory=None):
        self.settings,self.uploads = settings,uploads
        self.mcp_factory = mcp_factory or (lambda:MCPClient(timeout=settings.agent_tool_timeout_seconds))
        self.llm_factory = llm_factory or (lambda:AsyncOpenAI(api_key=settings.require_openai_api_key(),base_url=settings.openai_base_url,timeout=settings.request_timeout_seconds,max_retries=0))

    def run(self,operation,args,progress=None,analysis=None):
        # Called in a job worker, with a fresh event loop per task. MCP contexts
        # enter and exit in the SAME task; nothing async is cached in session.
        return asyncio.run(self.execute(operation,args,progress,analysis))

    async def execute(self,operation,args,progress=None,analysis=None):
        outcome = TaskOutcome()
        started = time.monotonic()
        sdk = None
        budget = None
        service = None
        if operation not in {'search','analyze_paper','recommend_related','check'}:
            outcome.error = {'code':'invalid_action','message':'未知操作。'}
            return outcome
        if operation in {'analyze_paper','recommend_related'} and args.get('source_type') == 'local' and not self.uploads.owns(args.get('file_path')):
            outcome.error = {'code':'upload_not_owned','message':'只能访问当前会话上传的 PDF。'}
            return outcome
        try:
            async with asyncio.timeout(self.settings.agent_task_timeout_seconds):
                if progress:
                    progress('正在连接 MCP Server')
                async with self.mcp_factory().connect() as client:
                    outcome.connected = True
                    if progress:
                        progress('MCP 已连接')
                    class TimedTools:
                        async def call_tool(self,name,params):
                            begin = time.monotonic()
                            result = await client.call_tool(name,params)
                            if name == 'search_arxiv' and operation == 'recommend_related':
                                outcome.data.setdefault('candidate_searches', []).append({'parameters': params, 'result': result})
                            outcome.trace.append({'name':name,'success':result.get('success'), 'error':result.get('error'), 'elapsed_seconds':round(time.monotonic()-begin,2)})
                            return result
                    tools = TimedTools()
                    if operation == 'check':
                        outcome.success = True
                        outcome.data = {'tools':list(client.tools)}
                    elif operation == 'search':
                        result = await tools.call_tool('search_arxiv',args)
                        outcome.success = bool(result.get('success'))
                        outcome.error = result.get('error')
                        if outcome.success:
                            outcome.data = {'query':args.get('query',''),'papers':result.get('papers',[]),'warnings':result.get('warnings',[])}
                    else:
                        sdk = self.llm_factory()
                        budget = BudgetedLLM(sdk,self.settings,progress)
                        service = ResearchService(tools,budget,self.settings,[])
                        if analysis is not None:
                            service.seed_analysis(args,PaperAnalysis.model_validate(analysis))
                            if progress:
                                progress('复用本会话已验证的源论文报告，无需重新分析')
                        result = await service.execute(operation,args)
                        outcome.success = bool(result.get('success'))
                        outcome.error = result.get('error')
                        if result.get('analysis'):
                            outcome.data['analysis'] = PaperAnalysis.model_validate(result['analysis']).model_dump()
                        if result.get('recommendations'):
                            outcome.data['recommendations'] = Recommendations.model_validate(result['recommendations']).model_dump()
        except TimeoutError:
            outcome.error = {'code':'task_timeout','message':'任务超过总时间限制。'}
            outcome.success = False
        except Exception as exc:
            safe = find_resource_error(exc)
            outcome.error = {'code':safe.code,'message':safe.message} if safe else {'code':'backend_error','message':'后端连接或模型请求失败，请检查配置和日志。'}
            outcome.success = False
        finally:
            # Preserve a valid source report even when recommendation fails.
            if service:
                source_key = (args.get('source_type'),args.get('file_path'),args.get('arxiv_id'),args.get('language','中文'))
                if source_key in service.cache:
                    outcome.data.setdefault('analysis',service.cache[source_key].model_dump())
            if budget:
                outcome.usage = {'llm_calls':budget.calls,'accounted_tokens':budget.reserved_tokens}
            if sdk:
                try:
                    await sdk.close()
                except Exception:
                    outcome.error = outcome.error or {'code':'cleanup_error','message':'模型连接释放异常。'}
                    outcome.success = False
            outcome.elapsed = round(time.monotonic()-started,2)
            if outcome.error:
                logger.warning('Web task %s failed after %.2fs [%s]: %s',operation,outcome.elapsed,
                    outcome.error.get('code','error'),outcome.error.get('message','Task failed'))
            if operation in {'analyze_paper','recommend_related'}:
                outcome.trace.append({'name':operation,'success':outcome.success,'error':outcome.error,'elapsed_seconds':outcome.elapsed})
        return outcome
