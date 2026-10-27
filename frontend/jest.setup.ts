// The native safe-area module is not available under Jest: use the library's own mock.
jest.mock('react-native-safe-area-context', () =>
  require('react-native-safe-area-context/jest/mock').default,
);

// Icons are drawn from a font, which a device loads natively and Jest cannot. Here the font counts
// as loaded, so the real icon component renders its glyph with the size and color it was given.
jest.mock('expo-font', () => ({
  isLoaded: () => true,
  loadAsync: () => Promise.resolve(),
}));
