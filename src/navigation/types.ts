/**
 * Type-safe navigation param list for the entire app.
 * Issue #11: Replaces all `NativeStackNavigationProp<any>` with typed navigation.
 */
import type { NavigatorScreenParams } from '@react-navigation/native';

export type RootStackParamList = {
  OnboardingCuisines: undefined;
  OnboardingRestrictions: undefined;
  Upgrade: undefined;
  MainTabs: NavigatorScreenParams<MainTabParamList> | undefined;
  Detail: { itemId?: number; title?: string; image?: string } | undefined;
  History: undefined;
  Checkout: { plan: 'pro' | 'family' };
};

// Tab navigator param list
export type MainTabParamList = {
  Home: undefined;
  Explore: { initialQuery?: string } | undefined;
  Favorites: undefined;
  Profile: undefined;
};
