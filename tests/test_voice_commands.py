"""Regressions at ASR segment/intent/tool boundaries, without microphone or sends."""
from collections import deque
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jarvis.voice import VoiceInput, WakeGate


class VoiceBoundaryTests(unittest.TestCase):
    def capture(self, segments, *, interrupt=False):
        clock=[100.0];state={'open':False,'blocks':0}
        class Recognizer:
            def AcceptWaveform(self, _):
                self.segment=segments[state['blocks']]
                state['blocks']+=1;clock[0]+=.2
                return self.segment[0] is not None
            def Result(self):return json.dumps({'text':self.segment[0]})
            def PartialResult(self):return json.dumps({'partial':self.segment[1]})
        class Stream:
            def __init__(self, **kw):self.callback=kw['callback']
            def __enter__(self):
                state['open']=True
                for _ in segments:self.callback(b'\0\0'*3200,3200,None,None)
            def __exit__(self,*_):state['open']=False
        voice=VoiceInput.__new__(VoiceInput)
        voice.model,voice.sample_rate,voice.device=object(),16000,None
        voice.gate,voice.messages=WakeGate(),deque()
        def refine(text,pcm):
            self.assertFalse(state['open'])
            return text
        voice._refine=refine
        with patch.dict(sys.modules,sounddevice=SimpleNamespace(RawInputStream=Stream),
                        vosk=SimpleNamespace(KaldiRecognizer=lambda *_:Recognizer())), \
             patch('jarvis.voice.time.monotonic',side_effect=lambda:clock[0]):
            result=voice.next_command(stop_requested=lambda:state['open'] and state['blocks']>=len(segments),
                interrupt_requested=(lambda:True) if interrupt else None)
        return result,state['blocks']

    def test_wake_segment_waits_for_command_in_same_microphone_session(self):
        result,_=self.capture([('джарвис',''),(None,'открой'),
            ('открой вк и напиши Пете привет от джарвиса','')])
        self.assertEqual(result,'открой вк и напиши Пете привет от джарвиса')

    def test_speech_in_progress_is_not_replaced_by_ack_at_timeout(self):
        segments=[('джарвис','')]+[(None,'открой вк')]*9+[
            ('открой вк и напиши Пете привет','')]
        self.assertEqual(self.capture(segments)[0],'открой вк и напиши Пете привет')

    def test_notification_does_not_interrupt_wake_and_lose_following_speech(self):
        self.assertEqual(self.capture([('джарвис',''),(None,'напиши'),
            ('напиши Пете в вк сообщение привет','')],interrupt=True)[0],
            'напиши Пете в вк сообщение привет')

    def test_standalone_wake_still_acknowledges_after_short_wait(self):
        result,blocks=self.capture([('джарвис','')]+[(None,'')]*10)
        self.assertEqual(result,'');self.assertGreaterEqual(blocks,7)

    def test_complete_command_does_not_get_extra_wake_delay(self):
        result,blocks=self.capture([('джарвис включи музыку в вк','')])
        self.assertEqual(result,'включи музыку в вк');self.assertEqual(blocks,1)

    def test_wake_name_in_message_is_preserved_during_followup(self):
        gate=WakeGate();gate.resume(now=10)
        text='напиши Пете в вк сообщение привет от джарвис'
        self.assertEqual(gate.accept(text,now=11),text)
        self.assertIsNone(gate.accept(text,now=12))



if __name__=='__main__':unittest.main()
