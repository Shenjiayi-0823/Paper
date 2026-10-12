import asyncio
import pytest
from pydantic import ValidationError

from paper_research_agent.analysis.models import AnalysisContent
from paper_research_agent.analysis.structured import validation_issues, structured_call
from paper_research_agent.agent.budget import BudgetedLLM
from paper_research_agent.config import Settings
from test_analysis import llm_for


@pytest.mark.parametrize('claim,code',[
    ({'text':'private-paper-text','provenance':'not_specified'},'claim_missing_mismatch'),
    ({'text':'Not specified','provenance':'author_stated','evidence_ids':['e1']},'claim_missing_label'),
    ({'text':'private-paper-text','provenance':'author_stated','evidence_ids':[]},'claim_evidence_required')])
def test_background_validation_reason_is_specific_and_safe(claim,code):
    with pytest.raises(ValidationError) as caught:
        AnalysisContent.model_validate({'background':[claim]})
    detail = validation_issues(caught.value,AnalysisContent)
    assert 'background.0' in detail and code in detail
    assert 'private-paper-text' not in detail


def test_repair_receives_actionable_background_feedback():
    invalid = {'background':[{'text':'Background statement','provenance':'author_stated','evidence_ids':[]}]}
    valid = {'background':[{'text':'Not specified','provenance':'not_specified','evidence_ids':[]}]}
    raw = llm_for([invalid,valid])
    settings = Settings()
    result = asyncio.run(structured_call(BudgetedLLM(raw,settings),settings,AnalysisContent,'Analyze',{}))
    assert result.background[0].text == 'Not specified'
    correction = raw.chat.completions.create.call_args.kwargs['messages'][-1]['content']
    assert 'claim_evidence_required' in correction and 'supporting ID' in correction
