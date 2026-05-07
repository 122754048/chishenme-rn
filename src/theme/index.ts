import { useColorScheme } from 'react-native';

export const lightTheme = {
  colors: {
    primary: '#C9673C',
    primaryDark: '#A9542D',
    primaryLight: '#F8ECE5',

    accent: '#6E867D',
    accentLight: '#EEF4F0',

    success: '#7C9D87',
    successLight: '#EEF5F0',
    warning: '#C99658',
    warningLight: '#F8F0E4',
    error: '#C96D60',
    errorLight: '#F8EBE8',

    background: '#FAF6F2',
    surface: '#FFFFFF',
    surfaceMuted: '#F6F0EB',
    surfaceElevated: '#FFFDFC',
    foreground: '#1F1915',
    muted: '#6F6259',
    subtle: '#9B8E84',
    border: '#E6DBD3',
    borderLight: '#EEE5DF',

    star: '#D1A04A',
    premium: '#E5B86D',

    brand: '#C9673C',
    brandDark: '#A9542D',
    brandLight: '#F8ECE5',
    brandAccent: '#DCA24A',
    brandAccentLight: '#FFF4E2',
    brandWarm: '#E8C19E',
    brandWarmDark: '#8A5A2B',
    white: '#FFFFFF',
    red: '#D65947',
    blue: '#667FA4',
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
    md: 14,
    lg: 18,
    full: 9999,
  },

  interaction: {
    pressedOpacity: 0.9,
    pressedScale: 0.985,
    chipPressedOpacity: 0.82,
    // Disabled state
    disabledOpacity: 0.42,
    // Focus ring (Expo Web / accessibility)
    focusRingColor: '#C9673C',
    focusRingWidth: 2,
    // Spring animation parameters
    springDamping: 14,
    springStiffness: 220,
    pressAnimDuration: 70,
  },

  surface: {
    controlHeight: 40,
    compactChipHeight: 32,
    cardRadius: 20,
    insetCardPadding: 16,
    actionButtonSize: 60,
    listCardMinHeight: 88,
    // Interaction surface states
    pressed: '#F2EBE4',
    disabled: '#F0EBE6',
    focus: '#FAF6F2',
  },

  overlay: {
    // Image scrims — card bottom info overlays
    cardInfoGradient: 'rgba(17, 12, 9, 0.42)',    // Home main card info area (deeper)
    cardPreview: 'rgba(17, 12, 9, 0.22)',          // Home preview deck card (lighter)
    heroDetail: 'rgba(16, 12, 10, 0.36)',          // Detail screen hero
    featuredCard: 'rgba(20, 15, 12, 0.24)',        // Explore featured nearby card
    visualCard: 'rgba(20, 15, 12, 0.26)',          // Explore restaurant visual card
    fitCard: 'rgba(20, 15, 12, 0.30)',             // Explore fit visual card
    // Glass morphism — light translucent surfaces (icons, buttons on images)
    glassLight: 'rgba(255, 255, 255, 0.92)',       // navCircle, heartBtn
    glassMedium: 'rgba(255, 255, 255, 0.78)',      // unlockIcon, summaryStat, summaryAction
    glassMuted: 'rgba(255, 255, 255, 0.55)',       // scanActionIcon
    glassInline: 'rgba(255, 255, 255, 0.16)',      // inlinePill, ratingBadge on cards
    // Scrim — behind modals / bottom sheets
    scrim: 'rgba(0, 0, 0, 0.42)',                  // modal/sheet backdrop
    scrimLight: 'rgba(0, 0, 0, 0.24)',             // lightweight scrim
    // Backdrop — non-image translucent surfaces
    backdropSurface: 'rgba(255, 255, 255, 0.94)', // SearchOverlay background
    // Text on images
    textOnImage: '#FFFFFF',
    textOnImageSecondary: 'rgba(255, 255, 255, 0.88)',
    textOnImageMeta: 'rgba(255, 255, 255, 0.70)',
    // Brand border
    primaryBorder: 'rgba(201, 103, 60, 0.18)',
  },

  shadows: {
    sm: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.025,
      shadowRadius: 3,
      elevation: 1,
    },
    md: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.045,
      shadowRadius: 10,
      elevation: 2,
    },
    lg: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.06,
      shadowRadius: 16,
      elevation: 4,
    },
  },

  typography: {
    display: { fontSize: 32, lineHeight: 40, fontWeight: '800' as const },
    h1: { fontSize: 22, lineHeight: 30, fontWeight: '700' as const },
    h2: { fontSize: 18, lineHeight: 26, fontWeight: '700' as const },
    body: { fontSize: 16, lineHeight: 24, fontWeight: '400' as const },
    caption: { fontSize: 14, lineHeight: 20, fontWeight: '500' as const },
    micro: { fontSize: 12, lineHeight: 17, fontWeight: '600' as const },
  },

  topNavHeight: 56,
  tabBarHeight: 56,
};

export const darkTheme = {
  ...lightTheme,
  colors: {
    ...lightTheme.colors,
    background: '#141211',
    surface: '#1D1A18',
    surfaceMuted: '#1A1715',
    surfaceElevated: '#24201D',
    foreground: '#FAF6F2',
    muted: '#B6A99D',
    subtle: '#8F8177',
    border: '#332D29',
    borderLight: '#241F1D',
    primaryLight: 'rgba(201, 103, 60, 0.18)',
    successLight: 'rgba(114, 180, 125, 0.18)',
    warningLight: 'rgba(220, 162, 74, 0.18)',
    errorLight: 'rgba(214, 89, 71, 0.18)',
    accentLight: 'rgba(77, 139, 122, 0.18)',
    brandAccentLight: 'rgba(220, 162, 74, 0.18)',
  },
  surface: {
    ...lightTheme.surface,
    pressed: '#2A2420',
    disabled: '#231F1C',
    focus: '#1D1A18',
  },
  overlay: {
    ...lightTheme.overlay,
    // Dark mode image scrims are slightly heavier to compensate for reduced image contrast
    cardInfoGradient: 'rgba(17, 12, 9, 0.55)',
    cardPreview: 'rgba(17, 12, 9, 0.28)',
    heroDetail: 'rgba(10, 8, 6, 0.48)',
    featuredCard: 'rgba(10, 8, 6, 0.32)',
    visualCard: 'rgba(10, 8, 6, 0.34)',
    fitCard: 'rgba(10, 8, 6, 0.40)',
    // Dark glass — replace white glass with dark-tinted surfaces
    glassLight: 'rgba(36, 32, 29, 0.92)',
    glassMedium: 'rgba(36, 32, 29, 0.78)',
    glassMuted: 'rgba(36, 32, 29, 0.55)',
    glassInline: 'rgba(255, 255, 255, 0.14)',  // keep bright — used on images
    // Deeper scrims in dark mode
    scrim: 'rgba(0, 0, 0, 0.62)',
    scrimLight: 'rgba(0, 0, 0, 0.38)',
    backdropSurface: 'rgba(20, 18, 17, 0.96)',
  },
  shadows: {
    // Dark mode: use stronger opacity + subtle glow border (black shadows are invisible on dark bg)
    sm: {
      shadowColor: '#000000',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.32,
      shadowRadius: 4,
      elevation: 2,
      borderWidth: 1,
      borderColor: 'rgba(255,255,255,0.06)',
    },
    md: {
      shadowColor: '#000000',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.38,
      shadowRadius: 12,
      elevation: 4,
      borderWidth: 1,
      borderColor: 'rgba(255,255,255,0.08)',
    },
    lg: {
      shadowColor: '#000000',
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.45,
      shadowRadius: 20,
      elevation: 6,
      borderWidth: 1,
      borderColor: 'rgba(255,255,255,0.10)',
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

export { useThemedStyles, useThemeColors } from './useTheme';
export const theme = lightTheme;
