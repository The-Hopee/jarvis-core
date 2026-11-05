"""Per-job assistant state; shared platform resources, one foreground speaker."""
import copy
from contextlib import contextmanager
import re
import hashlib

from .assistant import Assistant,Turn,strip_wake
from .config import Settings
from .jobs import JobDispatcher,JobStore,GuardedKernel,RESOURCES
from .openrouter import OpenRouterClient
from .services import LocalServices
from .tools import ToolRegistry
from .telemetry import TurnTrace
from .http import ServiceError

STAGES={'queued':'в очереди','starting':'начинаю','model':'готовлю ответ','tool':'выполняю действие',
        'planning':'строю план','workers':'исполнители пишут код','checks':'проверяю результат','review':'выполняю ревью',
        'resource_wait':'ожидаю общий ресурс','completed':'готова','failed':'ошибка','cancelled':'остановлена',
        'cancel_requested':'останавливается','interrupted':'прервана перезапуском','blocked':'зависимая задача не выполнена'}


class JobTrace(TurnTrace):
    def __init__(self,store,ident):
        super().__init__('background_job');self.store,self.ident=store,ident
    @contextmanager
    def measure(self,name,operation='',*,foreground=True):
        if name in {'model','tool','resource_wait'}:self.store.stage(self.ident,name)
        try:
            with super().measure(name,operation,foreground=foreground) as span:yield span
        finally:
            if name=='resource_wait':self.store.stage(self.ident,'tool')


class HomeJobs:
    def __init__(self,kernel,vk,settings,*,store=None,stopped=None):
        self.kernel,self.vk,self.settings=kernel,vk,settings
        self.store=store or JobStore()
        self.dispatcher=JobDispatcher({'chat':self.run_chat,'coding':self.run_coding},store=self.store,stopped=stopped)

    def __enter__(self):
        from .runtime import RuntimeOwner
        name='Local\\Jarvis.Jobs.'+hashlib.sha256(str(self.store.path.resolve()).encode()).hexdigest()[:20]
        self.owner=RuntimeOwner(name).__enter__()
        try:self.dispatcher.__enter__()
        except BaseException:self.owner.close();raise
        return self
    def __exit__(self,*args):
        try:self.dispatcher.__exit__(*args)
        finally:self.owner.close()

    def run_chat(self,job,cancelled):
        kernel=GuardedKernel(self.kernel,cancelled)
        registry=ToolRegistry(kernel,LocalServices(self.settings,kernel),shared_vk=self.vk,resource_locks=RESOURCES,cancelled=cancelled)
        registry.home_jobs=self
        client=OpenRouterClient(self.settings.api_key,self.settings.model) if self.settings.api_key else None
        payload=job['payload']
        from .routing import Router
        assistant=Assistant(registry,client,stopped=cancelled,router=Router(self.settings,mode=payload.get('mode','auto')))
        assistant.history=copy.deepcopy(payload.get('history',[]))[-20:]
        assistant.conversation.context=copy.deepcopy(payload.get('context',{}))
        # Ambiguous-recipient send grants stay with the foreground conversation.
        assistant.conversation.pending=None
        trace=JobTrace(self.store,job['id'])
        state='error'
        try:
            with trace.activate():turn=assistant.respond(payload['text'])
            state='completed'
            return {'text':turn.text,'warning':bool(turn.warning),
                    'success':all(r['output'].get('ok') for r in turn.tools) and (not turn.warning or bool(turn.tools)),
                    'artifacts':[r['output']['result']['path'] for r in turn.tools if r['output'].get('ok') and isinstance(r['output'].get('result',{}).get('path'),str)],
                    'tools':[{'name':r['name'],'ok':r['output'].get('ok')} for r in turn.tools]}
        finally:
            registry.close();trace.finish('cancelled' if cancelled() else state)

    def run_coding(self,job,cancelled):
        # The coding implementation is attached in the coding acceptance stage.
        from .coding import run_queued_job
        return run_queued_job(job,self.store,cancelled)

    @staticmethod
    def background_text(text):
        match=re.match(r'^(?:в\s+фоне|фоновая\s+задача|фоном)\s*[:,—-]?\s+(.+)$',strip_wake(text),re.I|re.S)
        return match[1].strip() if match else None

    def submit(self,text,assistant):
        assistant.conversation.expire()
        job=self.store.submit('chat',{'text':text,'history':assistant.history[-20:],
                                      'context':assistant.conversation.context,
                                      'mode':assistant.router.mode if assistant.router else 'auto'})
        assistant.history=[*assistant.history,{'role':'user','content':text},{'role':'assistant','content':f"Задача {job['number']} принята в очередь."}][-20:]
        return job

    def control(self,text):
        lower=strip_wake(text).casefold().strip(' .!?,')
        if re.fullmatch(r'(?:что\s+(?:сейчас\s+)?выполняется|какие\s+задачи|статус\s+задач|список\s+задач)',lower):
            jobs=self.store.recent(16)
            live=[j for j in jobs if j['status'] in {'queued','running','cancel_requested'}]
            if not live:return Turn('Активных задач нет, сэр.')
            return Turn(' '.join(f"Задача {j['number']}: {STAGES.get(j['stage'],STAGES.get(j['status'],'работает'))}." for j in live))
        match=re.fullmatch(r'(?:статус|отмени)\s+задач[ауи]\s+(\d+)',lower)
        if match:
            try:job=self.store.cancel(match[1]) if lower.startswith('отмени') else self.store.get(match[1])
            except ServiceError as exc:return Turn(str(exc))
            if lower.startswith('отмени'):
                return Turn(f"Отмена задачи {job['number']} {'завершена' if job['status']=='cancelled' else 'запрошена'}. Уже выполненные действия не откатываются.")
            return Turn(f"Задача {job['number']}: {STAGES.get(job['stage'],STAGES.get(job['status'],'работает'))}."+((' '+job['result']['text']) if job.get('result',{} ) and job['result'].get('text') else ''))
        return None

    def drain(self,assistant=None):
        turns=[]
        for job in self.store.notifications(consume=True):
            if job['status']=='completed':
                text=(job.get('result') or {}).get('text','Результат сохранён.')
                artifacts=[{'name':'background_artifact','output':{'ok':True,'result':{'path':p}}} for p in (job.get('result') or {}).get('artifacts',[])]
                turns.append(Turn(f"Задача {job['number']} готова. {text}",artifacts))
            elif job['status']=='cancelled':turns.append(Turn(f"Задача {job['number']} остановлена. Выполненные действия не откатываются."))
            elif job['status']=='interrupted':turns.append(Turn(f"Задача {job['number']} прервана перезапуском. Автоматически повторять её не буду."))
            else:turns.append(Turn(f"Задача {job['number']}: {STAGES.get(job['status'],'ошибка')}. "+(job.get('result') or {}).get('text','Подробности доступны в состоянии задачи.')))
        if assistant:
            for turn in turns:assistant.history=[*assistant.history,{'role':'assistant','content':turn.text}][-20:]
        return turns
