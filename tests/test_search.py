"""Search contracts use catalog fixtures, never a popularity/name whitelist."""
import gzip
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backend', Path(__file__).parents[1] / 'backend/app_center_backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def app(name, **kw):
    return dict(dict(source='flatpak', id='org.example.' + name.replace(' ', ''), name=name,
                     summary='', categories=[], desktop_app=True), **kw)


class SearchTests(unittest.TestCase):
    def test_browser_synonyms_find_category_apps_without_brand_preferences(self):
        browsers = [app(name, categories=['Network', 'WebBrowser']) for name in ('Brave', 'Google Chrome', 'Firefox', 'An Unfamiliar App')]
        unrelated = [app('OBS', description='Includes a web browser plugin'),
                     app('Database Browser', categories=['Development']),
                     app('Inkscape', summary='Vector graphics editor', description='SVG works in web browsers')]
        for query in ('web browsers', 'web browser', 'browsers', 'internet browsers', 'WEB BROWSERS'):
            self.assertEqual({x['name'] for x in b.ranked_search(unrelated + browsers, query)},
                             {x['name'] for x in browsers})

    def test_helpers_and_nightly_builds_follow_desktop_browsers(self):
        browser = app('Stable', categories=['WebBrowser'])
        nightly = app('Stable Nightly', categories=['WebBrowser'])
        launcher = app('Browser Launcher', categories=['WebBrowser'])
        helper = app('chromium-sandbox', source='deb', summary='web browser - setuid security sandbox', desktop_app=False)
        incidental = app('IRC', source='deb', summary='Web browser based IRC client', desktop_app=False)
        self.assertEqual([x['name'] for x in b.ranked_search([helper, launcher, nightly, incidental, browser], 'web browsers')],
                         ['Stable', 'Stable Nightly', 'Browser Launcher'])

    def test_exact_app_and_exact_technical_package_precede_incidental_text(self):
        items = [app('Alpha Notes', summary='Use Firefox to open links'),
                 app('firefox-l10n-de', source='deb', summary='German language pack for Firefox', desktop_app=False),
                 app('Firefox')]
        self.assertEqual(b.ranked_search(items, 'firefox')[0]['name'], 'Firefox')
        self.assertEqual(b.ranked_search([app('Firefox', source='appimage', catalog=True), app('Firefox')], 'firefox')[0]['source'], 'flatpak')
        helper = app('libfoo-dev', source='deb', id='libfoo-dev', summary='Development files for foo', desktop_app=False)
        self.assertEqual(b.ranked_search([app('Foo'), helper], 'libfoo-dev'), [helper])

    def test_rank_before_limit(self):
        items = [app('AAA ' + str(n), summary='Links open in Firefox') for n in range(150)] + [app('Firefox')]
        self.assertEqual(b.ranked_search(items, 'firefox', limit=3)[0]['name'], 'Firefox')

    def test_multiword_query_matches_all_terms_across_short_fields(self):
        self.assertEqual([x['name'] for x in b.ranked_search([app('Paint', summary='Draw pictures'), app('Paint Only')], 'paint pictures')], ['Paint'])

    def test_source_completion_order_does_not_change_ranking(self):
        items = [app('Example', source='flatpak', remote=r, branch=branch, scope='system')
                 for r, branch in [('second', 'stable'), ('first', 'beta'), ('first', 'stable')]]
        self.assertEqual(b.ranked_search(items, 'example'), b.ranked_search(list(reversed(items)), 'example'))

    def test_appstream_reads_english_categories_keywords_and_legacy_desktop(self):
        xml = '''<components><component type="desktop"><id>org.example.Browser</id><pkgname>browser</pkgname>
        <name xml:lang="de">Deutsch</name><name>English</name><summary>Browse the web</summary>
        <categories><category>WebBrowser</category></categories><keywords><keyword>Internet</keyword></keywords>
        <keywords xml:lang="de"><keyword>Netz</keyword></keywords><provides><mediatype>x-scheme-handler/https</mediatype></provides>
        <bundle type="flatpak">app/org.example.Browser/x86_64/stable</bundle></component>
        <component type="addon"><id>org.example.Plugin</id><name>Plugin</name></component></components>'''
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / 'catalog.xml.gz'
            p.write_bytes(gzip.compress(xml.encode()))
            items = b.appstream_components([p])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['name'], 'English')
        self.assertEqual(items[0]['keywords'], ['Internet'])
        self.assertEqual(items[0]['categories'], ['WebBrowser'])
        self.assertIn('x-scheme-handler/https', items[0]['mediatypes'])

    def test_debian_search_uses_summaries_and_keeps_exact_name_after_many_matches(self):
        calls = []
        def run(args, **kw):
            calls.append(args)
            return ''.join(f'a-{n} - Open links with Firefox\n' for n in range(150)) + 'firefox - Mozilla web browser\n'
        with patch.object(b, 'run', side_effect=run), patch.object(b, 'appstream', return_value={}), patch.object(b, 'dpkg_installed', return_value=[]):
            results = b.deb_search('firefox')
        self.assertEqual(results[0]['id'], 'firefox')
        self.assertNotIn('--names-only', calls[0])
        with patch.object(b, 'run', return_value='') as run, patch.object(b, 'appstream', return_value={}), patch.object(b, 'dpkg_installed', return_value=[]):
            b.deb_search('c++')
        self.assertIn(r'c\+\+', run.call_args.args[0])

    def test_debian_category_matches_must_be_available_from_apt(self):
        metadata = {key: dict(name=name, summary='', categories=['WebBrowser'], desktop_app=True, pkgname=key)
                    for key, name in [('real', 'Real'), ('gone', 'Gone')]}
        def run(args, **kw):
            return 'real\n' if 'pkgnames' in args else ''
        with patch.object(b, 'run', side_effect=run), patch.object(b, 'appstream', return_value=metadata), patch.object(b, 'dpkg_installed', return_value=[]):
            self.assertEqual([x['id'] for x in b.deb_search('web browsers')], ['real'])

    def test_flatpak_category_lookup_joins_exact_available_refs_and_scopes(self):
        meta = {('org.example.App', 'x86_64', branch, 'flathub'): app('No Browser In Name', categories=['WebBrowser'])
                for branch in ('stable', 'beta', 'unavailable')}
        def run(args, **kw):
            if '--default-arch' in args: return 'x86_64\n'
            if 'remote-ls' in args: return 'org.example.App\tx86_64\tstable\tflathub\norg.example.App\tx86_64\tbeta\tflathub\n'
            if 'list' in args: return 'org.example.App\tstable\tflathub\tx86_64\n' if '--system' in args else ''
            if 'search' in args:
                self.assertEqual(args[-1], 'browser')
                return ''
            self.fail(args)
        with patch.object(b.shutil, 'which', return_value='/usr/bin/flatpak'), patch.object(b, 'run', side_effect=run), patch.object(b, 'flatpak_appstream', return_value=meta):
            items = b.flatpak_items('web browsers')
        self.assertEqual(len(items), 4)
        self.assertEqual({(i['scope'], i['branch']) for i in items}, {('user', 'stable'), ('system', 'stable'), ('user', 'beta'), ('system', 'beta')})
        self.assertEqual([(i['scope'], i['branch']) for i in items if i['installed']], [('system', 'stable')])
        self.assertTrue(all(i['arch'] == 'x86_64' and i['remote'] == 'flathub' for i in items))

    def test_snap_normalizes_category_and_filters_incidental_descriptions_and_bases(self):
        records = [dict(name='browser', title='Example', summary='Private web browser', type='app'),
                   dict(name='notes', summary='Take notes', description='Links open in a web browser', type='app'),
                   dict(name='base', summary='Web browser base', type='base')]
        def api(path):
            if path == '/v2/snaps': return {'result': []}
            self.assertEqual(path, '/v2/find?q=browser')
            return {'result': records}
        with patch.object(b, 'snap_api', side_effect=api):
            self.assertEqual([i['id'] for i in b.snap_items('web browsers')], ['browser'])

    def test_appimage_category_and_purpose_find_browsers_but_not_every_network_app(self):
        records = [dict(name='New Browser', categories=['WebBrowser']),
                   dict(name='Firefox', description='Browse the World Wide Web', categories=['Network']),
                   dict(name='Firefox_Nightly', description='Browse the Web', categories=['Network']),
                   dict(name='Notes', description='Links open in a web browser', categories=['Network'])]
        with patch.object(b, 'appimage_feed', return_value=records):
            result = b.appimage_catalog('web browsers')
        self.assertEqual({i['name'] for i in result}, {'New Browser', 'Firefox', 'Firefox_Nightly'})
        self.assertLess([i['name'] for i in result].index('Firefox'), [i['name'] for i in result].index('Firefox_Nightly'))
        self.assertTrue(all(i['catalog'] for i in result))

    def test_other_categories_do_not_treat_viewers_as_image_editors(self):
        records = [app('Paint', categories=['Graphics', 'RasterGraphics']),
                   app('Viewer', categories=['Graphics', 'RasterGraphics', 'Viewer']),
                   app('Writer', categories=['Office']), app('Editor', categories=['TextEditor'])]
        self.assertEqual([i['name'] for i in b.ranked_search(records, 'image editors')], ['Paint'])
        self.assertEqual([i['name'] for i in b.ranked_search(records, 'text editors')], ['Editor'])

    def test_installed_and_updates_keep_inventory_order_and_local_filter(self):
        records = [app('Zed'), app('Alpha')]
        with patch.object(b, 'inventory_provider', return_value=records):
            self.assertEqual([i['name'] for i in b.listing({'mode': 'updates', 'source': 'flatpak'})['items']], ['Alpha', 'Zed'])
            filtered = b.listing({'mode': 'installed', 'source': 'flatpak', 'query': 'Zed'})
        self.assertEqual(filtered['total'], 1)
        self.assertEqual(filtered['items'][0]['name'], 'Zed')

    def test_one_failed_search_provider_does_not_hide_ranked_results(self):
        def provider(source, mode, query):
            if source == 'snap': raise b.AppCenterError('offline')
            return [app('Other', description='Firefox can view links'), app('Firefox')]
        with patch.object(b, 'inventory_provider', side_effect=provider):
            result = b.listing({'mode': 'search', 'query': 'firefox'})
        self.assertEqual(result['items'][0]['name'], 'Firefox')
        self.assertEqual(result['warnings'], ['snap: offline'])


if __name__ == '__main__':
    unittest.main()
