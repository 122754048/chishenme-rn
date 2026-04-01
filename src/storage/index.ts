import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  ONBOARDING_COMPLETE: '@chishenme/onboarding_complete',
  SELECTED_CUISINES: '@chishenme/selected_cuisines',
  SELECTED_RESTRICTIONS: '@chishenme/selected_restrictions',
  FAVORITES: '@chishenme/favorites',
  HISTORY: '@chishenme/history',
};

function parseJsonWithFallback<T>(
  raw: string | null,
  fallback: T,
  validate?: (value: unknown) => value is T
): T {
  if (!raw) return fallback;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (validate) return validate(parsed) ? parsed : fallback;
    return parsed as T;
  } catch {
    return fallback;
  }
}

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string');

const isNumberArray = (value: unknown): value is number[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'number');
const isBoolean = (value: unknown): value is boolean => typeof value === 'boolean';

type HistoryItem = {
  id: number;
  title: string;
  img: string;
  time: string;
  category: string;
  status: 'Liked' | 'Skipped';
};

const isHistoryArray = (value: unknown): value is HistoryItem[] =>
  Array.isArray(value) &&
  value.every(
    (item) =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as HistoryItem).id === 'number' &&
      typeof (item as HistoryItem).title === 'string' &&
      typeof (item as HistoryItem).img === 'string' &&
      typeof (item as HistoryItem).time === 'string' &&
      typeof (item as HistoryItem).category === 'string' &&
      ((item as HistoryItem).status === 'Liked' || (item as HistoryItem).status === 'Skipped')
  );

export const storage = {
  async setOnboardingComplete(value: boolean): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.ONBOARDING_COMPLETE, JSON.stringify(value));
    } catch (error) {
      console.warn('Failed to save onboarding status:', error);
    }
  },

  async getOnboardingComplete(): Promise<boolean> {
    try {
      const val = await AsyncStorage.getItem(KEYS.ONBOARDING_COMPLETE);
      return parseJsonWithFallback(val, false, isBoolean);
    } catch (error) {
      console.warn('Failed to read onboarding status:', error);
      return false;
    }
  },

  async setSelectedCuisines(cuisines: string[]): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.SELECTED_CUISINES, JSON.stringify(cuisines));
    } catch (error) {
      console.warn('Failed to save cuisines:', error);
    }
  },

  async getSelectedCuisines(): Promise<string[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.SELECTED_CUISINES);
      return parseJsonWithFallback(val, [], isStringArray);
    } catch (error) {
      console.warn('Failed to read cuisines:', error);
      return [];
    }
  },

  async setSelectedRestrictions(restrictions: string[]): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.SELECTED_RESTRICTIONS, JSON.stringify(restrictions));
    } catch (error) {
      console.warn('Failed to save restrictions:', error);
    }
  },

  async getSelectedRestrictions(): Promise<string[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.SELECTED_RESTRICTIONS);
      return parseJsonWithFallback(val, [], isStringArray);
    } catch (error) {
      console.warn('Failed to read restrictions:', error);
      return [];
    }
  },

  async setFavorites(favorites: number[]): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.FAVORITES, JSON.stringify(favorites));
    } catch (error) {
      console.warn('Failed to save favorites:', error);
    }
  },

  async getFavorites(): Promise<number[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.FAVORITES);
      return parseJsonWithFallback(val, [], isNumberArray);
    } catch (error) {
      console.warn('Failed to read favorites:', error);
      return [];
    }
  },

  async addToHistory(item: HistoryItem): Promise<void> {
    try {
      const existing = await this.getHistory();
      const updated = [item, ...existing].slice(0, 50); // keep last 50
      await AsyncStorage.setItem(KEYS.HISTORY, JSON.stringify(updated));
    } catch (error) {
      console.warn('Failed to save history:', error);
    }
  },

  async getHistory(): Promise<HistoryItem[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.HISTORY);
      return parseJsonWithFallback(val, [], isHistoryArray);
    } catch (error) {
      console.warn('Failed to read history:', error);
      return [];
    }
  },
};
