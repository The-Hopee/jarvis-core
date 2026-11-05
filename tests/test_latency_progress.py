import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from jarvis.assistant import Assistant, Turn
from jarvis.cloud_voice import request_audio
from jarvis.config import Settings
from jarvis.http import ServiceError
from jarvis.interaction import run_turn
from jarvis.openrouter import OpenRouterClient
from jarvis.progress import ProgressFeedback, cache_directory
from jarvis.speech import Speaker, play_mp3
from jarvis.telemetry import TurnTrace, append_record, mark, measure, report
from jarvis.tools import ToolRegistry
from jarvis.services import LocalServices


def wav(path, seconds=.03):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b'\0\0' * int(16000 * seconds))


class TimingsTests(unittest.TestCase):
    def test_brief_weather_preserves_requested_details_and_failure_explanation(self):
        from jarvis.assistant import describe_tool
        output={'ok':True,'result':{'location':{'city':'Дзержинск','source':'configured_city'},'current':{'temperature_2m':5}}}
        record={'name':'get_weather','output':output}
        tools=ToolRegistry(object(),LocalServices(Settings(),object()))
        assistant=Assistant(tools)
        long_text='Подробный ответ о погоде. '*20
        result=assistant._remember('какая погода?',Turn(long_text,[record]))
        self.assertEqual(result.text,describe_tool('get_weather',output))
        self.assertEqual(assistant.history[-1]['content'],result.text)
        self.assertEqual(assistant._remember('объясни погоду подробно',Turn(long_text,[record])).text,long_text)
        self.assertEqual(assistant._remember('какая погода завтра',Turn(long_text,[record])).text,long_text)
        self.assertEqual(assistant._remember('какая погода и куда сходить',Turn(long_text,[record])).text,long_text)
        self.assertEqual(assistant._remember('какая погода?',Turn(long_text,[record],'partial')).text,long_text)

    def test_stage_times_first_feedback_and_speech_are_separate_and_no_contents_leak(self):
        now, rows = [10.0], []
        trace = TurnTrace('voice', origin=9, speech_end_source='vosk_word_end_estimate', sink=rows.append, clock=lambda:now[0])
        private = 'secret message and private recipient'
        client = OpenRouterClient('fake-secret-key', 'test/model', http=lambda *_a,**_kw:{'choices':[{'message':{'content':private}}]})
        with trace.activate():
            mark('endpoint_final')
            with measure('asr', 'test/asr'):
                now[0] += .2
                mark('feedback_start')
            with measure('model', 'test/model'):
                client.complete([{'role':'user','content':private}], [])
                now[0] += .3
            mark('answer_ready')
            with measure('tts', 'test/voice'):
                now[0] += .4
            mark('answer_playback_start')
            with measure('playback', 'wav'):
                now[0] += 2
        trace.finish()
        trace.finish()
        self.assertEqual(len(rows), 1)
        s = rows[0]['summary']
        self.assertEqual((s['asr_ms'],s['model_ms'],s['tts_ms'],s['playback_ms']), (200,300,400,2000))
        self.assertEqual((s['feedback_start_ms'],s['answer_playback_start_ms']), (1200,1900))
        self.assertNotIn(private,json.dumps(rows))
        self.assertNotIn('fake-secret-key',json.dumps(rows))
        self.assertNotIn('private recipient',json.dumps(rows))

    def test_network_first_byte_precedes_complete_tts_and_asr_is_not_mislabelled(self):
        rows, clock = [], [1.0]
        class Response(io.BytesIO):
            def read(self, n=-1):
                clock[0] += .1 if n == 1 else 2
                return super().read(n)
        trace = TurnTrace('text', sink=rows.append, clock=lambda:clock[0])
        with trace.activate(), patch('urllib.request.urlopen', return_value=Response(b'ID3' + b'x'*200)):
            with measure('tts', 'fake'):
                raw=request_audio('https://example.test',data=b'',headers={})
        trace.finish()
        self.assertEqual(len(raw),203)
        self.assertEqual(rows[0]['events_ms']['tts_first_byte'],100)
        self.assertEqual(rows[0]['summary']['tts_ms'],2100)

    def test_failures_are_timed_without_error_messages(self):
        rows=[]
        trace=TurnTrace(sink=rows.append)
        with trace.activate():
            with self.assertRaises(ServiceError):
                with measure('asr','fake'):
                    raise ServiceError('secret transcript')
        trace.finish('degraded')
        self.assertEqual(rows[0]['spans'][0]['status'],'error')
        self.assertNotIn('secret transcript',json.dumps(rows))

    def test_report_keeps_source_filter_and_p95_separate_from_playback(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'timings.jsonl'
            for n in range(1,21):
                append_record({'schema_version':1,'source':'voice','summary':{'model_ms':n,'playback_ms':1000*n}},path)
            append_record({'schema_version':1,'source':'text','summary':{'model_ms':999}},path)
            with path.open('a') as out:
                out.write('broken json\n')
            result=report([path],source='voice')
            self.assertEqual(result['turns'],20)
            self.assertEqual(result['metrics']['model_ms'],{'n':20,'p50_ms':10.5,'p95_ms':19})
            self.assertEqual(result['metrics']['playback_ms']['p50_ms'],10500)

    def test_readonly_log_directory_does_not_break_execution(self):
        with patch('pathlib.Path.mkdir',side_effect=OSError('read only')):
            append_record({'schema_version':1})

    def test_log_rotation_keeps_only_three_previous_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'latency.jsonl'
            path.write_bytes(b'x'*(2*1024*1024))
            for n in (1,2,3):path.with_name(path.name+'.'+str(n)).write_text(str(n))
            append_record({'schema_version':1,'source':'text','summary':{}},path)
            self.assertEqual(json.loads(path.read_text())['source'],'text')
            self.assertEqual(path.with_name(path.name+'.3').read_text(),'2')
            self.assertEqual(len(list(Path(folder).iterdir())),4)

    def test_rejected_tool_is_timed_as_error_without_arguments(self):
        rows=[];trace=TurnTrace(sink=rows.append)
        tools=ToolRegistry(object(),LocalServices(Settings(),object()))
        with trace.activate():
            result=tools.execute('open_website',{'target':['private recipient']})
        trace.finish()
        self.assertFalse(result['ok'])
        self.assertEqual(rows[0]['spans'][0]['status'],'error')
        self.assertNotIn('private recipient',json.dumps(rows))

    def test_voice_estimate_and_accept_callback_happen_after_stream_closed(self):
        from collections import deque
        from types import SimpleNamespace
        import sys
        from jarvis.voice import VoiceInput,WakeGate
        opened=[False]; callbacks=[]
        class Input:
            def __init__(self,**kw):self.callback=kw['callback']
            def __enter__(self):
                opened[0]=True
                self.callback(b'\0\0'*16000,16000,None,None)
            def __exit__(self,*_):opened[0]=False
        class Recognizer:
            def SetWords(self,enabled):pass
            def AcceptWaveform(self,_):return True
            def Result(self):return json.dumps({'text':'джарвис привет','result':[{'end':.5}]})
        voice=VoiceInput.__new__(VoiceInput)
        voice.model,voice.sample_rate,voice.device=object(),16000,None
        voice.gate,voice.messages=WakeGate(),deque()
        voice._refine=lambda text,pcm:text
        def accepted(trace):
            self.assertFalse(opened[0]);callbacks.append(trace)
        with patch.dict(sys.modules,sounddevice=SimpleNamespace(RawInputStream=Input),vosk=SimpleNamespace(KaldiRecognizer=lambda *_:Recognizer())):
            self.assertEqual(voice.next_command(on_accepted=accepted),'привет')
        self.assertEqual(len(callbacks),1)
        self.assertEqual(voice.last_trace.speech_end_source,'vosk_word_end_estimate')
        self.assertGreaterEqual(voice.last_trace.events['endpoint_final'],490)


class ProgressTests(unittest.TestCase):
    def test_status_driver_timeout_releases_device_and_rejects_long_clip(self):
        from types import SimpleNamespace
        calls=[]
        def send(command,buffer,*_):
            calls.append(command)
            if command.endswith(' length'):buffer.value='100'
            if command.endswith(' mode'):buffer.value='playing'
            return 0
        with patch('jarvis.speech.ctypes.WinDLL',return_value=SimpleNamespace(mciSendStringW=send)),patch('jarvis.speech.time.monotonic',side_effect=[0,1]):
            with self.assertRaisesRegex(RuntimeError,'истекло'):
                play_mp3(Path('clip.mp3'),max_seconds=.1)
        self.assertTrue(any(c.startswith('stop ') for c in calls))
        self.assertTrue(calls[-1].startswith('close '))
        calls.clear()
        def long_send(command,buffer,*_):
            calls.append(command)
            if command.endswith(' length'):buffer.value='10000'
            return 0
        with patch('jarvis.speech.ctypes.WinDLL',return_value=SimpleNamespace(mciSendStringW=long_send)):
            with self.assertRaisesRegex(RuntimeError,'коротким'):
                play_mp3(Path('clip.mp3'),max_seconds=6)
        self.assertFalse(any(c.startswith('play ') for c in calls))
        self.assertTrue(calls[-1].startswith('close '))

    def test_fast_turn_has_no_status_and_slow_stages_are_not_repeated(self):
        class Output:
            def __init__(self): self.kinds=[]; self.played=threading.Event()
            def play_status(self, kind, relevant):
                if relevant():
                    self.kinds.append(kind);self.played.set();return True
                return False
        output=Output(); trace=TurnTrace(sink=lambda _:None)
        feedback=ProgressFeedback(output,delay=.1,interval=.01)
        with trace.activate(),measure('model','fake'):
            feedback.start(trace)
        feedback.stop()
        self.assertEqual(output.kinds,[])
        output=Output(); trace=TurnTrace(sink=lambda _:None)
        feedback=ProgressFeedback(output,delay=.01,interval=.01)
        with trace.activate(),measure('asr','fake'):
            feedback.start(trace)
            self.assertTrue(output.played.wait(1))
            time.sleep(.12)
        feedback.stop()
        self.assertEqual(output.kinds,['asr'])
        self.assertFalse(feedback.thread.is_alive())

    def test_status_and_answer_do_not_overlap_and_status_runs_during_synthesis(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder); wav(path/'tts.wav')
            speaker=Speaker(Settings(tts='openrouter'))
            # Use WAV cache with a Windows backend to exercise the real playback lock.
            speaker.settings=Settings(tts='windows')
            speaker.status_directory=path
            playing, calls, status_played = [False], [], threading.Event()
            def play(filename, _flags):
                self.assertFalse(playing[0])
                playing[0]=True
                calls.append(Path(filename).name)
                if Path(filename).name=='tts.wav':
                    status_played.set()
                    time.sleep(.04)
                playing[0]=False
            def render(text,destination):
                self.assertTrue(status_played.wait(2))
                wav(destination)
            rows=[];trace=TurnTrace(sink=rows.append)
            feedback=ProgressFeedback(speaker,delay=.01)
            with patch('winsound.PlaySound',side_effect=play),patch('jarvis.speech.windows_speak',side_effect=render):
                with trace.activate():
                    feedback.start(trace)
                    speaker.speak('Ответ готов.',before_playback=feedback.stop)
            feedback.stop();trace.finish()
            self.assertEqual(calls,['tts.wav','speech.wav'])
            self.assertLess(rows[0]['events_ms']['feedback_start'],rows[0]['events_ms']['answer_playback_start'])
            self.assertFalse(feedback.thread.is_alive())

    def test_stale_status_waiting_for_audio_lock_is_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);wav(path/'model.wav')
            speaker=Speaker(Settings(tts='windows'));speaker.status_directory=path
            trace=TurnTrace(sink=lambda _:None)
            feedback=ProgressFeedback(speaker,delay=.01)
            with patch('winsound.PlaySound') as play:
                with speaker.playback_lock:
                    with trace.activate(),measure('model','fake'):
                        feedback.start(trace)
                        time.sleep(.04)
                        feedback.cancelled.set()
                feedback.stop()
                play.assert_not_called()

    def test_missing_cache_never_calls_cloud_and_muted_never_plays(self):
        with tempfile.TemporaryDirectory() as folder:
            speaker=Speaker(Settings(tts='openrouter'));speaker.status_directory=Path(folder)
            with patch('jarvis.cloud_voice.OpenRouterVoice.synthesize') as cloud,patch('jarvis.speech.play_mp3') as play:
                self.assertFalse(speaker.play_status('model',lambda:True))
                cloud.assert_not_called();play.assert_not_called()
            wav(Path(folder)/'model.wav')
            speaker.settings=Settings(tts='windows');speaker.muted=True
            with patch('winsound.PlaySound') as play:
                self.assertFalse(speaker.play_status('model',lambda:True))
                play.assert_not_called()

    def test_voice_cache_changes_when_reference_contents_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reference.wav';path.write_bytes(b'voice-a')
            settings=Settings(tts='openrouter',voice_reference=str(path))
            first=cache_directory(settings)
            path.write_bytes(b'voice-b')
            self.assertNotEqual(first,cache_directory(settings))

    def test_stop_after_synthesis_does_not_play_and_response_is_not_reexecuted(self):
        with tempfile.TemporaryDirectory() as folder:
            stopped=[False]; calls=[]; rows=[]
            class Agent:
                def respond(self,text):
                    calls.append('respond');return Turn('Готово.')
            speaker=Speaker(Settings(tts='windows',progress_enabled=False))
            def render(text,path):
                wav(path);stopped[0]=True
            with patch('jarvis.speech.windows_speak',side_effect=render),patch('winsound.PlaySound') as play:
                run_turn(Agent(),speaker,'команда',trace=TurnTrace(sink=rows.append),stopped=lambda:stopped[0])
                play.assert_not_called()
            self.assertEqual(calls,['respond'])
            self.assertEqual(rows[0]['status'],'cancelled')


if __name__=='__main__':
    unittest.main()
