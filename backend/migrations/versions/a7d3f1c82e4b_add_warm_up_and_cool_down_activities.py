"""add warm-up and cool-down activities, and say how to do them

Revision ID: a7d3f1c82e4b
Revises: 9f7cfca45752
Create Date: 2026-10-19 10:00:00.000000

The warm-up and cool-down activities of 14d543e636a8 left some muscles with
nothing to prepare or stretch them (no warm-up drill worked the triceps, none
had the biceps as its main muscle, one had the chest), and said nothing about
how long to do them or what to watch for. This adds, as Formiq's own exercises
(docs/warm-up-cool-down.md has the rules, the sources and what is unverified):

- 14 warm-up activities: a low-impact way to raise the heart rate, and drills
  that mobilise the ankles, hips, spine and shoulders or switch on the glutes,
  the core, the shoulder blades, the chest and the arms. All BEGINNER and
  light; the arm drills use a light resistance band, the rest need nothing.
- 7 cool-down activities: stretches, and an easy walk to slow down with.

and gives the 26 existing Formiq warm-up and cool-down activities (those whose
uses name WARM_UP or COOL_DOWN) a suggested dose and a safety note after the
text they have. The doses are suggestions, not medical rules.

Every description follows the same pattern: the steps, "Suggested dose: ...",
"Safety: ...". Nothing promises a benefit.

Safe to run on a catalog that has users' plans: no exercise is deleted or
renamed and no id changes, so every plan and session still reads. A name that
already exists stops the upgrade instead of attaching muscles to another
exercise. A description is changed only while it is still the one 14d543e636a8
wrote, so one edited since is left alone. The downgrade restores those
descriptions and deletes the new exercises; one that a plan or session uses
cannot be deleted, so the downgrade then fails and changes nothing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert


# revision identifiers, used by Alembic.
revision: str = 'a7d3f1c82e4b'
down_revision: Union[str, Sequence[str], None] = '9f7cfca45752'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The tables as they are at this revision. The application models are not
# imported, so later model changes do not change this migration.
muscle_groups = sa.table(
    "muscle_groups",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)
equipment = sa.table(
    "equipment",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)
exercises = sa.table(
    "exercises",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("difficulty", sa.String),
    sa.column("movement_pattern", sa.String),
    sa.column("uses", postgresql.ARRAY(sa.String(20))),
    sa.column("source", sa.String),
)
exercise_muscles = sa.table(
    "exercise_muscles",
    sa.column("exercise_id", sa.Integer),
    sa.column("muscle_group_id", sa.Integer),
    sa.column("role", sa.String),
)
exercise_equipment = sa.table(
    "exercise_equipment",
    sa.column("exercise_id", sa.Integer),
    sa.column("equipment_id", sa.Integer),
)

# The muscle groups and the equipment are the earlier seeds'.
WARM_UP = ["WARM_UP"]
COOL_DOWN = ["COOL_DOWN"]

# All BEGINNER. The muscles are those the activity prepares or stretches, at
# least one of them PRIMARY.
NEW_ACTIVITIES = [
    # --- warm-up ---
    {
        "name": "Step Jacks",
        "description": "Step one foot out to the side while raising both arms overhead, then "
        "step back and repeat on the other side. A low-impact alternative to Jumping Jacks: "
        "no jumping. Suggested dose: 30 to 60 seconds at an easy pace. Safety: keep the "
        "movement light and slow down if you feel breathless or a joint hurts.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARDIO",
        "uses": WARM_UP,
        "muscles": {
            "Abductors": "PRIMARY",
            "Glutes": "PRIMARY",
            "Shoulders": "SECONDARY",
            "Calves": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Ankle Rocks",
        "description": "Stand facing a wall with one foot forward and the toes about a hand's "
        "width from it. Keeping the front heel down, glide the front knee forward toward the "
        "wall, then back; switch feet. Suggested dose: 8 to 10 slow rocks on each foot. "
        "Safety: keep the heel on the floor and the knee in line with the toes; stop if the "
        "front of the ankle pinches or hurts.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {"Calves": "PRIMARY", "Quadriceps": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Bodyweight Hip Hinge",
        "description": "Stand with the feet hip-width apart, hands on the hips and the knees "
        "slightly bent. Push the hips straight back, keeping the back flat and the chest "
        "proud, until you feel the back of the thighs, then stand tall by driving the hips "
        "forward. Suggested dose: 8 to 10 slow reps. Safety: keep the back flat rather than "
        "rounded and stay within a comfortable range; stop if you feel pain in the lower "
        "back.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {
            "Hamstrings": "PRIMARY",
            "Glutes": "PRIMARY",
            "Lower Back": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Lateral Lunge",
        "description": "Stand tall with the feet together, step wide to one side and sit the "
        "hips back and down over that leg while the other leg stays straight, then push back "
        "to the start. Alternate sides. Suggested dose: 6 to 8 reps on each side, using a "
        "shallow range at first. Safety: keep the knee over the toes and the heel down; "
        "reduce the depth or stop if the knee or groin hurts.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {
            "Adductors": "PRIMARY",
            "Glutes": "PRIMARY",
            "Quadriceps": "SECONDARY",
            "Hamstrings": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Side-Lying Clamshell",
        "description": "Lie on your side with the hips and knees bent and the feet together. "
        "Keeping the feet touching, lift the top knee as far as you can without rolling the "
        "hips back, then lower it slowly. Suggested dose: 10 to 12 slow reps on each side. "
        "Safety: keep the hips stacked and the movement small and controlled; stop if you "
        "feel pinching at the front of the hip.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {"Abductors": "PRIMARY", "Glutes": "PRIMARY"},
        "equipment": [],
    },
    {
        "name": "Lying Pelvic Tilt",
        "description": "Lie on your back with the knees bent and the feet flat. Breathe out "
        "and gently press the lower back toward the floor by tilting the pelvis up, then "
        "release back to a neutral spine. Suggested dose: 8 to 10 slow reps. Safety: keep "
        "the movement small and smooth, without lifting the hips high or holding the breath; "
        "stop if it causes back pain.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {"Core": "PRIMARY", "Lower Back": "SECONDARY", "Glutes": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Standing Cross-Crawl",
        "description": "Stand tall and lift one knee toward the chest while tapping it with "
        "the opposite hand or elbow, then switch sides in a steady rhythm. Suggested dose: "
        "10 to 20 touches in total, at an easy pace. Safety: stand tall and keep the "
        "movement controlled; hold a wall or chair if your balance is unsteady.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {
            "Core": "PRIMARY",
            "Obliques": "PRIMARY",
            "Quadriceps": "SECONDARY",
            "Shoulders": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Scapular Wall Slide",
        "description": "Stand with the back, hips and head near a wall and the arms bent at "
        "shoulder height with the backs of the hands toward the wall. Slide the arms up the "
        "wall as far as is comfortable, keeping the ribs down, then lower them. Suggested "
        "dose: 8 to 10 slow reps. Safety: stay within a pain-free range; stop if you feel "
        "pinching in the shoulder or tingling in the arm.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {
            "Upper Back": "PRIMARY",
            "Shoulders": "PRIMARY",
            "Rear Deltoid": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Scapular Push-Up",
        "description": "From a high plank (or on the knees) with straight arms, let the chest "
        "sink between the shoulder blades, then push the floor away to spread the shoulder "
        "blades apart. Only the shoulder blades move; the elbows stay straight. Suggested "
        "dose: 8 to 10 slow reps. Safety: keep the elbows straight and the body in one line; "
        "do it on the knees or against a wall if the wrists or shoulders feel strained.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {
            "Upper Back": "PRIMARY",
            "Chest": "SECONDARY",
            "Shoulders": "SECONDARY",
            "Core": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Wall Push-Up",
        "description": "Stand an arm's length from a wall, place the hands on it at chest "
        "height, bend the elbows to bring the chest toward the wall, then press back to "
        "straight arms. Suggested dose: 8 to 12 slow reps with light effort. Safety: keep "
        "the body in one straight line and the heels down; step the feet closer to the wall "
        "to make it easier if the wrists or shoulders hurt.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {
            "Chest": "PRIMARY",
            "Triceps": "PRIMARY",
            "Front Deltoid": "SECONDARY",
            "Core": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Light Band Biceps Curl",
        "description": "Stand on the middle of a light band holding an end in each hand with "
        "the palms forward. Curl the hands toward the shoulders, then lower slowly, keeping "
        "the elbows at the sides. Use the lightest band and stop well short of effort. "
        "Suggested dose: 10 to 12 easy reps. Safety: check the band for nicks or tears "
        "before use, keep the face clear of its path and keep the back straight.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {"Biceps": "PRIMARY", "Forearms": "SECONDARY"},
        "equipment": ["Resistance Band"],
    },
    {
        "name": "Light Band Triceps Pushdown",
        "description": "Loop a light band over a secure anchor above head height (such as "
        "the top of a door, with a door anchor) and hold an end in each hand with the elbows "
        "at the sides. Push the hands down until the elbows are straight, then let them rise "
        "slowly. Use the lightest band and stop well short of effort. Suggested dose: 10 to "
        "12 easy reps. Safety: use a purpose-made door anchor or another secure fixing, "
        "check the band for nicks or tears, and keep the face clear of its path.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {"Triceps": "PRIMARY", "Forearms": "SECONDARY"},
        "equipment": ["Resistance Band"],
    },
    {
        "name": "Walking Knee Hug",
        "description": "Walk forward, and on each step lift the knee and hug it gently to "
        "the chest for a moment before stepping through; alternate legs. Suggested dose: 6 "
        "to 8 steps on each leg. Safety: stay tall, hold a wall for balance if needed, and "
        "do not pull hard; stop if you feel pain in the hip or knee.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {"Glutes": "PRIMARY", "Hamstrings": "SECONDARY", "Core": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Squat to Stand",
        "description": "Stand with the feet shoulder-width apart, hinge forward and take hold "
        "of your toes (or shins). Keeping hold, drop the hips into a deep squat with the "
        "chest lifted, then straighten the legs by lifting the hips. Suggested dose: 6 to 8 "
        "slow reps. Safety: keep the movement slow and within a comfortable range, bend the "
        "knees as much as needed, and skip the squat if the knees or hips hurt.",
        "difficulty": "BEGINNER",
        "movement_pattern": "MOBILITY",
        "uses": WARM_UP,
        "muscles": {
            "Hamstrings": "PRIMARY",
            "Glutes": "PRIMARY",
            "Quadriceps": "SECONDARY",
            "Calves": "SECONDARY",
        },
        "equipment": [],
    },
    # --- cool-down ---
    {
        "name": "Butterfly Stretch",
        "description": "Sit tall with the soles of the feet together and the knees dropped out "
        "to the sides, holding the feet or ankles. Let the knees relax toward the floor and "
        "lean forward slightly from the hips with a long back. Suggested dose: hold 20 to 30 "
        "seconds, once or twice. Safety: do not press the knees down with the hands; ease "
        "off if you feel pain in the knees, hips or groin.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "uses": COOL_DOWN,
        "muscles": {"Adductors": "PRIMARY", "Lower Back": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Wall Biceps Stretch",
        "description": "Stand beside a wall and place the palm flat on it at shoulder height, "
        "with the fingers pointing back and the arm straight. Slowly turn the body away from "
        "the wall until you feel a stretch at the front of the arm. Suggested dose: hold 20 "
        "to 30 seconds on each arm, once or twice. Safety: keep a slight softness in the "
        "elbow and turn only until you feel a mild stretch; stop if you feel pain or tingling "
        "in the shoulder or arm.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "uses": COOL_DOWN,
        "muscles": {"Biceps": "PRIMARY", "Chest": "SECONDARY", "Shoulders": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Wrist Extensor Stretch",
        "description": "Extend one arm in front of you with the palm facing down. With the "
        "other hand, gently draw the back of the hand and fingers toward you until you feel a "
        "stretch along the top of the forearm. Suggested dose: hold 20 to 30 seconds on each "
        "arm, once or twice. Safety: pull gently, keep the elbow nearly straight but not "
        "locked, and stop if you feel pain, numbness or tingling in the wrist or hand.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "uses": COOL_DOWN,
        "muscles": {"Forearms": "PRIMARY"},
        "equipment": [],
    },
    {
        "name": "Lying Overhead Reach",
        "description": "Lie on your back with the legs straight and reach both arms overhead "
        "along the floor, lengthening from the fingertips to the toes. Breathe slowly and let "
        "the ribs soften toward the floor. Suggested dose: hold 20 to 30 seconds, once or "
        "twice. Safety: keep the lower back comfortable, bending the knees with the feet flat "
        "if it arches or aches; skip it if the shoulders feel tight or painful overhead.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "uses": COOL_DOWN,
        "muscles": {"Core": "PRIMARY", "Lats": "PRIMARY", "Obliques": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Standing Cross-Leg Side Bend",
        "description": "Stand tall and cross one foot behind the other. Reach the arm on the "
        "side of the back leg overhead and lean away from it until you feel a stretch along "
        "the outer hip and side. Suggested dose: hold 20 to 30 seconds on each side, once or "
        "twice. Safety: lean sideways rather than forward, keep both feet planted, and hold a "
        "wall for balance if needed; ease off if the hip or back hurts.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "uses": COOL_DOWN,
        "muscles": {"Abductors": "PRIMARY", "Obliques": "SECONDARY", "Lats": "SECONDARY"},
        "equipment": [],
    },
    {
        "name": "Seated Spinal Twist",
        "description": "Sit tall with the legs crossed (or straight in front of you if that is "
        "more comfortable). Place one hand on the opposite knee and the other hand on the "
        "floor behind you, then gently turn the chest toward the hand on the floor, keeping "
        "the spine long. Suggested dose: hold 20 to 30 seconds on each side, once or twice. "
        "Safety: turn from the middle of the back without forcing it, keep both hips on the "
        "floor, and ease off if you feel pain in the back or hips.",
        "difficulty": "BEGINNER",
        "movement_pattern": "STRETCH",
        "uses": COOL_DOWN,
        "muscles": {
            "Obliques": "PRIMARY",
            "Lower Back": "SECONDARY",
            "Upper Back": "SECONDARY",
            "Glutes": "SECONDARY",
        },
        "equipment": [],
    },
    {
        "name": "Easy Walk",
        "description": "Walk at a relaxed pace, easier than a brisk walk, letting your "
        "breathing and heart rate settle and slowing down a little more toward the end; "
        "outdoors, on a treadmill or around the room. Suggested dose: 3 to 5 minutes. "
        "Safety: stop and sit down if you feel dizzy, faint or unusually breathless.",
        "difficulty": "BEGINNER",
        "movement_pattern": "CARDIO",
        "uses": COOL_DOWN,
        "muscles": {
            "Calves": "PRIMARY",
            "Quadriceps": "SECONDARY",
            "Glutes": "SECONDARY",
            "Hamstrings": "SECONDARY",
        },
        "equipment": [],
    },
]

# The description 14d543e636a8 wrote for each existing Formiq warm-up and
# cool-down activity (the one a row must still have to be updated), and what is
# added after it: the new text is the old, a space, then the addition.
OLD_DESCRIPTIONS = {
    "Arm Circles": "Hold the arms out to the sides and draw small, then larger, circles "
    "forward and backward.",
    "Band Pull-Apart": "Hold a light band at shoulder height with straight arms and pull it "
    "apart until it touches the chest.",
    "Cat-Cow": "On hands and knees, slowly round the back up, then let it sag as the "
    "chest lifts; move with the breath.",
    "Leg Swings": "Holding a support, swing one leg forward and back in a relaxed, "
    "controlled arc; then the other leg.",
    "Hip Circles": "Hands on the hips, draw slow, wide circles with the hips in each "
    "direction.",
    "Inchworm": "From standing, walk the hands out to a high plank and back, keeping "
    "the legs as straight as is comfortable.",
    "World's Greatest Stretch": "Step into a long lunge, place both hands inside the front "
    "foot, then rotate the chest and reach one arm up; alternate sides.",
    "Thoracic Open Book": "Lying on your side with the knees bent, open the top arm across the "
    "body to rotate the upper back, then return.",
    "Brisk Walk": "Walk at a pace that raises your breathing but still lets you talk, "
    "outdoors or on a treadmill.",
    "Marching in Place": "March on the spot at an easy pace, lifting the knees and swinging the "
    "arms.",
    "Jumping Jacks": "Jump the feet out while raising the arms overhead, then jump back; "
    "keep it light.",
    "Easy Stationary Cycling": "Pedal at a light resistance and an easy, steady pace.",
    "Easy Rowing": "Row at a light, steady pace: push with the legs, then pull the "
    "handle to the lower ribs.",
    "Standing Quad Stretch": "Standing on one leg, hold the other foot behind you and draw the "
    "heel toward the glutes; hold, then switch.",
    "Standing Hamstring Stretch": "Place one heel forward with the leg straight and hinge at the "
    "hips until you feel the back of the thigh; hold, then switch.",
    "Figure-Four Glute Stretch": "Lying on your back, cross one ankle over the opposite knee and "
    "draw both legs toward the chest; hold, then switch.",
    "Kneeling Hip Flexor Stretch": "Kneel on one knee, tuck the pelvis under and shift forward "
    "until you feel the front of the hip; hold, then switch.",
    "Standing Calf Stretch": "With the hands on a wall, step one foot back and press the heel "
    "down; hold, then switch.",
    "Doorway Chest Stretch": "Place a forearm on a door frame at shoulder height and turn gently "
    "away until you feel the chest; hold, then switch.",
    "Cross-Body Shoulder Stretch": "Bring one straight arm across the chest and hold it there "
    "with the other arm; hold, then switch.",
    "Overhead Triceps Stretch": "Reach one hand down the upper back and gently press that elbow "
    "with the other hand; hold, then switch.",
    "Child's Pose": "Kneel, sit the hips back toward the heels and reach the arms forward "
    "on the floor; breathe slowly.",
    "Supine Spinal Twist": "Lying on your back, let both bent knees fall to one side while the "
    "shoulders stay down; hold, then switch.",
    # also main exercises: the dose is for the warm-up
    "Bodyweight Squat": "Stand with feet shoulder-width apart, sit the hips back and down, "
    "and stand back up.",
    "Glute Bridge": "Lie on your back with the knees bent and lift the hips until the "
    "body is straight from knees to shoulders.",
    "Bird Dog": "On hands and knees, reach one arm forward and the opposite leg back, "
    "hold, and return; alternate sides.",
}

ADDITIONS = {
    "Arm Circles": "Suggested dose: 8 to 10 circles in each direction. Safety: keep the "
    "shoulders relaxed and the circles within a comfortable range; stop if you feel "
    "pinching in the shoulder.",
    "Band Pull-Apart": "Suggested dose: 10 to 15 slow reps with a light band. Safety: check "
    "the band for nicks or tears before use, and keep the ribs down and the shoulders away "
    "from the ears.",
    "Cat-Cow": "Suggested dose: 6 to 10 slow cycles. Safety: move within a comfortable range; "
    "skip the sagging half if it hurts the lower back.",
    "Leg Swings": "Suggested dose: 8 to 10 swings on each leg. Safety: keep the swings small "
    "at first and the supporting knee soft; stop if you feel pain at the hip or back.",
    "Hip Circles": "Suggested dose: 8 to 10 circles in each direction. Safety: keep the knees "
    "soft and the circles slow; stop if you feel dizzy or feel pain in the lower back.",
    "Inchworm": "Suggested dose: 5 to 8 reps. Safety: bend the knees as much as needed, keep "
    "the hips from sagging in the plank, and stop if the wrists or lower back hurt.",
    "World's Greatest Stretch": "Suggested dose: 4 to 6 reps on each side, moving smoothly "
    "rather than holding. Safety: keep the front knee over the toes; use a shorter lunge "
    "or put a hand on a raised surface if the hip or hamstring feels tight.",
    "Thoracic Open Book": "Suggested dose: 6 to 8 slow reps on each side. Safety: rotate only "
    "as far as is comfortable and keep the knees together; stop if you feel pain in the "
    "shoulder or neck.",
    "Brisk Walk": "Suggested dose: 3 to 5 minutes as a warm-up; as a cool-down, slow the pace "
    "toward the end. Safety: stop and sit down if you feel dizzy, faint or unusually "
    "breathless.",
    "Marching in Place": "Suggested dose: 1 to 3 minutes. Safety: keep the lifts low and hold "
    "a wall or chair if your balance is unsteady.",
    "Jumping Jacks": "Suggested dose: 30 to 60 seconds at an easy pace. Safety: land softly; "
    "use Step Jacks instead if jumping bothers the knees, ankles or back.",
    "Easy Stationary Cycling": "Suggested dose: 3 to 5 minutes. Safety: set the seat so the "
    "knee is slightly bent at the bottom of each pedal stroke; stop if you feel dizzy or "
    "unusually breathless.",
    "Easy Rowing": "Suggested dose: 3 to 5 minutes at a pace where you can talk. Safety: keep "
    "the back straight and the effort light; stop if the lower back or knees hurt.",
    "Standing Quad Stretch": "Suggested dose: hold 20 to 30 seconds on each leg, once or "
    "twice. Safety: keep the knees close together, stand tall and hold a wall for balance; "
    "ease off if the knee hurts.",
    "Standing Hamstring Stretch": "Suggested dose: hold 20 to 30 seconds on each leg, once or "
    "twice. Safety: hinge from the hips with a long back and a soft knee; stop if you feel "
    "pain behind the knee or tingling down the leg.",
    "Figure-Four Glute Stretch": "Suggested dose: hold 20 to 30 seconds on each side, once or "
    "twice. Safety: ease the legs in gently and keep the neck and shoulders relaxed; stop if "
    "you feel pain in the knee.",
    "Kneeling Hip Flexor Stretch": "Suggested dose: hold 20 to 30 seconds on each side, once "
    "or twice. Safety: pad the kneeling knee, keep the ribs down rather than arching the "
    "back, and shift forward only a little.",
    "Standing Calf Stretch": "Suggested dose: hold 20 to 30 seconds on each leg, once or "
    "twice. Safety: keep the back heel on the floor and the movement gentle; ease off if you "
    "feel pain in the Achilles tendon.",
    "Doorway Chest Stretch": "Suggested dose: hold 20 to 30 seconds on each side, once or "
    "twice. Safety: keep the shoulder relaxed, turn only until you feel a mild stretch, and "
    "stop if you feel pain or tingling in the shoulder or arm.",
    "Cross-Body Shoulder Stretch": "Suggested dose: hold 20 to 30 seconds on each arm, once or "
    "twice. Safety: draw the arm in by the upper arm, not the elbow joint, and stop if the "
    "shoulder pinches.",
    "Overhead Triceps Stretch": "Suggested dose: hold 20 to 30 seconds on each arm, once or "
    "twice. Safety: press gently on the elbow and keep the neck relaxed; stop if you feel "
    "pain in the shoulder or elbow.",
    "Child's Pose": "Suggested dose: hold 20 to 30 seconds, once or twice. Safety: widen the "
    "knees, or place a cushion under the hips or between the thighs and calves, if the knees "
    "or hips are uncomfortable.",
    "Supine Spinal Twist": "Suggested dose: hold 20 to 30 seconds on each side, once or "
    "twice. Safety: let the knees fall only as far as is comfortable and keep both shoulders "
    "down; stop if you feel pain in the back or hips.",
    "Bodyweight Squat": "Suggested dose as a warm-up: 8 to 10 slow reps. Safety: keep the "
    "heels down and the knees in line with the toes; reduce the depth if the knees or hips "
    "hurt.",
    "Glute Bridge": "Suggested dose as a warm-up: 8 to 10 slow reps. Safety: keep the ribs "
    "down rather than arching the lower back; stop if you feel pain in the back.",
    "Bird Dog": "Suggested dose as a warm-up: 6 to 8 slow reps on each side. Safety: keep the "
    "hips level and the back flat; reduce the reach if the lower back sags or aches.",
}


def id_of(table, name):
    """The id of the row with this name, or NULL (a NOT NULL violation) if there is none."""
    return sa.select(table.c.id).where(table.c.name == name).scalar_subquery()


def uses_array(values):
    return sa.cast(postgresql.array(values), postgresql.ARRAY(sa.String(20)))


def upgrade() -> None:
    """Insert the new activities, then add the dose and safety note to the
    existing ones."""
    names = [activity["name"] for activity in NEW_ACTIVITIES]
    taken = op.get_bind().scalars(
        sa.select(exercises.c.name).where(exercises.c.name.in_(names))
    ).all()
    if taken:
        raise RuntimeError(
            f"the catalog already has exercises named {sorted(taken)}: rename or remove them "
            "before this migration, which would otherwise attach its muscles and equipment "
            "to them"
        )
    op.execute(
        insert(exercises).values(
            [
                {
                    **{
                        key: activity[key]
                        for key in ("name", "description", "difficulty", "movement_pattern")
                    },
                    "uses": uses_array(activity["uses"]),
                }
                for activity in NEW_ACTIVITIES
            ]
        )
    )
    op.execute(
        insert(exercise_muscles).values(
            [
                {
                    "exercise_id": id_of(exercises, activity["name"]),
                    "muscle_group_id": id_of(muscle_groups, muscle),
                    "role": role,
                }
                for activity in NEW_ACTIVITIES
                for muscle, role in activity["muscles"].items()
            ]
        )
    )
    links = [
        {
            "exercise_id": id_of(exercises, activity["name"]),
            "equipment_id": id_of(equipment, item),
        }
        for activity in NEW_ACTIVITIES
        for item in activity["equipment"]
    ]
    if links:
        op.execute(insert(exercise_equipment).values(links))
    for name, old in OLD_DESCRIPTIONS.items():
        op.execute(
            exercises.update()
            .where(
                exercises.c.name == name,
                exercises.c.source == "FORMIQ",
                exercises.c.description == old,
            )
            .values(description=f"{old} {ADDITIONS[name]}")
        )


def downgrade() -> None:
    """Take the dose and safety note off the existing activities, and delete the
    new ones (and with them their muscle and equipment links). An activity a
    workout plan or session uses cannot be deleted, so the downgrade then fails
    instead of changing it."""
    for name, old in OLD_DESCRIPTIONS.items():
        op.execute(
            exercises.update()
            .where(
                exercises.c.name == name,
                exercises.c.source == "FORMIQ",
                exercises.c.description == f"{old} {ADDITIONS[name]}",
            )
            .values(description=old)
        )
    op.execute(
        exercises.delete().where(
            exercises.c.name.in_([activity["name"] for activity in NEW_ACTIVITIES]),
            exercises.c.source == "FORMIQ",
        )
    )
