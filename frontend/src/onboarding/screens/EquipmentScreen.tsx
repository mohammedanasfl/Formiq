import { EquipmentOptions } from '../EquipmentOptions';
import { StepFrame } from '../StepFrame';
import { stepProgress } from '../steps';
import type { EquipmentCatalog } from '../useEquipmentCatalog';
import type { StepScreenProps } from './types';

type EquipmentScreenProps = StepScreenProps & { catalog: EquipmentCatalog };

// The options are the catalog's own (GET /equipment). The choice goes with the rest of the profile when it is
// saved at the end (ids, or "no equipment"); nothing is stored by choosing here.
export function EquipmentScreen({
  draft,
  onChange,
  onNext,
  onBack,
  nextLabel = 'Next',
  catalog,
}: EquipmentScreenProps) {
  return (
    <StepFrame
      step={stepProgress('equipment')}
      title="Available equipment"
      subtitle="Select the equipment you have access to."
      // nothing is required: the step can be left empty, and is when the list cannot be loaded
      primary={{ label: nextLabel, onPress: onNext, arrow: true }}
      onBack={onBack}
    >
      <EquipmentOptions
        choice={draft}
        onChange={onChange}
        catalog={catalog}
        errorHint="You can also continue without choosing equipment."
      />
    </StepFrame>
  );
}
