import { View } from 'react-native';

type CheckMarkProps = {
  // the height of the mark, in dp
  size: number;
  color: string;
};

// A check mark drawn from two borders, so it looks the same on every device and in every font. It is
// decoration: screen readers get "checked" from the control it sits in, never from this.
export function CheckMark({ size, color }: CheckMarkProps) {
  const stroke = Math.max(2, Math.round(size / 7));

  return (
    <View
      testID="check-mark"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{
        width: size * 0.36,
        height: size * 0.64,
        marginTop: -size * 0.14,
        borderRightWidth: stroke,
        borderBottomWidth: stroke,
        borderColor: color,
        transform: [{ rotate: '45deg' }],
      }}
    />
  );
}
