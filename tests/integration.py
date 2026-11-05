"""Black-box protocol, native metrics, DLL lifetime and owned-child tests."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

parser=argparse.ArgumentParser()
parser.add_argument('--exe',required=True)
parser.add_argument('--dll',required=True)
parser.add_argument('--child',required=True)
ARGS=parser.parse_args()

class Session:
    def __init__(self,*extra):
        self.p=subprocess.Popen([ARGS.exe,'--stdio',*extra],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    def raw(self,text):
        self.p.stdin.write(text+'\n'); self.p.stdin.flush()
        response=self.p.stdout.readline()
        if not response: raise AssertionError('Kernel closed stdout: '+self.p.stderr.read())
        return json.loads(response)
    def call(self,method,**params): return self.raw(json.dumps({'id':'test-русский','method':method,'params':params},ensure_ascii=False))
    def __enter__(self): return self
    def __exit__(self,*_):
        self.p.stdin.close()
        try: self.p.wait(timeout=5)
        except subprocess.TimeoutExpired: self.p.kill(); self.p.wait()
        self.p.stdout.close(); self.p.stderr.close()

class ContractTests(unittest.TestCase):
    def test_malformed_then_valid_and_unicode_id(self):
        with Session() as s:
            self.assertEqual(s.raw('{bad')['error']['code'],'parse_error')
            self.assertEqual(s.raw('[]')['error']['code'],'invalid_argument')
            response=s.call('ping')
            self.assertTrue(response['ok']); self.assertEqual(response['id'],'test-русский')
            self.assertEqual(response['protocol_version'],1)

    def test_validation_and_capabilities(self):
        with Session() as s:
            self.assertEqual(s.call('unknown')['error']['code'],'method_not_found')
            for params in [{'checks':['nope']},{'checks':[]},{'top_processes':-1},{'top_processes':True},{'top_processes':2**64-1},{'surprise':1}]:
                self.assertEqual(s.call('system_snapshot',**params)['error']['code'],'invalid_argument')
            capabilities=s.call('capabilities')['result']
            self.assertFalse(capabilities['actions_enabled'])
            self.assertTrue(all(t['enabled']==t['read_only'] for t in capabilities['tools']))
            self.assertEqual(s.call('launch_app',app_id='notepad')['error']['code'],'actions_disabled')
            self.assertEqual(s.call('open_url',url='https://example.com')['error']['code'],'actions_disabled')
            self.assertEqual(s.call('minimize_all')['error']['code'],'actions_disabled')
            self.assertTrue(s.call('list_apps')['ok'])
            self.assertEqual(s.call('get_location',timeout_seconds=100)['error']['code'],'invalid_argument')

    def test_browser_rejects_non_web_inputs_without_opening(self):
        with Session('--enable-actions') as s:
            self.assertEqual(s.call('minimize_all',unexpected=True)['error']['code'],'invalid_argument')
            for url in ['file:///C:/Windows/notepad.exe','cmd.exe','javascript:alert(1)',
                        'https://user:password@example.com/','https://example.com/\ncmd.exe',
                        'https://example.com/"bad','https://example.com/\\bad','https://']:
                response=s.call('open_url',url=url)
                self.assertFalse(response['ok'],url)
                self.assertEqual(response['error']['code'],'invalid_argument',response)

    def test_telegram_deep_links_reject_arbitrary_protocols_and_arguments(self):
        with Session() as s:
            self.assertEqual(s.call('open_telegram_dialog',username='example_user')['error']['code'],'actions_disabled')
        with Session('--enable-actions') as s:
            for params in [{},{'username':'bad&start=anything'},{'username':'abc?bad'},
                           {'username':'name','phone':'12345'},{'phone':'+7 999 999'},
                           {'phone':'12345&text=anything'},{'url':'cmd.exe'}]:
                response=s.call('open_telegram_dialog',**params)
                self.assertFalse(response['ok'],params)
                self.assertEqual(response['error']['code'],'invalid_argument',response)

    def test_oversized_line_recovers(self):
        with Session() as s:
            self.assertEqual(s.raw('x'*(1024*1024+1))['error']['code'],'request_too_large')
            self.assertTrue(s.call('ping')['ok'])

    def test_real_metrics_and_bounded_processes(self):
        with Session() as s:
            r=s.call('system_snapshot',checks=['cpu','memory','system','disk','battery','network','processes','startup'],top_processes=3)
            self.assertTrue(r['ok'],r)
            metrics=r['result']['metrics']
            self.assertEqual(len(metrics),8)
            ram=metrics['memory']; self.assertTrue(ram['available'])
            self.assertGreater(ram['physical_total_bytes'],0)
            self.assertEqual(ram['physical_used_bytes']+ram['physical_available_bytes'],ram['physical_total_bytes'])
            self.assertNotIn('pagefile_used_mb',ram)
            cpu=metrics['cpu']
            if cpu['available']:
                self.assertGreaterEqual(cpu['usage_percent'],0); self.assertLessEqual(cpu['usage_percent'],100)
                self.assertGreaterEqual(cpu['sample_window_ms'],250)
            self.assertGreaterEqual(metrics['system']['uptime_seconds'],0)
            procs=metrics['processes']; self.assertTrue(procs['available'])
            self.assertLessEqual(len(procs['top_by_cpu']),3); self.assertLessEqual(len(procs['top_by_memory']),3)
            self.assertGreater(procs['total_count'],0)
            windows=s.call('list_windows',limit=2); self.assertTrue(windows['ok'],windows)
            self.assertLessEqual(windows['result']['count'],2)
            audio=s.call('get_audio')
            if audio['ok']:
                self.assertGreaterEqual(audio['result']['volume_percent'],0)
                self.assertLessEqual(audio['result']['volume_percent'],100)
            else: self.assertEqual(audio['error']['code'],'audio_unavailable')

    def test_only_registered_and_owned_processes(self):
        with tempfile.TemporaryDirectory(prefix='jarvis-配置-') as tmp:
            config=Path(tmp)/'config.json'
            config.write_text(json.dumps({'enable_actions':True,'applications':{'fixture':{'path':str(Path(ARGS.child).resolve()),'hidden':True}}}),encoding='utf-8')
            with Session('--config',str(config)) as s:
                self.assertEqual(s.call('launch_app',app_id='not-registered')['error']['code'],'app_not_registered')
                self.assertEqual(s.call('stop_app',pid=os.getpid())['error']['code'],'process_not_owned')
                self.assertEqual(s.call('launch_app',app_id='fixture',path='cmd.exe')['error']['code'],'invalid_argument')
                for value in [-1,101,True,'25']:
                    self.assertEqual(s.call('set_volume',percent=value)['error']['code'],'invalid_argument')
                launched=s.call('launch_app',app_id='fixture'); self.assertTrue(launched['ok'],launched)
                pid=launched['result']['pid']
                try:
                    self.assertFalse(launched['result']['application_ready_verified'])
                    stopped=s.call('stop_app',pid=pid); self.assertTrue(stopped['ok'],stopped)
                    self.assertTrue(stopped['result']['verified'])
                    self.assertEqual(s.call('stop_app',pid=pid)['error']['code'],'process_not_owned')
                finally:
                    # Cleanup is confined to the test child PID created above.
                    s.call('stop_app',pid=pid)

    def test_document_opening_is_limited_to_docx_roots_and_registered_onlyoffice(self):
        with tempfile.TemporaryDirectory(prefix='jarvis-docs-') as tmp:
            root=Path(tmp)/'documents'; root.mkdir()
            document=root/'Документ с пробелами.docx'; document.write_bytes(b'fixture')
            outside=Path(tmp)/'outside.docx'; outside.write_bytes(b'fixture')
            executable=root/'command.exe'; executable.write_bytes(b'fixture')
            config=Path(tmp)/'config.json'
            config.write_text(json.dumps({'enable_actions':True,'document_roots':[str(root)],
                'applications':{'onlyoffice':{'path':str(Path(ARGS.child).resolve()),'hidden':True}}}),encoding='utf-8')
            with Session('--config',str(config)) as s:
                for path in [str(outside),str(executable),'relative.docx',str(root/'missing.docx')]:
                    response=s.call('open_document',path=path)
                    self.assertFalse(response['ok'],response)
                response=s.call('open_document',path=str(document),args=['anything'])
                self.assertFalse(response['ok'])
                launched=s.call('open_document',path=str(document)); self.assertTrue(launched['ok'],launched)
                try:
                    self.assertEqual(launched['result']['app_id'],'onlyoffice')
                    self.assertTrue(Path(launched['result']['path']).samefile(document))
                finally:
                    s.call('stop_app',pid=launched['result']['pid'])

    def test_dll_ownership_and_repeated_calls(self):
        dll=ctypes.CDLL(ARGS.dll)
        dll.jarvis_create.argtypes=[ctypes.c_char_p]; dll.jarvis_create.restype=ctypes.c_void_p
        dll.jarvis_execute.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; dll.jarvis_execute.restype=ctypes.c_void_p
        dll.jarvis_free_string.argtypes=[ctypes.c_void_p]; dll.jarvis_free_string.restype=None
        dll.jarvis_destroy.argtypes=[ctypes.c_void_p]; dll.jarvis_destroy.restype=None
        self.assertFalse(dll.jarvis_create(b'{bad'))
        handle=dll.jarvis_create(b'{}'); self.assertTrue(handle)
        try:
            for _ in range(20):
                pointer=dll.jarvis_execute(handle,b'{"method":"ping"}'); self.assertTrue(pointer)
                try: self.assertTrue(json.loads(ctypes.string_at(pointer))['ok'])
                finally: dll.jarvis_free_string(pointer)
            pointer=dll.jarvis_execute(handle,b'{"method":"system_snapshot","params":{"checks":["memory"]}}')
            try: self.assertTrue(json.loads(ctypes.string_at(pointer))['ok'])
            finally: dll.jarvis_free_string(pointer)
        finally: dll.jarvis_destroy(handle)

if __name__=='__main__': unittest.main(argv=['integration.py'],verbosity=2)
