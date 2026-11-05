import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.assistant import local_intent
from jarvis.coding import Orchestrator, git, validate_plan
from jarvis.coding_worker import WorkspaceTools, run_worker
from jarvis.http import ServiceError
from jarvis.media import YouTube, parse_videos


def call(name, args, identifier='one'):
    return {'content': None, 'tool_calls': [{'id': identifier, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args)}}]}


class Model:
    def __init__(self, *messages):
        self.messages = list(messages)
    def complete(self, *_args, **_kwargs):
        return self.messages.pop(0)


class MediaTests(unittest.TestCase):
    def test_spoken_video_request_is_not_a_domain(self):
        self.assertEqual(local_intent('Джарвис, открой на ютубе видео Егора Крида'),
                         ('open_youtube_video', {'query': 'Егора Крида'}))
        self.assertEqual(local_intent('включи клип Розовое вино на ютубе'),
                         ('open_youtube_video', {'query': 'Розовое вино'}))

    def test_resolves_new_and_old_video_renderers_and_skips_ads(self):
        state = {'contents': [
            {'adSlotRenderer': {'videoRenderer': {'videoId': 'AAAAAAAAAAA', 'title': {'simpleText': 'Реклама'}}}},
            {'videoRenderer': {'videoId': 'abcdefghijk', 'title': {'runs': [{'text': 'Видео один'}]}}},
            {'lockupViewModel': {'contentId': '123456789_-', 'contentType': 'LOCKUP_CONTENT_TYPE_VIDEO',
                                'metadata': {'lockupMetadataViewModel': {'title': {'content': 'Видео два'}}}}}]}
        html = 'var ytInitialData = ' + json.dumps(state) + ';'
        results = parse_videos(html)
        self.assertEqual([item['title'] for item in results], ['Видео один', 'Видео два'])
        class Kernel:
            calls = []
            def call(self, method, params):
                self.calls.append((method, params))
                return {'result': {'status': 'shell_accepted'}}
        kernel = Kernel()
        result = YouTube(kernel, fetch=lambda _url: html).open_video('описание', index=2)
        self.assertEqual(result['url'], 'https://www.youtube.com/watch?v=123456789_-')
        self.assertEqual(kernel.calls[0][1]['url'], result['url'])

    def test_challenge_page_never_fabricates_a_video(self):
        with self.assertRaises(ServiceError):
            parse_videos('<html>Please sign in</html>')


class CodingTests(unittest.TestCase):
    def test_worker_boundaries_reject_secrets_and_path_traversal(self):
        with tempfile.TemporaryDirectory(prefix='jarvis-scope-') as directory:
            tools = WorkspaceTools(directory, ['src/'], [])
            for path in ('../outside.py', '.env', '.git/config', 'C:/secret', 'src/../../a'):
                with self.assertRaises(ServiceError):
                    tools.path(path, write=True)
            with self.assertRaises(ServiceError):
                tools.path('other.py', write=True)
            tools.execute('write_file', {'path': 'src/example.py', 'content': 'VALUE = 1\n'})
            self.assertEqual((Path(directory) / 'src/example.py').read_text(), 'VALUE = 1\n')

    def test_plan_rejects_cycles(self):
        plan = {'summary': 'cycle', 'tasks': [
            {'id': 'a', 'goal': 'a', 'paths': ['a.py'], 'depends_on': ['b']},
            {'id': 'b', 'goal': 'b', 'paths': ['b.py'], 'depends_on': ['a']}]}
        with self.assertRaises(ServiceError):
            validate_plan(plan)

    def test_six_agents_run_in_bounded_waves_then_integrate_and_test(self):
        with tempfile.TemporaryDirectory(prefix='jarvis-coding-') as directory:
            root = Path(directory) / 'project'
            root.mkdir()
            subprocess.run(['git', 'init', '-b', 'main', str(root)], check=True, capture_output=True)
            (root / 'README.md').write_text('Test project', encoding='utf-8')
            git(root, 'add', 'README.md')
            git(root, 'commit', '-m', 'initial')
            original = git(root, 'rev-parse', 'HEAD')
            plan = {'summary': 'Six modules', 'tasks': [
                {'id':'module_'+str(i),'goal':'Create module','paths':['a'+str(i)+'.py'],'depends_on':[]} for i in range(6)]}
            planner = Model(call('submit_plan', plan))
            reviewer = Model(call('submit_review', {'approved': True, 'comments': 'Both modules and checks pass'}))
            barrier = threading.Barrier(2)
            def worker(task, workspace):
                barrier.wait(timeout=5)
                name = task['paths'][0]
                value = int(name[1])
                client = Model(call('write_file', {'path': name, 'content': f'VALUE = {value}\n'}), {'content': 'Implemented'})
                return run_worker({'workspace': str(workspace), 'task': task, 'checks': []}, client)
            job = Path(directory) / 'job'
            job.mkdir()
            checks = [[sys.executable, '-c', 'import a0,a1,a2,a3,a4,a5; assert a0.VALUE+a1.VALUE+a2.VALUE+a3.VALUE+a4.VALUE+a5.VALUE == 15']]
            with patch('jarvis.agent_limits.capacity',return_value=2):
                result = Orchestrator({'path': str(root), 'checks': checks}, 'Create six modules', job, planner, reviewer, worker).run()
            self.assertEqual(result['status'], 'ready_for_review')
            self.assertEqual(result['checks'][0]['exit_code'], 0)
            self.assertEqual(len(result['workers']), 6)
            self.assertEqual(git(root, 'rev-parse', 'HEAD'), original)
            self.assertFalse((root / 'a0.py').exists())
            self.assertTrue((job / 'integration/a0.py').is_file())
            self.assertTrue((job / 'integration/a5.py').is_file())
            self.assertEqual(git(root, 'status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()
