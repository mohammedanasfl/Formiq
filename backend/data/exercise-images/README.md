# Exercise images

The images the API serves at `GET /exercises/{exercise_id}/images/{position}`. The database keeps
only each image's path relative to this directory, in order (`exercises.image_paths`); the API
never exposes the path, and serves a file only when the stored path resolves to a file inside this
directory.

Layout: one directory per upstream exercise id, with the upstream file names:

```
exercise-images/
└── 3_4_Sit-Up/
    ├── 0.jpg
    └── 1.jpg
```

**No images are included yet.** The free-exercise-db images are not cleared for redistribution
(see `../free-exercise-db/SOURCE.md`), so they are not copied here, and every exercise's
`images` list is empty: the API's fallback for an exercise without images.

To add images whose licence allows it:

1. Put each file at `<upstream exercise id>/<n>.jpg`, the path the exercise's upstream record
   lists in its `"images"` (for example `3_4_Sit-Up/0.jpg`).
2. Run the import again from `backend/`: `python -m app.cli import-exercises --dry-run`, then
   without `--dry-run`. It registers each listed image whose file exists, in the upstream order, and
   reports the ones still missing. It never registers a path whose file does not exist.

`EXERCISE_IMAGES_DIR` overrides where this directory is.
