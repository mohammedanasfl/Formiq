# Nutrition and recovery (Phase 7)

`POST /users/{user_id}/workout-sessions/{session_id}/recovery-summary` returns a structured
summary for one **completed** workout: post-workout protein and carbohydrate, hydration, recovery
for the muscles actually trained, food examples that fit the user's diet, and the day's targets.

It only reads. It commits, flushes and locks nothing, stores nothing, and is not traced. All the
rules are deterministic Python (`app/guidance/`, applied by
`app/services/recovery_summary_service.py`). **No language model is involved**: there is no coach
tool, no LangGraph change and no Gemini call, and the response explains itself in fixed text.
A later phase can give the coach a read tool that explains exactly this validated result (that
changes the tool set pinned in `tests/unit/test_agent_contract.py`, so it is a deliberate
decision, with a contract update).

## Who may call it

- A Bearer token is required (401 otherwise). The path user must be the signed-in user: any other
  `user_id` is `404 {"detail": "not found"}`.
- Another user's session, and a missing one, are `404 user {id} has no workout session {sid}`.
  That check comes **before** the status check, so someone else's running session is a 404, never
  a 409: its existence is not revealed.
- Your own session that is `IN_PROGRESS` or `CANCELLED` is `409`.
- `422` for a bad body (the existing handler strips the input), or a path id outside 1 to
  2,147,483,647.
- A user with no profile still gets `200`: see "Missing data".

## Request

Optional: no body, `{}` and a full body are all valid. Unknown fields (including `user_id`) are
`422`. **Nothing is free text**, so no note can reach the rules, and nothing sent is stored or
echoed.

```json
{
  "discomfort": [{"area": "KNEES", "kind": "SORENESS", "severity": 5}],
  "warning_signs": ["DARK_URINE"],
  "avoid_allergens": ["PEANUTS", "MILK"]
}
```

| Field | Values |
|---|---|
| `discomfort[].area` | NECK, SHOULDERS, CHEST, UPPER_BACK, LOWER_BACK, ARMS, ELBOWS, WRISTS_HANDS, CORE, HIPS, GLUTES, FRONT_THIGHS, BACK_THIGHS, KNEES, CALVES, ANKLES_FEET |
| `discomfort[].kind` | SORENESS, PAIN, KNOWN_INJURY |
| `discomfort[].severity` | a JSON integer 0 to 10 (`"5"`, `5.5` and `true` are rejected) |
| `warning_signs[]` | CHEST_PAIN, SHORTNESS_OF_BREATH, FAINTING_OR_DIZZINESS, DARK_URINE, SEVERE_SWELLING, NUMBNESS_OR_TINGLING, SUDDEN_SEVERE_PAIN |
| `avoid_allergens[]` | the FDA's nine: MILK, EGG, FISH, CRUSTACEAN_SHELLFISH, TREE_NUTS, PEANUTS, WHEAT, SOY, SESAME |

At most 10 discomfort reports, each (area, kind) once; each warning sign and allergen once.

## Response: three kinds of statement

The groups are structural, so a client cannot mistake an estimate for a measurement.

| Group | What it is |
|---|---|
| `calculated` | Exact arithmetic on recorded data: session length, sets, reps, `volume_kg`, `average_rpe`, the muscles trained, the profile values the rules saw. |
| `estimates` | A published per-kg or MET coefficient applied to recorded data. **Always a range** (`low`, `high`, `unit`), with its `basis` (the arithmetic), `applies_if`, `assumptions` and `source_ids`. |
| `guidance` | General advice with no user-specific number: hydration, carbohydrate, sleep, recovery per muscle, food examples. |

Also: `safety` (`OK`, `CAUTION` or `SEEK_MEDICAL_CARE`, with notices), `missing_data` (each
input that was missing or out of range and what is not given because of it) and `sources` (only
those cited in this response). `volume_kg` and `average_rpe` are `null`, never 0, when no
completed set has a weight or an RPE. Notes are never echoed.

## Calculation rules

Constants are in `app/guidance/nutrition.py`, each with a comment naming its source.

**Gates** (an estimate is withheld, with a `missing_data` reason, and never guessed):
weight 30 to 300 kg (inclusive); age 18 or more for any numeric target; session length 5 to 240
minutes (a session left open would inflate it); the post-workout protein and the rapid-refuel
range only within 24 hours of finishing.

| Estimate | Rule |
|---|---|
| Post-workout protein | 0.25 to 0.40 g/kg, one meal or snack within about 2 h. Needs at least one counted exercise. |
| Daily protein | 1.6 to 2.0 g/kg for a goal of building muscle or losing fat; 1.4 to 2.0 g/kg otherwise (general fitness, or a goal Formiq does not recognise, which is noted). |
| Daily carbohydrate | Session under 60 min: 3 to 5 g/kg/day. 60 min or more: 5 to 7 g/kg/day. |
| Rapid refuel | 1.0 to 1.2 g/kg/h for the first 4 h, only `applies_if` you train hard again within 8 h. |
| Active energy | (MET - 1) x kg x hours, with MET 3.5 (Compendium code 02054, resistance training, multiple exercises, 8 to 15 reps) to 6.0 (code 02050, vigorous). Rounded out to 10 kcal. Ages 19 to 59 only. A range of energy the session used, never a food target, never a single number. |

Goals are normalised from the profile's free text: `muscle_gain` and `build_muscle` build
muscle; `fat_loss` and `lose_weight` lose fat; `general_fitness` is general. Every estimate
carries these assumptions: a healthy adult (not kidney disease, pregnancy, breastfeeding or
medical nutrition therapy); per-kg values use total recorded body weight (a note names the BMI
from 30); for a fat-loss goal, "these ranges fuel training, they are not a fat-loss plan; Formiq
sets no calorie target".

**What counts as trained.** Each session exercise is TRAINED (at least one completed set),
SKIPPED (sets, none completed) or LOGGED_WITHOUT_SETS (a timed exercise has no sets). Only
TRAINED and LOGGED_WITHOUT_SETS exercises in the **main workout** are counted. The section is
the linked plan exercise's, else the catalog `uses` (an exercise with none, or that suits the main
workout, is main work). Warm-up and cool-down never create a rest window. A muscle is PRIMARY if
it is primary in any counted exercise.

**Hydration.** Fixed text. Formiq does not measure fluid loss (`fluid_loss_measured` is always
`false`) and gives no amount of fluid to drink. The one per-kg figure, about 1.25 to 1.5 L per
kg lost, is worded as a check the user can make if they weighed themselves before and after
training. It is never multiplied by anything.

**Recovery, per muscle.** A PRIMARY muscle rests 48 h (`rest_until = completed_at + 48 h`). A
muscle worked only as a supporting muscle is `ALSO_WORKED`, with no window. Reported soreness of
4 or more makes that muscle 72 h; 7 or more also lists the warning signs to watch for; 0 to 3
changes nothing. `PAIN` or `KNOWN_INJURY` makes the mapped muscles `SEE_PROFESSIONAL`: no rest
time and no return-to-training time, which Formiq never gives (the response schema rejects a
`SEE_PROFESSIONAL` or `ALSO_WORKED` muscle that has a window). Body areas map to the 19 seeded
muscle groups in `app/guidance/recovery.py` (`AREA_MUSCLES`). Self-reported typical sleep under
7 hours adds a note (labelled self-reported, not measured); it is ignored at 0 or less and above
16.

**Food examples.** A catalog of 24 foods (14 protein-forward, 10 carbohydrate-forward) with
serving, protein and carbohydrate from USDA FoodData Central SR Legacy (one `fdc_id` each, pinned
in the unit tests). Up to 4 protein and 3 carbohydrate examples, in catalog order, no randomness.
Diet patterns: VEGAN; VEGETARIAN (lacto-vegetarian: **eggs excluded on purpose**, as in Indian
usage, and the conservative choice); EGGETARIAN; PESCATARIAN; NO_RESTRICTION. A profile value that
is unset gives examples marked "not filtered by diet"; one Formiq does not recognise gives no
foods and lists the accepted values. Allergies are not recorded: without `avoid_allergens` the
response says to check labels, and with them it says other allergens are not checked.

## Safety, decided in code, in this order

1. **A warning sign** (any entry in `warning_signs`) returns `SEEK_MEDICAL_CARE`: only the
   calculated facts and one urgent-care notice. No estimate, hydration, food or recovery timing is
   worked out, because fluid advice during a possible rhabdomyolysis is medical. Notes are not
   scanned in this branch.
2. **Caution** (any of these makes the status `CAUTION`):
   - pain or a known injury; soreness of 4 or more;
   - a note flagged by the coach's keyword backstop (`app.agent.safety.assess_safety`);
   - a recorded goal that loses more than 2 kg a week (`MAX_WEEKLY_LOSS_KG`; a period under a
     week counts as one week). The ranges are still shown.
3. Otherwise `OK`.

**Notes.** The session's, each exercise's and each set's `notes` are the only free text. They are
scanned once and never echoed; only Formiq's own fixed wording is returned.
- Pain, injury, medical, dangerous-exercise or unclear-discomfort note on an exercise or a set:
  that exercise's primary muscles become `SEE_PROFESSIONAL`. On the session: **all** counted
  muscles do (over-cautious on purpose: a session-level note cannot say where).
- Extreme dieting or weight loss in a note: a notice that the targets here fuel training and are
  not a diet. A note over 4000 characters (the coach's message cap) is not scanned, and the
  summary says so.
- Known false positive: a note such as "not injured" still raises the notice. That is accepted
  because the notice is harmless.

The thresholds (2 kg/week, the 24 h window, soreness 4 and 7, the 72 h rule) are **product
guardrails, not medical rules**, in the same sense as CLAUDE.md's.

**Never:** invent what the user ate, their fluid loss, sex, allergies or timezone; give a single
calorie number; give a calorie intake target; recommend a supplement; give a return-to-training
time for a painful or injured area.

## Missing data

| Missing or out of range | Effect |
|---|---|
| No profile | Calculated facts, hydration and recovery windows remain. No estimate, no sleep note, one `missing_data` entry `profile`. Food examples are not filtered (NOT_SET). |
| Weight outside 30 to 300 kg | No per-kg estimate and no energy estimate. |
| Age under 18 | No numeric target. |
| Age 60 or more | No energy estimate; the protein and carbohydrate ranges stay. |
| Age 18 | Everything except the energy estimate (the Compendium covers 19 to 59). |
| Implausible session length | `duration_plausible` is `false`: no daily carbohydrate, rapid refuel or energy estimate. |
| More than 24 h since completion | No post-workout protein or rapid refuel; daily targets and recovery stay. |
| No `completed_at` (data written outside the API) | The last update time is used for rest windows, no session length, and `missing_data` says so (not reported in the warning-sign branch). |
| Nothing counted | No muscles, no rest windows, no post-workout protein. |
| Only timed exercises, no sets | Muscles are counted, with the reason "how much work was done is unknown". |

## Sources

Every response cites only the sources it uses (`sources`); the registry is
`app/guidance/sources.py`. ISSN protein and nutrient-timing position stands (2017), Morton 2018,
Schoenfeld and Aragon 2018, ACSM/AND/DC nutrition and athletic performance (2016), ACSM fluid
replacement (2007), the 2024 Adult Compendium of Physical Activities, ACSM quantity and quality
of exercise (2011), Cheung 2003, AASM/SRS sleep (2015), USDA FoodData Central, the FDA's nine
allergens, CDC/NIOSH on rhabdomyolysis.

**Not verified against a primary text** (marked `# UNVERIFIED:` in the code):
- The carbohydrate band by session length. The ACSM table picks a row by the whole daily
  programme, not one session, and lists higher rows (6 to 10 g/kg/day) above about 1 h a day. The
  assumptions say so.
- That soreness peaks 24 to 72 h after training (Cheung 2003's full text is paywalled), so no
  text says it; 72 h is a product rule at the top of the 48 to 72 h range ACSM 2011 gives.
- Pale-yellow urine as a check *after* training (the source gives it for before exercise).
- The warning-sign list. CDC supports dark urine and unusually severe muscle pain or weakness;
  the cardiac and nerve signs are Formiq's own added caution.
- The 1.5 L/kg figure in the ACSM 2007 stand itself (only seen as a quote). The 1.25 to 1.5 L
  figure is verified in the 2016 joint position.
- The 11th edition of ACSM's guidelines (paywalled): the 48 h rule cites the 2011 position stand
  instead.

Food values come from the SR Legacy download and were cross-checked by the implementer against
the live FDC API; they are pinned per `fdc_id` in `tests/unit/test_guidance_foods.py`.

## Tests

- Unit (no database): `tests/unit/test_guidance_nutrition.py`, `test_guidance_recovery.py`,
  `test_guidance_foods.py` (the rules, gates, catalog and package purity),
  `test_recovery_summary_schemas.py` (the contract, and that its status literals equal the
  guidance enums).
- Integration (`formiq_test`): `test_recovery_summary_service.py` (the service, including that
  nothing is written and that notes are never echoed) and `test_recovery_summary_api.py` (every
  status code and the 404-not-403 rule), plus the route in `test_auth_api.py`'s `PROTECTED` and
  `OTHER_USERS` lists.

## Not done yet

- A coach read tool to explain the summary (needs a contract update).
- Persisted discomfort or injuries, and allergies in the profile (both need a migration).
- A daily summary by date and timezone, combining several sessions on one day.
- Measured fluid loss (weight before and after).
- Regional food data (for example IFCT 2017); paneer and roti are not in FDC SR Legacy.
- The Older Adult Compendium, for ages 60 and over.
- A playground view.
- A different carbohydrate row for a BMI of 30 or more (it is only noted).
