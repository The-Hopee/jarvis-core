import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

import av
import numpy as np

from jarvis.audio_stream import decode_mp3,play_stream,PartialSpeechError
from jarvis.cloud_voice import stream_audio
from jarvis.config import Settings
from jarvis.speech import Speaker
from jarvis.telemetry import TurnTrace


def mp3():
    target=io.BytesIO()
    with av.open(target,mode='w',format='mp3') as output:
        stream=output.add_stream('mp3',rate=24000)
        stream.layout='mono'
        for start in range(0,24000,2400):
            data=(np.sin(np.arange(start,start+2400)*2*np.pi*220/24000)*8000).astype('int16').reshape(1,-1)
            frame=av.AudioFrame.from_ndarray(data,format='s16',layout='mono')
            frame.sample_rate=24000
            for packet in stream.encode(frame):output.mux(packet)
        for packet in stream.encode(None):output.mux(packet)
    return target.getvalue()


class StreamingTests(unittest.TestCase):
    def test_real_mp3_decoder_yields_pcm_before_input_complete_and_handles_id3(self):
        raw=mp3();received=[0]
        def chunks():
            for offset in range(0,len(raw),73):
                received[0]+=min(73,len(raw)-offset)
                yield raw[offset:offset+73]
        pcm=decode_mp3(chunks())
        first=next(pcm)
        self.assertGreater(len(first),0)
        self.assertLess(received[0],len(raw))
        total=len(first)+sum(map(len,pcm))
        self.assertGreater(total,40000)
        self.assertLess(total,65000)

    def test_network_error_after_first_audio_does_not_restart_speech(self):
        raw=mp3();closed=[False]
        def data():
            try:
                yield raw[:len(raw)//2]
                raise RuntimeError('network interrupted')
            finally:closed[0]=True
        class Sink:
            def __init__(self,**kw):self.bytes=0
            def __enter__(self):return self
            def write(self,chunk):self.bytes+=len(chunk)
            def __exit__(self,*a):pass
        speaker=Speaker(Settings(tts='openrouter'))
        ready=[]
        with self.assertRaises(PartialSpeechError):
            play_stream(speaker,data(),before_playback=lambda:ready.append(True),sink_factory=Sink)
        self.assertEqual(ready,[True])
        self.assertTrue(closed[0])

    def test_stop_releases_network_and_aborts_audio(self):
        raw=mp3();stop=[False];closed=[False];aborted=[]
        def data():
            try:
                for n in range(0,len(raw),512):yield raw[n:n+512]
            finally:closed[0]=True
        class Sink:
            def __init__(self,**kw):pass
            def __enter__(self):return self
            def write(self,chunk):stop[0]=True
            def abort(self):aborted.append(True)
            def __exit__(self,*a):pass
        play_stream(Speaker(Settings(tts='openrouter')),data(),stopped=lambda:stop[0],sink_factory=Sink)
        self.assertTrue(closed[0]);self.assertEqual(aborted,[True])

    def test_json_audio_and_oversized_network_body_are_rejected_without_retry(self):
        class Response(io.BytesIO):
            headers={'Content-Type':'application/json'}
        with patch('urllib.request.urlopen',return_value=Response(b'{"secret":"not audio"}')) as request:
            with self.assertRaises(RuntimeError):list(stream_audio('https://example.test',data=b'',headers={}))
            self.assertEqual(request.call_count,1)
        class Audio(io.BytesIO):
            headers={'Content-Type':'audio/mpeg'}
        with patch('urllib.request.urlopen',return_value=Audio(b'x'*1024)):
            with self.assertRaises(RuntimeError):list(stream_audio('https://example.test',data=b'',headers={},max_bytes=100))

    def test_failed_partial_stream_does_not_enter_local_fallback(self):
        speaker=Speaker(Settings(tts='openrouter'))
        with patch('jarvis.audio_stream.play_stream',side_effect=PartialSpeechError('partial')),patch('jarvis.tts_local.LocalVoice') as fallback:
            speaker.speak('Полный ответ.')
            fallback.assert_not_called()

    def test_cancel_before_first_audio_does_not_open_output(self):
        with patch('sounddevice.RawOutputStream') as sink:
            play_stream(Speaker(Settings(tts='openrouter')),iter([mp3()]),before_playback=lambda:False)
            sink.assert_not_called()


if __name__=='__main__':unittest.main()
