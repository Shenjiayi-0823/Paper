"""All paper content and job results are per Streamlit session, not global cache."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import queue
import time

from .uploads import UploadStore
from .backend import TaskOutcome


@dataclass
class Job:
    key: str
    operation: str
    source_key: str | None
    future: object
    executor: object
    events: object
    started: float


def initialize(state):
    if 'pra' not in state:
        state['pra'] = {'uploads':UploadStore(),'tasks':{},'analyses':{},'recommendations':{},
            'search':[],'search_query':'','selected':None,'job':None,'last':None,'events':[], 'connection':'尚未检测'}
    return state['pra']


def start_job(state,key,operation,source_key,runner):
    if state['job'] is not None or key in state['tasks']:
        return False
    events = queue.Queue()
    started = time.monotonic()
    def progress(message):
        events.put((round(time.monotonic()-started,1),message))
    def work():
        try:
            return runner(progress)
        except Exception:
            return TaskOutcome(error={'code':'backend_error','message':'任务执行异常，未展示原始异常或敏感配置。'})
    executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix='paper-ui')
    future = executor.submit(work)
    state['job'] = Job(key,operation,source_key,future,executor,events,started)
    state['events'] = []
    return True


def poll_job(state):
    job = state['job']
    if job is None:
        return False
    while True:
        try:
            state['events'].append(job.events.get_nowait())
        except queue.Empty:
            break
    if not job.future.done():
        return False
    outcome = job.future.result()
    job.executor.shutdown(wait=False)
    state['tasks'][job.key] = outcome
    state['last'] = outcome
    state['connection'] = '最近任务已连接；连接现已释放' if outcome.connected else '最近任务未确认连接'
    if job.operation == 'search' and outcome.success:
        state['search'] = outcome.data.get('papers',[])
        state['search_query'] = outcome.data.get('query','')
    if job.source_key and outcome.data.get('analysis'):
        state['analyses'][job.source_key] = outcome.data['analysis']
    if job.source_key and outcome.data.get('recommendations'):
        state['recommendations'][job.source_key] = outcome.data['recommendations']
    state['job'] = None
    return True
