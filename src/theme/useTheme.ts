import { StyleSheet, useColorScheme } from 'react-native';
import { lightTheme, darkTheme } from './index';

export type AppTheme = typeof lightTheme;

/** Pass a style-factory that receives the theme, returns styles object */
export function useThemedStyles<T extends StyleSheet.NamedStyles<T>>(
  factory: (theme: AppTheme) => T,
): T {
  const colorScheme = useColorScheme();
  const theme = colorScheme === 'dark' ? darkTheme : lightTheme;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return StyleSheet.create(factory(theme));
}

/** Returns the current theme object */
export function useThemeColors(): AppTheme {
  const colorScheme = useColorScheme();
  return colorScheme === 'dark' ? darkTheme : lightTheme;
}
