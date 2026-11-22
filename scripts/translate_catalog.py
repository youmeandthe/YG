"""Incrementally translate the CurseForge snapshot to Simplified Chinese."""
import argparse
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from translation_cache import CACHE_PATH, cached_translation, fingerprint, read_cache, write_cache
from zh_catalog import enrich


def argos_translator(install_model):
    from argostranslate import package
    from ctranslate2 import Translator

    def english_to_chinese(models):
        return next((model for model in models
                     if model.from_code == 'en' and model.to_code == 'zh'), None)

    model = english_to_chinese(package.get_installed_packages())
    if model is None and install_model:
        package.update_package_index()
        available = english_to_chinese(package.get_available_packages())
        if available is None:
            raise RuntimeError('No English → Chinese model was found in the Argos index.')
        package.install_from_path(available.download())
        model = english_to_chinese(package.get_installed_packages())
    if model is None:
        raise RuntimeError('Install the English → Chinese Argos model with --install-model.')

    # Catalog fields are short. Run the packaged model directly so inference
    # needs no separate sentence-boundary model or first-run network request.
    engine = Translator(str(model.package_path / 'model'), device='cpu', intra_threads=2)

    def translate(text):
        result = engine.translate_batch(
            [model.tokenizer.encode(text)], replace_unknowns=True,
            max_input_length=0, max_decoding_length=1024, length_penalty=0.2,
        )[0]
        return model.tokenizer.decode(result.hypotheses[0])

    return translate


def translate_field(text, translate):
    text = text.strip()
    if not text or not re.search(r'[A-Za-z]', text):
        return text
    result = translate(text).strip()
    if not result:
        raise ValueError('Translator returned empty text')
    return result


def update_catalog(items, cache, limit, translate, path):
    machine_count = 0
    updated_count = 0
    for item in items:
        source_id = str(item.get('id') or '')
        title = str(item.get('name') or source_id)
        summary = str(item.get('summary') or '')
        if not source_id or not title.strip():
            continue

        zh_title, zh_summary, _ = enrich(title, summary)
        if zh_title and zh_summary:
            method = 'curated'
        else:
            if cached_translation(cache, source_id, title, summary):
                continue
            if translate is None or machine_count >= limit:
                continue
            zh_title = translate_field(title, translate)
            zh_summary = translate_field(summary, translate)
            method = 'argos'
            machine_count += 1

        record = {'fingerprint': fingerprint(title, summary), 'zh_title': zh_title,
                  'zh_summary': zh_summary, 'method': method}
        if cache.get(source_id) != record:
            cache[source_id] = record
            updated_count += 1
            write_cache(cache, path)

    return updated_count, machine_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=30, help='Maximum new machine translations')
    parser.add_argument('--engine', choices=('curated', 'argos'), default='curated')
    parser.add_argument('--install-model', action='store_true', help='Download the Argos en→zh model')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'data' / 'curseforge.json')
    parser.add_argument('--cache', type=Path, default=CACHE_PATH)
    args = parser.parse_args()
    if not 0 <= args.limit <= 500:
        parser.error('--limit must be between 0 and 500')
    if args.install_model and args.engine != 'argos':
        parser.error('--install-model requires --engine argos')

    payload = json.loads(args.catalog.read_text(encoding='utf-8'))
    if payload.get('source') != 'curseforge' or not isinstance(payload.get('items'), list):
        parser.error('Expected a CurseForge catalog snapshot')
    cache = read_cache(args.cache)
    translate = None
    if args.engine == 'argos' and args.limit:
        translate = argos_translator(args.install_model)
    updated, machine = update_catalog(payload['items'], cache, args.limit, translate, args.cache)
    if not args.cache.exists():
        write_cache(cache, args.cache)
    print(f'Updated {updated} translations ({machine} by Argos); cache contains {len(cache)} records.')


if __name__ == '__main__':
    main()
