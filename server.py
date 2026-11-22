"""Stardew Mod Hub v0.4: permission-aware metadata index and Chinese search."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from translation_cache import cached_translation, read_cache
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


def upsert(m):
    with db() as c:
        c.execute('''INSERT INTO mods
            (uid,source,source_id,title,summary,category,url,image,updated,version,
             downloads,android_status,zh_title,zh_summary,raw)
            VALUES (:uid,:source,:source_id,:title,:summary,:category,:url,:image,
                    :updated,:version,:downloads,:android_status,:zh_title,:zh_summary,:raw)
            ON CONFLICT(uid) DO UPDATE SET
                title=excluded.title, summary=excluded.summary,
                category=excluded.category, url=excluded.url, image=excluded.image,
                updated=excluded.updated, version=excluded.version,
                downloads=excluded.downloads, zh_title=excluded.zh_title,
                zh_summary=excluded.zh_summary, raw=excluded.raw''', m)
    # android_status deliberately NOT overwritten: compatibility needs real testing.


def entry(uid, title, summary, url, source='curated', source_id='',
          category='其他', image='', version='', downloads=0, raw='{}',
          zh_title='', zh_summary=''):
    return dict(uid=uid, source=source, source_id=source_id or uid,
                title=str(title), summary=str(summary), category=category,
                url=url, image=image, updated=int(time.time()), version=version,
                downloads=downloads, android_status='untested',
                zh_title=zh_title, zh_summary=zh_summary, raw=raw)


def load_translation_cache():
    try:
        return read_cache()
    except (OSError, ValueError) as exc:
        print('Translation cache load failed:', exc)
        return {}


def translate_mod(m, translations=None):
    zh_title, zh_summary, category = enrich(m['title'], m['summary'])
    if m['source'] == 'curseforge' and translations:
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


def seed_catalog():
    with db() as c:
        count = c.execute('SELECT COUNT(*) FROM mods').fetchone()[0]
    if count:
        return
    for key, name, summary, nexus_id in SEED:
        mod = entry('seed:' + key, name, summary,
                    'https://www.nexusmods.com/stardewvalley/mods/' + nexus_id)
        upsert(translate_mod(mod))


def load_snapshot():
    """Load checked-in catalog at startup, even if Render SQLite resets."""
    snapshot = ROOT / 'data' / 'curseforge.json'
    if not snapshot.is_file():
        return
    try:
        payload = json.loads(snapshot.read_text(encoding='utf-8'))
        if payload.get('source') != 'curseforge':
            return
        count = 0
        translations = load_translation_cache()
        for m in payload.get('items', []):
            ident = str(m['id'])
            url = str(m.get('url') or '')
            if not url.startswith('https://'):
                continue
            mod = entry('curseforge:' + ident, str(m.get('name') or ident),
                        str(m.get('summary') or ''), url, source='curseforge',
                        source_id=ident, image=str(m.get('image') or ''),
                        version=str(m.get('version') or ''),
                        downloads=int(m.get('downloads') or 0))
            mod['updated'] = int(m.get('updated') or 0)
            upsert(translate_mod(mod, translations))
            count += 1
        with db() as c:
            c.execute('INSERT OR REPLACE INTO sync_state VALUES (?,?,?)',
                      ('curseforge_snapshot', int(time.time()), count))
        print('Loaded CurseForge snapshot:', count)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print('Snapshot load failed:', exc)


init()
seed_catalog()
load_snapshot()


@app.get('/api/mods')
def mods(q: str = '', category: str = '', status: str = '', source: str = '',
         page: int = Query(1, ge=1), size: int = Query(24, ge=1, le=100),
         sort: str = 'updated'):
    clauses, args = [], []
    if q.strip():
        parts = []
        for term in query_terms(q):
            parts.append('(title LIKE ? OR summary LIKE ? OR zh_title LIKE ? OR zh_summary LIKE ?)')
            args.extend(['%' + term + '%'] * 4)
        if parts:
            clauses.append('(' + ' OR '.join(parts) + ')')
    if category:
        clauses.append('category=?')
        args.append(category)
    if status:
        clauses.append('android_status=?')
        args.append(status)
    if source:
        clauses.append('source=?')
        args.append(source)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    order = {'updated': 'updated DESC', 'popular': 'downloads DESC',
             'name': 'title COLLATE NOCASE ASC'}.get(sort, 'updated DESC')
    with db() as c:
        total = c.execute('SELECT COUNT(*) FROM mods' + where, args).fetchone()[0]
        rows = c.execute('''SELECT uid,source,title,summary,category,url,image,updated,
                                  version,downloads,android_status,zh_title,zh_summary
                           FROM mods''' + where + ' ORDER BY ' + order +
                         ' LIMIT ? OFFSET ?', args + [size, (page - 1) * size]).fetchall()
    return {'total': total, 'page': page, 'size': size,
            'items': [dict(row) for row in rows]}


@app.get('/api/stats')
def stats():
    with db() as c:
        count = c.execute('SELECT COUNT(*) FROM mods').fetchone()[0]
        state = [dict(row) for row in c.execute('SELECT * FROM sync_state')]
    return {'total': count, 'sources': state,
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
                    upsert(translate_mod(mod, translations))
                    total += 1
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


app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='web')
