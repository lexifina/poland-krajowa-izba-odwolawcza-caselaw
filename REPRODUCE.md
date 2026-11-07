# Reproducing this repository

Input: the SAOS judgment dump (https://www.saos.org.pl/api/dump/judgments, pages of 100, withGenerated=true) fetched on
2026-11-07 by `tools/fetch.py`, parsed by `tools/parse.py`; poland-law `main` for the overlay (`tools/pl_index.py`).

```
python tools/fetch.py <cache>
python tools/parse.py <cache> <parsed>
python tools/build.py krajowa-izba-odwolawcza <parsed> <empty folder> --today 2026-11-07 --fetched 2026-11-07
```

Gives 22,168 judgment commits and one documentation commit.

## The UZP decisions
After the SAOS build, the decisions given from 2018-06-01 that SAOS lacks are appended from https://orzeczenia.uzp.gov.pl:

```
python -X utf8 tools/kio_uzp.py fetch --from 2018-06-01
python -X utf8 tools/kio_uzp.py append
```

`fetch` lists them by month and reads each PDF; `append` writes one commit each and this documentation commit.
