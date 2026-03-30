/**
 * Type-safe navigation param list for the entire app.
 * Issue #11: Replaces all `NativeStackNavigationProp<any>` with typed navigation.
 */

export type RootStackParamList = {
  OnboardingCuisines: undefined;
  OnboardingRestrictions: undefined;
  Upgrade: undefined;
  MainTabs: undefined;
  Detail: { itemId: number; title: string; image: string };
  History: undefined;
};

// Tab navigator param list
export type MainTabParamList = {
  Home: undefined;
  Explore: undefined;
  Favorites: undefined;
  Profile: undefined;
};
