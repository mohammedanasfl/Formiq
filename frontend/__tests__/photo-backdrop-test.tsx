import { StyleSheet, View } from 'react-native';
import { screen } from '@testing-library/react-native';

import { PhotoBackdrop } from '../src/components';
import { darkColors, lightColors } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const PHOTO = require('../assets/images/signup-background.png');

describe('<PhotoBackdrop />', () => {
  test('fills its parent, cropped to cover, with an explicit size so Android does not use the picture\'s own', async () => {
    await renderWithTheme(
      <View>
        <PhotoBackdrop testID="photo" source={PHOTO} />
      </View>,
    );

    const photo = screen.getByTestId('photo');
    expect(photo).toHaveProp('source', PHOTO);
    expect(photo).toHaveProp('resizeMode', 'cover');
    expect(photo).toHaveStyle({ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%' });
  });

  test('is decoration: no name, not focusable by a screen reader', async () => {
    await renderWithTheme(<PhotoBackdrop testID="photo" source={PHOTO} />);

    const photo = screen.getByTestId('photo');
    expect(photo).toHaveProp('accessible', false);
    expect(photo).toHaveProp('importantForAccessibility', 'no');
    expect(photo).not.toHaveProp('accessibilityLabel');
    expect(photo).not.toHaveProp('alt');
  });

  test('has no layer over the picture unless asked', async () => {
    await renderWithTheme(<PhotoBackdrop testID="photo" source={PHOTO} />);

    expect(screen.queryByTestId('photo-scrim')).toBeNull();
  });

  test.each([
    ['dark', darkColors],
    ['light', lightColors],
  ] as const)('puts a layer in the %s page color over the picture, as strong as asked', async (scheme, colors) => {
    await renderWithTheme(<PhotoBackdrop testID="photo" source={PHOTO} scrim={0.4} />, scheme);

    const scrim = screen.getByTestId('photo-scrim');
    expect(scrim).toHaveStyle({ backgroundColor: colors.background });
    expect(StyleSheet.flatten(scrim.props.style).opacity).toBe(0.4);
    expect(scrim).toHaveProp('pointerEvents', 'none');
  });
});
