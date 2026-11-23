"""Stardew Mod Hub v0.4: permission-aware metadata index and Chinese search."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from translation_cache import CACHE_PATHS, cached_translation, read_cache
from zh_catalog import enrich, query_terms

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv('MODHUB_DB', str(ROOT / 'mods.db')))
GAME_ID = int(os.getenv('CURSEFORGE_GAME_ID', '669'))
app = FastAPI(title='Stardew Mod Hub', version='0.4.0')


@contextmanager
def db():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS mods (
            uid TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
            title TEXT NOT NULL, summary TEXT DEFAULT '', category TEXT DEFAULT '其他',
            url TEXT NOT NULL, image TEXT DEFAULT '', updated INTEGER DEFAULT 0,
            version TEXT DEFAULT '', downloads INTEGER DEFAULT 0,
            android_status TEXT DEFAULT 'untested',
            zh_title TEXT DEFAULT '', zh_summary TEXT DEFAULT '', raw TEXT DEFAULT '{}')''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_mod_title ON mods(title)')
        c.execute('''CREATE TABLE IF NOT EXISTS sync_state
                     (source TEXT PRIMARY KEY, last_sync INTEGER, count INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS mod_aliases
                     (alias_uid TEXT PRIMARY KEY, mod_uid TEXT NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_mod_aliases_target ON mod_aliases(mod_uid)')


def upsert(c, m, *, retain_translation=False):
    c.execute('''INSERT INTO mods
            (uid,source,source_id,title,summary,category,url,image,updated,version,
             downloads,android_status,zh_title,zh_summary,raw)
            VALUES (:uid,:source,:source_id,:title,:summary,:category,:url,:image,
                    :updated,:version,:downloads,:android_status,:zh_title,:zh_summary,:raw)
            ON CONFLICT(uid) DO UPDATE SET
                title=excluded.title, summary=excluded.summary,
                category=excluded.category, url=excluded.url, image=excluded.image,
                updated=excluded.updated, version=excluded.version,
                downloads=excluded.downloads,
                zh_title=CASE WHEN :retain_translation AND mods.title=excluded.title
                              AND mods.summary IS excluded.summary AND excluded.zh_title=''
                              THEN mods.zh_title ELSE excluded.zh_title END,
                zh_summary=CASE WHEN :retain_translation AND mods.title=excluded.title
                                AND mods.summary IS excluded.summary AND excluded.zh_summary=''
                                THEN mods.zh_summary ELSE excluded.zh_summary END,
                raw=excluded.raw''', dict(m, retain_translation=retain_translation))
    # android_status deliberately NOT overwritten: compatibility needs real testing.


def entry(uid, title, summary, url, source='curated', source_id='',
          category='其他', image='', version='', downloads=0, raw='{}',
          zh_title='', zh_summary=''):
    return dict(uid=uid, source=source, source_id=source_id or uid,
                title=str(title), summary=str(summary), category=category,
                url=url, image=image, updated=int(time.time()), version=version,
                downloads=downloads, android_status='untested',
                zh_title=zh_title, zh_summary=zh_summary, raw=raw)


def load_translation_cache(source='curseforge'):
    try:
        return read_cache(CACHE_PATHS[source], missing_ok=False)
    except (OSError, ValueError) as exc:
        print('Translation cache load failed:', exc)
        return None


def translate_mod(m, translations=None):
    zh_title, zh_summary, category = enrich(m['title'], m['summary'])
    zh_title = zh_title or m['zh_title']
    zh_summary = zh_summary or m['zh_summary']
    if translations:
        cached = cached_translation(translations, m['source_id'], m['title'], m['summary'])
        if cached:
            zh_title = zh_title or cached[0]
            zh_summary = zh_summary or cached[1]
    m['zh_title'] = zh_title
    m['zh_summary'] = zh_summary
    m['category'] = category
    return m


SEED = [
    ('gmcm', 'Generic Mod Config Menu', '游戏内 MOD 设置菜单', '5098'),
    ('npc', 'NPC Map Locations', '在地图上查看村民位置', '239'),
    ('lookup', 'Lookup Anything', '查询游戏物品与人物信息', '541'),
    ('automate', 'Automate', '自动化箱子和加工设备', '1063'),
    ('chests', 'Chests Anywhere', '远程访问箱子', '518'),
    ('tractor', 'Tractor Mod', '农场拖拉机', '1401'),
    ('ranch', 'Better Ranching', '牧场动物管理提示', '859'),
    ('skull', 'Skull Cavern Elevator', '骷髅洞穴电梯', '963'),
    ('patcher', 'Content Patcher', '内容包框架', '1915'),
    ('sve', 'Stardew Valley Expanded', '大型剧情与地图扩展', '3753'),
]
CURATED = [
    entry(
        'curated:cjb-item-spawner-android',
        'CJB Item Spawner (Android)',
        'Android SMAPI port of the in-game item spawner, with fixes for search and '
        'scrolling through the item list.',
        'https://github.com/NRTnarathip/SDV-Mods/releases/tag/2.5.1-android',
        category='工具',
        version='2.5.1 Android',
        zh_title='CJB 物品生成器安卓版',
        zh_summary='适用于安卓 SMAPI 的 CJB 物品生成器移植版。可在游戏内搜索并生成物品，'
                   '此版本修复了安卓端的搜索框和物品列表滚动。',
    ) | {'updated': 1734279845},
]


def seed_catalog():
    with db() as c:
        if not c.execute('SELECT 1 FROM mods LIMIT 1').fetchone():
            for key, name, summary, nexus_id in SEED:
                mod = entry('seed:' + key, name, summary,
                            'https://www.nexusmods.com/stardewvalley/mods/' + nexus_id)
                upsert(c, translate_mod(mod))
        for mod in CURATED:
            upsert(c, mod)


def nexus_id(url):
    parts = urlsplit(url)
    path = parts.path.strip('/').split('/')
    if (parts.hostname in ('nexusmods.com', 'www.nexusmods.com')
            and len(path) == 3 and path[:2] == ['stardewvalley', 'mods']
            and path[2].isdecimal()):
        return path[2]
    return None


def link_nexus_projects(c, items):
    rows = {row['uid']: row for row in c.execute(
        'SELECT uid, source, source_id, url, android_status FROM mods'
    )}
    curseforge = {row['source_id']: uid for uid, row in rows.items()
                  if row['source'] == 'curseforge'}
    curated = {}
    for uid, row in rows.items():
        if row['source'] == 'curated' and (ident := nexus_id(row['url'])):
            curated[ident] = uid

    aliases = []
    for item in items:
        ident = item['id']
        linked = [
            uid for uid in (curseforge.get(item.get('curseforge_id')), curated.get(ident),
                            'nexus:' + ident)
            if uid in rows
        ]
        # A compatibility result belongs to its own release and download link.
        primary = next((uid for uid in linked if rows[uid]['android_status']
                        in ('verified', 'incompatible')), linked[0])
        aliases.extend((uid, primary) for uid in linked if uid != primary)

    c.execute('DELETE FROM mod_aliases')
    c.executemany('INSERT INTO mod_aliases(alias_uid, mod_uid) VALUES (?, ?)', aliases)


def load_snapshot(source='curseforge'):
    """Load checked-in catalog at startup, even if Render SQLite resets."""
    snapshot = ROOT / 'data' / (source + '.json')
    if not snapshot.is_file():
        return
    try:
        payload = json.loads(snapshot.read_text(encoding='utf-8'))
        if payload.get('source') != source:
            return
        items = payload['items']
        imported = []
        translations = load_translation_cache(source)
        with db() as c:
            for m in items:
                ident = str(m['id'])
                url = str(m.get('url') or '')
                if not url.startswith('https://'):
                    continue
                mod = entry(source + ':' + ident, str(m.get('name') or ident),
                            str(m.get('summary') or ''), url, source=source,
                            source_id=ident, image=str(m.get('image') or ''),
                            version=str(m.get('version') or ''),
                            downloads=int(m.get('downloads') or 0))
                mod['updated'] = int(m.get('updated') or 0)
                upsert(c, translate_mod(mod, translations), retain_translation=translations is None)
                imported.append(m | {'id': ident})
            if source == 'nexus':
                if not imported:
                    raise ValueError('Empty Nexus snapshot')
                current = {'nexus:' + item['id'] for item in imported}
                stale = c.execute("SELECT uid FROM mods WHERE source='nexus'").fetchall()
                c.executemany('DELETE FROM mods WHERE uid=?',
                              ((row['uid'],) for row in stale if row['uid'] not in current))
                link_nexus_projects(c, imported)
            c.execute('INSERT OR REPLACE INTO sync_state VALUES (?,?,?)',
                      (source + '_snapshot', int(time.time()), len(imported)))
        print(f'Loaded {source} snapshot:', len(imported))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f'{source} snapshot load failed:', exc)


init()
seed_catalog()
load_snapshot()
load_snapshot('nexus')


@app.get('/api/mods')
def mods(q: str = '', category: str = '', status: str = '', source: str = '',
         page: int = Query(1, ge=1), size: int = Query(24, ge=1, le=100),
         sort: str = 'updated'):
    clauses, args = ['uid NOT IN (SELECT alias_uid FROM mod_aliases)'], []
    if q.strip():
        parts = []
        for term in query_terms(q):
            parts.append('''(title LIKE ? OR summary LIKE ? OR zh_title LIKE ? OR zh_summary LIKE ?
                OR uid IN (SELECT a.mod_uid FROM mod_aliases a JOIN mods alias
                           ON alias.uid=a.alias_uid WHERE alias.title LIKE ? OR alias.zh_title LIKE ?))''')
            args.extend(['%' + term + '%'] * 6)
        if parts:
            clauses.append('(' + ' OR '.join(parts) + ')')
    if category:
        clauses.append('category=?')
        args.append(category)
    if status:
        clauses.append('android_status=?')
        args.append(status)
    if source:
        clauses.append('''(source=? OR uid IN (SELECT a.mod_uid FROM mod_aliases a JOIN mods alias
                           ON alias.uid=a.alias_uid WHERE alias.source=?))''')
        args.extend([source, source])
    where = ' WHERE ' + ' AND '.join(clauses)
    order = {'updated': 'updated DESC', 'popular': 'downloads DESC',
             'name': 'title COLLATE NOCASE ASC'}.get(sort, 'updated DESC')
    with db() as c:
        total = c.execute('SELECT COUNT(*) FROM mods' + where, args).fetchone()[0]
        rows = c.execute('''SELECT uid,source,title,summary,category,url,image,updated,
                                  version,downloads,android_status,zh_title,zh_summary
                           FROM mods''' + where + ' ORDER BY ' + order + ', uid' +
                         ' LIMIT ? OFFSET ?', args + [size, (page - 1) * size]).fetchall()
        items = {row['uid']: dict(row, aliases=[], alternate_links=[]) for row in rows}
        if items:
            slots = ','.join('?' for _ in items)
            links = c.execute('''SELECT a.mod_uid, m.uid, m.source, m.url
                                 FROM mod_aliases a JOIN mods m ON m.uid=a.alias_uid
                                 WHERE a.mod_uid IN (''' + slots + ''')
                                 ORDER BY CASE m.source WHEN 'nexus' THEN 0 ELSE 1 END, m.uid''',
                              list(items))
            urls = {uid: {item['url']} for uid, item in items.items()}
            for link in links:
                uid = link['mod_uid']
                items[uid]['aliases'].append(link['uid'])
                if link['url'] not in urls[uid]:
                    items[uid]['alternate_links'].append({'source': link['source'], 'url': link['url']})
                    urls[uid].add(link['url'])
    return {'total': total, 'page': page, 'size': size, 'items': list(items.values())}


@app.get('/api/stats')
def stats():
    with db() as c:
        counts = dict(c.execute('''
            WITH translated AS (
                SELECT TRIM(COALESCE(zh_title, '')) != '' AS title,
                       TRIM(COALESCE(zh_summary, '')) != '' AS summary
                FROM mods WHERE uid NOT IN (SELECT alias_uid FROM mod_aliases)
            )
            SELECT COUNT(*) AS total, COUNT(CASE WHEN title THEN 1 END) AS titles,
                   COUNT(CASE WHEN summary THEN 1 END) AS summaries,
                   COUNT(CASE WHEN title AND summary THEN 1 END) AS complete,
                   COUNT(CASE WHEN NOT title AND NOT summary THEN 1 END) AS untranslated
            FROM translated
        ''').fetchone())
        state = [dict(row) for row in c.execute('SELECT * FROM sync_state')]
        aliases = c.execute('SELECT COUNT(*) FROM mod_aliases').fetchone()[0]
    total = counts.pop('total')
    coverage = {field: round(counts[field] * 100 / total, 2) if total else 0
                for field in ('titles', 'summaries', 'complete')}
    return {'total': total, 'sources': state, 'duplicates_collapsed': aliases,
            'translation': dict(counts, coverage_percent=coverage),
            'release': {'version': app.version, 'branch': os.getenv('RENDER_GIT_BRANCH'),
                        'commit': os.getenv('RENDER_GIT_COMMIT')},
            'target_game': '1.6.15.3', 'target_smapi': '4.3.2.1'}


@app.post('/api/sync/curseforge')
async def sync_curseforge(x_admin_token: str | None = Header(None),
                         pages: int = Query(3, ge=1, le=30)):
    token = os.getenv('ADMIN_TOKEN')
    if not token or x_admin_token != token:
        raise HTTPException(403, 'Admin token required')
    key = os.getenv('CURSEFORGE_API_KEY')
    if not key:
        raise HTTPException(400, 'Set CURSEFORGE_API_KEY first')
    total, errors = 0, []
    translations = load_translation_cache()
    async with httpx.AsyncClient(timeout=25) as client:
        for p in range(pages):
            try:
                response = await client.get(
                    'https://api.curseforge.com/v1/mods/search',
                    headers={'x-api-key': key, 'Accept': 'application/json'},
                    params={'gameId': GAME_ID, 'pageSize': 50, 'index': p * 50,
                            'sortField': 3, 'sortOrder': 'desc'})
                response.raise_for_status()
                data = response.json().get('data', [])
                if not data:
                    break
                count = 0
                with db() as c:
                    for m in data:
                        ident = str(m.get('id') or '')
                        if not ident:
                            continue
                        url = (m.get('links') or {}).get('websiteUrl') or ''
                        if not url.startswith('https://'):
                            continue
                        logo = m.get('logo') or {}
                        latest = m.get('latestFiles') or []
                        mod = entry('curseforge:' + ident, m.get('name') or ident,
                                    m.get('summary') or '', url, source='curseforge',
                                    source_id=ident, image=logo.get('thumbnailUrl') or '',
                                    version=str(latest[0].get('displayName') or '') if latest else '',
                                    downloads=int(m.get('downloadCount') or 0),
                                    raw=json.dumps({'id': ident, 'slug': m.get('slug')},
                                                   ensure_ascii=False))
                        upsert(c, translate_mod(mod, translations),
                               retain_translation=translations is None)
                        count += 1
                total += count
                if len(data) < 50:
                    break
            except (httpx.HTTPError, ValueError, TypeError, sqlite3.Error) as exc:
                errors.append(str(exc))
                break
    with db() as c:
        c.execute('INSERT OR REPLACE INTO sync_state VALUES (?,?,?)',
                  ('curseforge', int(time.time()), total))
    return {'imported': total, 'errors': errors,
            'note': 'Metadata only. Android compatibility remains untested.'}


@app.get('/manifest.webmanifest')
def manifest():
    return FileResponse(ROOT / 'static' / 'manifest.webmanifest',
                        media_type='application/manifest+json')


@app.get('/sw.js')
def worker():
    return FileResponse(ROOT / 'static' / 'sw.js',
                        media_type='application/javascript')


class WebFiles(StaticFiles):
    def lookup_path(self, path):
        try:
            return super().lookup_path(path)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 123:
                # Windows rejects URL paths containing literal wildcard characters.
                return '', None
            raise


app.mount('/', WebFiles(directory=ROOT / 'static', html=True), name='web')
