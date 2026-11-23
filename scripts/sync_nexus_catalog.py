"""Index Nexus project links published in the licensed SMAPI community catalog."""
import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sync_catalog import write_snapshot

UPSTREAM = 'https://raw.githubusercontent.com/Pathoschild/SmapiCompatibilityList/develop/data/'
FILES = {'mods.jsonc': 'mods', 'broken-content-packs.jsonc': 'brokenContentPacks'}
NEXUS = 'https://www.nexusmods.com/stardewvalley/mods/'
MARKDOWN_LINK = re.compile(r'\[([^\[\]]+)\]\([^)]*\)')


def read_community_catalog(directory=None):
    import json5

    records = []
    with httpx.Client(timeout=35) as client:
        for name, key in FILES.items():
            text = ((directory / name).read_text(encoding='utf-8-sig') if directory else
                    client.get(UPSTREAM + name).raise_for_status().text)
            items = json5.loads(text)[key]
            if not isinstance(items, list) or not items:
                raise ValueError(f'Unexpected SMAPI catalog: {name}')
            records.extend(items)
    return records


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def project_key(name, author):
    return normalize(name), normalize(author)


def index_projects(records, curseforge):
    groups = defaultdict(list)
    for record in records:
        ident = record.get('nexus')
        if type(ident) is int and ident > 0 and record.get('abandonedReason') not in (
            'hidden', 'deleted',
        ):
            groups[ident].append(record)

    cf_ids = {item['id'] for item in curseforge}
    cf_by_identity = defaultdict(set)
    for item in curseforge:
        for author in item.get('authors', []):
            cf_by_identity[project_key(item['name'], author)].add(item['id'])

    results = []
    matches = defaultdict(list)
    for ident, group in sorted(groups.items()):
        primary = group[0]
        names = {name for mod in group for name in (mod['name'], *mod['name'].split(', '))}
        authors = {author for mod in group for author in mod['author'].split(', ') if author.strip()}
        declared = {str(mod['curse']) for mod in group if mod.get('curse')}
        candidates = declared & cf_ids
        if not declared:
            for name in names:
                for author in authors:
                    candidates.update(cf_by_identity[project_key(name, author)])
        note = next((mod['summary'] for mod in group if mod.get('summary')), '')
        note = ' '.join(MARKDOWN_LINK.sub(r'\1', note).split())
        item = {
            'id': str(ident),
            'name': primary['name'],
            'summary': 'SMAPI community note: ' + note if note else '',
            'url': NEXUS + str(ident),
            'authors': sorted(authors, key=lambda author: (author.casefold(), author)),
            'curseforge_id': next(iter(candidates)) if len(candidates) == 1 else '',
        }
        results.append(item)
        if item['curseforge_id']:
            matches[item['curseforge_id']].append((item, bool(declared)))

    for group in matches.values():
        direct = [item for item, declared in group if declared]
        candidates = direct or [item for item, _ in group]
        chosen = candidates[0] if len(candidates) == 1 else None
        for item, _ in group:
            if item is not chosen:
                item['curseforge_id'] = ''
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smapi-data', type=Path, help='Local checkout data directory')
    parser.add_argument('--curseforge', type=Path, default=ROOT / 'data' / 'curseforge.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'nexus.json')
    args = parser.parse_args()
    curseforge = json.loads(args.curseforge.read_text(encoding='utf-8'))['items']
    items = index_projects(read_community_catalog(args.smapi_data), curseforge)
    if not items:
        sys.exit('No eligible Nexus projects; keeping the previous snapshot.')
    write_snapshot({'source': 'nexus', 'items': items}, args.output)
    print(f'Indexed {len(items)} Nexus projects from SMAPI; found '
          f'{sum(bool(item["curseforge_id"]) for item in items)} CurseForge matches.')


if __name__ == '__main__':
    main()
