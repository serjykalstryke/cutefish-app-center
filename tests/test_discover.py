"""Discovery availability and preservation of imports across the app rename."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('backend',Path(__file__).parents[1]/'backend/app_center_backend.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class DiscoverTests(unittest.TestCase):
    def test_featured_apps_require_configured_available_refs(self):
        meta={('org.mozilla.firefox','x86_64','stable','flathub'):dict(name='Firefox',desktop_app=True,summary='Browser'),
              ('org.gimp.GIMP','x86_64','stable','removed'):dict(name='GIMP',desktop_app=True),
              ('org.kde.krita','aarch64','stable','flathub'):dict(name='Krita',desktop_app=True)}
        def run(args,**kw):
            if '--default-arch' in args:return 'x86_64\n'
            if 'remote-ls' in args:return 'org.mozilla.firefox\tx86_64\tstable\tflathub\n'
            if 'apt-cache' in args:return ''
            self.fail(args)
        with patch.object(b.shutil,'which',return_value='/usr/bin/flatpak'),patch.object(b,'flatpak_appstream',return_value=meta),patch.object(b,'appstream',return_value={}),patch.object(b,'run',side_effect=run):
            result=b.discover_apps()
        self.assertEqual([i['id'] for i in result['items']],['org.mozilla.firefox'])
        self.assertEqual(result['items'][0]['query'],'firefox')
    def test_debian_catalog_is_a_working_fallback_without_flatpak(self):
        with patch.object(b.shutil,'which',return_value=None),patch.object(b,'run',return_value='vlc - Multimedia player\n'),patch.object(b,'appstream',return_value={}):
            result=b.discover_apps()
        self.assertEqual([(i['feature_name'],i['source']) for i in result['items']],[('VLC','deb')])
    def test_missing_apps_are_never_fabricated(self):
        with patch.object(b.shutil,'which',return_value=None),patch.object(b,'run',return_value=''),patch.object(b,'appstream',return_value={}):
            self.assertEqual(b.discover_apps()['items'],[])
    def test_one_source_failure_does_not_hide_available_native_featured_apps(self):
        def run(args,**kw):
            if args[0]=='flatpak':raise b.AppCenterError('offline')
            return 'gimp - Image editor\n'
        with patch.object(b.shutil,'which',return_value='/usr/bin/flatpak'),patch.object(b,'run',side_effect=run),patch.object(b,'appstream',return_value={}):
            result=b.discover_apps()
        self.assertEqual(result['items'][0]['feature_name'],'GIMP');self.assertTrue(result['warnings'])
    def test_all_discover_categories_use_app_metadata(self):
        for query,category in [('internet','Network'),('graphics','Graphics'),('office','Office'),('audio video','AudioVideo'),('development','Development'),('games','Game'),('education','Education'),('utilities','Utility')]:
            with self.subTest(query=query):
                item=dict(id='org.example.App',name='Example',source='flatpak',categories=[category],desktop_app=True)
                self.assertGreater(b.search_score(item,query),0)
                self.assertEqual(b.search_score(dict(item,categories=[],description='Mentions '+query),query),0)

class RenameMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'XDG_DATA_HOME':str(self.root/'data')});self.env.start()
        self.legacy=self.root/'data/cutefish-store/appimages'
        self.raw=b'\x7fELF\x02\x01\x01\x00AI\x02'+bytes(64)
        self.ident=b.hashlib.sha256(self.raw).hexdigest()
        self.old=self.legacy/self.ident;self.old.mkdir(parents=True)
        (self.old/'application.AppImage').write_bytes(self.raw)
        (self.old/'icon.png').write_bytes(b'icon fixture')
        self.meta=dict(source='appimage',id=self.ident,name='An Imported App',path=str(self.old/'application.AppImage'),icon=str(self.old/'icon.png'),installed=True,metadata_version=b.APPIMAGE_METADATA_VERSION)
        (self.old/'metadata.json').write_text(json.dumps(self.meta))
        self.download=self.root/'Original Download.AppImage';self.download.write_bytes(self.raw)
        self.apps=self.root/'data/applications';self.apps.mkdir()
        self.old_launcher=self.apps/('org.cutefish.Store.AppImage-'+self.ident+'.desktop')
        self.old_launcher.write_text(b.appimage_launcher(self.meta))
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_import_paths_artwork_and_menu_entry_migrate_without_touching_download(self):
        b.migrate_legacy_library();items=b.appimage_items();self.assertEqual(len(items),1)
        item=items[0];self.assertIn('cutefish-app-center/appimages',item['path'])
        self.assertEqual(Path(item['path']).read_bytes(),self.raw)
        self.assertTrue(Path(item['icon']).is_file());self.assertFalse(self.old_launcher.exists())
        launcher=self.apps/('org.cutefish.AppCenter.AppImage-'+self.ident+'.desktop')
        self.assertIn(item['path'],launcher.read_text());self.assertEqual(self.download.read_bytes(),self.raw)
        b.migrate_legacy_library();self.assertEqual(b.appimage_items(),items)
    def test_interrupted_directory_move_is_resumed_from_the_old_launcher(self):
        dest=b.state_dir()/'appimages'/self.ident;dest.parent.mkdir();self.old.rename(dest)
        b.migrate_legacy_library()
        self.assertEqual(json.loads((dest/'metadata.json').read_text())['path'],str(dest/'application.AppImage'))
        self.assertFalse(self.old_launcher.exists())
    def test_invalid_old_image_is_preserved_and_not_executed_or_overwritten(self):
        (self.old/'application.AppImage').write_bytes(b'changed')
        with self.assertRaises(b.AppCenterError):b.migrate_legacy_library()
        self.assertTrue(self.old_launcher.exists());self.assertTrue(self.old.exists())
    def test_active_old_transaction_prevents_migration(self):
        import fcntl
        with open(self.legacy.parent/'transaction.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(b.AppCenterError,'Finish the operation'):b.migrate_legacy_library()
        self.assertTrue(self.old.exists())
    def test_existing_new_import_retains_its_own_metadata(self):
        import shutil
        dest=b.state_dir()/'appimages'/self.ident;dest.parent.mkdir();shutil.copytree(self.old,dest)
        meta=dict(self.meta,name='Newer Name',path=str(dest/'application.AppImage'),icon=str(dest/'icon.png'))
        (dest/'metadata.json').write_text(json.dumps(meta));b.migrate_legacy_library()
        self.assertEqual(json.loads((dest/'metadata.json').read_text())['name'],'Newer Name')
        self.assertTrue((self.legacy/('.migrated-'+self.ident)).exists())
    def test_symlinked_legacy_library_is_not_followed(self):
        import shutil
        shutil.rmtree(self.legacy);self.legacy.symlink_to(self.root)
        with self.assertRaisesRegex(b.AppCenterError,'symbolic link'):b.migrate_legacy_library()

if __name__=='__main__':unittest.main()
