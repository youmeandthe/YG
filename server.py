"""Stardew Mod Hub: permission-aware metadata index and PWA server."""
import os, json, sqlite3, time, re
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import httpx

ROOT=Path(__file__).resolve().parent
DB=Path(os.getenv('MODHUB_DB',str(ROOT/'mods.db')))
GAME_ID=int(os.getenv('CURSEFORGE_GAME_ID','669'))  # Stardew Valley; verify against provider before production
app=FastAPI(title='Stardew Mod Hub', version='0.1.0')

@contextmanager
def db():
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally: conn.close()

def init():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS mods (
          uid TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
          title TEXT NOT NULL, summary TEXT DEFAULT '', category TEXT DEFAULT '其他',
          url TEXT NOT NULL, image TEXT DEFAULT '', updated INTEGER DEFAULT 0,
          version TEXT DEFAULT '', downloads INTEGER DEFAULT 0,
          android_status TEXT DEFAULT 'untested',
          zh_title TEXT DEFAULT '', zh_summary TEXT DEFAULT '',
          raw TEXT DEFAULT '{}')''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_mod_title ON mods(title)')
        c.execute('''CREATE TABLE IF NOT EXISTS sync_state (source TEXT PRIMARY KEY, last_sync INTEGER, count INTEGER)''')
init()

def upsert(m):
    with db() as c:
        c.execute('''INSERT INTO mods(uid,source,source_id,title,summary,category,url,image,updated,version,downloads,android_status,zh_title,zh_summary,raw)
          VALUES (:uid,:source,:source_id,:title,:summary,:category,:url,:image,:updated,:version,:downloads,:android_status,:zh_title,:zh_summary,:raw)
          ON CONFLICT(uid) DO UPDATE SET title=excluded.title,summary=excluded.summary,category=excluded.category,
          url=excluded.url,image=excluded.image,updated=excluded.updated,version=excluded.version,
          downloads=excluded.downloads,raw=excluded.raw''',m)

def entry(uid,title,summary,url,source='curated',source_id='',category='其他',image='',version='',downloads=0,raw='{}',zh_title='',zh_summary=''):
    return dict(uid=uid,source=source,source_id=source_id or uid,title=title,summary=summary,
                category=category,url=url,image=image,updated=int(time.time()),version=version,
                downloads=downloads,android_status='untested',zh_title=zh_title,zh_summary=zh_summary,raw=raw)

# Small starter index. Not claimed Android compatible; actual compatibility needs launch testing.
SEED=[
 ('gmcm','Generic Mod Config Menu','游戏内 MOD 设置菜单','工具','5098'),
 ('npc','NPC Map Locations','在地图上查看村民位置','地图','239'),
 ('lookup','Lookup Anything','查询游戏物品与人物信息','工具','541'),
 ('automate','Automate','自动化箱子和加工设备','自动化','1063'),
 ('chests','Chests Anywhere','远程访问箱子','便利','518'),
 ('tractor','Tractor Mod','农场拖拉机','自动化','1401'),
 ('ranch','Better Ranching','牧场动物管理提示','便利','859'),
 ('skull','Skull Cavern Elevator','骷髅洞穴电梯','便利','963'),
 ('patcher','Content Patcher','内容包框架','框架','1915'),
 ('sve','Stardew Valley Expanded','大型剧情与地图扩展','扩展','3753'),
]
with db() as c:
    n=c.execute('SELECT COUNT(*) FROM mods').fetchone()[0]
if n==0:
    for key,name,summary,cat,nexus_id in SEED:
        upsert(entry('seed:'+key,name,summary,'https://www.nexusmods.com/stardewvalley/mods/'+nexus_id,
                     source='curated',category=cat,zh_title=name,zh_summary=summary))
    with db() as c:
        c.execute("UPDATE mods SET android_status='verified' WHERE uid='seed:gmcm'")

@app.get('/api/mods')
def mods(q:str='',category:str='',status:str='',source:str='',page:int=Query(1,ge=1),size:int=Query(24,ge=1,le=100),sort:str='updated'):
    clauses=[]; args=[]
    if q:
        clauses.append('(title LIKE ? OR summary LIKE ? OR zh_title LIKE ? OR zh_summary LIKE ?)')
        args += ['%'+q+'%']*4
    if category: clauses.append('category=?');args.append(category)
    if status: clauses.append('android_status=?');args.append(status)
    if source: clauses.append('source=?');args.append(source)
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    order={'updated':'updated DESC','popular':'downloads DESC','name':'title COLLATE NOCASE ASC'}.get(sort,'updated DESC')
    with db() as c:
        total=c.execute('SELECT COUNT(*) FROM mods'+where,args).fetchone()[0]
        rows=c.execute('SELECT uid,source,title,summary,category,url,image,updated,version,downloads,android_status,zh_title,zh_summary FROM mods'+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[size,(page-1)*size]).fetchall()
    return {'total':total,'page':page,'size':size,'items':[dict(r) for r in rows]}

@app.get('/api/stats')
def stats():
    with db() as c:
        count=c.execute('SELECT COUNT(*) FROM mods').fetchone()[0]
        state=[dict(r) for r in c.execute('SELECT * FROM sync_state')]
    return {'total':count,'sources':state,'target_game':'1.6.15.3','target_smapi':'4.3.2.1'}

@app.post('/api/sync/curseforge')
async def sync_curseforge(x_admin_token:str|None=Header(None),pages:int=Query(3,ge=1,le=30)):
    token=os.getenv('ADMIN_TOKEN')
    if not token or x_admin_token!=token: raise HTTPException(403,'Admin token required')
    key=os.getenv('CURSEFORGE_API_KEY')
    if not key: raise HTTPException(400,'Set CURSEFORGE_API_KEY first')
    total=0; errors=[]
    async with httpx.AsyncClient(timeout=25) as client:
        for p in range(pages):
            try:
                response=await client.get('https://api.curseforge.com/v1/mods/search',
                  headers={'x-api-key':key,'Accept':'application/json'},
                  params={'gameId':GAME_ID,'pageSize':50,'index':p*50,'sortField':3,'sortOrder':'desc'})
                response.raise_for_status()
                data=response.json().get('data',[])
                if not data: break
                for m in data:
                    ident=str(m.get('id',''))
                    if not ident: continue
                    links=m.get('links') or {}
                    url=links.get('websiteUrl') or ''
                    if not url.startswith('https://'): continue
                    logo=m.get('logo') or {}
                    latest=m.get('latestFiles') or []
                    mod=entry('curseforge:'+ident,m.get('name') or ident,m.get('summary') or '',url,
                      source='curseforge',source_id=ident,
                      category='其他',image=logo.get('thumbnailUrl') or '',
                      version=str(latest[0].get('displayName') or '') if latest else '',
                      downloads=int(m.get('downloadCount') or 0),raw=json.dumps({'id':ident,'slug':m.get('slug')},ensure_ascii=False))
                    upsert(mod);total+=1
                if len(data)<50: break
            except (httpx.HTTPError,ValueError) as exc:
                errors.append(str(exc));break
    with db() as c:
        c.execute('INSERT OR REPLACE INTO sync_state VALUES (?,?,?)',('curseforge',int(time.time()),total))
    return {'imported':total,'errors':errors,'note':'Only metadata indexed; files are not mirrored. Android compatibility is untested.'}

@app.get('/manifest.webmanifest')
def manifest(): return FileResponse(ROOT/'static'/'manifest.webmanifest',media_type='application/manifest+json')
@app.get('/sw.js')
def worker(): return FileResponse(ROOT/'static'/'sw.js',media_type='application/javascript')
app.mount('/',StaticFiles(directory=ROOT/'static',html=True),name='web')
