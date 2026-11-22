"""Fetch public CurseForge metadata into a versioned JSON snapshot (no MOD binaries)."""
import json, os, sys, time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data'/'curseforge.json'

def main():
    key=os.environ.get('CURSEFORGE_API_KEY','').strip()
    game=os.environ.get('CURSEFORGE_GAME_ID','').strip()
    if not key or not game or not game.isdecimal():
        sys.exit('Set CURSEFORGE_API_KEY and verified CURSEFORGE_GAME_ID.')
    pages=max(1,min(int(os.getenv('SYNC_PAGES','10')),40))
    items={}
    with httpx.Client(timeout=35,follow_redirects=False) as client:
        for p in range(pages):
            response=client.get('https://api.curseforge.com/v1/mods/search',headers={'x-api-key':key,'Accept':'application/json'},params={'gameId':int(game),'pageSize':50,'index':p*50,'sortField':3,'sortOrder':'desc'})
            response.raise_for_status()
            batch=response.json().get('data',[])
            if not isinstance(batch,list): raise RuntimeError('Unexpected API response')
            for m in batch:
                mid=m.get('id')
                url=(m.get('links') or {}).get('websiteUrl') or ''
                if mid is None or not url.startswith('https://'): continue
                latest=m.get('latestFiles') or []
                items[str(mid)]={'id':str(mid),'name':str(m.get('name') or mid),'summary':str(m.get('summary') or ''),'url':url,'image':str((m.get('logo') or {}).get('thumbnailUrl') or ''),'version':str((latest[0].get('displayName') or '') if latest else ''),'downloads':int(m.get('downloadCount') or 0),'updated':int(time.time())}
            if len(batch)<50: break
    if not items: sys.exit('No entries received; keeping existing snapshot.')
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({'source':'curseforge','game_id':int(game),'items':list(items.values())},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Indexed {len(items)} CurseForge records')

if __name__=='__main__': main()
