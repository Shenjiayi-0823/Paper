import asyncio
import pytest
from pydantic import ValidationError

from paper_research_agent.analysis.models import AnalysisContent, SummarySelection
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


@pytest.mark.parametrize('length',[601,181])
def test_experiment_length_repair_uses_output_schema_and_preserves_ids(length):
    invalid = {'experiments':[{'text':'Not specified'},
        {'text':'x'*length,'provenance':'author_stated','evidence_ids':['e1']}]}
    valid = {'experiments':[{'text':'Not specified'},
        {'text':'The authors compare scheduling methods using measured energy consumption.',
         'provenance':'author_stated','evidence_ids':['e1']}]}
    raw = llm_for([invalid,valid])
    settings = Settings()
    result = asyncio.run(structured_call(BudgetedLLM(raw,settings),settings,AnalysisContent,'Analyze',
        {'evidence_catalog':[{'id':'e1'}]}, schema_model=SummarySelection,
        validator=lambda value: SummarySelection.model_validate(value.model_dump(exclude={'evidence'}))))
    correction = raw.chat.completions.create.call_args.kwargs['messages'][-1]['content']
    assert 'experiments.1.text' in correction and 'maximum 180 characters' in correction
    assert 'NOT words or tokens' in correction and 'provenance and evidence_ids' in correction
    assert 'x'*100 not in correction
    assert result.experiments[1].evidence_ids == ['e1']
    assert raw.chat.completions.create.await_count == 2


def test_quote_length_feedback_does_not_request_paraphrasing():
    with pytest.raises(ValidationError) as caught:
        AnalysisContent.model_validate({'evidence':[{'id':'e1','page_number':1,'quote':'x'*351}]})
    detail = validation_issues(caught.value,AnalysisContent,SummarySelection)
    assert 'maximum 350 characters' in detail and 'never paraphrase' in detail
    assert 'x'*100 not in detail
