import { useColorScheme } from 'react-native';

export const lightTheme = {
  colors: {
    // Brand
    primary: '#FF6B35',
    primaryDark: '#E85D2C',
    primaryLight: '#FFF0E8',

    // Accent
    accent: '#2EC4B6',
    accentLight: '#E8FAF8',

    // Semantic
    success: '#4CAF50',
    successLight: '#E8F5E9',
    warning: '#F2994A',
    warningLight: '#FFF3E0',
    error: '#EF4444',
    errorLight: '#FEE2E2',

    // Neutral
    background: '#FAFAF8',
    surface: '#FFFFFF',
    foreground: '#111827',
    muted: '#6B7280',
    subtle: '#9CA3AF',
    border: '#E5E7EB',
    borderLight: '#F3F4F6',

    // Special
    star: '#F2994A',
    premium: '#FFD700',

    // Legacy aliases
    brand: '#FF6B35',
    brandDark: '#E85D2C',
    brandLight: '#FFF0E8',
    brandAccent: '#F2994A',
    brandAccentLight: '#FFF3E0',
    brandWarm: '#E69A5A',
    brandWarmDark: '#8A5A2B',
    white: '#FFFFFF',
    red: '#EF4444',
    blue: '#3B82F6',
  },

  spacing: {
    '2xs': 4,
    xs: 8,
    sm: 12,
    md: 16,
    lg: 24,
    xl: 32,
    '2xl': 48,
  },

  radius: {
    sm: 8,
    md: 12,
    lg: 16,
    full: 9999,
  },

  shadows: {
    sm: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.08,
      shadowRadius: 3,
      elevation: 2,
    },
    md: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.12,
      shadowRadius: 8,
      elevation: 4,
    },
    lg: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.15,
      shadowRadius: 16,
      elevation: 8,
    },
  },

  typography: {
    display: { fontSize: 26, lineHeight: 34, fontWeight: '800' as const },
    h1: { fontSize: 20, lineHeight: 28, fontWeight: '700' as const },
    h2: { fontSize: 16, lineHeight: 24, fontWeight: '600' as const },
    body: { fontSize: 14, lineHeight: 22, fontWeight: '400' as const },
    caption: { fontSize: 12, lineHeight: 18, fontWeight: '500' as const },
    micro: { fontSize: 10, lineHeight: 14, fontWeight: '600' as const },
  },

  topNavHeight: 56,
  tabBarHeight: 56,
};

export const darkTheme = {
  ...lightTheme,
  colors: {
    ...lightTheme.colors,
    // Dark mode adjustments
    background: '#0F0F0F',
    surface: '#1A1A1A',
    foreground: '#F9FAFB',
    muted: '#9CA3AF',
    subtle: '#6B7280',
    border: '#2A2A2A',
    borderLight: '#1F1F1F',

    // Adjusted for dark mode contrast
    primaryLight: 'rgba(255, 107, 53, 0.15)',
    successLight: 'rgba(76, 175, 80, 0.15)',
    warningLight: 'rgba(242, 153, 74, 0.15)',
    errorLight: 'rgba(239, 68, 68, 0.15)',
    accentLight: 'rgba(46, 196, 182, 0.15)',
    brandAccentLight: 'rgba(242, 153, 74, 0.15)',
  },
  shadows: {
    sm: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.2,
      shadowRadius: 4,
      elevation: 3,
    },
    md: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.3,
      shadowRadius: 10,
      elevation: 6,
    },
    lg: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.4,
      shadowRadius: 20,
      elevation: 10,
    },
  },
};

export function useTheme() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  return {
    theme: isDark ? darkTheme : lightTheme,
    isDark,
    colorScheme,
  };
}

// Export default theme for backward compatibility
export const theme = lightTheme;
