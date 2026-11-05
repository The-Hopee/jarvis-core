"""Incremental MP3 decoding and bounded PCM playback with no full-file wait."""
from contextlib import closing
import time

from .telemetry import mark,measure


class PartialSpeechError(RuntimeError):
    """Some audio was already handed to the output. Do not repeat the answer."""


def decode_mp3(chunks, *, rate=24000, max_seconds=180):
    import av
    codec=av.CodecContext.create('mp3','r')
    resampler=av.AudioResampler(format='s16',layout='mono',rate=rate)
    samples=0
    prefix=bytearray()
    header_done=False

    def pcm(frame):
        nonlocal samples
        if not 8000<=frame.sample_rate<=192000 or len(frame.layout.channels)>2:
            raise RuntimeError('Неподдерживаемые параметры звукового потока')
        for out in resampler.resample(frame):
            samples+=out.samples
            if samples>rate*max_seconds:
                raise RuntimeError('Голосовой поток слишком длинный')
            yield out.to_ndarray().tobytes()

    try:
        for raw in chunks:
            if not header_done:
                prefix.extend(raw)
                if len(prefix)<10:
                    continue
                skip=0
                if prefix[:3]==b'ID3':
                    if any(n>=128 for n in prefix[6:10]):
                        raise RuntimeError('Некорректный заголовок MP3')
                    size=sum(prefix[6+i]<<(7*(3-i)) for i in range(4))
                    if size>1024*1024:
                        raise RuntimeError('Слишком большой заголовок MP3')
                    skip=10+size+(10 if prefix[5]&16 else 0)
                    if len(prefix)<skip:
                        continue
                raw=bytes(prefix[skip:]);prefix.clear();header_done=True
            for packet in codec.parse(raw):
                for frame in codec.decode(packet):
                    yield from pcm(frame)
        for packet in codec.parse(b''):
            for frame in codec.decode(packet):
                yield from pcm(frame)
        for frame in codec.decode(None):
            yield from pcm(frame)
        for frame in resampler.resample(None):
            samples+=frame.samples
            if samples>rate*max_seconds:
                raise RuntimeError('Голосовой поток слишком длинный')
            yield frame.to_ndarray().tobytes()
        if not samples:
            raise RuntimeError('Не удалось декодировать голосовой поток')
    except Exception as exc:
        if isinstance(exc,RuntimeError):
            raise
        raise RuntimeError('Ошибка декодирования голосового потока') from exc
    finally:
        close=getattr(chunks,'close',None)
        if close:
            close()


def play_stream(speaker, chunks, *, before_playback=None, stopped=None, sink_factory=None):
    """Stop progress before real output. A failed partial answer is never replayed."""
    import sounddevice
    stopped=stopped or (lambda:False)
    sink_factory=sink_factory or sounddevice.RawOutputStream
    rate=24000
    started=False
    with closing(decode_mp3(chunks,rate=rate)) as pcm:
        try:
            with measure('tts',speaker.settings.tts_model):
                first=next(pcm)
            mark('tts_ready')
            if stopped() or before_playback and before_playback() is False:
                return
            with speaker.playback_lock:
                if stopped():
                    return
                with sink_factory(samplerate=rate,channels=1,dtype='int16',blocksize=1024) as output:
                    with measure('playback','stream_pcm'):
                        mark('tts_streaming')
                        mark('answer_playback_start')
                        started=True
                        output.write(first)
                        for data in pcm:
                            if stopped():
                                output.abort()
                                return
                            output.write(data)
            mark('stream_complete')
        except Exception as exc:
            if started:
                mark('stream_interrupted')
                raise PartialSpeechError('Озвучивание прервано; полный ответ сохранён текстом.') from exc
            raise RuntimeError('Не удалось начать потоковое озвучивание') from exc
