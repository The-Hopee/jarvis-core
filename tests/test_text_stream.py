import io
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.text_stream import events,completion
from jarvis.sentence_speech import SentenceSpeech
from jarvis.telemetry import TurnTrace,measure
from jarvis.http import ServiceError


class TextStreamTests(unittest.TestCase):
    def test_sse_requires_done_and_preserves_final_text(self):
        payload={'choices':[{'delta':{'content':'Я на связи.'},'finish_reason':'stop'}]}
        seen=[]
        body=b'data: '+json.dumps(payload).encode()+b'\n\ndata: [DONE]\n'
        with io.BytesIO(body) as response:
            result=completion(events({}, {}, opener=lambda *_a,**_kw:response),seen.append)
        self.assertEqual(result['content'],'Я на связи.')
        self.assertEqual(seen,['Я на связи.'])
        response=io.BytesIO(body.split(b'data: [DONE]')[0])
        with self.assertRaises(ServiceError):completion(events({}, {},opener=lambda *_a,**_kw:response))

    def test_partial_tool_arguments_are_collected_but_not_executed(self):
        chunks=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c1','function':{'name':'get_weather','arguments':'{"city":'}}]}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"Дзержинск"}'}}]},'finish_reason':'tool_calls'}]}]
        result=completion(iter(chunks))
        self.assertEqual(json.loads(result['tool_calls'][0]['function']['arguments']),{'city':'Дзержинск'})
        with self.assertRaises(ServiceError):completion(iter(chunks),lambda _:None)

    def test_sentence_starts_before_model_finishes_without_replaying_answer(self):
        spoken=[];played=threading.Event()
        class Output:
            def speak(self,text,**kw):
                kw['before_playback']();spoken.append(text);played.set()
        stream=SentenceSpeech(Output(),SimpleNamespace(stop=lambda:None),TurnTrace(sink=lambda _:None),lambda:False)
        stream.feed('Первое предложение. ')
        self.assertTrue(played.wait(1))
        stream.feed('Второе предложение.')
        stream.finish()
        self.assertEqual(spoken,['Первое предложение.','Второе предложение.'])
        self.assertFalse(stream.thread.is_alive())

    def test_interleaved_spans_restore_the_actual_active_stage(self):
        trace=TurnTrace(sink=lambda _:None);first=threading.Event();second=threading.Event()
        def worker():
            with trace.activate(),measure('tts','voice'):
                first.set();second.wait(1)
        with trace.activate():
            with measure('model','test'):
                thread=threading.Thread(target=worker);thread.start();self.assertTrue(first.wait(1))
                self.assertEqual(trace.phase()[0],'tts')
            self.assertEqual(trace.phase()[0],'tts')
            second.set();thread.join(timeout=1)
        self.assertEqual(trace.phase()[0],'idle')

    def test_cancel_drops_uncommitted_sentence(self):
        spoken=[]
        stream=SentenceSpeech(SimpleNamespace(speak=lambda *a,**k:spoken.append(a)),SimpleNamespace(stop=lambda:None),TurnTrace(sink=lambda _:None),lambda:False)
        stream.feed('Незавершённое предложение')
        stream.finish(cancel=True)
        self.assertEqual(spoken,[])


if __name__=='__main__':unittest.main()
