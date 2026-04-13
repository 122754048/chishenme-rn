import { useMemo } from 'react';
import { StyleSheet, useColorScheme } from 'react-native';
import { lightTheme, darkTheme } from './index';

export type AppTheme = typeof lightTheme;

/** Pass a style-factory that receives the theme, returns styles object.
 *  StyleSheet.create is memoized per colorScheme to avoid re-creating on every render. */
export function useThemedStyles<T extends StyleSheet.NamedStyles<T>>(
  factory: (theme: AppTheme) => T,
): T {
  const colorScheme = useColorScheme();
  const theme = colorScheme === 'dark' ? darkTheme : lightTheme;
  // colorScheme is the only dependency — within the same scheme the theme object
  // reference is stable (module-level constant), so styles only rebuild on scheme change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => StyleSheet.create(factory(theme)), [colorScheme]);
}

/** Returns the current theme object */
export function useThemeColors(): AppTheme {
  const colorScheme = useColorScheme();
  return colorScheme === 'dark' ? darkTheme : lightTheme;
}
