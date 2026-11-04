import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backend', Path(__file__).parents[1] / 'backend/store_backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'data')})
        self.env.start()
        metadata = patch.object(b, 'flatpak_appstream', return_value={})
        metadata.start()
        self.addCleanup(metadata.stop)
    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()
    def image(self, name='My App.AppImage'):
        p=self.root/name
        p.write_bytes(b'\x7fELF\x02\x01\x01\x00AI\x02' + bytes(64))
        return p
    def test_appimage_import_remove_preserves_download_and_does_not_execute(self):
        path=self.image('My "App" $x `x` 100%.AppImage')
        target=b.inspect_local(str(path))
        approved=b.plan(target,'install')
        b.apply(approved)
        records=b.appimage_items()
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['id'],target['id'])
        self.assertEqual(Path(records[0]['path']).read_bytes(),path.read_bytes())
        self.assertEqual(Path(records[0]['path']).stat().st_mode & 0o777,0o755)
        launchers=list((self.root/'data/applications').glob('*.desktop'))
        self.assertEqual(len(launchers),1)
        self.assertIn('100%%',b.desktop_quote(path))
        b.apply(b.plan(records[0],'remove'))
        self.assertTrue(path.exists())
        self.assertFalse(Path(records[0]['path']).exists())
        self.assertEqual(b.appimage_items(),[])
        self.assertFalse(launchers[0].exists())
    def test_changed_image_rejected_before_apply(self):
        p=self.image(); approved=b.plan(b.inspect_local(str(p)),'install')
        p.write_bytes(p.read_bytes()+b'changed')
        with self.assertRaises(b.StoreError): b.apply(approved)
        self.assertEqual(b.appimage_items(),[])
    def test_duplicate_import_keeps_existing_copy(self):
        target=b.inspect_local(str(self.image())); b.apply(b.plan(target,'install'))
        with self.assertRaises(b.StoreError): b.apply(b.plan(target,'install'))
        self.assertEqual(len(b.appimage_items()),1)
    def test_executable_without_appimage_signature_is_rejected(self):
        p=self.root/'fake.AppImage'; p.write_bytes(b'\x7fELF'+bytes(100))
        with self.assertRaises(b.StoreError): b.inspect_local(str(p))
    def test_deb_inspection_and_hash(self):
        package=self.root/'pkg'; (package/'DEBIAN').mkdir(parents=True)
        (package/'DEBIAN/control').write_text('Package: cutefish-store-test-fixture\nVersion: 1.0\nArchitecture: all\nMaintainer: Test <test@example.invalid>\nDescription: A local inspection fixture\n')
        dest=self.root/'test file.deb'
        subprocess.run(['dpkg-deb','--build','--root-owner-group',str(package),str(dest)],check=True,stdout=subprocess.DEVNULL)
        item=b.inspect_local(str(dest))
        self.assertEqual(item['id'],'cutefish-store-test-fixture')
        self.assertEqual(item['sha256'],b.file_hash(dest))
        self.assertEqual(item['architecture'],'all')
    def test_shell_metacharacters_in_ids_are_rejected(self):
        for source in ['deb','snap','flatpak','appimage']:
            with self.assertRaises(b.StoreError): b.validate_target({'source':source,'id':'x; touch /tmp/x'})
    def test_flatpak_scopes_and_exact_refs_are_preserved(self):
        def run(args, **kw):
            if 'search' in args: return 'org.example.App\tExample\tDescription\t1.2\tstable\tflathub\n'
            if 'list' in args: return 'org.example.App\tstable\tflathub\tx86_64\n' if '--system' in args else ''
            if '--default-arch' in args: return 'x86_64\n'
            if 'remote-ls' in args: return 'org.example.App\tx86_64\tstable\tflathub\n'
            self.fail(args)
        with patch.object(b.shutil,'which',return_value='/usr/bin/flatpak'),patch.object(b,'run',side_effect=run):
            items=b.flatpak_items('example')
        by_scope = {x['scope']: x for x in items}
        self.assertEqual(set(by_scope), {'user', 'system'})
        self.assertFalse(by_scope['user']['installed']); self.assertTrue(by_scope['system']['installed'])
        with patch.object(b,'run',return_value='x86_64\n'):
            self.assertEqual(b.flatpak_ref(items[0]),'app/org.example.App/x86_64/stable')
    def test_flatpak_other_branch_is_not_marked_installed(self):
        def run(args, **kw):
            if 'search' in args:return 'org.example.App\tExample\tDescription\t2.0\tbeta\tflathub\n'
            if 'list' in args:return 'org.example.App\tstable\tflathub\tx86_64\n'
            if '--default-arch' in args:return 'x86_64\n'
            if 'remote-ls' in args:return 'org.example.App\tx86_64\tbeta\tflathub\n'
            self.fail(args)
        with patch.object(b.shutil,'which',return_value='/usr/bin/flatpak'),patch.object(b,'run',side_effect=run):
            self.assertTrue(all(not x['installed'] for x in b.flatpak_items('example')))
    def test_flatpak_plan_uses_supported_metadata_option_and_displays_access(self):
        metadata = "[Application]\nname=org.example.App\n[Context]\nshared=network;\nfilesystems=host;\n[Session Bus Policy]\norg.example.Service=talk\n[Environment]\nIGNORE=this\n"
        calls=[]
        def run(args, **kw):
            calls.append(args)
            if '--show-metadata' in args:return metadata
            self.fail('Unsupported command: '+repr(args))
        target=dict(source='flatpak',id='org.example.App',name='Example',scope='system',remote='flathub',branch='stable',arch='x86_64')
        with patch.object(b,'run',side_effect=run):
            approved=b.plan(target,'install')
            with patch.object(b,'stream_command') as execute:
                b.apply(approved)
        self.assertIn('filesystems=host;',approved['note'])
        self.assertIn('org.example.Service=talk',approved['note'])
        self.assertNotIn('IGNORE',approved['note'])
        execute.assert_called_once_with(['flatpak','--system','install','--assumeyes','--noninteractive','--','flathub','app/org.example.App/x86_64/stable'])
        self.assertTrue(all('--show-permissions' not in cmd for cmd in calls))
    def test_flatpak_runtime_metadata_is_not_an_application(self):
        with self.assertRaisesRegex(b.StoreError,'runtime or extension'):
            b.flatpak_permissions('[Runtime]\nname=org.example.Extension\n')
    def test_flatpak_addon_search_results_are_filtered(self):
        def run(args, **kw):
            if 'search' in args:return 'org.example.App.Plugin\tPlugin\tAn extension\t1\tstable\tflathub\norg.example.App\tExample\tAn app\t1\tstable\tflathub\n'
            if 'remote-ls' in args:return 'org.example.App\tx86_64\tstable\tflathub\n'
            if 'list' in args:return ''
            if '--default-arch' in args:return 'x86_64\n'
            self.fail(args)
        with patch.object(b.shutil,'which',return_value='/usr/bin/flatpak'),patch.object(b,'run',side_effect=run):
            self.assertTrue(all(x['id']=='org.example.App' for x in b.flatpak_items('example')))
    def test_appimage_catalog_search_and_safe_page_links(self):
        entries=[{'name':'Paint Tool','description':'<p>Draw &amp; paint pictures</p>'}, {'name':'Music','description':'Listen'}, {'name':None}]
        with patch.object(b,'appimage_feed',return_value=entries):
            items=b.appimage_catalog('paint pictures')
        self.assertEqual(len(items),1)
        self.assertTrue(items[0]['catalog'])
        self.assertEqual(items[0]['summary'],'Draw & paint pictures')
        self.assertEqual(b.appimage_catalog_link(items[0]),'https://appimage.github.io/Paint%20Tool/')
        items[0]['catalog_url']='file:///etc/passwd'
        self.assertTrue(b.appimage_catalog_link(items[0]).startswith('https://appimage.github.io/'))
        items[0]['id']='invalid'
        with self.assertRaises(b.StoreError):b.appimage_catalog_link(items[0])
    def test_appimage_catalog_is_cached_without_refetch(self):
        payload=json.dumps({'items':[{'name':'Example'}]}).encode()
        with patch.dict(os.environ,{'XDG_CACHE_HOME':str(self.root/'cache')}):
            with patch.object(b.urllib.request,'urlopen') as fetch:
                fetch.return_value.__enter__.return_value.read.return_value=payload
                self.assertEqual(b.appimage_feed(),[{'name':'Example'}])
            with patch.object(b.urllib.request,'urlopen',side_effect=AssertionError('Cache ignored')):
                self.assertEqual(b.appimage_feed(),[{'name':'Example'}])
    def test_debian_update_preserves_exact_package_id_and_architecture(self):
        pid='fixture;2.0;arm64;debian'
        class FakePK:
            def transaction(self,*a):return ([{'id':pid}],[])
        with patch.object(b,'PackageKit',FakePK):
            _,method,_,args=b.pk_args({'source':'deb','id':'fixture','package_id':pid},'update',6)
            self.assertEqual(method,'UpdatePackages');self.assertEqual(args[1],[pid])
            with self.assertRaises(b.StoreError):
                b.pk_args({'source':'deb','id':'fixture','package_id':'fixture;1.0;amd64;debian'},'update',6)
    def test_failed_source_does_not_hide_other_sources(self):
        def provider(source, mode, query):
            if source=='snap':raise b.StoreError('offline')
            return [{'source':source,'id':'x','name':'Example'}]
        with patch.object(b,'inventory_provider',side_effect=provider): result=b.listing({'mode':'installed'})
        self.assertEqual(len(result['items']),3)
        self.assertEqual(result['warnings'],['snap: offline'])
    def test_changed_dependency_plan_requires_new_review(self):
        approved={'target':{'source':'deb','id':'test'},'action':'install','fingerprint':'old'}
        with patch.object(b,'plan',return_value={'fingerprint':'new'}):
            with self.assertRaisesRegex(b.StoreError,'plan changed'): b.apply(approved)
    def test_protected_dependency_removal_is_refused(self):
        class FakePK:
            def resolve(self,*a,**kw):return 'test;1;amd64;repo'
            def transaction(self,*a):return ([{'info':'remove','id':'libc6;1;amd64;installed','summary':'libc'}],[])
        with patch.object(b,'PackageKit',FakePK),patch.object(b,'dpkg_installed',return_value=[{'id':'libc6:amd64','protected':True}]):
            with self.assertRaisesRegex(b.StoreError,'protected'): b.plan({'source':'deb','id':'test'},'install')
    def test_classic_snap_is_explicit_in_review_and_request(self):
        calls=[]
        def api(path,body=None):
            calls.append((path,body))
            if body:return {'type':'sync'}
            return {'result':[{'confinement':'classic'}]}
        with patch.object(b,'snap_api',side_effect=api):
            approved=b.plan({'source':'snap','id':'test','name':'Test'},'install')
            self.assertIn('Classic confinement',approved['note'])
            b.apply(approved)
        self.assertTrue(calls[-1][1]['classic'])
        self.assertEqual(calls[-1][1]['channel'],'stable')
    def test_no_automatic_appimage_updater(self):
        with self.assertRaisesRegex(b.StoreError,'publisher'):
            b.plan({'source':'appimage','id':'a'*64},'update')
    def test_transaction_lock_excludes_other_instances(self):
        with b.mutation_lock():
            with self.assertRaisesRegex(b.StoreError,'Another'):
                with b.mutation_lock(): pass

    def bundled_image(self, *, icon=b'', icon_path='demo.png', dir_icon=None, desktop=None):
        if not b.shutil.which('mksquashfs') or not b.shutil.which('prlimit'):
            self.skipTest('squashfs-tools and util-linux are required')
        folder=self.root/'AppDir'; folder.mkdir(exist_ok=True)
        (folder/'demo.desktop').write_text(desktop or '[Desktop Entry]\nType=Application\nName=Demo App\nComment=An embedded app\nIcon=demo\nCategories=Graphics;Utility;\nStartupWMClass=demo-window\nX-AppImage-Version=2.3\nExec=/untrusted/program --unsafe\n')
        if icon:
            dest=folder/icon_path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(icon)
        if dir_icon:
            (folder/'.DirIcon').symlink_to(dir_icon)
        filesystem=self.root/'filesystem.squashfs'
        subprocess.run(['mksquashfs',str(folder),str(filesystem),'-noappend','-processors','1','-comp','gzip','-no-progress'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        archive=self.root/'Bundled.AppImage'
        archive.write_bytes(b'\x7fELF\x02\x01\x01\x00AI\x02'+bytes(64)+filesystem.read_bytes())
        return archive
    def png(self):
        import base64
        return base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBZkAAAAASUVORK5CYII=')
    def test_import_uses_embedded_name_icon_and_window_class_without_source_exec(self):
        archive=self.bundled_image(icon=self.png())
        b.apply(b.plan(b.inspect_local(str(archive)),'install'))
        item=b.appimage_items()[0]
        self.assertEqual(item['name'],'Demo App');self.assertEqual(item['summary'],'An embedded app')
        self.assertEqual(item['version'],'2.3')
        self.assertEqual(Path(item['icon']).read_bytes(),self.png())
        launcher=next((self.root/'data/applications').glob('*.desktop')).read_text()
        self.assertIn('Icon='+item['icon'],launcher)
        self.assertIn('StartupWMClass=demo-window',launcher)
        self.assertIn('Categories=Graphics;Utility;',launcher)
        self.assertNotIn('/untrusted/program',launcher)
        self.assertIn(b.desktop_quote(item['path']),launcher)
    def test_diricon_can_link_to_an_icon_inside_the_archive(self):
        archive=self.bundled_image(icon=self.png(),icon_path='usr/share/icons/demo.png',dir_icon='usr/share/icons/demo.png')
        fields,artwork,suffix=b.embedded_appimage_metadata(archive)
        self.assertEqual(artwork,self.png());self.assertEqual(suffix,'png')
    def test_archive_symlink_cannot_read_an_icon_outside_the_archive(self):
        secret=self.root/'outside.png';secret.write_bytes(self.png())
        archive=self.bundled_image(dir_icon=str(secret))
        _,artwork,_=b.embedded_appimage_metadata(archive)
        self.assertIsNone(artwork)
    def test_existing_import_gets_metadata_and_launcher_repaired(self):
        archive=self.bundled_image(icon=self.png())
        checked=b.inspect_local(str(archive));b.apply(b.plan(checked,'install'))
        dest=self.root/'data/cutefish-store/appimages'/checked['id']
        old=dict(checked,installed=True,path=str(dest/'application.AppImage'))
        (dest/'metadata.json').write_text(json.dumps(old))
        item=b.appimage_items()[0]
        self.assertEqual(item['metadata_version'],b.APPIMAGE_METADATA_VERSION)
        self.assertEqual(item['name'],'Demo App')
        self.assertTrue(Path(item['icon']).exists())
        self.assertEqual(b.file_hash(Path(item['path'])),checked['id'])
    def test_oversized_embedded_icon_does_not_prevent_import(self):
        archive=self.bundled_image(icon=self.png()+bytes(b.ICON_MAX_BYTES))
        b.apply(b.plan(b.inspect_local(str(archive)),'install'))
        item=b.appimage_items()[0]
        self.assertEqual(item['icon'],'application-x-executable')
        self.assertEqual(item['name'],'Demo App')
    def test_svg_with_external_resources_is_not_installed(self):
        svg=b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>'
        archive=self.bundled_image(icon=svg,icon_path='demo.svg')
        _,artwork,_=b.embedded_appimage_metadata(archive)
        self.assertIsNone(artwork)
    def test_missing_archive_tool_keeps_import_working_with_generic_icon(self):
        archive=self.bundled_image(icon=self.png())
        with patch.object(b.shutil,'which',return_value=None):
            b.apply(b.plan(b.inspect_local(str(archive)),'install'))
        self.assertEqual(b.appimage_items()[0]['icon'],'application-x-executable')

if __name__=='__main__':unittest.main()
