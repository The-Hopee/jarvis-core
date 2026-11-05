import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.assistant import Assistant, local_intent
from jarvis.config import Settings, read_env
from jarvis.http import ServiceError
from jarvis.http import request_json
from jarvis.ipc import KernelClient, KernelError
from jarvis.openrouter import OpenRouterClient
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry, normalize_url
from jarvis.voice import WakeGate
from jarvis.speech import Speaker

ROOT = Path(__file__).resolve().parents[1]


class FakeKernel:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == 'get_location':
            raise KernelError('location_unavailable', 'Disabled')
        return {'timestamp_utc': '2026-11-04T10:00:00Z', 'result': {'status': 'shell_accepted', 'method': method}}


def tool_call(name, arguments, call_id='call-1'):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}


class FakeModel:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def complete(self, messages, tools, **kwargs):
        self.calls.append(json.loads(json.dumps(messages)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.kernel = FakeKernel()
        self.services = LocalServices(Settings(), self.kernel)
        self.registry = ToolRegistry(self.kernel, self.services)

    def test_tool_roundtrip_returns_correlated_tool_result(self):
        model = FakeModel(tool_call('open_website', {'target': 'ютуб'}), {'content': 'Открываю YouTube.'})
        turn = Assistant(self.registry, model).respond('джарвис, открой ютуб')
        self.assertEqual(turn.text, 'Открываю YouTube.')
        self.assertEqual(self.kernel.calls, [('open_url', {'url': 'https://www.youtube.com/'})])
        message = model.calls[1][-1]
        self.assertEqual(message['role'], 'tool')
        self.assertEqual(message['tool_call_id'], 'call-1')
        self.assertTrue(json.loads(message['content'])['ok'])

    def test_model_failure_does_not_replay_action(self):
        model = FakeModel(tool_call('open_website', {'target': 'youtube'}), ServiceError('offline'))
        turn = Assistant(self.registry, model).respond('открой ютуб')
        self.assertEqual(len(self.kernel.calls), 1)
        self.assertIn('браузеру', turn.text)
        self.assertEqual(turn.warning, 'offline')

    def test_duplicate_actions_are_not_executed_twice(self):
        model = FakeModel(tool_call('open_website', {'target': 'youtube'}),
                          tool_call('open_website', {'target': 'youtube'}, 'call-2'), {'content': 'Готово'})
        Assistant(self.registry, model).respond('открой youtube')
        self.assertEqual(len(self.kernel.calls), 1)

    def test_tool_loop_stops_at_a_bounded_number_of_model_requests(self):
        model = FakeModel(*(tool_call('unknown_tool', {}, f'call-{n}') for n in range(6)))
        turn = Assistant(self.registry, model).respond('Привет')
        self.assertEqual(len(model.calls), 6)
        self.assertIn('лимит', turn.warning)
        self.assertEqual(self.kernel.calls, [])

    def test_bad_tool_arguments_return_error_and_no_side_effect(self):
        for arguments in ({'target': 'youtube', 'command': 'calc.exe'}, {'target': []}, [], None):
            result = self.registry.execute('open_website', arguments)
            self.assertFalse(result['ok'])
        self.assertFalse(self.registry.execute('execute_shell', {'command': 'whoami'})['ok'])
        self.assertEqual(self.kernel.calls, [])

    def test_malformed_batch_never_partially_executes(self):
        first = tool_call('open_website', {'target': 'youtube'})
        first['tool_calls'].append({'id': 'broken', 'type': 'shell'})
        # Use a free-form user request so offline fallback also causes no action.
        Assistant(self.registry, FakeModel(first)).respond('Привет')
        self.assertEqual(self.kernel.calls, [])

    def test_missing_key_fallback_and_native_error(self):
        turn = Assistant(self.registry).respond('джарвис, открой телеграмм')
        self.assertEqual(self.kernel.calls[-1], ('launch_app', {'app_id': 'telegram'}))
        with patch.object(self.kernel, 'call', side_effect=KernelError('app_not_found', 'Приложение отсутствует')):
            turn = Assistant(self.registry).respond('открой телеграмм')
        self.assertIn('Не удалось', turn.text)
        self.assertFalse(turn.tools[0]['output']['ok'])

    def test_wake_word_and_followup_expiry(self):
        gate = WakeGate(8)
        self.assertIsNone(gate.accept('открой ютуб', now=1))
        self.assertEqual(gate.accept('джарвис', now=2), '')
        self.assertEqual(gate.accept('открой ютуб', now=3), 'открой ютуб')
        self.assertIsNone(gate.accept('какая погода', now=4))
        gate.accept('джарвис', now=10)
        self.assertIsNone(gate.accept('открой сайт', now=19))
        self.assertEqual(gate.accept('джарвис состояние машины', now=20), 'состояние машины')
        self.assertEqual(local_intent('состоянии машины'), ('get_system_status', {}))

    def test_openrouter_request_contract_and_secret_free_errors(self):
        captured = {}
        def http(url, **kwargs):
            captured.update(kwargs)
            return {'choices': [{'message': {'role': 'assistant', 'content': 'Привет'}}]}
        client = OpenRouterClient('fake-key-for-test', 'test-model', http)
        self.assertEqual(client.complete([{'role': 'user', 'content': 'Привет'}], self.registry.definitions())['content'], 'Привет')
        self.assertEqual(captured['headers']['Authorization'], 'Bearer fake-key-for-test')
        self.assertNotIn('parallel_tool_calls', captured['data'])
        self.assertTrue(captured['data']['tools'])
        self.assertNotIn('fake-key-for-test', repr(Settings(api_key='fake-key-for-test')))

    def test_url_normalization(self):
        self.assertEqual(normalize_url('ютуб'), 'https://www.youtube.com/')
        self.assertIn('xn--', normalize_url('пример.рф/привет мир'))
        self.assertIn('%20', normalize_url('example.com/a b'))
        for target in ['file:///C:/Windows/notepad.exe', 'javascript:alert(1)', 'https://user:password@example.com', 'example.com\ncmd', 'https://', 'https://a b.com', 'ftp://example.com']:
            with self.assertRaises(ValueError, msg=target):
                normalize_url(target)

    def test_env_is_literal_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / '.env'
            file.write_text('OPENROUTER_API_KEY="literal$(not-executed)"\n# comment\nJARVIS_CITY=Москва\n', encoding='utf-8')
            values = read_env(file)
            self.assertEqual(values['OPENROUTER_API_KEY'], 'literal$(not-executed)')
            self.assertEqual(values['JARVIS_CITY'], 'Москва')

    def test_tts_service_failure_falls_back_to_windows(self):
        async def failed_edge(*_args):
            raise RuntimeError('offline')
        speaker = Speaker(Settings())
        with patch('jarvis.speech.edge_save', failed_edge), patch('jarvis.speech.windows_speak') as windows:
            speaker.speak('Проверка голоса')
            speaker.speak('Второй ответ')
        self.assertEqual(windows.call_count, 2)
        self.assertFalse(speaker.edge_healthy)


class ServiceTests(unittest.TestCase):
    def test_places_outage_returns_explicit_map_fallback(self):
        def http(*args, **kwargs):
            raise ServiceError('offline')
        services = LocalServices(Settings(latitude=55.75, longitude=37.61), FakeKernel(), http)
        result = services.places()
        self.assertEqual(result['lookup_status'], 'unavailable')
        self.assertEqual(result['places'], [])
        self.assertTrue(result['search_url'].startswith('https://yandex.ru/maps/?'))

    def test_ip_fallback_discards_ip_and_reports_approximation(self):
        def http(url, **kwargs):
            return {'latitude': 55.75, 'longitude': 37.61, 'city': 'Москва', 'ip': 'sensitive-ip'}
        location = LocalServices(Settings(), FakeKernel(), http).location()
        self.assertTrue(location['approximate'])
        self.assertEqual(location['source'], 'ip_city')
        self.assertNotIn('ip', location)

    def test_configured_coordinates_skip_network_location(self):
        kernel = FakeKernel()
        services = LocalServices(Settings(latitude=55.75, longitude=37.61), kernel,
                                 lambda *_args, **_kwargs: self.fail('No geolocation network request expected'))
        self.assertEqual(services.location()['source'], 'configured_coordinates')
        self.assertEqual(kernel.calls, [])

    def test_weather_fetch_uses_live_data_and_cache(self):
        requests = []
        def http(url, **kwargs):
            requests.append(url)
            return {'current': {'temperature_2m': -2, 'time': '2026-11-04T10:00'}, 'timezone': 'Europe/Moscow'}
        services = LocalServices(Settings(latitude=55.75, longitude=37.61), FakeKernel(), http)
        first, second = services.weather(), services.weather()
        self.assertEqual(first['current']['temperature_2m'], -2)
        self.assertEqual(len(requests), 1)
        self.assertEqual(first, second)

    def test_places_are_real_linked_results_with_precision_note(self):
        def http(url, **kwargs):
            return {'elements': [{'type': 'node', 'id': 123, 'lat': 55.7501, 'lon': 37.61,
                                  'tags': {'name': 'Парк', 'opening_hours': 'unknown'}}]}
        services = LocalServices(Settings(latitude=55.75, longitude=37.61), FakeKernel(), http)
        result = services.places()
        self.assertEqual(result['places'][0]['map_url'], 'https://www.openstreetmap.org/node/123')
        self.assertIn('не проверены', result['note'])

    def test_location_failure_explains_city_override(self):
        def http(*args, **kwargs):
            raise ServiceError('offline')
        with self.assertRaisesRegex(ServiceError, 'JARVIS_CITY'):
            LocalServices(Settings(), FakeKernel(), http).location()


class RealIPCTests(unittest.TestCase):
    def test_timeout_closes_only_its_unresponsive_child(self):
        child = ROOT / 'build/bin/Release/jarvis-test-child.exe'
        kernel = KernelClient(child, timeout=0.05)
        with self.assertRaisesRegex(KernelError, 'не повторялась'):
            kernel.call('ping')
        self.assertTrue(kernel._closed)
        self.assertIsNotNone(kernel.process.poll())

    def test_reuses_process_and_correlates_serialized_threads(self):
        with KernelClient(Settings().executable) as kernel:
            pid = kernel.process.pid
            results, failures = [], []
            def call():
                try:
                    results.append(kernel.call('ping'))
                except Exception as exc:
                    failures.append(exc)
            threads = [threading.Thread(target=call) for _ in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertEqual(failures, [])
            self.assertEqual(len(results), 6)
            self.assertEqual(len({result['id'] for result in results}), 6)
            self.assertEqual(kernel.process.pid, pid)
            with self.assertRaises(KernelError):
                kernel.call('does-not-exist')
            self.assertTrue(kernel.call('ping')['ok'])
        self.assertIsNotNone(kernel.process.poll())

    def test_broken_child_is_not_restarted_or_replayed(self):
        kernel = KernelClient(Settings().executable, timeout=0.3)
        kernel.process.kill()
        kernel.process.wait(timeout=3)
        with self.assertRaises(KernelError):
            kernel.call('ping')
        self.assertTrue(kernel._closed)

    def test_http_tool_cycle_reaches_real_native_metrics(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                if len(requests) == 1:
                    message = tool_call('get_system_status', {})
                else:
                    message = {'role': 'assistant', 'content': 'Метрики компьютера получены.'}
                raw = json.dumps({'choices': [{'message': message}]}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def transport(_url, **kwargs):
                # The host may configure an HTTP proxy even for loopback traffic.
                local_open = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
                with patch('urllib.request.urlopen', local_open):
                    return request_json(f'http://127.0.0.1:{server.server_port}/chat/completions', **kwargs)
            with KernelClient(Settings().executable) as kernel:
                registry = ToolRegistry(kernel, LocalServices(Settings(), kernel))
                client = OpenRouterClient('local-test-key', 'test-model', transport)
                turn = Assistant(registry, client).respond('Прочитай свежие показатели компьютера и оцени их')
            self.assertEqual(turn.warning, '', turn.warning)
            self.assertEqual(turn.text, 'Метрики компьютера получены.')
            self.assertEqual(len(requests), 2)
            tool_message = requests[1]['messages'][-1]
            metrics = json.loads(tool_message['content'])['result']['metrics']
            self.assertGreater(metrics['memory']['physical_total_bytes'], 0)
            self.assertEqual(tool_message['tool_call_id'], 'call-1')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
