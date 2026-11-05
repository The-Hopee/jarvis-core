from pathlib import Path
import tempfile
import threading
import time
import unittest
import sys
from unittest.mock import patch

from jarvis.jobs import JobStore,JobDispatcher,ResourceLocks,JobCancelled,GuardedKernel
from jarvis.assistant import Assistant
from jarvis.config import Settings
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry
from jarvis.http import ServiceError


def until(predicate,seconds=3):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():return True
        time.sleep(.01)
    return False


class QueueTests(unittest.TestCase):
    def test_idle_notification_closes_input_without_transcribing_room_audio(self):
        from collections import deque
        from types import SimpleNamespace
        from jarvis.voice import VoiceInput,WakeGate
        opened=[False]
        class Input:
            def __init__(self,**kw):self.callback=kw['callback']
            def __enter__(self):opened[0]=True;self.callback(b'\0\0'*100,100,None,None)
            def __exit__(self,*_):opened[0]=False
        class Recognizer:
            def AcceptWaveform(self,_):return False
            def PartialResult(self):return '{"partial":""}'
        voice=VoiceInput.__new__(VoiceInput)
        voice.model,voice.sample_rate,voice.device,voice.gate,voice.messages=object(),16000,None,WakeGate(),deque()
        voice._refine=lambda *_:self.fail('idle audio must not be sent to cloud')
        with patch.dict(sys.modules,sounddevice=SimpleNamespace(RawInputStream=Input),vosk=SimpleNamespace(KaldiRecognizer=lambda *_:Recognizer())):
            self.assertIsNone(voice.next_command(interrupt_requested=lambda:True))
        self.assertTrue(voice.last_interrupted);self.assertFalse(opened[0]);self.assertIsNone(voice.last_trace)

    def test_cancelling_real_check_stops_only_its_owned_child(self):
        from jarvis.coding import run_check
        with tempfile.TemporaryDirectory() as folder:
            cancel=threading.Event();timer=threading.Timer(.2,cancel.set);timer.start()
            started=time.monotonic()
            try:
                with self.assertRaises(JobCancelled):
                    run_check(Path(folder),[sys.executable,'-c','import time;time.sleep(30)'],cancelled=cancel.is_set)
            finally:timer.cancel()
            self.assertLess(time.monotonic()-started,5)

    def test_two_jobs_run_independently_and_queued_cancel_never_executes(self):
        with tempfile.TemporaryDirectory() as folder:
            store=JobStore(Path(folder)/'queue.sqlite')
            entered=[];guard=threading.Lock();both=threading.Event();release=threading.Event()
            def handler(job,cancelled):
                with guard:
                    entered.append(job['payload']['value'])
                    if len(entered)==2:both.set()
                while not release.wait(.01):
                    if cancelled():raise JobCancelled('cancelled')
                return {'text':str(job['payload']['value'])}
            with JobDispatcher({'chat':handler},store=store) as dispatcher:
                a=store.submit('chat',{'value':1});b=store.submit('chat',{'value':2})
                self.assertTrue(both.wait(2))
                c=store.submit('chat',{'value':3});store.cancel(c['id'])
                store.cancel(a['id']);release.set()
                self.assertTrue(until(lambda:store.get(b['id'])['status']=='completed'))
                self.assertTrue(until(lambda:store.get(a['id'])['status']=='cancelled'))
                self.assertEqual(store.get(c['id'])['status'],'cancelled')
                self.assertNotIn(3,entered)
            self.assertNotIn('payload',store.get(b['id']))
            self.assertEqual(store.get(b['id'])['result']['text'],'2')

    def test_restart_marks_work_interrupted_and_never_replays_it(self):
        with tempfile.TemporaryDirectory() as folder:
            store=JobStore(Path(folder)/'queue.sqlite')
            a=store.submit('chat',{'text':'first'});store.claim()
            b=store.submit('chat',{'text':'second'});calls=[]
            with JobDispatcher({'chat':lambda *_:calls.append(True)},store=store):
                self.assertEqual(store.get(a['id'])['status'],'interrupted')
                self.assertEqual(store.get(b['id'])['status'],'interrupted')
                self.assertTrue(store.has_notifications())
                self.assertEqual(len(store.notifications(consume=True)),2)
                self.assertFalse(store.has_notifications())
            self.assertEqual(calls,[])

    def test_dependencies_wait_then_run_and_failed_dependency_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            store=JobStore(Path(folder)/'queue.sqlite');order=[]
            def handler(job,_):
                order.append(job['payload']['value'])
                if job['payload'].get('fail'):raise RuntimeError('test')
                return {'text':'done'}
            with JobDispatcher({'chat':handler},store=store):
                a=store.submit('chat',{'value':1})
                b=store.submit('chat',{'value':2},dependencies=[a['id']])
                bad=store.submit('chat',{'value':3,'fail':True})
                blocked=store.submit('chat',{'value':4},dependencies=[bad['id']])
                self.assertTrue(until(lambda:store.get(b['id'])['status']=='completed'))
                self.assertTrue(until(lambda:store.get(blocked['id'])['status']=='blocked'))
                self.assertLess(order.index(1),order.index(2));self.assertNotIn(4,order)

    def test_only_one_coding_job_occupies_workers_so_chat_can_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            store=JobStore(Path(folder)/'queue.sqlite');started=threading.Event();release=threading.Event();coding=[]
            def code(job,cancelled):
                coding.append(job['id']);started.set()
                while not release.wait(.01):
                    if cancelled():raise JobCancelled()
                return {'text':'done'}
            with JobDispatcher({'coding':code,'chat':lambda *_:{'text':'weather'}},store=store):
                first=store.submit('coding',{});self.assertTrue(started.wait(2))
                second=store.submit('coding',{});chat=store.submit('chat',{})
                self.assertTrue(until(lambda:store.get(chat['id'])['status']=='completed'))
                self.assertEqual(len(coding),1)
                store.cancel(second['id']);release.set()

    def test_waiting_for_shared_resource_can_be_cancelled_without_action(self):
        locks=ResourceLocks();cancel=threading.Event();attempting=threading.Event();actions=[]
        def worker():
            try:
                attempting.set()
                with locks.hold('documents',cancel.is_set):actions.append(True)
            except JobCancelled:pass
        with locks.hold('documents'):
            thread=threading.Thread(target=worker);thread.start();self.assertTrue(attempting.wait(1))
            cancel.set();thread.join(timeout=1)
        self.assertEqual(actions,[]);self.assertFalse(thread.is_alive())

    def test_late_model_result_after_cancel_cannot_execute_a_tool_or_fallback(self):
        stopped=[False];calls=[]
        class Kernel:
            def call(self,*args,**kw):calls.append(args);return {'result':{}}
        class Model:
            def complete(self,*args,**kw):
                stopped[0]=True
                return {'tool_calls':[{'id':'one','type':'function','function':{'name':'open_website','arguments':'{"target":"example.com"}'}}]}
        kernel=Kernel();registry=ToolRegistry(GuardedKernel(kernel,lambda:stopped[0]),LocalServices(Settings(),kernel),cancelled=lambda:stopped[0])
        assistant=Assistant(registry,Model(),stopped=lambda:stopped[0])
        with self.assertRaises(JobCancelled):assistant.respond('Найди подходящий сайт')
        self.assertEqual(calls,[])

    def test_queue_capacity_and_unknown_dependency_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store=JobStore(Path(folder)/'queue.sqlite')
            with self.assertRaises(ServiceError):store.submit('chat',{},dependencies=['missing'])
            for _ in range(16):store.submit('chat',{})
            with self.assertRaises(ServiceError):store.submit('chat',{})

    def test_worker_registry_does_not_close_shared_vk(self):
        from jarvis.vk_browser import VKBrowser
        class VK(VKBrowser):
            def __init__(self):super().__init__();self.closed=False
            def close(self):self.closed=True
        vk=VK();registry=ToolRegistry(object(),LocalServices(Settings(),object()),shared_vk=vk)
        registry.close();self.assertFalse(vk.closed)


if __name__=='__main__':unittest.main()
