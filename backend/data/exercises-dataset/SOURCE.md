# exercises-dataset: source record

Formiq's record of where the files in this directory come from. Everything here except this file
is an unmodified copy of the upstream repository at the pinned commit. Do not edit those files:
to move to another upstream version, replace them, update this record and `SOURCE_VERSION` and
`SOURCE_SHA256` in `app/catalog/exercises_dataset.py` together, and run the import again
(`python -m app.cli import-exercises --source exercises-dataset --dry-run` first).

| | |
|---|---|
| Upstream | https://github.com/hasaneyldrm/exercises-dataset |
| Pinned commit | `7455efae41b330c265e7cd4b78dfa848e7ce5ebd` (2026-07-16, "Merge pull request #56 from hasaneyldrm/readme-fix-merged") |
| Records | 1,324 exercises (`data/exercises.json`); every one valid against the published schema |
| Licence | MIT for the data and instruction text (`LICENSE`); the images and GIFs are excluded from it (see below) |
| Retrieved | 2026-10-27 (audited read-only before it was copied here) |

## Files

| File | Upstream path | SHA-256 |
|---|---|---|
| `exercises.json` | `data/exercises.json` | `656634224b8977b99a6d765470ee123260d4979715eaa4e7c0b7c8bb0d79f93d` |
| `exercises.schema.json` | `data/exercises.schema.json` | `33fb14b439c68e12365e14a0759006c40564646ac27084efe1f2e956804b2d49` |
| `LICENSE` | `LICENSE` | `99230e0c2e74c54386e31e7282fc4d939ca14942df542b706fcd9fa71c3187fa` |
| `NOTICE.md` | `NOTICE.md` | `2b078c9ff73670bbcd4503703eb6be624250193b33655948799acc635a11557b` |

The importer checks the checksum of `exercises.json` against `SOURCE_SHA256` and refuses a file that
differs, so a changed file is never imported under this commit's name. The upstream `images/` and
`videos/` directories (1,324 JPG thumbnails and 1,324 GIFs) are **not** here and are never
downloaded.

## Licence findings

**Exercise data (names, body parts, equipment, muscles, instructions and their translations).**
MIT, so it may be copied, modified and used commercially if the licence text travels with the copy
(`LICENSE` here). Formiq also records the source, the upstream id and the commit of every imported
exercise. Two questions stay open, as they do for free-exercise-db: the upstream README says the
repository does not claim ownership of the underlying exercise content, and neither it nor the
licence says where the instruction text, or its nine translations, came from. GitHub itself shows
the repository's licence as "NOASSERTION", because of the media exception.

**Exercise media: not cleared, and not used.** The licence's media exception, and `NOTICE.md`,
say the images and GIFs belong to Gym visual (https://gymvisual.com/), are included in the upstream
repository with the rights holder's separate written permission (which is not in the repository),
at 180x180, and are governed by Gym visual's own terms, which Formiq has not read. Cloning the
repository grants no right to them, and every use must carry the credit "© Gym visual", so Formiq
does not register, copy, serve or link them: `image_paths` is empty for every exercise from this
source. The records keep their `image`, `gif_url`, `media_id` and `attribution` fields as text only
(they are never followed), so media can be registered later from a source whose licence is
confirmed (`../exercise-images/README.md`), with Formiq's own licence from Gym visual.

## What the import does with it

The rules and tables are in `app/catalog/exercises_dataset.py`; the tests pin the counts.

- **Kept:** the external id (`source_id`), the source (`EXERCISES_DATASET`), the commit
  (`source_version`), and the record as it is with **only the English instructions** (the other nine
  languages stay in this file). The name is normalized for display (Title Case, acronyms in capitals,
  and four names whose degree sign was read in the wrong character set corrected by id); the original
  is in the record.
- **Not made up:** the dataset has no level, so the difficulty is `UNRATED`; it has no movement
  pattern, no workout section (`uses` is empty, so the coach cannot put the exercise in a proposed
  workout until Formiq classifies it), no sets, reps or rest, and no description.
- **Held back, with the reason, never guessed:**
  - an equipment value that is not a piece of equipment (`weighted`, `assisted`) or has no entry in
    the table;
  - a record whose name or steps name gear that its one equipment value does not (a body-weight pull-up
    with a bar, a dumbbell press on a bench, an exercise-ball move filed under dumbbell): the
    dataset gives each record a single equipment value, so a "needs nothing else" would be false;
  - a primary muscle with no Formiq muscle group (`cardiovascular system`, `serratus anterior`,
    `spine`, which is the target of lower-back extensions and also of a hug, a pelvic tilt and
    upward-facing dog);
  - an unusable name, or a name another record already has (the lowest id wins).
- **Mapped through a table, never by guess:** equipment and muscles. A value with no entry rejects
  the record and is reported. A secondary muscle with no Formiq group (hip flexors, ankles...) is
  left unlinked and reported, and the record keeps it.
- **Skipped at import, not here:** an exact name collision (case, spaces and punctuation ignored)
  with an exercise the catalog already has, Formiq's own or another source's. Exercises are matched
  by `(source, source_id)`, never by name, so the import is idempotent, and no existing exercise or
  id is changed.
