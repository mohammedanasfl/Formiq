# Formiq Frontend

The Formiq mobile app: React Native with Expo (SDK 58) and TypeScript. The backend stays the source
of truth for workouts, proposals and approvals; the app only presents them.

Status: Phase 10.3, onboarding, then the UI-first design phase (started 2026-10-20). The app signs a
user in or creates their account, collects their profile, and saves it. After that it shows the signed-in
app: a bottom tab bar with five tabs (Home, Discover, AI Coach, Progress, Profile). Home, Discover, AI Coach and
Profile are designed so far (Home, Profile on **mock data**, AI Coach on the **backend's coach**; see "Home
dashboard", "Bottom navigation" and "AI Coach" below). Progress, and the screens Discover leads to, are labelled placeholders until
each is designed.

## Requirements

- Node 22 (`.nvmrc`). With nvm, run `nvm use` in this directory. Other Node versions are not
  supported, and the global default does not need to change.
- Android: the Android SDK and an emulator (or a device). Set `ANDROID_HOME` to the SDK path
  (macOS default: `~/Library/Android/sdk`).
- The first run on a device or emulator installs Expo Go (about 226 MB).

## Setup and run

```bash
cd frontend
nvm use                 # Node 22
npm install
npm run android         # starts Metro and opens the app in Expo Go on the running emulator
```

If an emulator will not restore its saved snapshot (`Error -5 while loading VM state`), cold-boot it
with `emulator -avd <name> -no-snapshot`.

## Pointing the app at a backend

The app talks to the FastAPI backend (`backend/README.md`, port 8000). Set `EXPO_PUBLIC_API_URL` when
starting Metro to use another address; it is read when the app is bundled, so restart Metro to change it.

```bash
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000 npm run android
```

With no value, an Android emulator uses `http://10.0.2.2:8000` (the emulator's name for the computer)
and everything else `http://localhost:8000`. A phone needs the computer's network address. Check what
answers on the port first: another dev server may be using 8000.

## Scripts

| Script              | What it does                                |
| ------------------- | ------------------------------------------- |
| `npm start`         | Start Metro (the Expo dev server)           |
| `npm run android`   | Start Metro and open on an Android emulator |
| `npm run ios`       | Start Metro and open on an iOS simulator    |
| `npm run typecheck` | TypeScript check (`tsc --noEmit`)           |
| `npm test`          | Jest with `jest-expo` and React Native Testing Library |

Add packages with `npx expo install <package>`, which picks the version that matches the SDK. Check
the setup with `npx expo-doctor`.

## Structure

```
frontend/
├── index.ts              # entry point: registers the root component
├── app.json              # Expo configuration
├── jest.setup.ts         # Jest setup (mocks the native safe-area module)
├── assets/               # app icons (placeholders, see below) and images/ (welcome and sign-up photos)
├── src/
│   ├── App.tsx           # root: safe-area, theme and session providers around the onboarding
│   ├── api/              # fetch client and the backend calls the app uses, with their types
│   ├── coach/            # the AI Coach tab: the conversation, the workout card and its rules, against a CoachGateway
│   ├── components/       # the design system (AppScreen, AppButton, AppInput, OptionCard, TabScreen, ...)
│   ├── discover/         # the Discover tab (four photo cards that lead to placeholders)
│   ├── home/             # the Home dashboard (presentational: it is given its data)
│   ├── mock/             # MOCK DATA and the made-up coach gateway (mock mode, previews, tests): nothing in it comes from the backend
│   ├── onboarding/       # the flow: steps, draft, validation, units, payload, and the screens
│   ├── profile/          # the Profile tab (name, saved equipment and its editor, theme choice, log out)
│   ├── session/          # the signed-in user, in memory
│   ├── shell/            # the signed-in app: tab state, screens over the tabs, the bottom tab bar, placeholders
│   ├── workouts/         # the workout card, the workout screen, the exercise screen, the categories, the pictures and the GIFs
│   └── theme/            # tokens (colors, spacing, radii, typography, layout) and ThemeProvider
├── test-utils/           # renderWithTheme, a scripted fetch, and helpers that walk the flow
└── __tests__/            # Jest tests (*-test.ts and *-test.tsx)
```

`ios/` and `android/` are not committed: Expo generates them when a development build needs them.
There is no navigation library yet: the flow is linear, so `src/onboarding/OnboardingFlow.tsx` is a small
state machine (it also handles Android's back button). Its last step, `home`, renders `src/shell/AppShell.tsx`,
which holds the current tab as its own state, and a short stack of screens that open over the tabs (a workout,
then one of its exercises; Workouts, Nutrition & recovery, Exercises or Mobility: `src/shell/routes.ts`). While one is open the tabs stay mounted but hidden, so
Home keeps its scroll position. Android's back button closes the screen on top, then goes to Home from another
tab, and leaves the app from Home. A navigator is chosen when the app needs more than this.

## Design system

Components read colors from the theme and everything else from static tokens; screens never use
hex values or loose numbers.

```tsx
import { AppButton, AppCard, AppInput, AppScreen, AppText } from '../components';
import { spacing, useTheme } from '../theme';

const { scheme, colors, setScheme } = useTheme(); // 'dark' | 'light'
setScheme('light');                                // switch programmatically
```

- Colors are semantic (`background`, `surface`, `textPrimary`, `primary`, `error`, ...) and have a
  dark and a light value each, in `src/theme/colors.ts`. Dark is the default. Nothing is persisted
  and there is no settings screen yet.
- `spacing` (4-point scale), `radii`, `typography` (variants: display, title, heading, body, button,
  label, caption) and `layout` (48 dp touch target, screen padding, border widths, font scale cap)
  are the same in both themes.
- Add a color to both themes at once: the `ColorTokens` type fails the type-check if either is
  missing it. `__tests__/theme-test.tsx` checks contrast (WCAG AA) for the pairs the components use.
- `AppScreen` keeps clear of the system bars and sets the status bar icons for the theme. With
  `scrollable` it scrolls, keeps taps working with the keyboard open, makes room for the keyboard, and
  holds a `footer` that stays in reach.
- `UnderlineTabs` (a tab list of text tabs, the selected one bold with an emerald line under it; a long label at a
  large font size shrinks, never truncates) and `NumberStepper` (a `-  12 reps  +` control, adjustable for a screen
  reader; the screen owns the number and its limits) are the exercise screen's controls, and reusable.
- Selection is announced as `checked` on `radio` / `checkbox` controls, errors use the `alert` role
  with a polite live region, and every button has an explicit `accessibilityLabel`. Do not give a
  button `accessibilityState.busy`: on Android it replaced the button's name with "busy".

## Onboarding

Welcome, then sign up or log in, then six profile steps with progress ("Step n of 6"), then a saved
screen and a temporary home. What it sends, checked against the backend source:

| Step | Backend call |
| ---- | ------------ |
| Sign up | `POST /auth/register` with `email` and `password` only |
| Log in | `POST /auth/login`, then `GET /users/{id}/profile` (200: setup is done, go to home; 404: continue) |
| Equipment list | `GET /equipment` (public) |
| Save profile | `POST /users/{id}/profile` with the token; 409 means a profile already exists |
| Change equipment (Profile tab, after setup) | `PATCH /users/{id}/profile` with `equipment_ids` and `no_equipment` only; the answer is the profile, read for its equipment |

The user id comes from the token's `sub` claim (there is no "who am I" route). The token is kept in
memory only, so closing the app signs the user out; storing it needs secure storage, a later phase.

Where the app deliberately differs from the mockup, because of the backend:

- **No Full Name or Phone at sign up, no Google or Apple:** the register route takes an email and a
  password and nothing else. The name goes into the profile.
- **Three goals, not four:** `lose_weight`, `build_muscle` and `general_fitness` are the values the
  backend recognises (`backend/app/guidance/nutrition.py`); any other text loses goal-specific guidance.
- **An extra "Your training" step** (experience, training days, daily activity, sleep): the backend
  requires them, and a profile is never filled with invented defaults. The first name is asked for on
  the details step.
- **Equipment is saved with the profile** (`equipment_ids` and `no_equipment` in the request, ids from
  `GET /equipment`; the backend keeps them in `user_profile_equipment` and `user_profiles.no_equipment`).
  "No equipment" is sent as `no_equipment: true` and no ids; choosing nothing sends neither (the backend
  keeps that the person did not say). The Profile tab reads the saved equipment back
  (`GET /users/{id}/profile`: `useSavedEquipment`) and shows it, and can change it (see "Changing the saved
  equipment" below); the coach takes what the person says in a conversation over it for that workout. The
  options are the catalog's own, which differ from the mockup's.
- **"Save profile", not "Create My Plan":** saving a profile does not create a plan. The proposal and
  approval flow is untouched, and the saved screen says plans are not in the app yet.
- **Home is a designed dashboard on mock data** (see "Home dashboard" below). The temporary home screen
  is no longer used: `onboarding/screens/HomePlaceholderScreen.tsx` stays in the repo, unused, until the
  user says to remove it.
- **The welcome screen is a photo, and dark in both themes.** `assets/images/welcome-hero.png` (1024 x
  1536) fills the screen (`resizeMode="cover"`, centered), with the "Form" + green "iq" wordmark and the
  tagline drawn as text over it. It is wrapped in `FixedTheme scheme="dark"`, so it keeps its look when
  the app is in the light theme while every other screen follows the theme. The image needs an explicit
  `width` and `height` of `100%`: on Android it otherwise keeps its own size and shows top-left,
  enlarged. `AppButton` has an `overlay` variant for buttons on a photo. "Get Started" has an arrow icon
  that screen readers skip, so the button is still named "Get Started". `WelcomeHero.tsx` (the old
  icon picture) is no longer used.
- **Sign up is a dark-only screen on a photo too.** `assets/images/signup-background.png` (1024 x 1536)
  sits behind a 30% near-black layer (`PhotoBackdrop`, which also holds the Android sizing fix above).
  It has a small "Form" + green "iq" wordmark, a back arrow (named "Back"), the heading "Create Account",
  an email field (email keyboard, no capitals or autocorrect), a password field with show / hide, a green
  56 dp "Create Account" button and "Already have an account? Log in" under it. The button and the link
  sit in the footer, above the keyboard. The request is the backend's own (`POST /auth/register`, email
  and password only, 201 with a token): the app moves on to the profile steps only after that answer, the
  button turns to "Creating account…", and the button, Back and "Log in" are off meanwhile. The screen
  is not built on `StepLayout` (see the profile steps below).
- **Log in looks the same as sign up, because both are built on `AccountFrame`** (the photo and its
  layer, the wordmark and back arrow, the heading, the footer with the green button and the link to the
  other screen; dark in both themes). Log in has the heading "Log in", an email and a password field
  (no rules shown: the backend decides), a green "Log in" button (it reads "Logging in…" while it
  works) and "New to Formiq? Create an account". What it sends is unchanged: `POST /auth/login`, then
  `GET /users/{id}/profile` (200: home; 404: the profile steps), and it moves on only after both
  answers. Both account screens turn off the button, Back and the link while a request is under way, and
  send one request however many times "done" and the button are pressed. A notice, such as an expired
  session, shows above the fields.
- **The goal step is dark, on the gym photo, in both themes.** It uses `StepFrame`: the photo of sign up
  and log in under a lighter dark layer, a back arrow and a compact progress bar on top, the heading
  "Your Fitness Goal", the cards that scroll, and one wide 56 dp "Continue →" button in the footer
  ("Done" when the goal is edited from the review). It is wrapped in `FixedTheme scheme="dark"`. The back
  arrow is drawn only when there is a step to go back to (editing from the review): the first step has
  nothing before it, so no arrow leads nowhere; the bar is as tall as the arrow either way. The three
  goals are `OptionCard`s, one wide row each with an icon, title, description and a radio: selected is an
  emerald outline, icon and filled radio, unselected a grey outline and a muted icon. The icons are
  `signal-cellular-3` (three bars), `fire` and `run-fast` from the bundled Material Community set; the
  values sent are unchanged (`build_muscle`, `lose_weight`, `general_fitness`). "Choose a goal to
  continue." sits in the footer, above the button, so it is in view on a small screen. `ProgressSteps`
  has a `compact` mode for the top bar (the label "Step n of 6" is still read out, not printed).
  `BackButton` and `photoScreen.ts` are shared with the account screens.
- **Personal details ("Tell us about yourself") has the goal step's dark design** (`StepFrame`): first
  name, last name (optional), age, gender, height and weight, the fields it always had. Experience,
  training days, activity and sleep stay on the next step, "Your training" (the user's choice,
  2026-10-20: the six steps are unchanged). Height and weight each have their name and a `UnitToggle`
  (cm or ft / in, kg or lb) on one row and the field under it, with the unit shown at the end of the
  field ("years" for the age too); changing a unit still converts what was typed. `AppInput` has
  `hideLabel` for these fields: the row shows the name, and the field's accessible name keeps the unit
  ("Height (cm)"). "next" on the keyboard moves through the text fields, and the last says "done". On
  Next, each field shows its own message and the footer says "Check the answers marked in red.", since
  the first one may be above the part in view.
- **Every profile step has that design now** (`StepFrame`: the photo, the top bar, a heading, content
  that scrolls, one wide button in the footer; dark in both themes). The steps share the same pieces:
  - `OptionCard` is the one choice card. Row: a wide card with an optional icon, a title, an optional
    description and a radio or a checkbox at its end (a goal, an experience level, a place, "No
    equipment"). Chip: a short card that wraps, for a long list (equipment): its icon is replaced by a
    check when chosen. Chosen is an emerald outline (thicker border, the padding gives back what the
    border takes), a green tint and the indicator; it is announced as checked.
  - `ChoiceChips` (gender, training days, daily activity) are chosen in the same emerald outline and
    tint. `columns` lays them out as an even grid (days in rows of 4, activity in rows of 2) so no chip
    is left alone on a row.
  - A missing answer is red text under its question, and the footer says "Check the answers marked in
    red." (`CheckAnswers`), since the first one may be above the part in view. A group of choices has
    only the text; a text field is also outlined in red.
  - **Training** ("Your training"): experience as three plain rows (no icons), days as a grid, activity,
    and sleep as a number field with "hours" at its end.
  - **Location**: gym and home, two rows with an icon each and what each means.
  - **Equipment**: "No equipment" and a chip per catalog item
    (`GET /equipment`; every icon is from the one bundled set). The step needs no answer, and can be left
    empty when the list cannot be loaded (the error has "Try again" and says so).
  - **Review**: one list, not a card per section: a heading with its Edit link, then the answers (a
    section of one answer shows just the answer). The note says nothing is saved yet. "Save profile"
    becomes "Saving…" (the button and the back arrow are off meanwhile), and after a failure the reason
    is in the footer with "Try again": a save the backend refuses (an equipment id it does not know, say)
    is never shown as saved. The equipment is listed with the other answers and goes with them.
  - **Saved** (`DoneScreen`, after the backend answered): "Profile saved" with one check mark and
    "Workout plans aren't in the app yet." If the account already had a
    profile (409) it says nothing was saved and shows no check mark. There is no celebration: no stars,
    dots or halo. It is followed by the Home dashboard, which is not part of this design.
  - `StepLayout` is no longer used by any screen (kept, like `WelcomeHero`, until the user says to
    remove it).

Profile values: gender `male` / `female` / `other`; experience `beginner` / `intermediate` /
`advanced`; daily activity `sedentary` / `light` / `moderate` / `very_active`; location `gym` / `home`.
They are free text in the backend, which reads only `beginner`; they follow the values its tests use.
The numeric limits (age 13 to 100, height 100 to 250 cm, weight 30 to 300 kg, sleep 3 to 14 hours) are
the app's own sanity checks, not backend rules. Height and weight can be typed in ft / in and lb; they
are converted, and the review shows what will be saved.

## Bottom navigation (UI-first design phase)

Five tabs, in this order, left to right, each an icon above its label in an equal column: **Home** (house),
**Discover** (compass), **AI Coach** (chat), **Progress** (bar chart), **Profile** (person). The tab list is
`TABS` in `src/shell/tabs.ts`; the bar is `BottomTabBar` and is unchanged in style: a fixed bar on the
theme's surface with a thin line above it, the current tab emerald with a filled icon (the others muted with
an outline, where the icon set has both), at least a touch target tall, its names growing only a little
with the font setting, the gesture bar's inset and the notch's sides part of the bar. No badge, glow,
gradient or animation.

Workouts and Nutrition are no longer tabs, and their screens are kept: they open over the tabs (no bar under
them, a Back arrow, Android's back button closes them) from Home's shortcuts and cards and from Discover.

- **Discover** (`src/discover/DiscoverScreen.tsx`): four photo cards in the style of Home's workout cards,
  Workouts, Exercises, Mobility and Recovery (which opens Nutrition & recovery). None has content yet: each
  opens a placeholder, and a line at the foot of the screen says so. Nothing on it is a user's data.
- **AI Coach** (`src/coach/CoachScreen.tsx`): a conversation with the backend's coach (`POST /coach/message`), see
  "AI Coach" below. It is also the screen "Edit with AI" opens with a workout's context.
- **Progress**: still a placeholder.
- **Profile** (`src/profile/ProfileScreen.tsx`): the user's first name (**mock**, Home's), "Edit profile"
  (**mock-only**: the notice "Editing your profile isn't built yet." Only the equipment can be changed, below),
  the **Equipment** saved with the profile, read from the backend, with an **Edit** link that opens its editor,
  a **Theme** choice, Dark or Light, that really switches the app through `ThemeProvider` (it is not remembered
  after the app is closed yet, and says so), and **Log out**, which really signs out.

### Changing the saved equipment

The one part of the profile the app can change after setup. **Edit** at the Equipment heading opens
`src/profile/EquipmentEditScreen.tsx` over the tabs (a route of the shell, so Android's back button closes it).
It is offered only over an answer the backend gave for a profile: not while the equipment is being read, not
after a failed read, and not for a user with no profile (a PATCH would only 404).

- **The choice** is the setup step's own chips, shared (`src/onboarding/EquipmentOptions.tsx`, with
  `useEquipmentCatalog`), in the Profile tab's theme: "No equipment" (bodyweight only) and one chip per catalog
  item, started from what is saved. "No equipment" empties the chips and choosing a chip clears it. Choosing
  nothing is allowed and is saved as "never said", as in setup.
- **Save** sends `PATCH /users/{id}/profile` with `equipment_ids` and `no_equipment` and nothing else
  (`saveEquipment`; ids once each, none with "no equipment": `equipmentChoice`). The request replaces the list,
  so asking again is safe. While it is out the button reads "Saving…" and Save, Cancel and Back are inactive.
- **Only the backend's answer is shown.** `saveEquipment` resolves with the equipment read from the PATCH's own
  response, `useSaveEquipment` hands that to the Profile tab (`useSavedEquipment.replace`), and the editor closes
  only then. What was chosen is never displayed as saved. A read that was already on its way when the answer came
  is ignored, as it may predate the change; the Profile tab reads again as it regains focus, as always.
- **A failed save** (no connection, a timeout, a server error, a refused piece, a 404, an answer the app cannot
  read) keeps the editor open with the choice as it was, says why (`describeError(error, 'saveEquipment')`), and
  Save tries again; the Profile tab keeps showing what it showed before. After a timeout or an unreadable answer
  the backend may have saved it all the same: Cancel then lets the Profile tab read the backend again, and it
  shows what the backend has. A 401 says "Your session has expired. Log in again.", disables Save and leaves
  Cancel and Log out working, as the other screens do.
- **Unchanged is not saved:** a choice equal to what is saved (order does not matter) closes the editor and asks
  nothing of the backend. A saved piece the catalog no longer lists (`GET /equipment` lists active items only,
  while a profile can still hold a retired one) is not shown and is left out of what is sent, since the backend
  refuses a retired id and the person could never fix it; it counts neither as a change nor as a reason to save.
- **Back, Cancel or Android's back** leave without saving and without asking. A save still out when the screen is
  left still ends in the Profile tab showing the backend's answer.

## Home dashboard (UI-first design phase)

The remaining screens are designed before any new backend integration. Home is the first; Progress, AI Coach and
the screens Discover leads to follow, one at a time, in the same visual system.

**Mock data.** `src/mock/homeMock.ts` (`MOCK_HOME`) holds made-up values: the name "Anas", today's workout
"Core & Abs Focus", 1,850 kcal at 60%, 4 of 7 sessions, three recent workouts.
None of it comes from the backend and no screen may present it as real. `HomeScreen` is presentational: it
is given a `HomeData` through its `data` prop (`AppShell` passes the mock), so connecting it later changes
where the data comes from and not the screen. The date is the device's own, not mock. The pictures on the
workout cards and the recent-activity thumbnails come from the workout picture lookup (see "Workout
cards").

**What is on it**, top to bottom: the header (below); "Today's
workout" as a workout card (see "Workout cards" below) with its "Start Workout" call to action, or, when
nothing is planned, an honest empty card offering "Ask Formiq"; a Nutrition and a Progress tile (a faint
wash of their own color, a bar and its figure); four quick actions; "Up next", a card for each planned
workout (left out when there are none); and recent activity with "See all", whose thumbnails come from the
same picture lookup as the cards.

**The header** is one row: a short greeting for the time of day, with the date under it in smaller, muted
text, and a **theme toggle** at the end. The greeting is "Good morning" from 05:00, "Good afternoon" from
12:00 and "Good evening" from 17:00 (the small hours count as evening), on the device's own clock, with
the name after a comma ("Good evening, Anas") and the name left out when there is none (`greetingText` in
`src/home/format.ts`); it wraps to a second line rather than cutting a long name off. The toggle
(`ThemeToggle`, a reusable component) shows the theme it will switch to, a sun while the app is dark and a
moon while it is light, is named for what it does ("Switch to light theme"), and switches the whole app
through `ThemeProvider`; it is the same state as the Profile tab's Theme choice and, like it, is not
remembered after the app is closed yet. It is a plain round button in the text color, 44 dp drawn and 48 dp
to hit. There is no notification bell (the app has no notifications), no avatar or initials (Profile is a
tab: Log out is there), and no emoji.

**Where every control leads.** Each is a real navigation to a screen that exists, or is documented mock-only:

| Control | What it does |
| ------- | ------------ |
| Today's card | opens that workout's own screen (below) |
| An up-next card, View Plan, See all, a recent-activity row | opens the Workouts screen over the tabs (a placeholder) |
| Nutrition tile, Log Meal | opens the Nutrition & recovery screen over the tabs (a placeholder) |
| Progress tile | selects the Progress tab |
| Ask Formiq (quick action, and the empty card's button) | selects the AI Coach tab |
| Update Profile | selects the Profile tab |
| Theme toggle | switches between the dark and the light theme |

The screens that open over the tabs are `SectionPlaceholderScreen`s ("Not designed yet", with a Back arrow);
the Progress tab is a `TabPlaceholderScreen`. They show nothing that looks like workouts, meals or progress. A
workout card therefore opens a placeholder that says so: no workout is started, and none is made to look started.

**Pieces**, all reusable by the next screens: `TabScreen` (the page under the tab bar: a solid themed
background, near-black in dark and a pale neutral in light, with no photograph or texture, since the
workout photographs live inside the workout cards; status bar and top inset, side padding, scrolling),
`SummaryTile`,
`ActionTile`, `ListRow`, `SectionHeader`, `ProgressBar`, `Toast` / `useToast`, `FadeEdge`, and in the shell
`BottomTabBar`. Colors: one new token, `progress` (the blue of the Progress tile, graphics only), next to
`warm`. `FadeEdge` fades a photo into the page with one native gradient (React Native 0.88's own
`backgroundImage: 'linear-gradient(...)'`, so no gradient library): the same color at every stop, its
opacity following a smoothstep curve, solid through an optional `hold`. (The first version stacked 24
translucent layers, which showed faint vertical bands over a bright photo.) `AppIcon` has `rotate`: the
icon set draws its `dumbbell` on a diagonal, and the design lays it flat.

### Workout cards

One component, `src/workouts/WorkoutCard.tsx`, draws every workout, from a `WorkoutCardData`
(`src/workouts/types.ts`). It shows the kind (a small muted heading), the title (two lines at most, then an
ellipsis), an optional description (two lines at most), the length and the exercise count, over a photo on
the right that fades into the card. The card is dark in both themes (a charcoal card with a hint of its
category's color, white words, the dark theme's call to action: `cardColorsFor` and a `FixedTheme` in
`CardFrame`), because it sits over a dark photograph and the design has it dark on the light page too;
Discover's cards are the same card. The light palette in `categoryColors.ts` is still used by the workout
screen. Only the left of the photo is faded, for the words; the
photograph itself is not tinted. Formiq's emerald is not a category color: it is kept for actions (the
call-to-action pill, selected navigation, primary buttons).

- **Category colors** are one typed table, `src/workouts/categoryColors.ts`, with three tokens per
  category and theme: `label` (the heading above the title), `border` (a quiet outline) and `blend` (the
  card's surface, which the photo fades into). Core is teal, upper body blue, lower body warm orange, full
  body violet, cardio red, mobility cyan, recovery golden amber, beginner muted plum. The dark surfaces are
  about 10% of the color over charcoal and the light ones about 10% over white (a hint, not a wash; a test
  limits how colorful a surface may be). Each heading is at least 4.5:1 on its surface, and so are the
  theme's title and description colors, in both themes (`__tests__/workout-category-colors-test.ts`). A
  workout with no known category gets the theme's plain surface and outline, a muted heading color and no
  heading at all. The values were derived from each accent and checked by script; they were not read off a
  design file (no design tokens exist for this), so they are the one place to adjust.

- **It is one button** when it is given `onPress` (named by what it says, with the call to action as its
  hint) and a plain view when it is not. `actionLabel` draws a "Start Workout"-style pill on the card, and
  only on a card that can be pressed: a call to action that does nothing would be a lie. The pill is part
  of the one button, not a second one, so a screen reader meets one control per workout.
- **What the backend has, and what it does not.** `WorkoutPlanResponse` (`backend/app/schemas/workout_plan.py`)
  has `id`, `name`, `description`, `status`, `scheduled_date` and `exercises`. It has **no category, no
  length and no image**. So the card shows `title` and `description` as given, treats the exercise count as
  `exercises.length`, and leaves out the length and the kind unless a source supplies them; they are marked
  "NOT in the backend contract" in `types.ts`, and the Home mock's categories and lengths are invented for
  the design. A value that is missing, zero, negative, not a number, or (for the count) not a whole number is
  left out, never replaced. There is no server-image field, so the pictures are local; if the backend ever
  sends one, it goes ahead of the lookup.
- **The pictures** are chosen by one lookup, `src/workouts/workoutImages.ts`, from the workout's
  `categories` (`src/workouts/categories.ts`): core -> `core-abs`, upper-body -> `upper-body`, lower-body ->
  `lower-body`, full-body -> `full-body`, cardio -> `cardio-hiit`, mobility -> `mobility`, recovery ->
  `recovery-stretch`, beginner -> `beginner`. When a workout lists several, the choice is fixed and
  independent of their order: upper and lower body together make full-body; otherwise full-body, lower body,
  upper body, core, cardio, mobility, recovery; and "beginner" last, so it names a workout only when nothing
  else does (a known workout is never relabelled for a beginner). The heading above the title is the
  category's label; core, upper and lower body are all "Strength", as the design groups them. A workout with
  no known category shows no heading and the neutral picture.
- **The eight photos** are in `assets/images/workouts/` (`core-abs.png`, `upper-body.png`,
  `lower-body.png`, `full-body.png`, `cardio-hiit.png`, `mobility.png`, `recovery-stretch.png`,
  `beginner.png`), each a wide strip of about 735 x 140 to 215 px. Metro needs each `require` written out,
  so a photo is registered by a line in `WORKOUT_IMAGES` in `workoutImages.ts`. A key with no photo shows
  the neutral picture (the dark gym of sign up, with nobody in it), so a photo can be added or replaced on
  its own. Tests check that every file in the folder is registered, that every registered photo has a
  file, that each file is a real PNG, and that its size is the one the framing table says.
  **Four of the eight files as supplied were not clean:** `cardio-hiit.png`, `mobility.png`,
  `recovery-stretch.png` and `beginner.png` each began with the filename caption of the picture before it
  (and the panel's rounded corners and border), as if sliced from a contact sheet one caption too late.
  Those four were trimmed by a plain pixel crop (the top 41 or 67 rows, 2 px each side; nothing resampled
  or recoloured), which is why they are shorter than the others. The other four are byte-for-byte as
  supplied, and the ZIP the files came from still holds all eight originals. Better files (clean, taller,
  and at least twice the resolution: the card shows them about 2 to 2.7 times larger than their pixels)
  can replace these without code changes beyond the sizes in the framing table.
- **How a photo is framed.** The photos are wide strips and the card shows about a third to a half of one,
  so a centred crop cut heads off. Each photo has a `focus` in `WORKOUT_IMAGE_FRAMING` (how far across it
  its subject is, from 0 to 1) and the card keeps that point 60% of the way across the photo box, right
  of the words: the photo is drawn as tall as the card in its own shape (`aspectRatio`), moved by
  percentages of its own width, in a box that clips. Nothing is measured, so it holds at any card size
  (checked at 411 dp and at 360 dp with 1.5 x text). The neutral picture has no subject and is simply
  cropped to cover.
- **The words and the fade.** The text column stops at 55% of the card, and the fade is solid through that
  column (66% of the photo box, 38% of it held solid) and then clears, so the subject is not veiled. A pale
  veil over a dark photo hazes a head far more than a dark veil does (which is one reason the cards stay dark
  in the light theme), so the fade cannot be longer. The numbers were chosen by compositing the real photos at the card's size with every line of
  text running to the column's limit: the worst description is 8.2:1, the worst detail line 6.3:1, and at
  most 15% of the veil covers a head, in both themes. At 360 dp with 1.5 x text the column is narrow and a
  description is cut to two lines sooner.
- **When a picture does not load**, the card drops it for the neutral picture, and when that fails too it
  keeps a quiet placeholder (a faint dumbbell on the card's green): there is never a broken-image area.
  The placeholder is also what shows before a picture has loaded.
- **No workout.** `EmptyWorkoutCard` has the same shell over the neutral picture, says there is nothing
  planned and offers a real button for the next step (Home: "Ask Formiq", which opens the AI Coach tab).

Where Home differs from the reference, on purpose:

- The recent activity lists earlier workouts: the reference shows "Core & Abs Focus" as today's workout
  and as completed today, which cannot both be true.
- The reference's bell and avatar are gone: the app has no notifications, and Profile is a tab (the account
  sheet that the avatar opened, with Log out, was removed with it: Log out is on the Profile tab).
- The quick-action tiles have no chevron (the words need the room); the summary tiles and rows keep it.
- Today's workout is now a workout card like the others (the kind on top instead of "Today's workout",
  which became a heading above the card), over its category photo, in its category's colors.
- The page behind Home no longer has the gym photograph in the dark theme (the reference had one): it is a
  solid color in both themes, and photography stays inside the workout cards.
- The Nutrition tile shows "1,850 kcal, Today's target" as the reference does. **Open product question:**
  `docs/nutrition-recovery.md` says Formiq "sets no calorie target" and never gives a calorie intake
  target. Before this tile is connected, decide what it really shows.

## Workout details (UI-first design phase)

`src/workouts/WorkoutDetailsScreen.tsx` is one workout in full, built to the design reference (a photo header,
round buttons, a "Covers" pill, a "Workout Plan" heading with Edit with AI, and three tinted cards). Home's
"Today's workout" card opens it; Android's back button and the round Back button close it.

- **The top** (`WorkoutHero`): the photograph of the workout's kind (the plank photo for a core workout; the
  neutral gym for a workout of no known kind) behind the title, fading into the page at the bottom and on the
  left so the title can sit on it; then "23 minutes | 6 exercises", the **"Covers core"** pill (the workout's
  main muscle, in its kind's colors) and **"View muscle focus"**, which opens the muscles the workout trains
  (primary and secondary) under the pills and closes them again. Both pills are left out when no exercise carries
  muscles, which is the case for a real plan today. The page behind is a solid themed color: the photograph is
  only the top.
- **The round Back button** stays over the page, in reach at any scroll: dark, see-through, with a white icon, in
  both themes. (The reference also has a heart and a "..." button; they were taken out at the owner's request, as
  neither had anything behind it.) A veil of the page's color behind the status bar is faint over the photograph
  and nearly solid once the page has scrolled, so rows never show through the clock.
- **"Workout Plan (N)"** counts the exercises there are; **Edit with AI** (green, with sparkles) sits beside it.
- **Three cards** in the order the workout is done, whatever order the plan arrives in (`groupBySection`:
  Warm-up purple, Main Workout green, Cool-down blue; a section with no exercises has no card). A card has a
  header (an icon on a disc of its color, its name, "2 exercises • 3 min", a chevron) that **folds it away**, and
  its exercises one per row. The numbers on the pictures run on across cards, and do not change when one folds.
  The section colors are one typed table, `src/workouts/sectionColors.ts`, checked for contrast in both themes.
- **Rows** (`ExerciseRow`): a wide picture with its number on the corner, the name, "3 sets • 30 seconds" ("(each
  side)" when it applies), two tags and a chevron; one button. The first tag wears the section's color: the
  main muscle for a main exercise, the section's name for a warm-up or cool-down one. The second is plain:
  the equipment for a main exercise ("Bodyweight" when the catalog lists none), the kind of movement for a
  warm-up or cool-down one (Mobility, Cardio, Flexibility). A line the exercise does not carry is left out.
- **Tapping an exercise** opens that exercise's own screen (see "Exercise details" below). The workout screen
  stays mounted under it, so going back finds it exactly as it was left (its scroll position, its folded cards).
- **Edit with AI** opens the AI Coach tab with the workout as its context (`CoachContext`), changes nothing and
  says so: "Nothing was changed or saved ... until you approve a revised proposal" (a note at the top of the
  conversation, "Opened from <workout>"). The conversation is about that saved plan: its id is sent as
  `workout_plan_id` with every message, the backend checks it before the model runs and holds the coach to it, and the
  conversation opens with the coach asking about the workout by name (shown, not sent as something said). Nothing is
  changed by opening the coach: it only reads which proposals are waiting.
- **Start Workout** (green, with a play triangle) is pinned below the scrolling page and above the system bar
  (the bottom inset is part of the footer). It says "Starting a workout isn't available yet. Nothing was
  started." (a notice above the button, announced politely) and starts nothing: the app has no workout session
  flow. The screen takes an optional `onStart`; the shell passes none. Disabled for a workout with no exercises.

**The screen is given its data** (`WorkoutDetailsData` in `src/workouts/planDetails.ts`): the same contract as
the card's, with every field the backend's plan lacks marked "NOT in the plan response" and optional. What the
plan does have is shown as the plan says it: `section`, `sets`, and one target per set (`reps` or
`duration_seconds`). Not in it, and shown only when a source supplies it: the workout's length and each section's
length, the kind, whether an exercise is done on each side, and (from the catalog, `GET /exercises/{id}`) each
exercise's movement pattern, equipment and muscles. The count is the number of exercises there are, never a
number it was told.

**Mock data**, clearly labelled: `src/mock/workoutDetailsMock.ts` ("Core & Abs Focus", in the reference's
structure: 2 warm-up, 3 main, 1 cool-down exercise, 3 + 18 + 2 = 23 minutes). Home's "Today's workout" card is
made from it (`workoutCardFromDetails`), so the card and the screen agree on the name, the length and the count.
The reference itself says "5 exercises" and "Workout Plan (5)" above a list of six; the screen counts what is
there. Replacing the fixture means writing a mapper from the backend plan to `WorkoutDetailsData` and passing its
result: the screen does not change.

**The pictures** (15, `assets/images/exercises/`, registered in `src/workouts/exerciseImages.ts` with static
`require`s, a typed key per file, each file's size and its athlete's point): the supplied files each had a black
border band of 2 to 9 px on one to three sides (the contact sheet they were cut from), so they were trimmed with a
plain pixel crop (no resampling; the supplied ZIP keeps the originals). A row without a picture, or whose picture
fails to load, shows a faint dumbbell on a muted square: never a broken-image box. The hero photograph is a card
photo (`assets/images/workouts/`) drawn about 1.3 times as large as the screen is wide, so it is soft.

**How a picture is framed.** The thumbnail box is a fixed 132 x 58 dp and the picture is placed in dp
(`framedImageStyleInBox`). The percent framing the workout cards use (`framedImageStyle`) does not work in a fixed
box: measured on the emulator, Android lays the image out at the file's own width and ignores `aspectRatio`, so a
64 dp box showed the middle half of the picture zoomed 2x. The cards escape it because they are about as tall as
the photo files (138 to 223 dp against 138 to 215 px); a card much shorter than its photo would lose some of the
top and bottom of it (not changed here). The hero is a fixed-height box and uses the dp framing too.

Where it differs from the reference, on purpose or by necessity:

- The reference's text is smaller than the app's (about 0.7 to 0.9 of the same words' width in Roboto): the type
  here follows it down to a floor (11 dp for tags, 12.5 for the pills), not all the way, to stay readable.
- The reference is dark only; the light theme is the same design on the pale page (the photograph fades into it,
  the cards are tints of their colors over white).
- The reference's Warm-up exercises (Arm Circles, High Knees) have no picture in the supplied set; the fixture
  uses Mountain Climbers and Lunges.
- The green of the buttons is the app's emerald (`colors.primary`, #10B981), a little darker than the
  reference's mint.

## Exercise details (UI-first design phase)

`src/workouts/ExerciseDetailsScreen.tsx` is one exercise in full, built to the design reference (a dark
training screen with the exercise's name, an animation, three tabs and the active set at the foot). The screen
is given the `PlannedExercise` that was pressed in the workout list and shows only what that exercise carries:
a field it does not have is shown as "not available", never filled in. "3/4 Sit-Up" in the reference is only
the example: no exercise is hard-coded.

- **Top:** the Back arrow (fixed, in reach at any scroll), the exercise's name as the heading, and compact labels:
  its primary muscles (two at most) and its equipment ("Bodyweight" for the catalog's empty list, two pieces at
  most). No labels at all when neither is known. There is no overflow ("...") menu: nothing would be in it.
- **The animation** (`ExerciseAnimation.tsx`) is a looping GIF in a 16 : 9 area the width of the content, drawn in
  explicit dp (Android ignores `aspectRatio` on images). No video player, no controls. It falls back, and says
  which: the exercise's still picture labelled "Still picture · no animation yet" (or "Animation couldn't load ·
  still picture" when the GIF fails), and with no picture either a plain panel ("No animation yet"). The label
  sits at the top left, which is empty in all six GIFs. The supplied GIFs are labelled "Placeholder animation".
- **Instructions** are the catalog's steps, numbered. With no steps it shows the description as written
  (Formiq's own exercises keep their steps there); with neither, "No instructions for this exercise yet."
  **Muscles** lists the primary and secondary muscles. **Tips**: the data contract has no tips field, so this tab
  is made only of what the plan and catalog do say about doing the exercise, each line labelled with what it is:
  the plan's note, the rest between sets, the weight, and the catalog's description (when Instructions already
  shows the steps). With none of them, "No tips for this exercise yet." The rules are in
  `src/workouts/exerciseDetails.ts` and are unit-tested.
- **The active set** is pinned below the scrolling page, above the system bar: "Set 1 of 3" with a dot per set,
  a `-  30 seconds  +` control, and **Complete Set**. The control starts at the plan's reps or seconds and moves
  by 1 rep or 5 seconds within 1 to 100 reps and 5 seconds to 10 minutes (a target outside those keeps its own value
  as the edge, so the plan's number is never shown as another). A plan with no target shows no control and no
  number ("This plan gives no reps or time for each set") and Complete Set still works. A plan with no number of
  sets shows "Set N" and never finishes. The number is also one adjustable element for a screen reader.
- **Complete Set is MOCK-ONLY.** The app has no workout session yet ("Start Workout" says so), so a set is counted
  on the screen only, kept by `AppShell` while the app runs (so it is still there when the exercise is opened
  again), and the notice says so: "Set 1 of 3 marked done on this screen only. Nothing was saved." Finishing every
  set shows "All 3 sets done", "Back to workout" and "Do the sets again" (a development reset); it does not
  complete the workout. Nothing here touches the proposal approval lifecycle or the backend's session rules (one
  session at a time). The backend also cannot record a timed set: `WorkoutSetCreate.reps` is required, so a
  held exercise (a plank) has no way to be logged until the schema gets a duration.

**The animations** (6, `assets/images/exercise-gifs/`, with the README that came with them, registered in
`src/workouts/exerciseGifs.ts`): plank, squat, push-up, sit-up, jumping-jack and lunge, 480 x 270, 14 to 16 frames,
looping forever. They are stylized development placeholders: their README says they are NOT instructional or
reference-quality, so replace them with reviewed media before production. An exercise is matched to its animation by the
stable key written on it (`animation`, set by the fixture or, later, a mapper from the catalog id), never by its
name. The fixture gives one to Plank and Lunges only; the other four GIFs are registered and tested but no exercise
of the mock workout uses them, and an exercise with no key shows its still picture.

**Why `expo-image`.** React Native's own `Image` shows only the first frame of a GIF in Expo Go 58 on the Android
emulator, even for a two-frame test GIF (measured: eight to ten screenshots over several seconds were
pixel-identical, while the same files in `expo-image` gave 4 to 7 distinct frames). `expo-image` (the SDK 58
version, `~58.0.15`, already inside Expo Go: no native rebuild) is used for the animation only; every still
picture is still a plain `Image`. It is the one dependency added.

**Mock data:** `src/mock/workoutDetailsMock.ts` now also gives the exercises a rest between sets (30 to 45 seconds;
made up), one plan note on Plank (made up), and steps for Mountain Climbers, Plank and Hamstring Stretch, copied
word for word from the free-exercise-db record of the same name in the backend's vendored dataset. Lunges, Bicycle
Crunches and Leg Raises have no record of their own name, so they have no steps and show the "not available"
state: that is deliberate, to keep the fixture honest and to show that state on the device.

Where it differs from the reference: no overflow menu; the reference's chevron after "Set 1 of 3" (it opens
nothing here) is a row of set dots; the animation is a GIF without a play button; the GIFs are crude placeholders,
not the reference's photograph; the green is the app's emerald.

## AI Coach

The AI Coach tab is a chat screen, `src/coach/CoachScreen.tsx`, in which the coach proposes workouts as cards the
person can apply, ask to change, or dismiss. By default it talks to the Formiq backend: messages go to
`POST /coach/message` (naming the saved workout the conversation is about, `workout_plan_id`, when it is about one,
and sending the device's valid IANA timezone as `timezone` when available), the
proposals still waiting are listed with `GET /coach/proposals/pending`, a workout is saved only when the person taps
Apply and `POST /coach/proposals/{id}/approve` answers (201, or 200 with the same plan when the answer to the first
was lost), and a proposal is dismissed only when `POST /coach/proposals/{id}/reject` answers 204. Nothing is saved by
being shown. The contract the card rests on, how the screen is connected, and every limit that is left are in
`docs/coach-workout-card.md`.

**Two coaches behind one interface.** The screen and its state are written against a `CoachGateway` (`send`,
`pending`, `approve`, `reject`). `src/coach/apiGateway.ts` is the backend's; `src/mock/` is a made-up one that answers
from fixed examples and calls nothing, for looking at the screen and for tests. Start the app with
`EXPO_PUBLIC_COACH_MODE=mock npx expo start` to get the made-up one (the menu then has "Mock: next request fails", "Mock:
next apply fails" and "Mock: next dismiss fails", which fail once, and "Mock: a workout is waiting" and "Mock: two workouts
are waiting", which leave proposals made earlier for the screen to find after Start over). In the connected app the menu
has "Start over" and, in a development build only, "Preview card states" (every state of the card from fixtures, nothing
sent).

**The conversation** opens with a greeting of the app's own (not sent to the coach) and two replies in a row that
scrolls sideways: "Create a 25-minute upper-body workout" and "Suggest a different workout for today". From **Edit
with AI** it opens with the coach asking what to change in the workout, by name, and offers "Make it shorter", "Make it
easier" and "Suggest a different workout". The conversation is kept while the person looks at another tab (the shell
keeps the screen mounted), including an answer on its way and a workout being applied or dismissed. A request in flight
shows the workout card loading (for the replies that ask for a workout) or typing dots; a failure shows why, with Try
Again where trying again can help. A message to a workout that can no longer be edited (it was replaced or cancelled)
says so, with no Try Again. Try Again asks the latest request again, never an older failed bubble.

A conversation opened from no workout (after a restart or a new sign-in, or Start over) is about none, and the app
remembers none. It becomes about a saved plan when the person asks for changes to a card that replaces one (`Ask for
More Changes`, or a suggested change on that card): its messages then name that plan, the typed ones too, and the
backend reads that plan's proposals only. Nothing else makes it about a plan (not a card being there, not a list of
waiting workouts), and a card for a different plan than the one being edited, or a new workout in a conversation about a
plan, can only be applied or dismissed, and says so.

**Workouts waiting from before.** The backend keeps a proposal 30 minutes, so one made earlier can still be waiting after
the app was closed, the person signed out, or the conversation was cleared. When the connected AI Coach is first shown,
each time it is shown again after another tab, after Start over, and on a retry, it asks the backend which proposals are
waiting (never while a message, an apply or a dismissal is under way, one request at a time). One is shown as its card,
after a line saying it was proposed earlier and "Proposed 12 min ago"; several are listed to choose from, each with what it
is, what it replaces, when it was proposed and when it expires, and a `Review` button that puts its card in the
conversation. Nothing is applied, dismissed or chosen for the person, and nothing already on the screen is added twice. If
the look fails, a notice says so with Try Again (it never says there is none). One left in the list says "1 workout is
waiting".

**The card** (`WorkoutProposalCard`) is one component for a new workout and a revision of a saved one: a status label
(`New Workout`, `Updated Workout`, `Applied`, `Dismissed`, `Older version`), the picture of the workout's kind with its
focus, the title, what the proposal says of it (focus and day), its length and number of exercises, three sections
(warm-up, main workout, cool-down, in the workout screen's purple, green and blue) that open on their exercises, **Key
Changes** for a revision, and the actions `Apply This Workout` or `Apply Updated Workout`, `Ask for More Changes` and
`Dismiss`. Key Changes are the backend's own comparison of the proposal with the saved plan it replaces (the proposal
carries it: the app compares nothing and reads no saved plan): replaced, added or removed exercises, a different
prescription (a weight the saved plan has and the proposal drops included), and the length and day when the backend gave
them. When the backend could not compare, the card says so and lists nothing. It never lists "knee friendly" or "same
duration" it cannot verify.

| State | What the card shows |
| ----- | ------------------- |
| Loading | its shape with nothing in it, "Preparing your workout" (for a request known to be for a workout; otherwise the coach shows typing dots) |
| New workout / Updated workout | the label, the content, the three actions, and a line saying it is not saved yet, or that applying replaces "X" and until then X stays as it is; a note when X is not the workout the conversation is about |
| Waiting from before | the same card, with when it was proposed; an older version of its workout (the same saved plan, or any newer proposal for a new workout) says the coach changes the newest, and one for another plan than the one being edited says it is not a change to that: both offer Apply and Dismiss only |
| Applying | the apply as a spinner ("Applying…"), the other buttons out of use |
| Applied | `Applied`, no more actions, and what the backend answered with: "Added “Y” to your plan for today." or "Replaced “X” with “Y” for today." (only after the approval succeeded) |
| Apply failed | the proposal as it was, an alert saying why, and `Try Again` where trying again can help; otherwise the apply stays out of use and `Ask for More Changes` is the way on |
| Dismissing | the dismissal as a spinner ("Dismissing…"), the other buttons out of use |
| Dismissed | `Dismissed`, "Nothing was saved" (and that the saved workout is as it was), no more actions (only after the backend answered 204) |
| Dismiss failed | an alert saying why and `Dismiss Again` where trying again can help (the card still waits and can be applied); a 409 for another version says it was already applied or changed. A 409 "already approved" (the answer to its approval was lost) asks the approval again and shows the saved plan as Applied (see Applied): it is never called Dismissed |
| No longer waiting | the backend does not have it any more (it expired): said, not called dismissed; no more actions |
| Generation failed | "Couldn't create the workout", why, and `Try Again` where it can help, which asks again without sending the message a second time |
| Older version | a newer version of the same workout exists (the same saved plan, or a new workout beside another), or another version of it was applied: no actions. A card for another plan, or a new workout beside a revision, is not an older version |

**Ask for More Changes** puts the keyboard up with a field that asks what to change, and offers ways to change it
("Keep same duration", "Try different length", "Make it more intense", "Use no equipment"). A change is an ordinary
message with the conversation so far and the workout it is about; the coach answers with a NEW proposal, which takes the
older one's place, and its Key Changes are the backend's comparison with the ORIGINAL saved workout. Once a revision of
the workout is applied, the conversation is about the plan that replaced it.

**What cannot happen** (each is a test, and each guard was broken on purpose to see a test fail): a workout shown as saved
before the backend said so, or as dismissed before it said so; a second approval or rejection from a double press; a
message sent while a workout is applying or being dismissed; Start over while one is; a late answer showing up after Start
over; a proposal shown from an answer the app could not read in full; a card added twice by looking again; a waiting
workout applied, dismissed or chosen without the person; an older waiting workout offered "Ask for More Changes", which
would change another; the saved workout being touched by anything but a successful approval (the app only ever sends
approvals and rejections the person asked for).

**Layers.** `src/api/` (`coach.ts`: the four coach calls and the strict readers; `types.ts`: the backend's shapes),
`src/coach/` (the screen and everything it needs, written against a `CoachGateway`; `apiGateway.ts` and
`ConnectedCoachScreen.tsx` connect it, `mode.ts` picks the coach), `src/mock/` (the made-up gateway, its fixtures and
the screen wired to them). The pure parts (`proposalChanges.ts`, `proposalCard.ts`, `chatState.ts`, `coachErrors.ts`,
`opening.ts`) have no React in them.

**The rest of the screen** is as it was: the header (Back goes to Home, as Android's back button does), the overflow
menu ("Start over" first), the messages that stay at the newest one (a card is taller than the room above the
keyboard, so the list goes to where the coach's reply to it begins), the composer that rides above the keyboard (a
`KeyboardAvoidingView` that pads only by what the keyboard covers above the tab bar), "Opened from <workout>" after
"Edit with AI", and the light and dark themes.

**Where the card differs from the reference image, on purpose:** the reference's description line and "Moderate" are
not in a proposal, so they are not shown (a line with the focus and day is); its "(knee friendly)" and "Uses your
available equipment" cannot be verified from the data, so they are never produced, and "Kept the same duration" appears
only when the backend gave the replaced workout's length; its section dots are green, blue and purple where the app's
workout screen uses purple, green and blue, which the card follows; its button on an updated workout reads "Apply This
Workout" where the brief says `Apply Updated Workout`, which it follows. Not built from the reference's chat around the
card: timestamps, an avatar beside each message, the "+" button and the leaf logo (there is nothing for them to do or
show).

**Not done.** The conversation lives in memory: closing the app, signing out or Start over clears it, and what the coach
proposed stays waiting on the backend and is offered again (Dismiss removes it). Waiting proposals are looked for when the
screen opens or is shown again, not while it stays open. An expired session is said, not acted on (the app does not
return to sign-in by itself). The backend's reply to a message was never exercised live in this phase (no Gemini); the
flows were verified against the backend's own tests, its schemas and the payloads its routes write, and a stub. The
typing dots do not move. With the keyboard up on a short screen at large text (360 x 640 dp, 1.5 x font) little room is
left for messages. No attachments, voice, message actions or expiry countdown.

## Provisional choices to confirm

- The colors in `src/theme/colors.ts` follow the approved direction (near-black, charcoal, emerald,
  white) but are not taken from the UX storyboards yet. `app.json` repeats the dark background
  (`backgroundColor`).
- The brand green as a filled button on the light page background is 2.4:1 against it; the label
  on the button is 7.7:1.
- The icons in `assets/` are Expo's placeholders, and there is no splash screen yet.
- The Android package name `com.formiq.app` is a placeholder; change it before any release build.
- The Android keyboard and native dialogs do not follow the in-app theme: in Expo Go they stayed light
  while the app was dark and the phone was light. Whether `Appearance.setColorScheme` styles native
  dialogs in a development build is not verified.
- Progress segments and unselected card outlines in the light theme are faint on purpose (they are
  decoration); the step number is also written out.
- Full-height keyboard behaviour (the keyboard pushing the footer up) is covered by a unit test with
  simulated keyboard events, but was not seen on a device: the emulator showed only Gboard's compact
  floating toolbar.
