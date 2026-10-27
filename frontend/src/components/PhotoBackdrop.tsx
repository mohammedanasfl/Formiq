import { Image, StyleSheet, View, type ImageSourcePropType } from 'react-native';

import { useTheme } from '../theme';

type PhotoBackdropProps = {
  source: ImageSourcePropType;
  // How much of a layer in the page color lies over the picture, from 0 to 1. More makes the text
  // on top easier to read and the picture quieter.
  scrim?: number;
  testID?: string;
};

// A picture that fills the whole screen behind the content (place it first, inside a screen-sized
// view). It is decoration: no name, hidden from screen readers.
export function PhotoBackdrop({ source, scrim = 0, testID }: PhotoBackdropProps) {
  const { colors } = useTheme();

  return (
    <>
      <Image
        testID={testID}
        source={source}
        resizeMode="cover"
        accessible={false}
        importantForAccessibility="no"
        // an explicit size: on Android an image otherwise keeps the asset's own width and height,
        // which win over the four edges of absoluteFill and leave a huge, top-left picture
        style={[StyleSheet.absoluteFill, { width: '100%', height: '100%' }]}
      />
      {scrim > 0 ? (
        <View
          testID={testID ? `${testID}-scrim` : undefined}
          pointerEvents="none"
          style={[StyleSheet.absoluteFill, { backgroundColor: colors.background, opacity: scrim }]}
        />
      ) : null}
    </>
  );
}
