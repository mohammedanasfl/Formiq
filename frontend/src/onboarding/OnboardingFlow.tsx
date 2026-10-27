import { useCallback, useEffect, useState } from 'react';
import { BackHandler } from 'react-native';

import { ApiError, createProfile, describeError, type Session } from '../api';
import { useSession } from '../session/SessionProvider';
import { AppShell } from '../shell/AppShell';
import { emptyDraft, type ProfileDraft } from './draft';
import { buildProfilePayload } from './profilePayload';
import { DetailsScreen } from './screens/DetailsScreen';
import { DoneScreen } from './screens/DoneScreen';
import { EquipmentScreen } from './screens/EquipmentScreen';
import { GoalScreen } from './screens/GoalScreen';
import { LocationScreen } from './screens/LocationScreen';
import { ReviewScreen } from './screens/ReviewScreen';
import { SignInScreen } from './screens/SignInScreen';
import { SignUpScreen } from './screens/SignUpScreen';
import { TrainingScreen } from './screens/TrainingScreen';
import { WelcomeScreen } from './screens/WelcomeScreen';
import { PROFILE_STEPS, type ProfileStep, type StepId } from './steps';
import { useEquipmentCatalog } from './useEquipmentCatalog';
import { isProfileComplete } from './validation';

type SaveState = { saving: boolean; error: string | null };

// The whole onboarding, as a small state machine: which screen, and the draft the screens share.
// No navigation library yet: the flow is linear, and a navigator can replace this when the app has
// more than onboarding to move between.
export function OnboardingFlow() {
  const { session, startSession, endSession } = useSession();
  const [step, setStep] = useState<StepId>('welcome');
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft);
  // true while a step is being edited from the review: its next and back lead back to the review
  const [editingFromReview, setEditingFromReview] = useState(false);
  const [signInNotice, setSignInNotice] = useState<string | null>(null);
  const [save, setSave] = useState<SaveState>({ saving: false, error: null });
  const [alreadySaved, setAlreadySaved] = useState(false);
  const catalog = useEquipmentCatalog();

  const updateDraft = useCallback(
    (patch: Partial<ProfileDraft>) => setDraft((current) => ({ ...current, ...patch })),
    [],
  );

  const goTo = (target: StepId) => {
    setSave((current) => ({ ...current, error: null }));
    setStep(target);
  };

  const goNext = (from: ProfileStep) => {
    if (editingFromReview) {
      setEditingFromReview(false);
      goTo('review');
      return;
    }
    goTo(PROFILE_STEPS[PROFILE_STEPS.indexOf(from) + 1]);
  };

  const goBack = (from: ProfileStep) => {
    if (editingFromReview) {
      setEditingFromReview(false);
      goTo('review');
      return;
    }
    const previous = PROFILE_STEPS[PROFILE_STEPS.indexOf(from) - 1];
    if (previous) goTo(previous);
  };

  // The first step has nothing before it: the account was just made.
  const backFor = (from: ProfileStep) =>
    from === 'goal' && !editingFromReview ? undefined : () => goBack(from);

  // Android's back button follows the same path as the on-screen Back.
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      switch (step) {
        case 'signUp':
        case 'signIn':
          goTo('welcome');
          return true;
        case 'details':
        case 'training':
        case 'location':
        case 'equipment':
        case 'review':
          if (!save.saving) goBack(step);
          return true;
        case 'done':
          return true;
        default:
          // welcome, goal and home: leave the app
          return false;
      }
    });
    return () => subscription.remove();
  });

  const handleSignedUp = (newSession: Session) => {
    startSession(newSession);
    setSignInNotice(null);
    goTo('goal');
  };

  const handleSignedIn = (newSession: Session, profileExists: boolean) => {
    startSession(newSession);
    setSignInNotice(null);
    goTo(profileExists ? 'home' : isProfileComplete(draft) ? 'review' : 'goal');
  };

  // Saves the profile. The done screen is reached only when the backend has said so.
  const saveProfile = async () => {
    if (save.saving) return;
    if (!session) {
      goTo('signIn');
      return;
    }
    let payload;
    try {
      payload = buildProfilePayload(draft);
    } catch {
      setSave({ saving: false, error: 'Some answers are missing. Go back and complete them.' });
      return;
    }

    setSave({ saving: true, error: null });
    try {
      await createProfile(session, payload);
      setAlreadySaved(false);
      setSave({ saving: false, error: null });
      setStep('done');
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        // the token ran out: nothing was saved, and the answers are kept for after logging in
        endSession();
        setSignInNotice('Your session expired, so nothing was saved. Log in again: your answers are kept.');
        setSave({ saving: false, error: null });
        setStep('signIn');
      } else if (error instanceof ApiError && error.status === 409) {
        // the account already has a profile, so this one was not saved
        setAlreadySaved(true);
        setSave({ saving: false, error: null });
        setStep('done');
      } else {
        setSave({ saving: false, error: describeError(error, 'saveProfile') });
      }
    }
  };

  const signOut = () => {
    endSession();
    setDraft(emptyDraft);
    setEditingFromReview(false);
    setAlreadySaved(false);
    setSignInNotice(null);
    setSave({ saving: false, error: null });
    setStep('welcome');
  };

  const stepProps = (from: ProfileStep) => ({
    draft,
    onChange: updateDraft,
    onNext: () => goNext(from),
    onBack: backFor(from),
    nextLabel: editingFromReview ? 'Done' : 'Next',
  });

  switch (step) {
    case 'welcome':
      return (
        <WelcomeScreen onGetStarted={() => goTo('signUp')} onHaveAccount={() => goTo('signIn')} />
      );
    case 'signUp':
      return (
        <SignUpScreen
          onSignedUp={handleSignedUp}
          onBack={() => goTo('welcome')}
          onSwitchToSignIn={() => goTo('signIn')}
        />
      );
    case 'signIn':
      return (
        <SignInScreen
          notice={signInNotice}
          onSignedIn={handleSignedIn}
          onBack={() => goTo('welcome')}
          onSwitchToSignUp={() => goTo('signUp')}
        />
      );
    case 'goal':
      return <GoalScreen {...stepProps('goal')} />;
    case 'details':
      return <DetailsScreen {...stepProps('details')} />;
    case 'training':
      return <TrainingScreen {...stepProps('training')} />;
    case 'location':
      return <LocationScreen {...stepProps('location')} />;
    case 'equipment':
      return <EquipmentScreen {...stepProps('equipment')} catalog={catalog} />;
    case 'review':
      return (
        <ReviewScreen
          draft={draft}
          equipmentNames={catalog.items
            .filter((item) => draft.equipmentIds.includes(item.id))
            .map((item) => item.name)}
          saving={save.saving}
          error={save.error}
          onSave={saveProfile}
          onBack={() => goBack('review')}
          onEdit={(target) => {
            if (save.saving) return;
            setEditingFromReview(true);
            goTo(target);
          }}
        />
      );
    case 'done':
      return (
        <DoneScreen alreadySaved={alreadySaved} onContinue={() => goTo('home')} />
      );
    case 'home':
      // a session always exists here: this step is reached by signing in, or after saving the profile with one
      return session ? <AppShell session={session} onSignOut={signOut} /> : null;
  }
}
