import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  ONBOARDING_COMPLETE: '@chishenme/onboarding_complete',
  SELECTED_CUISINES: '@chishenme/selected_cuisines',
  SELECTED_RESTRICTIONS: '@chishenme/selected_restrictions',
  FAVORITES: '@chishenme/favorites',
  HISTORY: '@chishenme/history',
};

export const storage = {
  async setOnboardingComplete(value: boolean): Promise<void> {
    await AsyncStorage.setItem(KEYS.ONBOARDING_COMPLETE, JSON.stringify(value));
  },

  async getOnboardingComplete(): Promise<boolean> {
    const val = await AsyncStorage.getItem(KEYS.ONBOARDING_COMPLETE);
    return val === 'true';
  },

  async setSelectedCuisines(cuisines: string[]): Promise<void> {
    await AsyncStorage.setItem(KEYS.SELECTED_CUISINES, JSON.stringify(cuisines));
  },

  async getSelectedCuisines(): Promise<string[]> {
    const val = await AsyncStorage.getItem(KEYS.SELECTED_CUISINES);
    return val ? JSON.parse(val) : [];
  },

  async setSelectedRestrictions(restrictions: string[]): Promise<void> {
    await AsyncStorage.setItem(KEYS.SELECTED_RESTRICTIONS, JSON.stringify(restrictions));
  },

  async getSelectedRestrictions(): Promise<string[]> {
    const val = await AsyncStorage.getItem(KEYS.SELECTED_RESTRICTIONS);
    return val ? JSON.parse(val) : [];
  },

  async setFavorites(favorites: number[]): Promise<void> {
    await AsyncStorage.setItem(KEYS.FAVORITES, JSON.stringify(favorites));
  },

  async getFavorites(): Promise<number[]> {
    const val = await AsyncStorage.getItem(KEYS.FAVORITES);
    return val ? JSON.parse(val) : [];
  },

  async addToHistory(item: {
    id: number;
    title: string;
    img: string;
    time: string;
    category: string;
    status: 'Liked' | 'Skipped';
  }): Promise<void> {
    const existing = await this.getHistory();
    const updated = [item, ...existing].slice(0, 50); // keep last 50
    await AsyncStorage.setItem(KEYS.HISTORY, JSON.stringify(updated));
  },

  async getHistory(): Promise<
    Array<{
      id: number;
      title: string;
      img: string;
      time: string;
      category: string;
      status: 'Liked' | 'Skipped';
    }>
  > {
    const val = await AsyncStorage.getItem(KEYS.HISTORY);
    return val ? JSON.parse(val) : [];
  },
};
