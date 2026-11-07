"""Read real DEP-11 fixtures through Debian's libappstream; never install apps."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import gi

gi.require_version('AppStream', '1.0')
from gi.repository import AppStream as As

spec = importlib.util.spec_from_file_location('backend', Path(__file__).parents[1] / 'backend/app_center_backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

CATALOG = '''---
File: DEP-11
Version: '0.16'
Origin: debian-test-main
---
Type: desktop-application
ID: org.example.Demo
Package: demo
Name:
  C: Demo Browser
  de: Deutscher Name
Summary:
  C: Browse the web
Description:
  C: <p>A browser.</p><p>More details.</p>
DeveloperName:
  C: Demo Team
ProjectLicense: GPL-3.0-or-later
Url:
  homepage: https://example.org
Launchable:
  desktop-id:
    - org.example.Demo.desktop
Icon:
  stock: demo
  cached:
    - name: demo_org.example.Demo.png
      width: 64
      height: 64
  remote:
    - url: https://example.org/demo.png
      width: 128
      height: 128
Categories:
  - Network
  - WebBrowser
Keywords:
  C:
    - internet
Provides:
  mediatypes:
    - x-scheme-handler/https
Screenshots:
  - default: true
    caption:
      C: The browser
    source-image:
      url: https://example.org/full.png
      width: 1920
      height: 1080
    thumbnails:
      - url: https://example.org/medium.png
        width: 752
        height: 423
---
Type: addon
ID: org.example.Plugin
Package: demo-plugin
Name:
  C: Plugin
Summary:
  C: Not a desktop application
---
Type: desktop-application
ID: org.example.Flatpak
Bundle:
  - type: flatpak
    id: app/org.example.Flatpak/x86_64/stable
Name:
  C: A Flatpak
Summary:
  C: Must not become a Debian package
'''

class DebianCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'yaml').mkdir()
        (self.root / 'yaml/catalog.yml').write_text(CATALOG)
        self.icon = self.root / 'icons/debian-test-main/64x64/demo_org.example.Demo.png'
        self.icon.parent.mkdir(parents=True)
        # An existing cache file is enough for libappstream path resolution.
        self.icon.write_bytes(b'fixture')

    def read(self):
        pool = As.Pool()
        pool.set_load_std_data_locations(False)
        pool.set_flags(As.PoolFlags.NONE)
        pool.set_locale('C')
        pool.add_extra_data_location(str(self.root), As.FormatStyle.CATALOG)
        pool.load(None)
        return b.distribution_appstream(pool)

    def test_yaml_uses_repository_icon_without_installation_or_download(self):
        with patch.object(b, 'cached_artwork', side_effect=AssertionError('network artwork requested')):
            item = self.read()['demo']
        self.assertEqual(item['icon'], str(self.icon))
        self.assertNotIn('icon_url', item)
        self.assertEqual(item['name'], 'Demo Browser')
        self.assertEqual(item['publisher'], 'Demo Team')
        self.assertEqual(item['desktop_ids'], ['org.example.Demo.desktop'])
        self.assertIn('WebBrowser', item['categories'])
        self.assertIn('internet', item['keywords'])
        self.assertIn('x-scheme-handler/https', item['mediatypes'])
        self.assertIn('\n\n', item['description'])
        self.assertEqual(item['screenshot_urls'], [dict(url='https://example.org/medium.png', caption='The browser')])

    def test_addons_and_flatpak_components_are_not_debian_apps(self):
        self.assertEqual(set(self.read()), {'demo'})

    def test_missing_cached_file_keeps_theme_and_optional_remote_fallback(self):
        self.icon.unlink()
        item = self.read()['demo']
        self.assertEqual(item['icon'], 'demo')
        self.assertEqual(item['icon_url'], 'https://example.org/demo.png')

    def test_missing_artwork_uses_generic_icon(self):
        p = self.root / 'yaml/catalog.yml'
        s = p.read_text()
        s = s[:s.index('Icon:')] + s[s.index('Categories:'):]
        p.write_text(s)
        item = self.read()['demo']
        self.assertEqual(item['icon'], 'application-x-deb')
        self.assertNotIn('icon_url', item)

    def test_yaml_metadata_joins_only_available_apt_packages(self):
        metadata = self.read()
        with patch.object(b, 'distribution_appstream', return_value=metadata), patch.object(b, 'dpkg_installed', return_value=[]), patch.object(b, 'run', side_effect=['', 'demo\n']):
            item = b.deb_search('web browsers')[0]
        self.assertEqual((item['source'], item['id'], item['scope']), ('deb', 'demo', 'system'))
        self.assertFalse(item['installed'])
        self.assertEqual(item['icon'], str(self.icon))
        with patch.object(b, 'appstream', return_value=metadata), patch.object(b, 'dpkg_installed', return_value=[]), patch.object(b, 'run', return_value=''):
            self.assertEqual(b.deb_search('web browsers'), [])

    def test_details_keep_icon_before_app_is_installed(self):
        with patch.object(b, 'appstream', return_value=self.read()), patch.object(b, 'run', return_value='Package: demo\nVersion: 1.0\nDescription: Browse the web\n'), patch.object(b, 'deb_installed', return_value=''), patch.object(b, 'launch_spec', return_value=None):
            item = b.app_details(dict(source='deb', id='demo'), artwork=False)['item']
        self.assertFalse(item['installed'])
        self.assertFalse(item['can_open'])
        self.assertEqual(item['icon'], str(self.icon))
        self.assertEqual(item['version'], '1.0')

    def test_updates_keep_packagekit_identity_and_version_with_catalog_icon(self):
        from unittest.mock import Mock
        pk = Mock()
        pk.transaction.return_value = ([dict(id='demo;2.0;amd64;debian', summary='Package summary')], [])
        installed = dict(source='deb', id='demo', architecture='amd64', version='1.0', name='demo', scope='system')
        with patch.object(b, 'appstream', return_value=self.read()), patch.object(b, 'PackageKit', return_value=pk), patch.object(b, 'dpkg_installed', return_value=[installed]):
            item = b.inventory_provider('deb', 'updates', '')[0]
        self.assertEqual(item['package_id'], 'demo;2.0;amd64;debian')
        self.assertEqual(item['version'], '2.0')
        self.assertEqual(item['icon'], str(self.icon))

if __name__ == '__main__':
    unittest.main()
