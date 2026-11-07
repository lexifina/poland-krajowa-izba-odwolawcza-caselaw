"""KIO decisions after SAOS (which stops at 2018-09-06), from the UZP's own portal orzeczenia.uzp.gov.pl, appended to the
krajowa-izba-odwolawcza repo, append-only.

The portal has no robots.txt (404) and states no reuse terms; KIO decisions are official documents outside copyright
(Art. 4 of the Polish Copyright Act). It is read politely: the result list by month (POST /Home/GetResults, 10 a page),
then each decision's text (GET /Home/PdfContent/<id>?Kind=KIO, a PDF read with PyMuPDF, never kept).

  python -X utf8 kio_uzp.py fetch [--from 2018-09-06] [--to YYYY-MM-DD] [--rate 6]   -> cache/uzp/records/<id>.json.gz
  python -X utf8 kio_uzp.py append [--push]                                            -> commits on the local repo

append: every cached record not yet in the repo ("UZP <id>" in decision-index.tsv), skipping a decision SAOS already holds
(same docket, given on or before 2018-09-06); one commit each (Kind: court, author date the day given at noon Warsaw,
committer date the run), sorted by the day given, then one Lexifina documentation commit (overlay, index, README,
corpus.json, REPRODUCE.md). nightly.py calls fetch for the last 60 days and append, so late uploads land too (out of
In-force order; the tools read the latest day from the trailers)."""
from __future__ import annotations

import argparse
import gzip
import html
import importlib.util
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_s = importlib.util.spec_from_file_location('pl_build_kio', HERE / 'build.py')
B = importlib.util.module_from_spec(_s)
_s.loader.exec_module(B)

BASE = 'https://orzeczenia.uzp.gov.pl'
UA = 'lexifina-gitlaw (case law archive; corpus@lexifina.com)'
GROUP = 'krajowa-izba-odwolawcza'
COURT = 'Krajowa Izba Odwoławcza'
SAOS_LAST = '2018-09-06'
FILL_FROM = '2018-06-01'  # SAOS holds 31 KIO decisions of June-August 2018 (about 150 a month before): the portal fills them
CACHE = Path.home() / 'Documents' / '.caselaw-cache' / 'pl' / 'uzp'
REPO = Path(os.environ.get('KIO_REPO') or Path.home() / 'Documents' / 'pl-caselaw-repos' / GROUP)
LAW = Path.home() / 'Documents' / 'caselaw-law-mirrors' / 'poland-law.git'
ITEM = re.compile(r'Rodzaj dokumentu:</label>\s*([^<]+?)\s*</p>.*?Sygnatura:</label>\s*([^<]+?)\s*</p>.*?'
                  r'Data wydania:</label>\s*(\d\d)-(\d\d)-(\d{4}).*?href="/Home/Details/(\d+)"', re.S)
COUNT = re.compile(r'Liczba znalezionych dokument[^:]*:\s*(\d+)')
DOCKET = re.compile(r'KIO(?:/KD|/UZP|/W)?\s*\d{1,5}/\d{2}(?![\d/])')
CHAIR = re.compile(r'Przewodnicząc[ya]\s*:?\s*([A-ZŁŚŻŹĆŃÓ][^\n:]{2,60})')
TYPES = {'wyrok': 'SENTENCE', 'wyok': 'SENTENCE', 'postanowienie': 'DECISION', 'uchwała': 'RESOLUTION', 'uchwala': 'RESOLUTION',
         'zarządzenie': 'REGULATION'}

_lock = threading.Lock()
_next = [0.0]
RATE = [3.0]
_local = threading.local()


def _session():
    import requests
    s = getattr(_local, 's', None)
    if s is None:
        s = _local.s = requests.Session()
        s.headers['User-Agent'] = UA
    return s


def http(url: str, data: dict | None = None) -> bytes:
    """One request on this thread's keep-alive connection, at most RATE a second over all threads; a slow or refused
    connection (the portal drops new connections when pressed) backs off, and the next requests wait with it."""
    err = None
    for i in range(6):
        with _lock:
            wait = _next[0] - time.time()
            _next[0] = max(_next[0], time.time()) + 1 / RATE[0]
        if wait > 0:
            time.sleep(wait)
        try:
            s = _session()
            r = s.post(url, data=data, timeout=(20, 180)) if data is not None else s.get(url, timeout=(20, 180))
            r.raise_for_status()
            return r.content
        except Exception as e:  # transient: back off, everyone
            err = e
            _local.s = None
            with _lock:
                _next[0] = max(_next[0], time.time() + 15 * (i + 1))
    raise err


def month_windows(d1: date, d2: date):
    d = d1
    while d <= d2:
        end = min((d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), d2)
        yield d, end
        d = end + timedelta(days=1)


def list_window(d1: date, d2: date) -> list[dict]:
    form = {'Phrase': '', 'Fle': '1', 'SCnt': '1', 'Sign': '', 'Kind': 'KIO', 'CountStats': 'True',
            'Dt': f'{d1:%d-%m-%Y} - {d2:%d-%m-%Y}'}
    out, pg, total = {}, 1, None
    while True:
        t = http(BASE + '/Home/GetResults', {**form, 'Pg': str(pg)}).decode('utf-8', 'replace')
        if total is None:
            m = COUNT.search(t)
            total = int(m.group(1)) if m else 0
        got = 0
        for typ, sygn, dd, mm, yy, i in ITEM.findall(t):
            out[int(i)] = {'uzp_id': int(i), 'type': html.unescape(typ).strip().lower(),
                           'sygnatura': html.unescape(sygn).strip(), 'decided': f'{yy}-{mm}-{dd}'}
            got += 1
        if not got or len(out) >= total or pg * 10 >= total:
            break
        pg += 1
    if len(out) < total:
        print(f'  {d1}..{d2}: listed {len(out)} of {total}', flush=True)
    return list(out.values())


def pdf_text(b: bytes) -> str:
    import pymupdf
    with pymupdf.open(stream=b, filetype='pdf') as d:
        t = '\n'.join(p.get_text() for p in d)
    lines = [re.sub(r'[ \t ]+', ' ', l).strip() for l in t.replace('\r', '').split('\n')]
    out, blank = [], False
    for l in lines:
        if not l:
            blank = bool(out)
            continue
        if blank:
            out.append('')
        out.append(l)
        blank = False
    return '\n'.join(out)


def record(item: dict) -> dict:
    i = item['uzp_id']
    text = pdf_text(http(f'{BASE}/Home/PdfContent/{i}?Kind=KIO'))
    head = text[:600]
    cases = []
    for d in [item['sygnatura']] + DOCKET.findall(head):
        d = re.sub(r'\s+', ' ', d.replace('KIO', 'KIO ').replace('KIO /', 'KIO/')).strip()
        if d not in cases:
            cases.append(d)
    m = CHAIR.search(text[:3000])
    judges = [re.sub(r'\s*(Protokolant|Członkowie).*$', '', m.group(1)).strip(' .')] if m else []
    return {'uzp_id': i, 'court': COURT, 'chamber': None, 'division': None, 'cases': cases, 'decided': item['decided'],
            'judgment_type': TYPES.get(item['type'], None), 'type_pl': item['type'], 'judges': [j for j in judges if j],
            'source_url': f'{BASE}/Home/Details/{i}', 'pdf_url': f'{BASE}/Home/PdfContent/{i}?Kind=KIO',
            'summary': '', 'decision': '', 'keywords': [], 'regulations': [], 'text': text}


def fetch(d1: date, d2: date, threads: int = 12) -> dict:
    (CACHE / 'records').mkdir(parents=True, exist_ok=True)
    (CACHE / 'lists').mkdir(parents=True, exist_ok=True)
    items = []
    wins = list(month_windows(d1, d2))
    settled = date.today() - timedelta(days=60)  # a month listed before this is kept; later ones are listed again

    def listed(w):
        p = CACHE / 'lists' / f'{w[0]}_{w[1]}.json'
        if p.exists():
            return json.loads(p.read_text())
        got = list_window(*w)
        if w[1] < settled:
            p.write_text(json.dumps(got))
        print(f'  listed {w[0]:%Y-%m}: {len(got)}', flush=True)
        return got

    with ThreadPoolExecutor(min(threads, 3)) as ex:
        for got in ex.map(listed, wins):
            items += got
    print(f'listed {len(items)} decisions {d1}..{d2}', flush=True)
    todo = [x for x in items if not (CACHE / 'records' / f"{x['uzp_id']}.json.gz").exists()]
    done, failed = [0], []

    def one(x):
        try:
            r = record(x)
        except Exception as e:
            failed.append((x['uzp_id'], repr(e)[:200]))
            return
        p = CACHE / 'records' / f"{x['uzp_id']}.json.gz"
        tmp = p.with_suffix('.part')
        with gzip.open(tmp, 'wt', encoding='utf-8', compresslevel=5) as f:
            json.dump(r, f, ensure_ascii=False)
        tmp.replace(p)
        done[0] += 1
        if done[0] % 500 == 0:
            print('fetched', done[0], 'of', len(todo), flush=True)

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    st = {'listed': len(items), 'fetched': done[0], 'failed': failed[:50], 'n_failed': len(failed), 'from': str(d1),
          'to': str(d2), 'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    (CACHE / 'FETCHED.json').write_text(json.dumps(st, indent=1))
    print(json.dumps({k: v for k, v in st.items() if k != 'failed'}), flush=True)
    return st


def norm(r: dict) -> dict:
    """The portal lists joined appeals as one docket ("KIO 1952/18|KIO 1957/18"): one docket each, first as listed; a
    misspelt type ("wyok") read as the word meant."""
    cases = []
    for c in r['cases']:
        for d in re.split(r'\s*[|,;]\s*|\s+i\s+', c):
            d = re.sub(r'\s+', ' ', d).strip()
            if d and d not in cases:
                cases.append(d)
    r['cases'] = cases
    if not r.get('judgment_type'):
        t = (r.get('type_pl') or '').lower()
        r['judgment_type'] = TYPES.get(t)
    return r


def render(r: dict, res, ver, extra=()):
    """One decision as build.render writes a SAOS one, keyed by the UZP id."""
    r = norm(r)
    day, court, uid = r['decided'], COURT, r['uzp_id']
    case = r['cases'][0] if r['cases'] else f'UZP {uid}'
    path = f"decisions/{B.slug(court).lower()[:50]}/{day[:4]}/{B.slug(case) or 'KIO'}-uzp-{uid}.md"
    cites = res.from_text(r['text'])
    kept = [(p, how) for p, how in cites if not ver.get(p) or ver[p][0][0] <= day]
    miss = len(cites) - len(kept)
    cites = kept
    url = r['source_url']
    fm = {'uzp_id': uid, 'court': court, 'sygnatura': case, 'other_case_numbers': r['cases'][1:] or None, 'decided': day,
          'judgment_type': r['judgment_type'], 'judges': r['judges'] or None, 'source_url': url, 'pdf_url': r['pdf_url']}
    lines = ['---'] + [f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in fm.items() if v not in (None, '')]
    uniq = sorted({p for p, _ in cites})
    if uniq:
        lines.append('cites_law: ' + json.dumps([f'{B.LAW_CORPUS}/{p}' for p in uniq], ensure_ascii=False))
    jt = {'SENTENCE': 'Wyrok', 'DECISION': 'Postanowienie', 'RESOLUTION': 'Uchwała', 'REGULATION': 'Zarządzenie'}.get(
        r['judgment_type'] or '', (r.get('type_pl') or 'orzeczenie').capitalize())
    lines += ['---', '', f'# {court}, {jt}, {day}, {case}', '', '## Treść', '', r['text'].strip(), '']
    body = '\n'.join(lines).encode('utf-8')
    author = f'{court} {case}'.replace('<', '').replace('>', '')[:200]
    email = f'{B.email_local(case)}-uzp-{uid}@caselaw.invalid'
    kind = 'correction' if any(t.startswith('Corrected:') for t in extra) else 'court'
    tr = [f'Kind: {kind}', f'In-force: {day}', f'Decided: {day}', f'Court: {court}', f'Docket: {case}', f'UZP: {uid}',
          f'Source: {url}']
    seen = set()
    for p, how in cites:
        if p not in seen and len(seen) < 60:
            seen.add(p)
            tr.append(f'Cites: {B.LAW_CORPUS}/{p} ({how[:120]})')
    tr += [t for t in extra if t]
    msg = (f'{court} {case}: {jt}'[:200] + '\n\n' + '\n'.join(tr) + '\n').encode('utf-8')
    counts = {}
    for p, _ in cites:
        counts[p] = counts.get(p, 0) + 1
    rows, done = [], set()
    for p, how in cites:
        if p in done:
            continue
        done.add(p)
        row = {'decided': day, 'name': f'{court} {case}', 'court': court, 'citation': case, 'url': url, 'how': how,
               'mentions': counts[p], 'decision': path}
        rows.append((p, B.RC.fix_row(row, p, ver)))
    refs = sorted({*r['cases'], f'UZP {uid}'})
    return path, body, author, email, msg, rows, refs, miss


def git(*args, inp=None, check=True):
    p = subprocess.run(['git', '-C', str(REPO), *args], input=inp, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f'git {args[0]}: {p.stderr.decode(errors="replace")[-400:]}')
    return p.stdout.decode('utf-8', errors='replace')


def docs(today: str, n_uzp: int, first_day: str, last_day: str, n_refs_total: int) -> dict:
    cj = json.loads(git('show', 'HEAD:corpus.json'))
    n_saos = (cj.get('counts') or {}).get('saos') or int(re.match(r'(\d+)', cj['coverage']).group(1))
    st = json.loads((CACHE / 'FETCHED.json').read_text()) if (CACHE / 'FETCHED.json').exists() else {}
    fetched = (st.get('at') or today)[:10]
    cj['coverage'] = (f'{n_saos + n_uzp} decisions with text, one file and one commit each, dated the day given: {n_saos} from SAOS '
                      f'(to {SAOS_LAST}) and {n_uzp} from the UZP portal orzeczenia.uzp.gov.pl ({first_day} to {last_day}); '
                      f'{n_refs_total} citations of law linked to poland-law.')
    cj['counts'] = {'saos': n_saos, 'uzp': n_uzp}
    cj['record_to'], cj['checked_on'] = fetched, today
    cj['record_note'] = ('Court decisions, not laws: every commit is Kind: court. In-force is the day given. Decisions with no '
                         f'usable date are in decisions/undated/. To {SAOS_LAST} the decisions are SAOS\'s; from {first_day} the ones SAOS '
                         'lacks are the UZP portal\'s (orzeczenia.uzp.gov.pl), appended after SAOS\'s, and the nightly run appends late '
                         'uploads, so the history is not wholly in In-force order. A decision the portal lists without a '
                         'readable text is not in the record.')
    cj['history_order'] = 'appended'
    cj['source'] = {'publisher': 'SAOS (saos.org.pl) to 2018-09-06; then the Urząd Zamówień Publicznych portal of KIO decisions',
                    'url': BASE, 'fetched': fetched,
                    'licence': 'Decisions are official documents, not subject to copyright (Art. 4 of the Polish Copyright Act); '
                               'neither SAOS nor the UZP portal states reuse conditions'}
    cj['sources'] = [{'name': 'SAOS', 'url': 'https://www.saos.org.pl/api/dump/judgments', 'to': SAOS_LAST},
                     {'name': 'orzeczenia.uzp.gov.pl', 'url': BASE, 'from': first_day, 'fetched': fetched}]
    readme = git('show', 'HEAD:README.md')
    readme = re.sub(r'(?s)\n## Later decisions: the UZP portal\n.*?(?=\n## )', '\n', readme)
    add = f"""
## Later decisions: the UZP portal
SAOS holds no KIO decision given after {SAOS_LAST}, and few after May 2018. The ones it lacks come from the Urząd Zamówień
Publicznych's own portal (https://orzeczenia.uzp.gov.pl): {n_uzp:,} decisions given from {first_day} to {last_day}, as it listed them on {fetched},
each with the text of its PDF (read with PyMuPDF; page layout is not kept). Their files end in `-uzp-<portal id>.md`, their
commits carry `UZP: <portal id>`, and `decision-index.tsv` lists them by docket and by `UZP <id>`. A decision SAOS already
holds (same docket) is not added twice. These commits come after SAOS's in the history
(author date the day given, committer date the run), and the nightly run appends late uploads, so the history is not wholly
in In-force order. The portal has no robots.txt and states no reuse terms; it is read a few requests a second.
"""
    i = readme.find('\n## Source and licence')
    readme = readme[:i] + add + readme[i:] if i >= 0 else readme + add
    readme = readme.replace('SAOS states no conditions on reuse.', 'Neither SAOS nor the UZP portal states conditions on reuse.')
    rep = git('show', 'HEAD:REPRODUCE.md')
    rep = re.sub(r'(?s)\n## The UZP decisions\n.*$', '\n', rep).rstrip() + f"""

## The UZP decisions
After the SAOS build, the decisions given from {FILL_FROM} that SAOS lacks are appended from https://orzeczenia.uzp.gov.pl:

```
python -X utf8 tools/kio_uzp.py fetch --from {FILL_FROM}
python -X utf8 tools/kio_uzp.py append
```

`fetch` lists them by month and reads each PDF; `append` writes one commit each and this documentation commit.
"""
    return {'corpus.json': json.dumps(cj, ensure_ascii=False, indent=2) + '\n', 'README.md': readme, 'REPRODUCE.md': rep,
            'tools/kio_uzp.py': (HERE / 'kio_uzp.py').read_text(encoding='utf-8')}


def append(push: bool, today: str | None = None, log=print) -> dict:
    today = today or date.today().isoformat()
    git('fetch', '-q', 'origin', 'main')
    if git('rev-parse', 'HEAD').strip() != git('rev-parse', 'origin/main').strip():
        git('reset', '-q', '--soft', 'origin/main')
    head = git('rev-parse', 'HEAD').strip()
    index = {}
    for l in git('show', 'HEAD:decision-index.tsv').splitlines()[1:]:
        ref, _, p = l.partition('\t')
        index[ref] = p
    recs = []
    for f in (CACHE / 'records').glob('*.json.gz'):
        with gzip.open(f, 'rt', encoding='utf-8') as fh:
            r = norm(json.load(fh))
        if f'UZP {r["uzp_id"]}' in index or not r.get('text') or not B.ISO.match(r.get('decided') or '') or r['decided'] > today:
            continue
        if r['decided'] <= SAOS_LAST and any(c in index for c in r['cases']):
            continue  # SAOS holds it
        recs.append(r)
    recs.sort(key=lambda r: (r['decided'], r['cases'][:1], r['uzp_id']))
    if not recs:
        log('kio uzp: nothing new')
        return {'new': 0}
    res = B.Resolver(json.load(open(HERE / 'pl_index.json', encoding='utf-8')))
    subprocess.run(['git', '-C', str(LAW), 'fetch', '-q', 'origin', 'main:main'], capture_output=True)
    ver = B.RC.versions(LAW, ref='main')
    now = int(time.time())
    w, overlay, new_refs, miss = [], {}, [], 0
    for r in recs:
        path, body, author, email, msg, rows, refs, m = render(r, res, ver)
        miss += m
        d0 = date.fromisoformat(r['decided'])
        ats = int(datetime(d0.year, d0.month, d0.day, 12, tzinfo=B.WARSAW).timestamp())
        w.append(b'commit refs/heads/main\nauthor %s <%s> %d +0100\ncommitter %s %d +0000\n' % (
            author.encode('utf-8'), email.encode(), ats, B.COMMITTER, now))
        w.append(b'data %d\n%s\n' % (len(msg), msg))
        if len(w) == 2:
            w.append(b'from %s\n' % head.encode())
        w.append(b'M 100644 inline %s\ndata %d\n%s\n' % (path.encode('utf-8'), len(body), body))
        new_refs += [x + '\t' + path for x in refs]
        for p, row in rows:
            overlay.setdefault(p, []).append(row)
    files = []
    for p, add in sorted(overlay.items()):
        rel = f'judgments/{B.LAW_CORPUS}/{p[:-3]}.jsonl'
        old = git('show', f'HEAD:{rel}', check=False)
        allr = [json.loads(l) for l in old.splitlines() if l.strip()] + add
        allr.sort(key=lambda x: (x['decided'], x['citation'], x['decision']))
        files.append((rel, ''.join(json.dumps(x, ensure_ascii=False, sort_keys=True) + '\n' for x in allr)))
    old = git('show', 'HEAD:decision-index.tsv').splitlines()
    rows_ = sorted(set(old[1:] + new_refs))
    files.append(('decision-index.tsv', 'reference\tpath\n' + ''.join(x + '\n' for x in rows_)))
    n_uzp = sum(1 for x in rows_ if x.startswith('UZP '))
    last_day = max(x['decided'] for x in recs)
    prev = json.loads(git('show', 'HEAD:corpus.json')).get('uzp_last_day') or ''
    last_day = max(last_day, prev)
    first_day = min([x['decided'] for x in recs] + [json.loads(git('show', 'HEAD:corpus.json')).get('uzp_first_day') or '9999'])
    old_refs = int(re.search(r'(\d+) citations', json.loads(git('show', 'HEAD:corpus.json'))['coverage']).group(1))
    n_refs = sum(len(v) for v in overlay.values())
    d = docs(today, n_uzp, first_day, last_day, old_refs + n_refs)
    cj = json.loads(d['corpus.json'])
    cj['uzp_first_day'], cj['uzp_last_day'] = first_day, last_day
    d['corpus.json'] = json.dumps(cj, ensure_ascii=False, indent=2) + '\n'
    unres = git('show', 'HEAD:unresolved.csv', check=False).splitlines()
    try:
        prev_miss = int(unres[1])
    except Exception:
        prev_miss = 0
    d['unresolved.csv'] = 'cited regulations with no article linked\n' + str(prev_miss + miss) + '\n'
    files += sorted(d.items())
    msg = (f'Documentation: {len(recs)} KIO decisions from orzeczenia.uzp.gov.pl ({n_refs} citations linked); overlay, '
           f'decision index, README, corpus.json, REPRODUCE.md\n').encode()
    w.append(b'commit refs/heads/main\nauthor Lexifina <corpus@lexifina.com> %d +0000\ncommitter %s %d +0000\n' % (now, B.COMMITTER, now))
    w.append(b'data %d\n%s\n' % (len(msg), msg))
    for rel, b in files:
        b = b.encode('utf-8')
        w.append(b'M 100644 inline %s\ndata %d\n%s\n' % (rel.encode('utf-8'), len(b), b))
    w.append(b'done\n')
    git('fast-import', '--quiet', '--done', inp=b''.join(w))
    out = {'new': len(recs), 'overlay_rows': n_refs, 'unlinked': miss, 'first': recs[0]['decided'], 'last': last_day}
    log('kio uzp:', json.dumps(out))
    if push:
        for i in range(4):
            pr = subprocess.run(['git', '-C', str(REPO), '-c', 'http.postBuffer=1048576000', 'push', '-q', 'origin', 'main'],
                                capture_output=True)
            if not pr.returncode:
                break
            time.sleep(30 * (i + 1))
        else:
            raise RuntimeError(f'push {GROUP}: {pr.stderr.decode(errors="replace")[-300:]}')
        log('kio uzp: pushed')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['fetch', 'append'])
    ap.add_argument('--from', dest='d1', default=FILL_FROM), ap.add_argument('--to', default=date.today().isoformat())
    ap.add_argument('--rate', type=float, default=3), ap.add_argument('--threads', type=int, default=6)
    ap.add_argument('--push', action='store_true')
    a = ap.parse_args()
    RATE[0] = a.rate
    if a.cmd == 'fetch':
        fetch(date.fromisoformat(a.d1), date.fromisoformat(a.to), a.threads)
    else:
        append(a.push)


if __name__ == '__main__':
    main()
