"""Read and write the shared Chinese translation cache."""
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

CACHE_PATH = Path(__file__).resolve().parent / 'data' / 'zh_translations.json'


def fingerprint(title, summary):
    return hashlib.sha256((title + '\0' + summary).encode('utf-8')).hexdigest()


def read_cache(path=CACHE_PATH):
    try:
        cache = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    if not isinstance(cache, dict):
        raise ValueError('Translation cache must be a JSON object')
    return cache


def cached_translation(cache, source_id, title, summary):
    record = cache.get(str(source_id))
    if not isinstance(record, dict) or record.get('fingerprint') != fingerprint(title, summary):
        return None
    zh_title, zh_summary = record.get('zh_title'), record.get('zh_summary')
    if isinstance(zh_title, str) and zh_title.strip() and isinstance(zh_summary, str):
        if zh_summary.strip() or not summary.strip():
            return zh_title, zh_summary
    return None


def write_cache(cache, path=CACHE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    output = NamedTemporaryFile(dir=path.parent, mode='w', encoding='utf-8', delete=False)
    temporary = Path(output.name)
    try:
        with output:
            json.dump(cache, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write('\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
