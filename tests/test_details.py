"""Metadata, artwork fallbacks and source-bound application launching."""
import base64
import importlib.util
import json
import gzip
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backend', Path(__file__).parents[1] / 'backend/app_center_backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBZkAAAAASUVORK5CYII=')


class DetailsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root/'data'), 'XDG_CACHE_HOME': str(self.root/'cache')})
        self.env.start()
    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()
    def flatpak(self, **kw):
        return dict(dict(source='flatpak', id='org.example.App', scope='system', remote='flathub', branch='stable', arch='x86_64', name='Example'), **kw)
    def test_description_preserves_paragraphs_and_removes_script_content(self):
        self.assertEqual(b.description_text('<p>First &amp; best.</p><p>Second <b>paragraph</b>.</p><script>hidden()</script>'), 'First & best.\n\nSecond paragraph.')
    def test_catalog_metadata_uses_english_publisher_cached_icon_and_medium_screenshot(self):
        folder = self.root/'catalog';icon = folder/'icons/128x128/org.example.App.png';icon.parent.mkdir(parents=True);icon.write_bytes(PNG)
        path = folder/'appstream.xml'
        path.write_text('''<components><component type="desktop-application"><id>org.example.App</id><name>Example</name>
        <description><p>First paragraph.</p><p>Second paragraph.</p></description>
        <developer><name xml:lang="de">Andere</name><name>Example Team</name></developer>
        <project_license>GPL-3.0-or-later</project_license><launchable type="desktop-id">org.example.App.desktop</launchable>
        <icon type="cached">org.example.App.png</icon><screenshots><screenshot type="default"><caption>Working</caption>
        <image type="source">https://example.org/original.png</image><image type="thumbnail" width="752">https://example.org/medium.png</image>
        <image type="thumbnail" width="112">https://example.org/tiny.png</image></screenshot></screenshots></component></components>''')
        item = b.appstream_components([path])[0]
        self.assertEqual(item['publisher'], 'Example Team')
        self.assertEqual(item['icon'], str(icon))
        self.assertEqual(item['desktop_ids'], ['org.example.App.desktop'])
        self.assertEqual(item['screenshot_urls'], [dict(url='https://example.org/medium.png', caption='Working')])
        self.assertIn('\n\n', item['description'])
    def test_artwork_cache_can_be_used_offline_without_another_download(self):
        with patch.object(b, 'public_https', return_value=True), patch.object(b.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = PNG
            first = b.cached_artwork('https://example.org/image.png')
        self.assertEqual(Path(first).read_bytes(), PNG)
        with patch.object(b.urllib.request, 'build_opener', side_effect=AssertionError('Refetched cached art')):
            self.assertEqual(b.cached_artwork('https://example.org/image.png'), first)
    def test_expired_cached_artwork_remains_available_offline(self):
        with patch.object(b, 'public_https', return_value=True), patch.object(b.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = PNG
            path = b.cached_artwork('https://example.org/old.png')
        os.utime(path, (0, 0))
        with patch.object(b, 'public_https', return_value=True), patch.object(b.urllib.request, 'build_opener', side_effect=OSError('offline')):
            self.assertEqual(b.cached_artwork('https://example.org/old.png'), path)
    def test_compressed_svg_artwork_is_bounded_and_validated(self):
        svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64"/></svg>'
        with patch.object(b, 'public_https', return_value=True), patch.object(b.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value=gzip.compress(svg)
            path=b.cached_artwork('https://example.org/icon.svgz')
        self.assertTrue(path.endswith('.svg'))
        self.assertEqual(Path(path).read_bytes(),svg)
    def test_artwork_rejects_local_addresses_credentials_and_non_https(self):
        for url in ('file:///etc/passwd', 'http://example.org/a.png', 'https://127.0.0.1/a', 'https://[::1]/a', 'https://192.168.1.1/a', 'https://localhost/a', 'https://user:password@example.org/a'):
            with self.subTest(url=url):
                self.assertFalse(b.public_https(url))
                self.assertEqual(b.cached_artwork(url), '')
    def test_artwork_rejects_bad_images_and_oversized_dimensions(self):
        huge = bytearray(PNG);struct.pack_into('>II', huge, 16, 100000, 100000)
        for raw in (b'<html>Not an image</html>', bytes(huge), b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>'):
            self.assertIsNone(b.artwork_format(raw))
        self.assertEqual(b.artwork_format(PNG), 'png')
        jpeg = b'\xff\xd8\xff\xc0\x00\x08\x08\x00\x64\x00\xc8\x00'
        self.assertEqual(b.artwork_format(jpeg), 'jpg')
    def test_failed_screenshots_preserve_description_and_actions(self):
        item = dict(name='Example', description='Useful description', installed=True, can_open=True)
        with patch.object(b, 'cached_artwork', side_effect=OSError('offline')):
            b.detail_artwork(item, dict(screenshot_urls=[dict(url='https://example.org/image.png')]))
        self.assertTrue(item['can_open']);self.assertEqual(item['description'], 'Useful description')
        self.assertEqual(item['screenshots'], [])
        self.assertIn('unavailable', item['artwork_note'])
    def test_debian_details_include_full_description_and_installed_version(self):
        fields = 'Package: demo\nVersion: 2.0\nArchitecture: amd64\nMaintainer: Package Team\nHomepage: https://example.org\nDescription-en: An app\n First paragraph.\n .\n Second paragraph.\n'
        with patch.object(b, 'run', return_value=fields), patch.object(b, 'appstream', return_value={}), patch.object(b, 'deb_installed', return_value='1.0'), patch.object(b, 'launch_spec', return_value=None):
            item = b.app_details(dict(source='deb', id='demo', name='demo'), artwork=False)['item']
        self.assertEqual(item['version'], '2.0');self.assertEqual(item['installed_version'], '1.0')
        self.assertIn('Second paragraph.', item['description'])
        self.assertTrue(item['installed']);self.assertFalse(item['can_open'])
        self.assertEqual(item['maintainer'], 'Package Team')
    def test_debian_open_rechecks_installation_and_uses_only_package_owned_launcher(self):
        target = dict(source='deb', id='demo', installed=True, can_open=True, launch_command='/untrusted')
        with patch.object(b, 'deb_installed', return_value=''), patch.object(b, 'launch_desktop') as launch:
            with self.assertRaises(b.AppCenterError):b.launch_installed(target)
            launch.assert_not_called()
        with patch.object(b, 'deb_installed', return_value='1'), patch.object(b, 'run', return_value='/etc/data\n/usr/share/applications/demo.desktop\n/tmp/evil.desktop\n'), patch.object(b, 'visible_desktop', return_value=True), patch.object(b, 'launch_desktop') as launch:
            b.launch_installed(target)
        launch.assert_called_once_with('/usr/share/applications/demo.desktop')
    def test_packages_without_visible_launchers_do_not_get_open(self):
        with patch.object(b, 'deb_installed', return_value='1'), patch.object(b, 'run', return_value='/usr/lib/libexample.so\n'):
            self.assertIsNone(b.launch_spec(dict(source='deb', id='libexample')))
    def test_flatpak_launch_retains_selected_scope_arch_branch_and_checks_origin(self):
        target = self.flatpak(arch='aarch64', branch='beta', remote='testing')
        with patch.object(b, 'run', return_value='org.example.App\tbeta\ttesting\taarch64\t1.0\n'), patch.object(b.subprocess, 'Popen') as launch:
            b.launch_installed(target)
        self.assertEqual(launch.call_args.args[0], ['flatpak', '--system', 'run', '--arch=aarch64', '--branch=beta', 'org.example.App'])
        with patch.object(b, 'run', return_value='org.example.App\tstable\tflathub\taarch64\t1.0\n'), patch.object(b.subprocess, 'Popen') as launch:
            with self.assertRaises(b.AppCenterError):b.launch_installed(target)
            launch.assert_not_called()
    def test_flatpak_details_do_not_download_artwork_supplied_by_the_caller(self):
        target = self.flatpak(icon_url='https://untrusted.example/a.png', screenshot_urls=[dict(url='https://untrusted.example/a.png')])
        with patch.object(b, 'flatpak_appstream', return_value={}), patch.object(b, 'flatpak_installed', return_value=None), patch.object(b, 'launch_spec', return_value=None), patch.object(b, 'cached_artwork') as artwork:
            item = b.app_details(target)['item']
        artwork.assert_not_called();self.assertFalse(item['can_open'])
    def test_flatpak_metadata_does_not_change_transaction_identity(self):
        metadata = dict(name='Better Name', description='Long description', publisher='Team', version='2', screenshot_urls=[])
        with patch.object(b, 'flatpak_appstream', return_value={('org.example.App','x86_64','stable','flathub'):metadata}), patch.object(b, 'flatpak_installed', return_value=dict(version='1',arch='x86_64')), patch.object(b, 'launch_spec', return_value=dict(kind='flatpak')):
            item = b.app_details(self.flatpak(), artwork=False)['item']
        self.assertEqual(tuple(item[k] for k in ('source','id','scope','branch','remote','arch')), ('flatpak','org.example.App','system','stable','flathub','x86_64'))
        self.assertEqual(item['installed_version'], '1');self.assertEqual(item['publisher'], 'Team');self.assertTrue(item['can_open'])
    def test_snap_offline_details_keep_installed_information(self):
        installed = dict(name='example', title='Example', version='1', status='active', summary='An app', description='Details', publisher=dict(username='team',validation='verified'))
        def api(path):
            if path.startswith('/v2/find'):raise b.AppCenterError('offline')
            return dict(result=installed)
        with patch.object(b, 'snap_api', side_effect=api), patch.object(b, 'launch_spec', return_value=None):
            result = b.app_details(dict(source='snap',id='example'), artwork=False)
        self.assertTrue(result['item']['installed']);self.assertTrue(result['item']['publisher_verified'])
        self.assertEqual(result['item']['publisher'], 'team');self.assertTrue(result['warnings'])
    def test_appimage_catalog_has_artwork_but_is_never_launchable(self):
        entry = dict(name='Example',description='<p>Full description</p>',authors=[dict(name='Packager')], icons=['Example/icon.png'],screenshots=['Example/screen.png'])
        ident=b.hashlib.sha256(b'Example').hexdigest()
        target=dict(source='appimage',id=ident,catalog=True,installed=True,can_open=True)
        with patch.object(b,'appimage_feed',return_value=[entry]),patch.object(b,'cached_artwork',return_value='/cache/asset.png'):
            item=b.app_details(target)['item']
        self.assertFalse(item['installed']);self.assertFalse(item['can_open']);self.assertEqual(item['catalog_author'],'Packager')
        self.assertEqual(len(item['screenshots']),1)
        with self.assertRaises(b.AppCenterError):b.launch_installed(target)
    def test_managed_appimage_open_does_not_use_original_download_path(self):
        ident='a'*64
        folder=self.root/'data/cutefish-app-center/appimages'/ident;folder.mkdir(parents=True)
        (folder/'application.AppImage').write_bytes(b'fixture')
        launcher=self.root/'data/applications'/('org.cutefish.AppCenter.AppImage-'+ident+'.desktop');launcher.parent.mkdir()
        launcher.write_text('[Desktop Entry]\nType=Application\nName=Example\nExec=/managed/application.AppImage\n')
        with patch.object(b,'launch_desktop') as launch:
            b.launch_installed(dict(source='appimage',id=ident,path='/untrusted/download.AppImage'))
        launch.assert_called_once_with(str(launcher))
        (folder/'application.AppImage').unlink()
        self.assertIsNone(b.launch_spec(dict(source='appimage',id=ident,installed=True)))
    def test_hidden_and_non_application_desktop_files_cannot_be_opened(self):
        path=self.root/'example.desktop'
        for extra in ('NoDisplay=true\n','Hidden=true\n'):
            path.write_text('[Desktop Entry]\nType=Application\nName=Example\nExec=/bin/true\n'+extra)
            self.assertFalse(b.visible_desktop(path))
        path.write_text('[Desktop Entry]\nType=Link\nName=Example\nURL=https://example.org\n')
        self.assertFalse(b.visible_desktop(path))
    def test_real_gio_launch_uses_the_registered_desktop_entry(self):
        try:
            from gi.repository import Gio
        except ImportError:
            self.skipTest('python3-gi is required for desktop launching')
        marker = self.root/'launch marker'
        path = self.root/'launch.desktop'
        path.write_text('[Desktop Entry]\nType=Application\nName=Fixture\nExec=/usr/bin/touch "'+str(marker)+'"\n')
        b.launch_desktop(str(path))
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(marker.exists())


if __name__=='__main__':unittest.main()
