# Warm-up and cool-down activities

What the catalog offers for the warm-up and cool-down sections of a proposed workout, the rules
behind it, the sources, and what is **not** verified. The classification of the imported exercises
is in `backend/app/catalog/classification.py`; Formiq's own activities are seeded by the
migrations `14d543e636a8`, `a7d3f1c82e4b` and `c9e24b7a5d13`.

Status: on branch `phase-7-nutrition-recovery`, uncommitted, not merged to `dev`.

## Rules

- **Structure.** A warm-up follows the RAMP idea (Raise, Activate and Mobilise, Potentiate): easy
  cardio to raise the heart rate, then drills that move the joints or switch on the muscles the
  main exercises use. "Potentiate" (the first lighter sets of the main lift) is part of the main
  workout, not of the catalog. A cool-down is easy cardio that slows down, and held stretches.
- **Dynamic before, held after.** Warm-up drills are dynamic: reps, circles, swings, light
  activation. Held stretches belong in the cool-down. The coach already enforces the section by
  each exercise's `uses`.
- **Light and solo.** Every activity is BEGINNER, done alone, and needs no equipment the record
  does not name. Faster or intermediate cardio is left out (see `classification.py`).
- **The coach's constraint.** A warm-up or cool-down activity must work a muscle the main
  exercises train (primary or secondary), or be easy CARDIO, which suits any workout
  (`suited_main` in `app/tools/formiq_tools.py`). So the muscles an activity names decide when it
  can be chosen, and a muscle with no activity can only be warmed up with easy cardio.
- **Every Formiq warm-up and cool-down description has the same shape:** the steps,
  `Suggested dose: ...`, `Safety: ...`. The dose is a suggestion, never a prescription.
- **No benefit is claimed.** A description never says an activity prevents injury, reduces
  soreness, aids recovery or burns calories. `tests/unit/test_warm_up_cool_down_catalog.py` fails
  on those words.

## What changed

### 13 duplicates are hidden

Imported records that repeat an activity the catalog keeps. They suit no section (`uses` is
empty), exactly as `FORMIQ_DUPLICATES` does for main exercises. Nothing is deleted: the rows stay,
active and readable by id, so a saved plan that holds one still reads it.

| Hidden (imported record) | Kept instead |
|---|---|
| `Standing_Hip_Circles` | Hip Circles |
| `Cat_Stretch` | Cat-Cow |
| `Kneeling_Hip_Flexor` | Kneeling Hip Flexor Stretch |
| `Calf_Stretch_Hands_Against_Wall`, `Calf_Stretch_Elbows_Against_Wall` | Standing Calf Stretch |
| `Triceps_Stretch` | Overhead Triceps Stretch |
| `Shoulder_Stretch` | Cross-Body Shoulder Stretch |
| `Ankle_On_The_Knee` | Figure-Four Glute Stretch |
| `Knee_Across_The_Body` | Supine Spinal Twist |
| `Front_Leg_Raises` | Leg Swings |
| `Bicycling_Stationary` | Easy Stationary Cycling |
| `Walking_Treadmill` | Brisk Walk |
| `Upward_Stretch` | Overhead Stretch (imported) |

Formiq's own row is kept where there is one because saved plans already use it. A test checks that
the exercise kept still suits every section the hidden one suited.

### 52 imported rows get a movement pattern

63 imported drills and stretches had none. 37 held stretches are now `STRETCH` and 15 drills are
`MOBILITY` (foam rolling is listed as both and is `MOBILITY`). Cardio records were already
`CARDIO`.

The 11 that are hidden duplicates (9 stretches, 2 drills) are **left without a pattern**: a search
by movement pattern has no section to leave them out by, so a pattern would offer the coach an
exercise it cannot propose (the proposal is refused: its `uses` are empty). This is why 52 rather
than 63 are classified. Main exercises, and the stretching records that suit no section, stay
unclassified too (until the field pass of 2026-10-20, which patterned them by rule and by hand:
`docs/exercise-fields.md`).

Giving the visible ones a pattern also changes search order: the coach ranks activities with no
pattern last, so the imported drills and stretches now rank with Formiq's own instead of after
them.

### Effect on the coach's searches

`search_exercises` returns at most `MAX_SEARCH_RESULTS` exercises, a limit pinned in
`tests/unit/test_agent_contract.py`. It was 10 when this work was done, and **15 since the second
pass of 2026-10-20** (below), which the user asked for; the 10 tool calls per round were 8. Until
now each kind of activity fitted in one such search: 8 drills (`MOBILITY`), 10 stretches
(`STRETCH`) and 5 easy cardio (`CARDIO`), because no imported record had a pattern. They no longer
do. On the seeded catalog alone there are 21, 16 and 7 (the output's `total_matches` says so), and
with the imported catalog 36 drills and 53 stretches.

- **What still holds.** Narrowed by a major muscle group, a search for a kind returns every match
  on the seeded catalog (9 at most), and the tool's own text already says to narrow by muscle. A
  test pins that, and the coach still searches by `use` and muscle.
- **What does not.** With the imported catalog loaded, a search narrowed by one muscle can still
  return more than the limit: 11 of the 36 warm-up and cool-down searches for one muscle (primary
  or secondary) match more than 10, and 5 more than 15 (the hamstrings in a cool-down: 20). The
  most relevant come first, easy cardio ahead of the rest, `total_matches` says how many there
  are, and a `note` says the list was cut.
- **The scripted tests.** The scenario tests script a model that searched a whole kind and then
  proposed one of its exercises; that exercise can now fall outside the first 10. They now search
  by muscle (`proposing` in `tests/integration/test_plan_proposals.py`, the trajectory test) or
  search for the easy cardio the workout uses (the two equipment tests). The grounding rule (an id
  must come from a tool result of the same request) is unchanged.
- **Measured live** (2026-10-19, `gemini-3.5-flash-lite`, 89 requests): see "Live QA, and what it
  changed" below.

### Easy cardio records say how to do them

The dataset's steps for `Bicycling`, `Recumbent_Bike` and `Jogging_Treadmill` are set-up text for a
machine, with nothing about an easy pace: one step to adjust the seat for `Bicycling`, and "select
the desired option from the menu" and "estimate the calories burned" for the other two. Formiq's
description is in `app/catalog/descriptions.py`, and **replaces the steps wherever instructions are
read** (`Exercise.instructions` is empty for an imported exercise Formiq described, as it is for
Formiq's own): the live QA found the machine menu and the calorie estimate still served by the
coach's `get_exercise` and by `/exercises/{id}` for `Recumbent_Bike` and `Jogging_Treadmill`. The
record itself is untouched, in `source_record`. The two other records with such text are the hidden
duplicates `Bicycling_Stationary` and `Walking_Treadmill`: a saved plan or a read by id still shows
them, and the dev check of 2026-10-20 found them serving the calorie estimate, so they have a
description too (five in all).

### Live QA, and what it changed

A live pass (2026-10-19 and 20, `gemini-3.5-flash-lite` through the real `/coach/message` route, on
`formiq_test` in one rolled-back transaction) tested 10 scenarios, 2 samples of the workout ones.
The coach produced valid proposals with no equipment mismatch and no hidden duplicate, but it
rarely found the new activities. Each finding and what was done:

| Finding | Change |
|---|---|
| The model never narrowed warm-up and cool-down searches by muscle (15 of 16 proposals), so it got the same generic 10 whatever the workout: only 2 of the 21 new activities were ever chosen, and ankle circles were offered for a chest day | `most_relevant` ranks an activity for a warm-up or cool-down search, once main exercises were found, by whether a main exercise trains its primary muscle, then any of its muscles, and last none (which no proposal could use). A muscle asked for still comes first, and easy cardio stays first. |
| A list cut at 10 was shown as complete ("every hamstring stretch": 10 of 11) | A cut search carries a `note` ("Showing 10 of 11 matches... say that 1 more exists"), the tool text and the prompt say never to present some matches as all of them. |
| "Recumbent Bike" and "Treadmill" were refused as unknown equipment (5 wasted searches in a turn) | "recumbent bike" is an alias of Stationary Bike, and `Treadmill` is catalog equipment (`c9e24b7a5d13`); `EQUIPMENT_NAMED` links `Jogging_Treadmill`, `Walking_Treadmill` and `Recumbent_Bike` to the equipment that names them. They were "Machine" in the records, which would also have said the user has the strength machines. |
| The model sent `available_equipment: [""]` for "none" (6 refused searches) | A blank name is dropped: `[""]` reads as `[]`. A name that is not blank is read as before, and an unknown one is still refused. |
| The upstream calorie text was still served for two cardio records | Formiq's description replaces the steps (above). |
| Stretches held for one 180-second set, against a catalog dose of 20 to 30 seconds | A held stretch (`STRETCH`) in a proposal is held 60 seconds a set at most (`MAX_STRETCH_HOLD_SECONDS`); more time is more sets. |
| A search with no section (`movement_pattern=CARDIO`) returned the hidden "Bicycling, Stationary" | Searches leave the hidden duplicates out (`visible`, from `HIDDEN_DUPLICATE_IDS`), and so does the list a section search that finds nothing names. They are still read by id and in saved plans. |
| The 8-call limit dropped the cool-down search in 4 of 25 turns, and the cool-down was chosen from the warm-up results | A call that was not run now says to ask again in the next round, before proposing. Fewer calls are wasted too (the two fixes above). The limit was first left at 8, and raised to 10 in the second pass. |
| A requested exercise or equipment the coach could not use was dropped or swapped without saying so ("includes the Cat Stretch you requested" when the card held Cat-Cow) | The prompt tells the coach to say so plainly and name what it used instead. A prompt is not a guarantee: the next live pass has to check it. |

**Re-run after the fixes** (2026-10-20, same model and harness, 16 turns, 57 requests, none
failed): no search was refused (22 of 101 before), no turn hit the 8-call limit (4 of 25), every
cut list carried its note and the coach said "10 of the hamstring stretches... there is 1 more", the
treadmill and recumbent bike were found and the coach read their instructions without the calorie
text, a neck stretch and a breathing drill were reported as not in the catalog, no hidden duplicate
was retrieved or proposed, no equipment mismatch. A leg day got hip flexor and glute stretches
where it got Cat-Cow, a chest day a dynamic chest stretch. What the re-run did **not** fix, and the
second pass below did:

- **The new activities are still rarely chosen** (3 of 45 picks). The ranking only helped when the
  model's main searches were narrowed by muscle (a chest and triceps day: yes; a back and biceps
  day searched without a muscle: its main set covers the whole body, so nothing ranked higher, and
  the biceps drill was not offered).
- **The coach says a hidden exercise is "not in the catalog"** ("Standing hip circles are not in the
  Formiq catalog"), which is wrong, and "included the Cat Stretch" for Cat-Cow. The tools could not
  look an exercise up by name, so it could not know.
- **The coach gave a calorie figure** ("25 to 45 calories") when asked, from its own knowledge. No
  rule forbade it in a reply about a workout; the recovery summary gives a range with its sources.
- **The limits**: 8 calls and 10 results.

Not changed, and why: the manual plan API still accepts a hidden duplicate in a plan (it checks no
exercise's `uses`, by design, so a user may build any plan); `MIN_WARM_UP_MINUTES = 3`; the model's
habit of putting the same easy cardio in the warm-up and the cool-down.

### Second pass (2026-10-20): the four things the first one left

Done at the user's request ("fix also") after the first re-run, and applied to the dev database
(below).

| Left open | Change |
|---|---|
| New activities rarely chosen when the main search names no muscle | A warm-up or cool-down search ranks by the muscles the **user's latest message names** (`app/tools/muscles.py`: the catalog's muscle names and common ones, "pecs", "abs", "legs", "upper body", "push day"; a muscle named with "no", "without", "hurts" or "yesterday" is left out, and so is it from a group that names it: "legs, without hamstrings"), and when it names none, by the main exercises found. It orders a search and refuses no proposal: a "workout for today" is ranked as before. A back and biceps day is now offered Light Band Biceps Curl and Band Pull-Apart, and Wall Biceps Stretch. |
| "Not in the catalog" for an exercise the catalog keeps | `search_exercises` takes `name`: the words of an exercise's name (`app/tools/exercise_names.py`: plural, hyphen and case tolerant, every word must match, never a near match). The name of a hidden duplicate finds the exercise kept in its place (`DUPLICATE_OF`, 18 of them, each pinned), first, and the `note` says "The catalog keeps 'Standing Hip Circles' as 'Hip Circles'". A name nothing has says that is not the catalog lacking the exercise. The prompt tells the coach to look an exercise up by name before saying it is missing. |
| A calorie figure from the model's own knowledge | A prompt rule: never give a number of calories burned by a workout, an exercise or a warm-up. It is a prompt, not a guarantee (the recovery summary's sourced range is unchanged). |
| The two pinned limits | `MAX_SEARCH_RESULTS` 10 to **15** (the longest single-muscle activity lists then mostly fit: 31 of 36 searches, against 25), and `MAX_EXECUTED_TOOL_CALLS_PER_TURN` 8 to **10** (a leg day searched by movement pattern used all 8 with its three reads, and the cool-down search was the one lost). A request holds one round of 10 results, so `CONTEXT_MAX_CHARS` follows, 500,000 to **600,000** characters (about 150,000 tokens, the bound in the worst case of ten 47,000-character results). All three are pinned in `tests/unit/test_agent_contract.py`; reverting is one constant each. |

Also: the two hidden cardio duplicates got a description (above), because the dev check found them
serving the calorie estimate.

**Measured live** (2026-10-20, `gemini-3.5-flash-lite`, same harness: 21 turns and 62 requests, all
answered; then S2, S8 and S11 again after two fixes, 8 turns and 22 requests):

- A back and biceps day got Band Pull-Apart and Light Band Biceps Curl for the warm-up and Wall Biceps
  Stretch for the cool-down; a chest and triceps day Dynamic Chest Stretch and Wall Push-Up, then
  Doorway Chest Stretch and Overhead Triceps Stretch. 12 of 14 workout sections held an activity for
  a muscle the main exercises train (11 of 14 before), and 7 of the 20 activities chosen besides easy
  cardio were among the 21 new ones (2 of 19 before).
- Asked for "every hamstring stretch", the coach listed all 11 (it said 10 of 11 and left one out
  before): the 15-result limit holds them, so no note was needed.
- Asked twice how many calories a warm-up burns, the coach gave no figure ("Formiq doesn't provide
  calorie burn figures"); it said "25 to 45 calories" before.
- Asked by name for "Standing Hip Circles" and "Cat Stretch" the coach said they are kept as "Hip
  Circles" and "Cat-Cow" (it said they were not in the catalog); a SkiErg was reported missing and
  the Sled Push found. The first run of the by-name scenario found two gaps, fixed and re-run:
  searching by name with a section ("main workout") found Cat-Cow only as a match for another use,
  with no note, and "walking on a treadmill" matched nothing because of the word "on". The coach is
  now told to search without a section, a name kept as another is said even then, and "on", "in",
  "at" and "to" are filler words. Re-run: the workout holds Hip Circles and Cat-Cow where the user
  asked for their hidden names.
- A leg day used 8 of the 10 calls. One request, to put three hidden names and a treadmill in a
  workout, asked for 12 calls in a round: 10 ran, 2 were refused, and the coach asked again.
- No hidden duplicate was returned, no search was refused for its equipment, every cut list carried
  its note (43 of 43), and the model reported was `gemini-3.5-flash-lite` on every request.

What this pass did **not** fix, and found:

- The coach's wording is still not exact: it wrote "Standing/Hip Circles", and "the Formiq catalog
  does not have a treadmill" to a user who said they have no equipment. Prompt rules are not
  guarantees.
- Gemini returned an empty reply twice in a row on the hardest request (13 calls in the turn), and
  the coach answered 502 ("could not answer; try again later"); the third try worked. None of the 119
  requests of the two earlier runs did. The retry is the client's.
- Seven imported cardio records that suit no section (`Elliptical_Trainer`, `Rope_Jumping`,
  `Running_Treadmill`, `Skating`, `Stairmaster`, `Step_Mill`, `Trail_Running_Walking`) still serve
  the dataset's own calorie estimate when read by id: its steps mix the instruction and the estimate
  in one sentence, so they cannot be cut safely. The new prompt rule is what keeps the coach from
  relaying them. Describing them as the five were, or hiding them, is a decision.

Not done, on purpose: no proposal is refused for lacking a drill for the muscles trained. Easy
cardio suits any workout is an existing guarantee (and the scenario tests rely on it), so the
choice stays the model's, with the best activities first.

### 21 new Formiq activities (`a7d3f1c82e4b`)

All BEGINNER. Doses are suggestions (see "Unverified").

| Activity | Section | Pattern | Main muscles | Equipment | Suggested dose |
|---|---|---|---|---|---|
| Step Jacks | warm-up | CARDIO | Abductors, Glutes | none | 30 to 60 s |
| Ankle Rocks | warm-up | MOBILITY | Calves | none | 8 to 10 each foot |
| Bodyweight Hip Hinge | warm-up | MOBILITY | Hamstrings, Glutes | none | 8 to 10 |
| Lateral Lunge | warm-up | MOBILITY | Adductors, Glutes | none | 6 to 8 each side |
| Side-Lying Clamshell | warm-up | MOBILITY | Abductors, Glutes | none | 10 to 12 each side |
| Lying Pelvic Tilt | warm-up | MOBILITY | Core | none | 8 to 10 |
| Standing Cross-Crawl | warm-up | MOBILITY | Core, Obliques | none | 10 to 20 touches |
| Scapular Wall Slide | warm-up | MOBILITY | Upper Back, Shoulders | none | 8 to 10 |
| Scapular Push-Up | warm-up | MOBILITY | Upper Back | none | 8 to 10 |
| Wall Push-Up | warm-up | MOBILITY | Chest, Triceps | none | 8 to 12 |
| Light Band Biceps Curl | warm-up | MOBILITY | Biceps | Resistance Band | 10 to 12 |
| Light Band Triceps Pushdown | warm-up | MOBILITY | Triceps | Resistance Band | 10 to 12 |
| Walking Knee Hug | warm-up | MOBILITY | Glutes | none | 6 to 8 steps each leg |
| Squat to Stand | warm-up | MOBILITY | Hamstrings, Glutes | none | 6 to 8 |
| Butterfly Stretch | cool-down | STRETCH | Adductors | none | hold 20 to 30 s, once or twice |
| Wall Biceps Stretch | cool-down | STRETCH | Biceps | none | hold 20 to 30 s each arm |
| Wrist Extensor Stretch | cool-down | STRETCH | Forearms | none | hold 20 to 30 s each arm |
| Lying Overhead Reach | cool-down | STRETCH | Core, Lats | none | hold 20 to 30 s |
| Standing Cross-Leg Side Bend | cool-down | STRETCH | Abductors | none | hold 20 to 30 s each side |
| Seated Spinal Twist | cool-down | STRETCH | Obliques | none | hold 20 to 30 s each side |
| Easy Walk | cool-down | CARDIO | Calves | none | 3 to 5 min |

None of the names matches an exercise in the dataset or the earlier seeds (a test checks this, so
the importer never has to skip a record for it).

### 26 existing Formiq activities gain a dose and a safety note

Every Formiq exercise whose `uses` name WARM_UP or COOL_DOWN keeps its text and gains
`Suggested dose: ...` and `Safety: ...` after it. The three that are also main exercises (Bodyweight
Squat, Glute Bridge, Bird Dog) get a dose "as a warm-up". A description is changed only while it is
still the one `14d543e636a8` wrote, so one edited by hand is left alone.

### Coverage

| | Before | After |
|---|---|---|
| Warm-up activities | 38 (16 Formiq) | 48 (30 Formiq) |
| Cool-down activities | 69 (17 Formiq) | 65 (24 Formiq) |
| Warm-up drills with the triceps as a main muscle | 0 | 2 |
| ... the biceps | 0 | 1 (needs a light band) |
| ... the chest | 1 | 2 |
| ... the core | 2 | 4 |
| Main exercises | 747 | 747 |

The cool-down is smaller because 11 duplicates are hidden; each muscle group the main exercises
train still has at least two stretches (`tests/integration/test_exercise_catalog_coverage.py`).

## Sources, and what was checked

"Opened" means the record's abstract was read through Europe PMC (by a summarising fetch tool,
not as a verbatim copy); "snippet" means only a search result or a summary of one was seen. No
paper was read in full.

| Source | Used for | Checked |
|---|---|---|
| Fradkin, Zazryn, Smoliga 2010, *J Strength Cond Res* 24(1):140-148 | a warm-up improved performance on 79% of the outcome measures (32 studies); not 79% of studies | snippet (PubMed record) |
| Behm, Blazevich, Kay, McHugh 2016, *Appl Physiol Nutr Metab* 41(1):1-11 (doi 10.1139/apnm-2015-0235) | tested right after, static stretching -3.7% and dynamic +1.3%; static holds of 60 s or more per muscle did worse; the rule "dynamic before, held after" | opened (Europe PMC record) |
| Thorborg et al. 2017, *Br J Sports Med* (FIFA 11+) | a structured neuromuscular warm-up cut injuries in football players (39% in six trials). Football only: used to justify activation drills, **not** to claim injury prevention | snippet |
| Jeffreys, RAMP warm-up (about 2007) | the warm-up structure; a coaching framework, not a trial result | snippet (secondary summaries) |
| Van Hooren, Peake 2018, *Sports Med* 48(7):1575-1595 (open access, PMC5999142) | active cool-downs were largely ineffective for most recovery markers, soreness included, and did not prevent injury: why no cool-down text promises a benefit | opened (Europe PMC record) |
| Afonso et al. 2021, *Front Physiol* (meta-analysis of post-exercise stretching) | data insufficient to recommend it for recovery | snippet |
| Garber et al. 2011, ACSM position stand, *Med Sci Sports Exerc* 43(7):1334-1359 | flexibility exercise on at least 2 days a week | opened; the abstract gives no hold time or warm-up length |

## Unverified

These are Formiq's judgement, in the same spirit as the product guardrails in `CLAUDE.md`, not
medical rules:

- **Every suggested dose.** Held stretches of 20 to 30 s, once or twice, sit inside the 10 to 30 s
  range that secondary summaries attribute to ACSM; that range, 2 to 4 repetitions, about 60 s per
  muscle group and 5 to 10 minutes for a warm-up or cool-down were **not** found in a primary text.
  The reps (6 to 12) and cardio times (30 s to 5 min) are chosen to match the ranges in the
  imported records ("hold for 10-20 seconds", "repeat 5-10 times"), not taken from a source.
- **The "talk test" pace** for easy cardio matches the existing Brisk Walk text; its source was not
  checked.
- **Every safety note.** Generic caution ("stop if you feel sharp pain, dizziness, numbness or
  tingling"; check a band for nicks); not clinical guidance, and not reviewed by a clinician.
- **The muscles tagged on each new activity** are Formiq's reading of the movement, not an
  anatomical source.
- **`MIN_WARM_UP_MINUTES = 3`** (`app/tools/limits.py`) is below the 5 to 10 minutes secondary
  sources cite. It was not changed.

## Known gaps, left on purpose

- **Neck.** No activity works the neck (5 main exercises do). Neck stretches pulled by the hands
  were already left out; a gentle no-pull tilt was considered and left for a decision, since it is a
  safety call.
- **A breathing drill** for the cool-down: no muscle group fits it honestly, and no source was
  checked.
- **A warm-up for the biceps without equipment.** The only drill that works the biceps as a main
  muscle needs a light band; the others are easy cardio.
- **Dead Bug and External Rotation with Band** already exist as imported main exercises. Copies
  would recreate the duplicates, so neither was added as a warm-up. Allowing an imported main
  exercise as a warm-up would be a change to `classification.py`'s rules.
- **Images.** None of these activities has one: the dataset's images are not cleared for
  redistribution, and the new activities have none yet.
- **A set needs `reps`**, so a timed activity (a hold, a cardio bout) is prescribed in the proposal
  by `duration_seconds`; the catalog has no default dose field. The dose lives in the description
  text.
- **Sessions with no plan.** A hidden duplicate logged in a session that has no plan counts as main
  work in the recovery summary, as any exercise that suits no section does. Sessions started from
  a plan use the plan's section and are unaffected.
- **A new proposal cannot hold a hidden duplicate** (`propose_workout_plan` checks `uses`), so a
  revision of a saved plan that holds one must name another exercise for that slot; the saved plan
  is never edited. Approval and saved plans do not check `uses` again, so a proposal already pending
  is still approved, and a saved plan still reads.
- **`playground/README.md`** listed "Cat Stretch" (hidden now) among the kneeling activities of a manual
  scenario; it was taken out of that list.

## Applying it

From `backend/`, in this order (no new name clashes with the dataset, which a test pins):

```bash
alembic upgrade head                           # c9e24b7a5d13 (a7d3f1c82e4b before it)
python -m app.cli import-exercises --dry-run   # then without --dry-run
```

Migrate **before** importing: the import links the treadmill records to the equipment
`c9e24b7a5d13` adds. Against a database still at `9f7cfca45752` the dry-run reports 66 updated and
rejects `Jogging_Treadmill` and `Walking_Treadmill` ("the catalog has no equipment 'Treadmill'"),
nothing else is lost. After `alembic upgrade head` it reports 68 updated: 52 gained a movement
pattern, 13 hidden duplicates changed `uses`, 5 cardio records gained a description (two of them
hidden duplicates, counted among the 13), and 3 treadmill and recumbent bike records changed
equipment (overlapping those). By section the imported exercises are WARM_UP 18, MAIN_WORKOUT 720,
COOL_DOWN 41.

**Applied to the dev database on 2026-10-20** (`formiq`, 127 users, 86 plans, 96 proposals, 31
sessions): a `pg_dump` first, then `alembic upgrade head` (`9f7cfca45752` to `c9e24b7a5d13`), the
dry-run (68 updated, 0 rejected, 0 unresolved) and the import. It left the eight user-owned tables
byte-identical (row hashes before and after), 913 exercises became 934 (the 21 new activities),
equipment 18 became 19 (Treadmill), all 86 saved plans and every exercise still serialise, and a
second dry-run reports nothing to update. The two descriptions of the second pass were imported
afterwards (2 updated).

To undo: `alembic downgrade 9f7cfca45752` gives the exercises linked to "Treadmill" their record's
"Machine" and deletes it, then restores the descriptions and deletes the 21 new activities. It
fails, changing nothing, if a plan or session uses one of them. The import is re-runnable:
restoring `uses`, patterns and equipment means reverting `classification.py` and importing again.
