export const brand = {
  appName: 'Teller',
  tagline: 'Find a better pick, faster.',
  homeFilters: ['Quick', 'Comfort', 'Healthy', 'Budget', 'Treat'] as const,
  colors: {
    accent: '#C9673C',
    accentDark: '#A9542D',
    accentLight: '#F8ECE5',
    warmSurface: '#FFF9F5',
    ink: '#1C1917',
    muted: '#6F665F',
  },
} as const;

export type HomeFilter = (typeof brand.homeFilters)[number];
