"""Regression tests for real document packages, turn references and audio boundaries."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import wave
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis.assistant import Assistant, local_intent
from jarvis.cloud_voice import CloudVoice, OpenRouterVoice, request_audio
from jarvis.config import Settings
from jarvis.conversation import Conversation
from jarvis.documents import Documents, W
from jarvis.http import ServiceError
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry
from jarvis.voice import VoiceInput, WakeGate
from jarvis.speech import Speaker
from test_assistant import FakeKernel, FakeModel, tool_call


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kernel = FakeKernel()
        self.settings = Settings(document_roots=(self.root,))
        self.documents = Documents(self.settings, self.kernel)

    def template(self):
        result = self.documents.create('Initial', filename='template.docx', open_after=False)
        path = Path(result['path'])
        with zipfile.ZipFile(path) as z:
            package = {n: z.read(n) for n in z.namelist()}
        package['word/document.xml'] = ('''<w:document xmlns:w="%s"
          xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
          xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14"><w:body>
          <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{{фи</w:t></w:r><w:r><w:t>о}} / {{фио}}</w:t></w:r></w:p>
          <w:tbl><w:tr><w:tc><w:p><w:r><w:t>{{город}}</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
          <w:sdt><w:sdtPr><w:tag w:val="phone"/><w:showingPlcHdr/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>Телефон</w:t></w:r></w:p></w:sdtContent></w:sdt>
          </w:body></w:document>''' % W[1:-1]).encode('utf-8')
        package['word/header1.xml'] = ('<w:hdr xmlns:w="%s"><w:p><w:r><w:t>{{город}}</w:t></w:r></w:p></w:hdr>' % W[1:-1]).encode()
        with zipfile.ZipFile(path, 'w') as z:
            for n, data in package.items():
                z.writestr(n, data)
        return path

    def test_fill_split_runs_table_header_and_content_control_without_changing_source(self):
        source = self.template()
        old_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        info = self.documents.read(str(source))
        self.assertEqual(info['placeholders'], ['{{город}}', '{{фио}}'])
        self.assertEqual(info['content_controls'], ['phone'])
        result = self.documents.fill(str(source), {'{{фио}}': 'Иван & Пётр', '{{город}}': 'Дзержинск'},
                                     {'phone': '+7 000 000 00 00'}, open_after=False)
        self.assertEqual(result['replacements'], {'{{фио}}': 2, '{{город}}': 2})
        self.assertEqual(result['fields'], {'phone': 1})
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), old_hash)
        copied = self.documents.read(result['path'])
        self.assertIn('Иван & Пётр / Иван & Пётр', copied['text'])
        self.assertIn('+7 000 000 00 00', copied['text'])
        with zipfile.ZipFile(result['path']) as z:
            raw = z.read('word/document.xml')
            self.assertIn(b'xmlns:w14=', raw)
            self.assertIn(b'mc:Ignorable="w14"', raw)
            root = ET.fromstring(raw)
            self.assertIsNotNone(root.find('.//' + W + 'b'))
            self.assertIsNone(root.find('.//' + W + 'showingPlcHdr'))

    def test_missing_field_is_atomic_and_inserted_values_are_literal(self):
        source = self.template()
        before = set(self.documents.output.iterdir())
        with self.assertRaisesRegex(ServiceError, 'Не найдены'):
            self.documents.fill(str(source), {'missing': 'value'})
        self.assertEqual(set(self.documents.output.iterdir()), before)
        result = self.documents.fill(str(source), {'{{фио}}': '{{город}}', '{{город}}': 'Дзержинск'}, open_after=False)
        self.assertIn('{{город}} / {{город}}', self.documents.read(result['path'])['text'])

    def test_semantic_fields_fill_both_text_placeholders_and_content_controls(self):
        source = self.template()
        result = self.documents.fill(str(source), fields={'ФИО': 'Тестовый Пользователь', 'город': 'Дзержинск', 'phone': '123'}, open_after=False)
        self.assertEqual(result['fields'], {'ФИО': 2, 'город': 2, 'phone': 1})
        self.assertEqual(self.documents.read(result['path'])['placeholders'], [])

    def test_creation_escapes_xml_never_overwrites_and_launches_only_native_operation(self):
        result = self.documents.create('А < Б & В\nВторая строка', 'report.docx', title='Заголовок')
        self.assertTrue(Path(result['path']).is_file())
        self.assertEqual(self.documents.read(result['path'])['text'], 'Заголовок\nА < Б & В\nВторая строка')
        self.assertEqual(self.kernel.calls, [('open_document', {'path': result['path']})])
        with self.assertRaisesRegex(ServiceError, 'уже существует'):
            self.documents.create('other', 'report.docx')
        for filename in ('../outside.docx', 'C:\\escape.docx', 'CON.docx', 'a:b.docx'):
            with self.assertRaises(ServiceError):
                self.documents.create('test', filename)

    def test_paths_and_bad_packages_are_bounded(self):
        for path in ('../outside.docx', __file__, 'missing.docx'):
            with self.assertRaises(ServiceError):
                self.documents.read(path)
        bad = self.root / 'bad.docx'
        bad.write_text('not a zip')
        with self.assertRaises(ServiceError):
            self.documents.read(str(bad))
        with zipfile.ZipFile(bad, 'w') as z:
            z.writestr('word/document.xml', b'<!DOCTYPE x [<!ENTITY y "bad">]><x/>')
        with self.assertRaises(ServiceError):
            self.documents.read(str(bad))

    def test_failed_open_still_reports_created_file_without_retrying_creation(self):
        self.kernel.call = lambda *_a, **_kw: (_ for _ in ()).throw(ServiceError('unavailable'))
        result = self.documents.create('saved', 'saved.docx')
        self.assertEqual(result['status'], 'created')
        self.assertEqual(result['open_error'], 'unavailable')
        self.assertTrue(Path(result['path']).is_file())

    def test_document_write_grant_continues_only_selected_template(self):
        source = self.template()
        other = self.documents.create('other', 'other.docx', open_after=False)['path']
        registry = ToolRegistry(self.kernel, LocalServices(self.settings, self.kernel))
        self.addCleanup(registry.close)
        registry.begin_turn('Заполни шаблон документа')
        registry.execute('read_document', {'path': str(source)})
        registry.begin_turn('ФИО Иван, город Дзержинск')
        self.assertFalse(registry.execute('fill_document', {'path': other, 'replacements': {'other': 'bad'}})['ok'])
        self.assertFalse(registry.execute('create_document', {'text': 'unsolicited'})['ok'])
        self.assertTrue(registry.execute('fill_document', {'path': str(source), 'replacements': {'{{фио}}': 'Иван'}, 'open_after': False})['ok'])
        registry.begin_turn('Прочитай документ, только покажи')
        self.assertFalse(registry.execute('fill_document', {'path': str(source), 'replacements': {'{{фио}}': 'other'}})['ok'])


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.kernel = FakeKernel()
        self.registry = ToolRegistry(self.kernel, LocalServices(Settings(), self.kernel))
        self.addCleanup(self.registry.close)

    def test_app_alias_and_offline_project_conversation_do_not_repeat_launch(self):
        for name in ('вс код', 'ви эс код', 'VS Code', 'visual studio code'):
            self.assertEqual(local_intent('открой ' + name), ('open_application', {'app_id': 'vscode'}))
        assistant = Assistant(self.registry)
        # FakeKernel does not echo app_id; emulate a native launch response.
        with patch.object(self.kernel, 'call', return_value={'result': {'app_id': 'vscode', 'status': 'process_created'}}) as launch:
            self.assertIn('новым проектом', assistant.respond('открой вс код').text)
            self.assertIn('идею', assistant.respond('да').text)
            self.assertEqual(launch.call_count, 1)
            self.assertNotIn('новым проектом?', assistant.respond('открой вс код').text)
        self.assertEqual(len(assistant.history), 6)

    def test_direct_app_launch_precedes_single_model_reply_and_punctuation_survives(self):
        model = FakeModel({'content': 'Открываю редактор, сэр. Новый проект?'})
        turn = Assistant(self.registry, model).respond('открой вс код')
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(self.kernel.calls, [('launch_app', {'app_id': 'vscode'})])
        self.assertEqual(model.calls[0][-1]['role'], 'tool')
        self.assertEqual(local_intent('Напиши Ивану в телеграмме: Привет!!!')[1]['text'], 'Привет!!!')

    def test_desktop_changes_require_current_request_and_volume_uses_fresh_value(self):
        self.registry.begin_turn('Привет')
        self.assertFalse(self.registry.execute('minimize_windows', {})['ok'])
        self.registry.begin_turn('Сделай тише')
        with patch.object(self.kernel, 'call', side_effect=[{'result': {'volume_percent': 7}}, {'result': {'volume_percent': 0}}]) as call:
            self.assertTrue(self.registry.execute('adjust_volume', {'delta': -10})['ok'])
            self.assertEqual(call.call_args.args, ('set_volume', {'percent': 0}))

    def test_history_contains_successful_tool_reference_for_real_model_followup(self):
        model = FakeModel(tool_call('open_application', {'app_id': 'vscode'}),
                          {'content': 'Редактор запускается. Мы работаем над новым проектом?'},
                          {'content': 'Что хочешь сделать?'})
        assistant = Assistant(self.registry, model)
        assistant.respond('открой вс код')
        result = assistant.respond('да')
        self.assertEqual(result.text, 'Что хочешь сделать?')
        self.assertEqual(len(self.kernel.calls), 1)
        self.assertIn('Мы работаем', model.calls[-1][-2]['content'])

    def test_recipient_pronoun_and_ambiguity_continue_exact_original_request(self):
        assistant = Assistant(self.registry)
        with patch.object(self.registry.telegram, 'open', return_value={'recipient': {'id': '100', 'name': 'Иван'}}), \
             patch.object(self.registry.telegram, 'send', return_value={'status': 'sent', 'recipient': {'id': '100', 'name': 'Иван'}}) as send:
            assistant.respond('открой диалог с Иваном в телеграмме')
            assistant.respond('напиши ему: Буду через десять минут')
            self.assertEqual(send.call_args.args[:2], ('100', 'Буду через десять минут'))
        conversation = Conversation()
        candidates = [{'id': '101', 'name': 'Иван Первый'}, {'id': '102', 'name': 'Иван Второй'}]
        conversation.observe('send_message', {'platform': 'telegram', 'recipient': 'Иван', 'text': 'Привет'},
                             {'ok': True, 'result': {'status': 'ambiguous', 'candidates': candidates}}, True)
        self.assertEqual(conversation.followup('второй'), ('send_message', {'platform': 'telegram', 'recipient': '102', 'text': 'Привет'}, True))
        conversation.context['dialog'] = {'platform': 'telegram', 'recipient': '100'}
        self.assertIsNone(conversation.followup('напиши маме в телеграмме: Привет'))
        self.assertIsNone(conversation.followup('не отправляй ему ничего'))

    def test_video_selection_uses_cached_order_without_another_search(self):
        self.registry.youtube.last_results = {'query': 'котики', 'videos': [
            {'video_id': 'abcdefghijk', 'title': 'Первое', 'url': 'https://youtube.com/watch?v=abcdefghijk'},
            {'video_id': 'ABCDEFGHIJK', 'title': 'Второе', 'url': 'https://youtube.com/watch?v=ABCDEFGHIJK'}]}
        assistant = Assistant(self.registry)
        assistant.conversation.context['youtube_query'] = 'котики'
        with patch.object(self.registry.youtube, 'fetch', side_effect=AssertionError('must not search')):
            result = assistant.respond('включи второе')
        self.assertIn('Второе', result.text)
        self.assertEqual(self.kernel.calls[-1], ('open_url', {'url': 'https://youtube.com/watch?v=ABCDEFGHIJK'}))

    def test_context_expires_and_network_failure_keeps_history_without_replay(self):
        assistant = Assistant(self.registry, FakeModel(ServiceError('HTTP 401: invalid')))
        assistant.respond('открой ютуб')
        assistant.respond('привет')
        self.assertEqual(len(assistant.client.calls), 1)
        self.assertEqual(len(self.kernel.calls), 1)
        self.assertEqual(len(assistant.history), 4)
        assistant.conversation.context['dialog'] = {'platform': 'telegram', 'recipient': '123'}
        assistant.conversation.updated_at = time.monotonic() - 1000
        self.assertIsNone(assistant.conversation.followup('напиши ему: привет'))
        assistant.respond('/reset')
        self.assertEqual(assistant.history, [])


class CloudVoiceTests(unittest.TestCase):
    def test_recorded_original_is_used_only_for_a_whole_matching_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            wav=root/'clip.wav'
            wav.write_bytes(b'RIFF'+b'\x00'*100)
            manifest=root/'samples.json'
            manifest.write_text(json.dumps({'samples':{'К вашим услугам, сэр.':'clip.wav'}},ensure_ascii=False),encoding='utf-8')
            speaker=Speaker(Settings(tts='openrouter',voice_samples=str(manifest),tts_streaming=False))
            with patch('winsound.PlaySound') as play, patch('jarvis.cloud_voice.OpenRouterVoice.synthesize') as synth, patch('jarvis.speech.play_mp3'):
                speaker.speak('К ВАШИМ УСЛУГАМ, СЭР!')
                self.assertEqual(play.call_count,1)
                synth.assert_not_called()
                speaker.speak('К вашим услугам, сэр. Открываю документ.')
                self.assertEqual(synth.call_count,1)
                self.assertEqual(play.call_count,1)

    def test_recorded_response_manifest_cannot_escape_its_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/'pack';folder.mkdir()
            outside=root/'outside.wav';outside.write_bytes(b'RIFF')
            manifest=folder/'samples.json'
            manifest.write_text(json.dumps({'samples':{'Да, сэр.':'../outside.wav'}}),encoding='utf-8')
            with patch('winsound.PlaySound') as play:
                self.assertFalse(Speaker(Settings(voice_samples=str(manifest)))._play_recording('Да, сэр.'))
                play.assert_not_called()

    def test_tts_recovers_after_cooldown_without_replaying_the_failed_request(self):
        speaker = Speaker(Settings(tts='openrouter', local_speaker='eugene',tts_streaming=False))
        with patch('jarvis.cloud_voice.OpenRouterVoice.synthesize', side_effect=[ServiceError('offline'), None]) as synth, \
             patch('jarvis.tts_local.LocalVoice') as local, patch('winsound.PlaySound'), \
             patch('jarvis.speech.play_mp3') as play:
            with patch('jarvis.speech.time.monotonic', return_value=10):
                speaker.speak('Первая фраза')
            with patch('jarvis.speech.time.monotonic', return_value=20):
                speaker.speak('Вторая фраза')
            with patch('jarvis.speech.time.monotonic', return_value=80):
                speaker.speak('Третья фраза')
        self.assertEqual(synth.call_count, 2)
        self.assertEqual(local.return_value.save.call_count, 2)
        self.assertEqual(play.call_count, 1)
    def test_openrouter_transcription_and_reference_voice_use_existing_key(self):
        import base64
        settings = Settings(api_key='fake-router-key')
        captured = {}
        def http(url, **kwargs):
            captured.update(url=url, **kwargs)
            return {'text': 'Открой VS Code'}
        result = OpenRouterVoice(settings, http=http).transcribe(b'\x01\x00' * 1600, 16000)
        self.assertEqual(result, 'Открой VS Code')
        self.assertTrue(captured['url'].endswith('/audio/transcriptions'))
        self.assertEqual(captured['headers']['Authorization'], 'Bearer fake-router-key')
        self.assertEqual(captured['data']['language'], 'ru')
        with wave.open(io.BytesIO(base64.b64decode(captured['data']['input_audio']['data']))) as wav:
            self.assertEqual(wav.getnframes(), 1600)
        with tempfile.TemporaryDirectory() as tmp:
            reference, output = Path(tmp) / 'sample.wav', Path(tmp) / 'output.mp3'
            reference.write_bytes(b'RIFF' + b'\x00' * 200)
            settings = replace(settings, voice_reference=str(reference), voice_reference_text='Образец речи')
            def audio_transport(url, **kwargs):
                captured.update(url=url, **kwargs)
                return b'ID3' + b'\x00' * 200
            OpenRouterVoice(settings, audio_transport=audio_transport).synthesize('На связи.', output)
            body = json.loads(captured['data'])
            self.assertEqual(body['model'], 'fish-audio/s2.1-pro')
            self.assertEqual(body['input_references'][1]['text'], 'Образец речи')
            self.assertEqual(base64.b64decode(body['input_references'][0]['input_audio']['data']), reference.read_bytes())
            self.assertNotIn('voice', body)
            self.assertTrue(output.is_file())

    def test_refinement_preserves_quoted_wake_name_and_recovers_from_outage(self):
        voice = VoiceInput.__new__(VoiceInput)
        voice.settings, voice.sample_rate, voice.cloud_retry_at = Settings(asr='openrouter'), 16000, 0
        with patch('jarvis.cloud_voice.OpenRouterVoice.transcribe', return_value='Напиши ему: Привет, Джарвис!'):
            self.assertEqual(voice._refine('локальная расшифровка', b'audio'), 'Напиши ему: Привет, Джарвис!')
        with patch('jarvis.cloud_voice.OpenRouterVoice.transcribe', return_value='  Джарвис, открой VS Code.'):
            self.assertEqual(voice._refine('открой вс код', b'audio'), 'открой VS Code.')
        with patch('jarvis.cloud_voice.OpenRouterVoice.transcribe', side_effect=ServiceError('HTTP 503')) as call:
            self.assertEqual(voice._refine('локальная команда', b'audio'), 'локальная команда')
            self.assertEqual(voice._refine('ещё команда', b'audio'), 'ещё команда')
            self.assertEqual(call.call_count, 1)

    def test_transcription_request_contains_real_wav_and_no_background_recording(self):
        captured = {}
        def transport(url, **kwargs):
            captured.update(url=url, **kwargs)
            return json.dumps({'text': 'Джарвис, открой VS Code.'}, ensure_ascii=False).encode()
        settings = Settings(elevenlabs_api_key='fake-secret')
        text = CloudVoice(settings, transport).transcribe(b'\x01\x00' * 1600, 16000)
        self.assertIn('VS Code', text)
        boundary = captured['headers']['Content-Type'].split('boundary=')[1].encode()
        wav_part = captured['data'].split(b'Content-Type: audio/wav\r\n\r\n')[1].split(b'\r\n--' + boundary)[0]
        with wave.open(io.BytesIO(wav_part)) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getnframes()), (16000, 1, 1600))
        self.assertIn(b'scribe_v2', captured['data'])
        self.assertNotIn('fake-secret', repr(settings))

    def test_cloud_voice_uses_selected_id_and_rejects_invalid_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'voice.mp3'
            settings = Settings(elevenlabs_api_key='fake', elevenlabs_voice_id='SelectedVoice12345')
            seen = {}
            def transport(url, **kwargs):
                seen.update(url=url, **kwargs)
                return b'ID3' + b'\x00' * 100
            CloudVoice(settings, transport).synthesize('Системы в норме.', path)
            self.assertIn('/SelectedVoice12345?', seen['url'])
            self.assertEqual(json.loads(seen['data'])['text'], 'Системы в норме.')
            with self.assertRaises(ServiceError):
                CloudVoice(settings, lambda *_a, **_kw: b'{"error":"not audio"}').synthesize('test', path)
            with self.assertRaises(ServiceError):
                CloudVoice(replace(settings, elevenlabs_voice_id='')).synthesize('test', path)

    def test_secret_free_http_errors_and_no_automatic_retry(self):
        error = urllib.error.HTTPError('https://api.elevenlabs.io', 401, 'fake-secret', {}, io.BytesIO(b'fake-secret'))
        with patch('urllib.request.urlopen', side_effect=error) as call:
            with self.assertRaisesRegex(ServiceError, 'HTTP 401') as raised:
                request_audio('https://api.elevenlabs.io/v1/speech-to-text', data=b'x', headers={'xi-api-key': 'fake-secret'})
        self.assertNotIn('fake-secret', str(raised.exception))
        self.assertEqual(call.call_count, 1)

    def test_conversation_timer_starts_after_response_and_can_be_put_to_sleep(self):
        voice = VoiceInput.__new__(VoiceInput)
        voice.gate, voice.settings = WakeGate(), Settings(conversation_seconds=40)
        with patch('jarvis.voice.time.monotonic', return_value=100):
            voice.after_response()
        self.assertEqual(voice.gate.accept('да новый проект', now=135), 'да новый проект')
        self.assertIsNone(voice.gate.accept('не обращаюсь к помощнику', now=136))
        voice.gate.resume(40, now=200)
        self.assertIsNone(voice.gate.accept('давно молчали', now=241))
        voice.gate.resume(40)
        voice.sleep()
        self.assertFalse(voice.gate.active())

    def test_stream_closes_before_cloud_request_and_idle_speech_is_not_sent(self):
        state = {'open': False}
        chunks = [b'\x01\x00' * 50, b'\x02\x00' * 50]
        class Stream:
            def __init__(self, **kwargs):
                self.callback = kwargs['callback']
            def __enter__(self):
                state['open'] = True
                for chunk in chunks:
                    self.callback(chunk, 50, None, None)
            def __exit__(self, *_):
                state['open'] = False
        class Recognizer:
            count = 0
            def AcceptWaveform(self, _):
                self.count += 1
                return True
            def Result(self):
                return json.dumps({'text': 'фоновая речь' if self.count == 1 else 'джарвис открой вс код'})
        voice = VoiceInput.__new__(VoiceInput)
        from collections import deque
        voice.model, voice.sample_rate, voice.device, voice.gate, voice.messages = object(), 16000, None, WakeGate(), deque()
        def refine(command, pcm):
            self.assertFalse(state['open'])
            self.assertEqual(pcm, chunks[1])
            return command
        voice._refine = refine
        with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Stream),
                        vosk=SimpleNamespace(KaldiRecognizer=lambda *_: Recognizer())):
            self.assertEqual(voice.next_command(), 'открой вс код')


if __name__ == '__main__':
    unittest.main()
