"""Owned, on-demand local model processes. Private inputs never use cloud fallback."""
import atexit
from contextlib import contextmanager
import ctypes
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time

from .config import ROOT,USER_DIR
from .http import ServiceError
from .ipc import JsonProcessClient,KernelError
from .telemetry import measure


def worker_environment():
    env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in
         ('API_KEY','API_HASH','TOKEN','PASSWORD','SECRET','AUTH','COOKIE','SESSION','PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'))}
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
               DO_NOT_TRACK='1',GRADIO_ANALYTICS_ENABLED='False',PYTHONIOENCODING='utf-8',
               PYTHONUTF8='1',OMP_NUM_THREADS='4',TOKENIZERS_PARALLELISM='false')
    return env


def own_process(process,*,resume=False):
    """Close the Windows job on parent exit/crash; never attach a foreign PID."""
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),
                  ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',w.DWORD),
                  ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class IO(ctypes.Structure):_fields_=[(name,ctypes.c_ulonglong) for name in ('r','w','o','rb','wb','ob')]
    class Limits(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                  ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];api.CreateJobObjectW.restype=w.HANDLE
    api.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    api.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    api.CloseHandle.argtypes=[w.HANDLE]
    handle=api.CreateJobObjectW(None,None);limits=Limits();limits.basic.flags=0x2000
    if not handle or not api.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not api.AssignProcessToJobObject(handle,int(process._handle)):
        if handle:api.CloseHandle(handle)
        process.kill();process.wait(timeout=5)
        raise ServiceError('Не удалось привязать локальную модель к процессу Джарвиса')
    state=[handle];guard=threading.Lock()
    def close_job():
        with guard:
            if state[0] is not None:
                api.CloseHandle(state[0]);state[0]=None
    if resume:
        class ThreadEntry(ctypes.Structure):
            _fields_=[('size',w.DWORD),('usage',w.DWORD),('tid',w.DWORD),('pid',w.DWORD),
                      ('base_priority',w.LONG),('delta_priority',w.LONG),('flags',w.DWORD)]
        api.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];api.CreateToolhelp32Snapshot.restype=w.HANDLE
        api.Thread32First.argtypes=[w.HANDLE,ctypes.POINTER(ThreadEntry)]
        api.Thread32Next.argtypes=[w.HANDLE,ctypes.POINTER(ThreadEntry)]
        api.OpenThread.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenThread.restype=w.HANDLE
        api.ResumeThread.argtypes=[w.HANDLE];api.ResumeThread.restype=w.DWORD
        snapshot=api.CreateToolhelp32Snapshot(4,0);entry=ThreadEntry();entry.size=ctypes.sizeof(entry);resumed=False
        try:
            found=api.Thread32First(snapshot,ctypes.byref(entry))
            while found:
                if entry.pid==process.pid:
                    thread=api.OpenThread(2,False,entry.tid)
                    if thread:
                        resumed=api.ResumeThread(thread)!=0xffffffff;api.CloseHandle(thread)
                    if resumed:break
                found=api.Thread32Next(snapshot,ctypes.byref(entry))
        finally:api.CloseHandle(snapshot)
        if not resumed:
            close_job();raise ServiceError('Не удалось запустить собственный процесс локальной модели')
    return close_job


class ModelProcess:
    def __init__(self,idle_seconds=90):
        self.lock=threading.RLock();self.idle_seconds=idle_seconds
        self.process=None;self.timer=None;self.generation=0;self.job_close=None
    @contextmanager
    def use(self):
        with self.lock:
            self.generation+=1
            if self.timer:self.timer.cancel()
            try:yield
            finally:
                generation=self.generation
                self.timer=threading.Timer(self.idle_seconds,self._expire,args=(generation,))
                self.timer.daemon=True;self.timer.start()
    def _expire(self,generation):
        with self.lock:
            if generation==self.generation:self.close()
    def close(self):
        with self.lock:
            self.generation+=1
            if self.timer:self.timer.cancel();self.timer=None
            if self.job_close:self.job_close();self.job_close=None
            if self.process is not None:
                if self.process.poll() is None:self.process.terminate()
                try:self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
                self.process=None
    def status(self):
        process=self.process;running=process is not None and process.poll() is None
        return {'running':running,'pid':process.pid if running else None}


class LocalText(ModelProcess):
    is_local=True
    model='local/qwen3.5-4b'
    def __init__(self,manifest,idle_seconds=90):
        super().__init__(idle_seconds);self.manifest=manifest;self.port=None;self.token=''
    def _request(self,path,body=None,timeout=45):
        # http.client bypasses proxy environment variables and never follows redirects.
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=timeout)
        raw=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None
        try:
            connection.request('POST' if body is not None else 'GET',path,body=raw,
                               headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
            response=connection.getresponse();data=response.read(1024*1024+1)
            if response.status!=200 or len(data)>1024*1024:raise ServiceError('Локальная модель не завершила запрос')
            return json.loads(data)
        finally:connection.close()
    def start(self):
        if self.process is not None and self.process.poll() is None:return
        executable=Path(self.manifest['llama_executable']);model=Path(self.manifest['text_model'])
        if not executable.is_file() or not model.is_file():raise ServiceError('Локальная языковая модель не установлена')
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));self.port=probe.getsockname()[1]
        self.token=secrets.token_hex(24)
        args=[str(executable),'-m',str(model),'--host','127.0.0.1','--port',str(self.port),
              '--api-key',self.token,'-c','8192','-ngl','99','--parallel','1','--log-disable','--no-webui']
        self.process=subprocess.Popen(args,env=worker_environment(),cwd=executable.parent,
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|0x00000004)
        self.job_close=own_process(self.process,resume=True)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            if self.process.poll() is not None:break
            try:
                if self._request('/health',timeout=1).get('status')=='ok':return
            except (OSError,ValueError,ServiceError):pass
            time.sleep(.15)
        self.close();raise ServiceError('Локальная языковая модель не запустилась. Переписка не отправлена в облако.')
    def complete(self,messages,tools=None,*,allow_tools=False,json_schema=None):
        if tools:raise ServiceError('Локальная модель возвращает данные; инструменты выполняет Джарвис')
        with self.use(),measure('model',self.model):
            self.start()
            from .privacy import audit
            audit('allowed','private_local_model','loopback')
            body={'messages':messages,'max_tokens':1000 if json_schema is None else 450,
                  'temperature':.2,'stream':False,'chat_template_kwargs':{'enable_thinking':False}}
            if json_schema is not None:body['response_format']={'type':'json_schema','json_schema':{'name':'private_command','schema':json_schema}}
            try:
                result=self._request('/v1/chat/completions',body)
                choice=result['choices'][0]
                if choice.get('finish_reason')!='stop':raise ServiceError('Локальная модель не завершила ответ')
                text=choice['message']['content']
                if not isinstance(text,str) or not text.strip():raise ValueError()
                return {'content':text.strip()}
            except (OSError,ValueError,KeyError,IndexError) as exc:
                raise ServiceError('Локальная модель не ответила корректно. Данные остались на ПК.') from exc


class LocalSpeech(ModelProcess):
    def __init__(self,manifest,idle_seconds=90):
        super().__init__(idle_seconds);self.manifest=manifest;self.client=None
    def start(self):
        if self.process is not None and self.process.poll() is None:return
        python=Path(self.manifest['voice_python'])
        if not python.is_file():raise ServiceError('Локальный синтезатор голоса не установлен')
        script=Path(__file__).with_name('local_voice_worker.py')
        self.client=JsonProcessClient([str(python),str(script),'--model',self.manifest['voice_model']],
                                     timeout=180,env=worker_environment(),cwd=ROOT,creationflags_extra=0x00000004)
        self.process=self.client.process;self.job_close=own_process(self.process,resume=True)
        self.client.terminate_tree=self.job_close
    def synthesize(self,text,destination,settings):
        with self.use():
            self.start()
            from .privacy import audit
            audit('allowed','private_local_voice','stdio')
            try:
                result=self.client.call('synthesize',{'text':str(text),'path':str(Path(destination).resolve()),
                    'reference':getattr(settings,'private_voice_reference','') or settings.voice_reference,
                    'reference_text':getattr(settings,'private_voice_reference_text','') or settings.voice_reference_text})['result']
                if not result.get('written') or not Path(destination).is_file():raise ValueError()
            except (KernelError,ValueError,OSError) as exc:
                self.last_error_details=list(self.client._stderr)
                self.close();raise ServiceError('Локальный голос недоступен. Приватный текст не отправлен в облако.') from exc
    def close(self):
        with self.lock:
            if self.client:
                self.client.close();self.client=None
            super().close()


class LocalAI:
    def __init__(self,manifest,idle_seconds=90):
        self.text=LocalText(manifest,idle_seconds);self.voice=LocalSpeech(manifest,idle_seconds)
        atexit.register(self.close)
    def close(self):self.text.close();self.voice.close()
    def status(self):return {'text':self.text.status(),'voice':self.voice.status()}


_instance=None;_instance_lock=threading.Lock()
def get_local_ai(settings):
    global _instance
    if not getattr(settings,'local_ai_enabled',False):return None
    with _instance_lock:
        if _instance is None:
            try:
                manifest=json.loads((USER_DIR/'local-model-install.json').read_text(encoding='utf-8'))
                _instance=LocalAI(manifest,getattr(settings,'local_ai_idle_seconds',90))
            except (OSError,ValueError,KeyError):return None
        return _instance
