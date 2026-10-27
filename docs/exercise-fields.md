# Exercise fields: what the catalog fills, and what it leaves

An audit of the dev database on 2026-10-20 found most imported exercises missing the fields a coach
and an app use: a **description** (842 of 845) and a **movement pattern** (781 of 845). This is what
was filled, how, what was left on purpose, and how to apply and undo it. No schema changes: the
fields already existed, and they are written by `python -m app.cli import-exercises`, so no
migration is needed.

Status: on branch `phase-7-nutrition-recovery`, uncommitted. Applied to the dev database on
2026-10-20.

## The audit

The dev database holds 934 exercises: 71 written by Formiq, 845 imported (free-exercise-db) that the
catalog shows, and 18 imported ones it hides as duplicates (`docs/warm-up-cool-down.md`).

| Field | Before | After |
|---|---|---|
| `description`, imported shown | 3 of 845 | 845 of 845 |
| `movement_pattern`, imported shown | 64 of 845 (the cardio, drills and stretches of the lists) | 828 of 845 |
| `uses`, imported shown | 775 of 845 | 775 of 845 (70 left empty on purpose) |
| steps (`instructions`), imported shown | 840 of 845 | 840 of 845 (5 records have none) |
| `muscles` with a primary muscle, difficulty | all | all |
| Formiq's own, every field | all but images | all but images |
| images | none | none |

Hidden duplicates are unchanged: no pattern, and no description but for the two cardio ones.

## Movement patterns: `app/catalog/patterns.py`

The classification was made by **rules** from what each record says (its name, `force`, `mechanic`,
primary muscles and category), not by hand, so it is the same for every record, can be read, and is
pinned by tests. A pattern is Formiq's coarse grouping, not a biomechanical claim:

| Pattern | Means | Imported exercises the catalog shows |
|---|---|---|
| `SQUAT`, `HINGE`, `LUNGE` | knee-dominant, hip-dominant, and single-leg or alternating-leg lifts | 59, 91, 49 |
| `HORIZONTAL_PUSH`, `VERTICAL_PUSH` | pressing forward, pressing overhead (dips included) | 76, 60 |
| `HORIZONTAL_PULL`, `VERTICAL_PULL` | rows; pull-ups, pulldowns, upright rows and pullovers | 33, 37 |
| `ISOLATION` | one joint does the work: curls, extensions, raises, flyes, crunches, calf and neck work | 284 |
| `ROTATION` | twists, chops, windmills and the holds that resist them (Formiq's own Bird Dog and Pallof Press are `ROTATION`) | 22 |
| `CARRY` | farmer's walk, yoke, rickshaw carry | 4 |
| `STRETCH`, `MOBILITY`, `CARDIO` | as before, from the lists, and by hand for the 61 records no section uses | 69, 32, 12 |
| none | see below | 17 |

The Olympic lifts are hinges (cleans, snatches) or vertical pushes (jerks, push presses). Jumps are
squat-like, and hops, bounds, skips and sprints are `LUNGE`, since they are done one leg after the
other.

- **Order of the rules.** A word of the name is read first (the name rules in `patterns.py`, in the
  order they are tried), then the record's own facts. The order matters and is commented: the squat
  rule beats the Olympic ones ("Front Squat (Clean Grip)"), the lunge rule beats the one-joint words
  ("Step-up with Knee Raise"), and so on.
- **Left without a pattern, on purpose: 17.** Twelve main exercises that fit none (a medicine-ball
  slam, a spider crawl, wind sprints, throws from the floor, a kettlebell pass between the legs...)
  and five drills of the 61 records no section uses. A wrong pattern is worse than none.
- **Exceptions and a table.** `EXCEPTIONS` names the dozen records the rules misread, by id, each
  with its reason (a test fails if the rules already agree with one). `OTHER_PATTERNS` places by hand
  the 61 records no section uses: held stretches `STRETCH`, foam rolling (`-SMR`) and dynamic drills
  `MOBILITY` (as in `classification.py`), and the few exercises among them with their own pattern.
- **Hidden duplicates keep none.** A search never shows them, and the 11 hidden drills and stretches
  were left unpatterned deliberately.
- **Pinned.** `tests/unit/test_movement_patterns.py` pins some sixty rule cases, the exact list of
  records left without a pattern, and the counts per pattern for the vendored dataset. A rule that
  moves an exercise is a decision, never a side effect.

### What it changes for the coach

`search_exercises` takes `movement_pattern`, and the live QA found the model searching a leg day by
SQUAT, HINGE and LUNGE. Until now those found only the exercises Formiq wrote (5 squats, 4 hinges, 1
lunge); they now find the catalog's (for a beginner with dumbbells, a barbell and a rack: 10 squat,
9 hinge and 15 lunge matches). To keep what the coach is offered sensible, the
ranking in `most_relevant` gained three steps (after the muscle asked for and the fit to the
workout, before the existing ones):

1. an exercise some section uses before one none does (a stretch Formiq keeps but does not use for
   any section cannot go into a workout);
2. outside a warm-up or cool-down search, **Formiq's own exercises before the imported ones**, now
   that the pattern no longer tells them apart: it wrote and described them;
3. outside a warm-up or cool-down search, the standard lifts (strength, powerlifting) before the
   specialised ones (plyometrics, Olympic lifts, strongman): without it, "Knee Tuck Jump" and "Fast
   Skipping" came before "Dumbbell Lunges" for a leg day.

Warm-up and cool-down searches are ranked as before.

## Descriptions: `app/catalog/descriptions.py`

- **Written by hand (8).** The five cardio records whose steps are a machine's menu and calorie
  estimate (`DESCRIPTIONS`, doses and safety notes, `docs/warm-up-cool-down.md`), and three main
  exercises whose records have **no steps at all**: Push Press, One-Arm Kettlebell Swings and Side
  Bridge (`MAIN_DESCRIPTIONS`: how the movement goes, nothing claimed for it, a coach recommended for
  the push press).
- **Generated (837).** One sentence from the facts the catalog already holds of the exercise: its
  level, what it is (its pattern, or its category for a heavy lift or a jump), the muscles it works
  and the equipment it needs, and, for a record with no steps, that the source gives none. For
  example: "An intermediate horizontal pushing exercise for the chest, with the shoulders and
  triceps helping. Equipment: barbell, bench." It is a **summary, not a how-to**: the steps stay the
  record's, served as they were. Nothing is claimed for the body: tests fail on a word that does
  (prevent, injury, sore, recover, burn, calorie, improve, strengthen, tone...).
- **Iron Cross and Side Jackknife** have no steps in the dataset and are not described by hand: I
  did not know the movements well enough to write steps for them. Their description says what they
  are and that the source gives no steps. A person should write theirs.
- **The steps.** The model used to hide an imported exercise's steps whenever it had a description,
  which was right for the five machine-cardio records. It now hides them only for those
  (`REPLACES_STEPS`): a generated description never replaces the record's steps. A test pins it.

## Left on purpose, and not filled

| Field | Why |
|---|---|
| `uses`, 70 imported records | `uses` is Formiq's judgement of the workout sections an exercise suits, and these were judged for none: faster cardio (elliptical, rope jumping, running), foam rolling and stretches Formiq did not list, athletic drills, and some bodyweight records the dataset gives no equipment (a decline push-up, an inverted row: they need a surface or a bar). Giving them a section would change what the coach proposes. Several are good candidates; each is a decision. |
| Images, all | The dataset's images are not cleared for redistribution and are not in the repository (`import-exercises` reports 1,720 listed and not found). Formiq's own exercises have none either. |
| Steps for Iron Cross and Side Jackknife | See above. |
| Hidden duplicates | Never shown; they keep what they had. |
| Calorie text in seven imported cardio records | See `docs/warm-up-cool-down.md`. |

## Applying it, and undoing it

From `backend/` (no migration):

```bash
python -m app.cli import-exercises --dry-run   # expect 842 updated on a catalog imported before
python -m app.cli import-exercises
```

The dry run on the dev database reported 842 updated (every shown imported exercise but the three
cardio ones that already had both), 0 rejected, and a second run reports nothing to update. The
import changes only imported exercises' `description` and `movement_pattern`, never a plan, session,
proposal or user; the eight user-owned tables were hashed before and after and are identical. A
`pg_dump` of the database was taken first.

To undo: revert `app/catalog/patterns.py`, `descriptions.py`, `free_exercise_db.py` and the ranking
steps, and run the import again: it writes every field the code gives, so the descriptions and
patterns return to what the code says (none).
