"""Source-backed artwork loading without installing or running applications."""
import base64
import gzip
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('backend', Path(__file__).parents[1] / 'backend/app_center_backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aBZkAAAAASUVORK5CYII=')
URL = 'https://example.org/icon.png'

class CatalogIconTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, XDG_CACHE_HOME=str(self.root));env.start();self.addCleanup(env.stop)

    def register(self, url=URL):
        return b.catalog_icon(dict(icon='application-x-executable'), dict(kind='https', url=url))

    def test_snap_search_registers_store_icon_without_fetching_it(self):
        records = [dict(name='demo', title='Demo', summary='A demo app', type='app', revision='1', media=[dict(type='icon', url=URL)])]
        with patch.object(b, 'snap_api', side_effect=[dict(result=records), dict(result=[])]), patch.object(b, 'cached_artwork', side_effect=AssertionError('blocked search on artwork')):
            item = b.snap_items('demo')[0]
        self.assertFalse(item['installed']);self.assertEqual(item['icon'], 'application-x-executable')
        self.assertTrue(item['icon_key'])

    def test_appimage_catalog_registers_relative_artwork_without_binary_download(self):
        entry = dict(name='Demo', description='A demo', icons=['Demo/icons/128x128/demo.png'])
        with patch.object(b, 'appimage_feed', return_value=[entry]), patch.object(b, 'cached_artwork', side_effect=AssertionError('blocked search on artwork')):
            item = b.appimage_catalog('demo')[0]
        registry = json.loads((b.cache_home() / 'icon-sources' / (item['icon_key'] + '.json')).read_text())
        self.assertEqual(registry['url'], 'https://appimage.github.io/database/Demo/icons/128x128/demo.png')
        self.assertEqual(item['catalog_url'], 'https://appimage.github.io/Demo/')
        self.assertFalse(item['installed'])

    def test_cached_icon_is_available_in_search_without_another_request(self):
        item = self.register();path = b.store_artwork(item['icon_key'], PNG)
        with patch.object(b, 'cached_artwork', side_effect=AssertionError('refetched artwork')):
            self.assertEqual(self.register()['icon'], path)
            self.assertEqual(b.load_catalog_icon(item['icon_key']), path)

    def test_unknown_key_cannot_trigger_caller_supplied_url(self):
        with patch.object(b, 'cached_artwork') as fetch:
            self.assertEqual(b.load_catalog_icon('a'*64), '')
            self.assertEqual(b.load_catalog_icon('../../etc/passwd'), '')
            fetch.assert_not_called()
        with self.assertRaises(b.AppCenterError):b.list_icons(dict(keys=['https://example.org/icon.png']))
        with self.assertRaises(b.AppCenterError):b.list_icons(dict(keys=['a'*64]*17))

    def test_corrupt_locator_is_not_used_under_a_different_key(self):
        item = self.register();p = b.cache_home() / 'icon-sources' / (item['icon_key'] + '.json')
        p.write_text(json.dumps(dict(kind='https', url='https://other.example/icon.png')))
        with patch.object(b, 'cached_artwork') as fetch:
            self.assertEqual(b.load_catalog_icon(item['icon_key']), '')
            fetch.assert_not_called()

    def test_nonpublic_and_non_https_catalog_artwork_keeps_fallback(self):
        for url in ['file:///etc/passwd','http://example.org/a.png','https://127.0.0.1/a.png','https://user:pw@example.org/a.png']:
            with self.subTest(url=url):self.assertNotIn('icon_key', self.register(url))
        self.assertEqual(b.appimage_artwork_locator(dict(icons='invalid')), {})
        self.assertEqual(b.snap_artwork_locator(dict(name='demo', media=[dict(type='icon', url='http://example.org/a')], icon=URL))['url'], URL)

    def test_installed_snap_artwork_comes_from_exact_unix_socket_endpoint(self):
        record = dict(name='demo', revision='23', icon='/v2/icons/demo/icon')
        item = b.catalog_icon({}, b.snap_artwork_locator(record))
        connection = Mock();response = connection.getresponse.return_value
        response.status = 200;response.read.return_value = PNG
        with patch.object(b, 'SnapHTTP', return_value=connection), patch.object(b, 'cached_artwork', side_effect=AssertionError('network used for installed icon')):
            path = b.load_catalog_icon(item['icon_key'])
        connection.request.assert_called_once_with('GET', '/v2/icons/demo/icon')
        connection.close.assert_called_once();self.assertEqual(Path(path).read_bytes(), PNG)
        self.assertNotEqual(item['icon_key'], b.catalog_icon({}, b.snap_artwork_locator(dict(record, revision='24')))['icon_key'])

    def test_bad_or_missing_snap_icon_keeps_generic_artwork(self):
        item = b.catalog_icon({}, dict(kind='snap', name='demo', revision='1'))
        connection = Mock();connection.getresponse.return_value.status = 404
        with patch.object(b, 'SnapHTTP', return_value=connection):self.assertEqual(b.load_catalog_icon(item['icon_key']), '')
        connection.getresponse.return_value.status = 200;connection.getresponse.return_value.read.return_value = b'<html>not an icon</html>'
        with patch.object(b, 'SnapHTTP', return_value=connection):self.assertEqual(b.load_catalog_icon(item['icon_key']), '')

    def test_compressed_appimage_svg_is_validated_and_cached(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64"/></svg>'
        item = self.register('https://appimage.github.io/Demo/icon.svgz')
        path = b.store_artwork(item['icon_key'], gzip.compress(svg))
        self.assertTrue(path.endswith('.svg'));self.assertEqual(Path(path).read_bytes(), svg)
        self.assertEqual(b.store_artwork(item['icon_key'], b'<html>error</html>', path), path)

    def test_svg_inline_gradients_and_filters_can_reference_local_ids(self):
        svg=b'<svg xmlns="http://www.w3.org/2000/svg"><path style="fill:url(#gradient);filter:url(#filter);opacity:0.5"/></svg>'
        self.assertEqual(b.artwork_format(svg), 'svg')
        for style in ('fill:url(https://example.org/external.svg)', 'fill:URL( file:///etc/passwd )', '@import "https://example.org/a.css"', r'fill:u\72l(https://example.org/a)'):
            raw=('<svg xmlns="http://www.w3.org/2000/svg"><style>'+style+'</style></svg>').encode()
            self.assertIsNone(b.artwork_format(raw))

    def test_svg_embedded_png_is_allowed_but_other_data_is_rejected(self):
        def svg(value):return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="'+value+'"/></svg>').encode()
        self.assertEqual(b.artwork_format(svg('data:image/png;base64,'+base64.b64encode(PNG).decode())), 'svg')
        self.assertIsNone(b.artwork_format(svg('data:image/svg+xml;base64,PHN2Zy8+')))
        self.assertIsNone(b.artwork_format(svg('data:image/png;base64,bm90IGEgcG5n')))
        self.assertIsNone(b.artwork_format(svg('https://example.org/external.png')))

    def test_offline_refresh_preserves_expired_icon(self):
        item = self.register();path = b.store_artwork(item['icon_key'], PNG);os.utime(path, (0, 0))
        with patch.object(b, 'public_https', return_value=True), patch.object(b.urllib.request, 'build_opener', side_effect=OSError('offline')):
            self.assertEqual(b.load_catalog_icon(item['icon_key']), path)

    def test_one_failed_icon_does_not_hide_successful_results(self):
        a, c = 'a'*64, 'c'*64
        def load(key):
            if key == a:raise OSError('unavailable')
            return '/cache/demo.png'
        with patch.object(b, 'load_catalog_icon', side_effect=load), patch.object(b, 'emit') as emit:
            b.list_icons(dict(keys=[a, c, c]))
        emit.assert_called_once_with(dict(event='icon', key=c, path='/cache/demo.png'))

    def test_details_rebuild_icon_key_from_provider_instead_of_caller(self):
        forged = self.register()['icon_key']
        info = dict(name='demo', title='Demo', media=[])
        with patch.object(b, 'snap_api', side_effect=[b.AppCenterError('not installed'),dict(result=[info])]), patch.object(b, 'launch_spec', return_value=None), patch.object(b, 'load_catalog_icon', return_value='') as load:
            b.app_details(dict(source='snap', id='demo', icon_key=forged))
        load.assert_called_once_with('')

    def test_read_only_cache_failure_does_not_break_catalog_results(self):
        with patch.object(b.Path, 'mkdir', side_effect=OSError('read only')):
            item = self.register()
        self.assertEqual(item['icon'], 'application-x-executable')
        self.assertNotIn('icon_key', item)

if __name__ == '__main__':unittest.main()
