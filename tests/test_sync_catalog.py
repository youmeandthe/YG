import unittest

import httpx

from scripts import sync_catalog


class CurseForgePaginationTests(unittest.TestCase):
    def test_reads_all_reported_projects_beyond_500(self):
        seen = []

        def reply(request):
            params = request.url.params
            index = int(params['index'])
            size = int(params['pageSize'])
            seen.append(index)
            self.assertEqual(params['gameId'], '669')
            self.assertEqual(size, 50)
            self.assertEqual(params['sortOrder'], 'asc')
            batch = [{'id': i + 1} for i in range(index, min(index + size, 523))]
            return httpx.Response(200, json={
                'data': batch, 'pagination': {'index': index, 'totalCount': 523},
            })

        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            projects = sync_catalog.fetch_catalog(client, 669)
        self.assertEqual(seen, list(range(0, 523, 50)))
        self.assertEqual([item['id'] for item in projects], list(range(1, 524)))

    def test_restarts_when_results_shift_between_pages(self):
        seen = []

        def reply(request):
            index = int(request.url.params['index'])
            seen.append(index)
            batch = [{'id': i + 1} for i in range(index, min(index + 50, 51))]
            if seen == [0, 50]:
                batch = [{'id': 50}]
            return httpx.Response(200, json={
                'data': batch, 'pagination': {'index': index, 'totalCount': 51},
            })

        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            projects = sync_catalog.fetch_catalog(client, 669)
        self.assertEqual(seen, [0, 50, 0, 50])
        self.assertEqual(len(projects), 51)

    def test_repeated_incomplete_pages_fail_instead_of_returning_a_partial_catalog(self):
        def reply(_):
            return httpx.Response(200, json={
                'data': [{'id': 1}], 'pagination': {'index': 0, 'totalCount': 51},
            })

        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            with self.assertRaises(sync_catalog.CatalogChanged):
                sync_catalog.fetch_catalog(client, 669)

    def test_rejects_source_totals_above_the_single_query_limit(self):
        def reply(_):
            return httpx.Response(200, json={
                'data': [], 'pagination': {'index': 0, 'totalCount': 10_001},
            })

        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            with self.assertRaisesRegex(ValueError, 'above its 10000 search limit'):
                sync_catalog.fetch_catalog(client, 669)

    def test_metadata_uses_source_timestamp_and_requires_a_public_url(self):
        project = {
            'id': 7, 'name': 'Example', 'summary': 'Details',
            'dateModified': '2026-11-22T03:00:00Z',
            'links': {'websiteUrl': 'https://example.com/mod'},
        }
        item = sync_catalog.project_metadata(project)
        self.assertEqual(item['updated'], 1795316400)
        self.assertEqual((item['id'], item['name'], item['summary']), ('7', 'Example', 'Details'))
        self.assertIsNone(sync_catalog.project_metadata(dict(project, links={})))
