# free-exercise-db: source record

Formiq's record of where the files in this directory come from. Everything here except this file
is an unmodified copy of the upstream repository at the pinned commit. Do not edit those files:
to move to another upstream version, replace them, update this record, and run the import again
(`python -m app.cli import-exercises --dry-run` first).

| | |
|---|---|
| Upstream | https://github.com/yuhonas/free-exercise-db |
| Pinned commit | `f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5` (2026-09-27, "Add GitHub stars badge to README") |
| Records | 876 exercises (`dist/exercises.json`; identical to the 876 per-exercise files in `exercises/`) |
| Licence | The Unlicense (public domain dedication): `LICENSE.md`, copied verbatim |
| Retrieved | 2026-10-13 |

## Files

| File | Upstream path | SHA-256 |
|---|---|---|
| `exercises.json` | `dist/exercises.json` | `5bb747e3fc658f095a60dcbf6d53c96627acdcc6ffb6fffde86f7e26995d40bf` |
| `schema.json` | `schema.json` | `9ec09dca20ed4dfe419df81ce4956b5d6ffd2723b266e0c9cdd9b627caa77fb6` |
| `LICENSE.md` | `LICENSE.md` | `6b0382b16279f26ff69014300541967a356a666eb0b91b422f6862f6b7dad17e` |

The importer checks the checksum of `exercises.json` against `SOURCE_SHA256` in
`app/catalog/free_exercise_db.py` and refuses a file that differs, so a changed file is never
imported under this commit's name.

## Licence findings

**Exercise data (names, instructions, muscles, equipment, level, category).** The repository
dedicates its contents to the public domain under the Unlicense, which allows copying, modifying,
distributing and commercial use with no attribution requirement. Formiq still records the source,
the upstream id and the commit for every imported exercise. The dataset is a restructuring of
[wrkout/exercises.json](https://github.com/wrkout/exercises.json), also released under the
Unlicense. Neither repository says where the instruction text was originally written; that origin
is undocumented.

**Exercise images: not cleared for redistribution, and not included.** The upstream repository
holds 1,746 images (two per exercise, three exercises without any), about 99 MB. Their own sources
say the Unlicense does not cover them:

- The free-exercise-db owner, in
  [issue #2](https://github.com/yuhonas/free-exercise-db/issues/2): "I actually have no idea where
  the images are from or if they are royalty free so usage would be at your own risk."
- The original dataset's `CONTRIBUTING.md`
  ([wrkout/exercises.json](https://github.com/wrkout/exercises.json/blob/master/CONTRIBUTING.md)):
  "these have been scrapped off the internet, therefore l do not own the copy right for these
  images and would advise against using them in comercial projects."
- [wrkout/exercises.json issue #305](https://github.com/wrkout/exercises.json/issues/305) reports a
  reverse image search pointing to a commercial fitness site whose terms forbid reproduction.

So the images are **not** copied into Formiq. The upstream image references (`"images"` in each
record) are kept in the imported records, unchanged, so the images can be registered later from a
source whose licence is confirmed: see `../exercise-images/README.md`.
