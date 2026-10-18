"""Live regression check; never changes the published subtitles."""
import concurrent.futures
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import subtitle_app as app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model')
    parser.add_argument('--output', default='review-v2-live.json')
    args = parser.parse_args()
    settings = app.load_ai_settings()
    if args.model:
        settings['model'] = args.model
    cases = [('1249473580435700', 1, 20), ('1249473580435700', 488, 508),
             ('1249473580435700', 704, 720), ('8192218992254200', 195, 215),
             ('8192218992254200', 297, 312), ('8192218992254200', 365, 377),
             ('8192218992254200', 865, 885), ('8192218992254200', 915, 945)]
    inputs = {}
    for tid, _, _ in cases:
        if tid in inputs:
            continue
        folder = app.episode_dir(tid)
        item = json.loads((folder/'episode.json').read_text(encoding='utf-8'))
        source = app.parse_source((folder/'source.srt').read_text(encoding='utf-8-sig'), 'srt')
        state = app.load_translation_state(folder, source)
        profile = (app.agent.load_episode_profile(folder, app.source_fingerprint(source))
                   or app.agent.load_profile(app.LIBRARY, item))
        inputs[tid] = (item, source, state['translations'], profile)
    def run(case):
        tid, first, last = case
        item, source, translations, profile = inputs[tid]
        ids = list(range(first, last+1))
        started = time.monotonic()
        result = {'tvid': tid, 'first': first, 'last': last,
                  'sourceHash': app.source_fingerprint(source)}
        try:
            for attempt in range(2):
                try:
                    rows = app.request_translation(tid, settings, settings['apiKey'],
                        app.agent.review_prompt(item, source, translations, profile, ids), len(ids),
                        system=app.agent.REVIEW_SYSTEM, schema=app.agent.REVIEW_SCHEMA,
                        max_tokens=max(2048, len(ids)*120))
                    fixes = app.agent.validate_review(rows, source, translations, ids)
                    break
                except ValueError:
                    if attempt:
                        raise
            result.update(rows=rows, corrections=[{'id': int(i), 'source': source[int(i)-1][2],
                'before': translations[i], 'after': text} for i, text in fixes.items()])
        except Exception as exc:
            result['error'] = str(exc)[:400]
        result['seconds'] = round(time.monotonic()-started, 2)
        print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'corrections')}, ensure_ascii=False), flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, cases))
    app.atomic_write(ROOT/'subtitles/benchmarks'/args.output, json.dumps(
        {'model': settings['model'], 'cases': results}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
