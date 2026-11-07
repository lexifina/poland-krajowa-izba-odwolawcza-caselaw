# Polish case law: the Krajowa Izba Odwoławcza (National Appeal Chamber)

Part of [lexifina/global-law](https://github.com/lexifina/global-law), one git history for every country's law: this is the case law of the Krajowa Izba Odwoławcza (National Appeal Chamber), Poland, which global-law reads at `poland/krajowa-izba-odwolawcza/caselaw/`.

Every judgment of the Krajowa Izba Odwoławcza (National Appeal Chamber) that SAOS (System Analizy Orzeczeń Sądowych) holds with its text, as a git history: one file per
judgment, one commit per judgment, dated the day it was given. 22,168 judgments given from 2007-12-10 to 2018-09-06, as SAOS held them on 2026-11-07. SAOS holds no judgment of the Krajowa Izba Odwoławcza (National Appeal Chamber) given after 2018-09-06: later judgments are not in this record, though it was checked against SAOS on 2026-11-07.

## Questions as git commands

| Question | Command |
|---|---|
| A judgment | `cat decisions/<court>/<year>/<sygnatura>-<saos id>.md` |
| By case number | `grep -P '^II CSK 123/20\t' decision-index.tsv` · `git log --grep='^Docket: II CSK 123/20$' --stat` |
| Judgments given in a window | `git log --since=2024-03-01 --until=2024-03-31 --format='%ad %an' --date=short` |
| Judgments applying art. 415 k.c. | `cat judgments/poland/national/acts/kodeks-cywilny/art-415.jsonl` |
| The article as the court applied it | each overlay row's `law_commit` is the article's own version in poland-law on the day given (`law_record_from` when the judgment is older than the record) |
| Who wrote a line? | `git blame decisions/...`: each line is credited to the judgment (court and case number) |

## Dates and authors
The commit date is the day the judgment was given, at noon Warsaw (`In-force:` and `Decided:`). The author is the court and
the case number (sygnatura), at an address that cannot exist. These are court rulings, not laws: every commit is
`Kind: court`.

## The judgment overlay
Links come from the courts' own list of cited provisions (SAOS `referencedRegulations`, by Dziennik Ustaw address) and
from citations in the text ("art. 415 k.c.", "art. 22¹ § 1 k.p.", "art. 32 Konstytucji RP"), kept only where they land on
an article file poland-law holds. 9,957 are linked.


## Later decisions: the UZP portal
SAOS holds no KIO decision given after 2018-09-06, and few after May 2018. The ones it lacks come from the Urząd Zamówień
Publicznych's own portal (https://orzeczenia.uzp.gov.pl): 26,900 decisions given from 2018-06-01 to 2026-10-12, as it listed them on 2026-11-07,
each with the text of its PDF (read with PyMuPDF; page layout is not kept). Their files end in `-uzp-<portal id>.md`, their
commits carry `UZP: <portal id>`, and `decision-index.tsv` lists them by docket and by `UZP <id>`. A decision SAOS already
holds (same docket) is not added twice. These commits come after SAOS's in the history
(author date the day given, committer date the run), and the nightly run appends late uploads, so the history is not wholly
in In-force order. The portal has no robots.txt and states no reuse terms; it is read a few requests a second.

## Source and licence
The judgments come from SAOS (https://www.saos.org.pl), which gathers them from the courts' own portals (orzeczenia.ms.gov.pl,
sn.pl, trybunal.gov.pl, orzeczenia.nsa.gov.pl, uzp.gov.pl); each file links to its source. Court judgments are official
documents and are not subject to copyright under Art. 4 of the Polish Copyright Act (ustawa o prawie autorskim i prawach
pokrewnych); Neither SAOS nor the UZP portal states conditions on reuse. Anonymisation is the courts' own. The arrangement of this repository is
dedicated to the public domain under CC0 1.0.

## What it does not show
Judgments the courts do not publish, and links to acts poland-law does not yet hold (counted in unresolved.csv).
