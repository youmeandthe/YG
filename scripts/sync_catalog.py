"""Fetch the public CurseForge catalog into a versioned metadata snapshot."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'curseforge.json'
SEARCH_URL = 'https://api.curseforge.com/v1/mods/search'
PAGE_SIZE = 50
SEARCH_LIMIT = 10_000
SORT_BY_NAME = 4


class CatalogChanged(RuntimeError):
    """The search result changed while its pages were being read."""


def fetch_projects(client, game):
    projects = {}
    index = 0
    total = None
    while total is None or index < total:
        response = client.get(SEARCH_URL, params={
            'gameId': game, 'pageSize': PAGE_SIZE, 'index': index,
            'sortField': SORT_BY_NAME, 'sortOrder': 'asc',
        })
        response.raise_for_status()
        payload = response.json()
        batch = payload['data']
        pagination = payload['pagination']
        reported_total = pagination['totalCount']
        if not isinstance(batch, list) or type(reported_total) is not int or reported_total < 0:
            raise ValueError('Unexpected CurseForge pagination response')
        if reported_total > SEARCH_LIMIT:
            raise ValueError(f'CurseForge reported {reported_total} projects, above its '
                             f'{SEARCH_LIMIT} search limit for one query')
        if total is None:
            total = reported_total
        if (reported_total != total or pagination['index'] != index
                or len(batch) != min(PAGE_SIZE, total - index)):
            raise CatalogChanged(f'Inconsistent CurseForge search page at index {index}')
        for project in batch:
            ident = project['id']
            if type(ident) is not int or ident <= 0:
                raise ValueError(f'Invalid CurseForge project ID at index {index}')
            if ident in projects:
                raise CatalogChanged(f'Duplicate CurseForge project {ident} at index {index}')
            projects[ident] = project
        index += len(batch)
    return projects.values()


def fetch_catalog(client, game):
    for attempt in range(1, 4):
        try:
            return fetch_projects(client, game)
        except CatalogChanged as exc:
            if attempt == 3:
                raise
            print(f'{exc}; restarting search ({attempt}/2).', file=sys.stderr)


def project_metadata(project):
    ident = str(project['id'])
    links = project.get('links') or {}
    url = links.get('websiteUrl') or ''
    if not url.startswith('https://'):
        return None
    latest = project.get('latestFiles') or []
    modified = project.get('dateModified')
    updated = int(datetime.fromisoformat(modified).timestamp()) if modified else 0
    return {
        'id': ident,
        'name': str(project.get('name') or ident),
        'summary': str(project.get('summary') or ''),
        'url': url,
        'image': str((project.get('logo') or {}).get('thumbnailUrl') or ''),
        'version': str(latest[0].get('displayName') or '') if latest else '',
        'downloads': int(project.get('downloadCount') or 0),
        'updated': updated,
        'authors': sorted({author['name'] for author in project.get('authors') or []
                           if author.get('name')}, key=lambda author: (author.casefold(), author)),
    }


def write_snapshot(payload, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    output = NamedTemporaryFile(dir=path.parent, mode='w', encoding='utf-8', delete=False)
    temporary = Path(output.name)
    try:
        with output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write('\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    key = os.getenv('CURSEFORGE_API_KEY', '').strip()
    game_id = os.getenv('CURSEFORGE_GAME_ID', '').strip()
    if not key or not game_id.isdecimal():
        sys.exit('Set CURSEFORGE_API_KEY and verified CURSEFORGE_GAME_ID.')
    game = int(game_id)
    with httpx.Client(timeout=35, headers={'x-api-key': key, 'Accept': 'application/json'}) as client:
        projects = fetch_catalog(client, game)
    items = [item for project in projects if (item := project_metadata(project)) is not None]
    if not items:
        sys.exit('No projects with a public HTTPS link; keeping existing snapshot.')
    items.sort(key=lambda item: (-item['updated'], int(item['id'])))
    write_snapshot({'source': 'curseforge', 'game_id': game, 'items': items}, OUT)
    print(f'Indexed {len(items)} CurseForge records from {len(projects)} API results '
          f'({len(projects) - len(items)} without a public HTTPS link).')


if __name__ == '__main__':
    main()
