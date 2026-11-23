import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from scripts.sync_nexus_catalog import index_projects
from test_catalog import server


class NexusIndexTests(unittest.TestCase):
    def test_official_links_beat_names_and_same_nexus_page_is_indexed_once(self):
        records = [
            {'nexus': 6, 'curse': 1, 'name': 'Explicit Match', 'author': 'Original'},
            {'nexus': 6, 'name': 'Another component', 'author': 'Original'},
            {'nexus': 7, 'name': 'Same Name', 'author': 'Original'},
            {'nexus': 8, 'name': 'Second Name', 'author': 'different author'},
            {'nexus': 9, 'name': 'A hidden mod', 'author': 'Any', 'abandonedReason': 'hidden'},
            {'nexus': 12, 'name': 'Second Name', 'author': 'Original'},
        ]
        curseforge = [
            {'id': '1', 'name': 'Same Name', 'authors': ['Original']},
            {'id': '2', 'name': 'Second Name', 'authors': ['original']},
        ]
        indexed = {item['id']: item for item in index_projects(records, curseforge)}
        self.assertEqual({key: item['curseforge_id'] for key, item in indexed.items()},
                         {'6': '1', '7': '', '8': '', '12': '2'})
        self.assertEqual(indexed['6']['url'], 'https://www.nexusmods.com/stardewvalley/mods/6')

    def test_ambiguous_cross_platform_matches_are_kept_separate(self):
        records = [
            {'nexus': 6, 'curse': 1, 'name': 'Entry one', 'author': 'Same'},
            {'nexus': 7, 'curse': 1, 'name': 'Entry two', 'author': 'Same'},
        ]
        items = index_projects(records, [{'id': '1', 'name': 'Other'}])
        self.assertEqual([item['curseforge_id'] for item in items], ['', ''])


class NexusApiTests(unittest.TestCase):
    def test_links_search_and_favorite_aliases_share_one_card(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(server, 'DB', Path(temp) / 'test.db'):
            server.init()
            with server.db() as conn:
                server.upsert(conn, server.entry('curseforge:1', 'CurseForge name', '',
                                                 'https://www.curseforge.com/example',
                                                 source='curseforge', source_id='1'))
                server.upsert(conn, server.entry('nexus:85', 'Nexus mod name', '',
                                                 'https://www.nexusmods.com/stardewvalley/mods/85',
                                                 source='nexus', source_id='85', zh_title='其他名字'))
                server.upsert(conn, server.entry('seed:old', 'Original card', '',
                                                 'https://www.nexusmods.com/stardewvalley/mods/85'))
                server.link_nexus_projects(conn, [{'id': '85', 'curseforge_id': '1'}])
            with TestClient(server.app) as client:
                stats = client.get('/api/stats').json()
                self.assertEqual((stats['total'], stats['duplicates_collapsed']), (1, 2))
                mods = client.get('/api/mods', params={'q': '其他名字', 'source': 'nexus'}).json()
                self.assertEqual(mods['total'], 1)
                item = mods['items'][0]
                self.assertEqual(item['uid'], 'curseforge:1')
                self.assertEqual(set(item['aliases']), {'seed:old', 'nexus:85'})
                self.assertEqual(item['alternate_links'], [
                    {'source': 'nexus', 'url': 'https://www.nexusmods.com/stardewvalley/mods/85'},
                ])
                self.assertEqual(item['android_status'], 'untested')

    def test_existing_android_result_stays_with_its_download(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(server, 'DB', Path(temp) / 'test.db'):
            server.init()
            with server.db() as conn:
                cf = server.entry('curseforge:1', 'Example', '', 'https://www.curseforge.com/example',
                                  source='curseforge', source_id='1')
                nx = server.entry('nexus:85', 'Example', '', 'https://www.nexusmods.com/example',
                                  source='nexus', source_id='85')
                nx['android_status'] = 'verified'
                server.upsert(conn, cf)
                server.upsert(conn, nx)
                server.link_nexus_projects(conn, [{'id': '85', 'curseforge_id': '1'}])
            with TestClient(server.app) as client:
                item = client.get('/api/mods').json()['items'][0]
                self.assertEqual(item['uid'], 'nexus:85')
                self.assertEqual(item['android_status'], 'verified')
                self.assertEqual([link['source'] for link in item['alternate_links']], ['curseforge'])
