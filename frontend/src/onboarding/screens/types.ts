import type { ProfileDraft } from '../draft';

// What every profile step receives from the flow. The draft lives in the flow, not in the screen, so
// going back never loses what was typed.
export type StepScreenProps = {
  draft: ProfileDraft;
  onChange: (patch: Partial<ProfileDraft>) => void;
  onNext: () => void;
  // left out where there is nothing before this step
  onBack?: () => void;
  nextLabel?: string;
};
