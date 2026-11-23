import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from scripts.translate_catalog import translate_field, update_catalog
from translation_cache import cached_translation, fingerprint, read_cache

state = tempfile.TemporaryDirectory()
unittest.addModuleCleanup(state.cleanup)
with patch.dict(os.environ, {'MODHUB_DB': str(Path(state.name) / 'catalog.db')}):
    import server


class TranslationCacheTests(unittest.TestCase):
    def test_translation_preserves_prefix_and_protected_terms(self):
        original = '[CP] Install SMAPI v4.3.2 at https://example.com/mod.'

        def translate(masked):
            self.assertNotIn('[CP]', masked)
            self.assertNotIn('https://', masked)
            return '访问 [900003] 安装 [900001] [900002]。'

        self.assertEqual(
            translate_field(original, translate),
            '[CP] 访问 https://example.com/mod 安装 SMAPI v4.3.2。',
        )
        self.assertEqual(translate_field(original, lambda _: '安装最新版。'), '')

    def test_partial_cache_and_source_updates(self):
        item = {'id': '1', 'name': 'Example', 'summary': 'Details'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.json'
            cache = {}
            self.assertEqual(
                update_catalog([item], cache, 1,
                               lambda text: '示例' if text == 'Example' else text, path),
                (1, 1),
            )
            self.assertEqual(cached_translation(read_cache(path), '1', 'Example', 'Details'),
                             ('示例', ''))
            with patch('scripts.translate_catalog.translate_field',
                       side_effect=AssertionError('An unchanged record must be reused')):
                self.assertEqual(update_catalog([item], cache, 1, str, path), (0, 0))
            self.assertIsNone(cached_translation(cache, '1', 'Example', 'New details'))
            item['summary'] = 'New details'
            self.assertEqual(
                update_catalog([item], cache, 1, lambda _: '新译文', path), (1, 1)
            )

    def test_curated_text_takes_precedence(self):
        m = server.entry('curseforge:1', 'Tractor Mod', 'A vehicle', 'https://example.com',
                         source='curseforge', source_id='1')
        cache = {'1': {'fingerprint': fingerprint(m['title'], m['summary']),
                       'zh_title': '机器译文', 'zh_summary': '机器简介'}}
        translated = server.translate_mod(m, cache)
        self.assertEqual(translated['zh_title'], '拖拉机 MOD')
        self.assertIn('拖拉机', translated['zh_summary'])
        self.assertEqual(translated['android_status'], 'untested')

    def test_upsert_preserves_review_status_and_invalidates_changed_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, 'DB', Path(tmp) / 'old.db'):
                server.init()
                kwargs = {'uid': 'curseforge:1', 'source': 'curseforge',
                          'title': 'Example', 'url': 'https://example.com'}
                mod = server.entry(**kwargs, summary='Details', zh_title='示例',
                                   zh_summary='简介')
                mod['android_status'] = 'verified'
                with server.db() as conn:
                    server.upsert(conn, mod)
                    server.upsert(conn, server.entry(**kwargs, summary='Details'),
                                  retain_translation=True)
                    row = conn.execute('SELECT * FROM mods').fetchone()
                    self.assertEqual((row['zh_title'], row['zh_summary']), ('示例', '简介'))
                    server.upsert(conn, server.entry(**kwargs, summary='Changed'),
                                  retain_translation=True)
                    row = conn.execute('SELECT * FROM mods').fetchone()
                    self.assertEqual((row['zh_title'], row['zh_summary']), ('', ''))
                    self.assertEqual(row['android_status'], 'verified')


class CatalogApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def test_deployable_snapshot_and_coverage(self):
        snapshot = json.loads((server.ROOT / 'data' / 'curseforge.json').read_text('utf-8'))
        mods = {str(row['id']): row for row in snapshot['items']}
        cache = read_cache()
        response = self.client.get('/api/stats')
        self.assertEqual(response.status_code, 200)
        stats = response.json()
        self.assertEqual(stats['total'], len(mods) + len(server.SEED))
        self.assertEqual(stats['release']['version'], '0.4.0')
        rows = []
        for page in range(1, (stats['total'] + 99) // 100 + 1):
            response = self.client.get('/api/mods', params={'page': page, 'size': 100})
            self.assertEqual(response.status_code, 200)
            rows.extend(response.json()['items'])
        self.assertEqual(len(rows), stats['total'])
        self.assertEqual(len({r['uid'] for r in rows}), stats['total'])
        self.assertEqual(sum(bool(r['zh_title']) for r in rows), stats['translation']['titles'])
        expected = sum(bool(r['zh_title'] and r['zh_summary']) for r in rows)
        self.assertEqual(expected, stats['translation']['complete'])
        machine_mods = 0
        for row in rows:
            if row['source'] != 'curseforge':
                continue
            ident = row['uid'].split(':', 1)[1]
            item = mods[ident]
            self.assertEqual((row['title'], row['summary'], row['url'], row['version']),
                             (item['name'], item['summary'], item['url'], item['version']))
            self.assertEqual(row['android_status'], 'untested')
            translated = cached_translation(cache, ident, row['title'], row['summary'])
            if translated and cache[ident]['method'] == 'argos' and all(translated):
                self.assertEqual((row['zh_title'], row['zh_summary']), translated)
                machine_mods += 1
        self.assertGreater(machine_mods, 0)

    def test_search_and_pwa_routes(self):
        for query in ('拖拉机', 'Tractor Mod'):
            results = self.client.get('/api/mods', params={'q': query}).json()['items']
            self.assertIn('seed:tractor', {item['uid'] for item in results})
        for route in ('/', '/manifest.webmanifest', '/sw.js', '/icon.svg'):
            self.assertEqual(self.client.get(route).status_code, 200)
        self.assertEqual(self.client.get('/**?utm_source=chatgpt').status_code, 404)
        self.assertEqual(self.client.get('/unknown-page').status_code, 404)
