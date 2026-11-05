import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jarvis.distribution import install,rollback,verify,read_state,version_path,uninstall_script
from jarvis.http import ServiceError
from jarvis.child_process import command

def package(root,version):
    source=root/version;source.mkdir()
    for name in ('Jarvis.exe','JarvisPanel.exe'):(source/name).write_bytes(version.encode())
    manifest={'version':version,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}}
    (source/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8');return source

class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_install_upgrade_rollback_preserve_external_settings(self):
        install_root=self.root/'Программы с пробелами';settings=self.root/'settings.env';settings.write_text('private',encoding='utf-8')
        first=package(self.root,'0.11.0-rc.1');second=package(self.root,'0.11.0-rc.2')
        installed=install(first,root=install_root,create_shortcuts=False);self.assertTrue(installed.is_dir())
        install(second,root=install_root,create_shortcuts=False)
        self.assertEqual(read_state(install_root)['previous'],'0.11.0-rc.1')
        self.assertEqual(rollback(root=install_root,create_shortcuts=False),installed)
        self.assertEqual(settings.read_text(encoding='utf-8'),'private')

    def test_corruption_extra_files_and_path_traversal_rejected(self):
        source=package(self.root,'0.11.0-rc.1');(source/'settings.env').write_text('secret')
        with self.assertRaises(ServiceError):verify(source)
        (source/'settings.env').unlink();(source/'Jarvis.exe').write_bytes(b'bad')
        with self.assertRaises(ServiceError):verify(source)
        for version in ('../x','C:/Windows','0.1.0/../../x'):
            with self.assertRaises(ServiceError):version_path(self.root,version)
        with self.assertRaises(ServiceError):uninstall_script(root=self.root)

    def test_frozen_child_uses_explicit_dispatch_and_preserves_paths(self):
        with patch('sys.frozen',True,create=True),patch('sys.executable',str(self.root/'JarvisPanel.exe')):
            argv=command('jarvis.vk_worker','--profile',self.root/'Профиль VK')
        self.assertEqual(argv,[str(self.root/'Jarvis.exe'),'--internal','vk_worker','--profile',str(self.root/'Профиль VK')])
        with self.assertRaises(ValueError):command('arbitrary.module')

    def test_foreign_directory_is_preserved_and_real_uninstaller_keeps_personal_data(self):
        import subprocess
        source=package(self.root,'0.11.0-rc.1')
        foreign=self.root/'foreign';foreign.mkdir();(foreign/'personal.txt').write_text('keep')
        with self.assertRaises(ServiceError):install(source,root=foreign,create_shortcuts=False)
        self.assertTrue((foreign/'personal.txt').is_file())
        local=self.root/'Local';program=local/'Programs/Jarvis';data=local/'Jarvis';data.mkdir(parents=True)
        (data/'settings.env').write_text('keep')
        install(source,root=program,create_shortcuts=False)
        with patch('jarvis.distribution.INSTALL_ROOT',program),patch('jarvis.distribution.USER_DIR',data),patch.dict('os.environ',LOCALAPPDATA=str(local)):
            helper=Path(uninstall_script(root=program,remove_shortcuts=False))
        try:
            subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(helper)],check=True,timeout=15,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertFalse(program.exists());self.assertEqual((data/'settings.env').read_text(),'keep')
        finally:helper.unlink(missing_ok=True)
