import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  ONBOARDING_COMPLETE: '@chishenme/onboarding_complete',
  SELECTED_CUISINES: '@chishenme/selected_cuisines',
  SELECTED_RESTRICTIONS: '@chishenme/selected_restrictions',
  FAVORITES: '@chishenme/favorites',
  HISTORY: '@chishenme/history',
  MEMBERSHIP_PLAN: '@chishenme/membership_plan',
  RECENT_SEARCHES: '@chishenme/recent_searches',
};

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
      if (val === null) return false;
      return JSON.parse(val) === true;
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
      return val ? JSON.parse(val) : [];
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
      return val ? JSON.parse(val) : [];
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
      return val ? JSON.parse(val) : [];
    } catch (error) {
      console.warn('Failed to read favorites:', error);
      return [];
    }
  },

  async addToHistory(item: {
    id: number;
    title: string;
    img: string;
    time: string;
    createdAt?: number;
    category: string;
    status: 'Liked' | 'Skipped';
  }): Promise<void> {
    try {
      const existing = await this.getHistory();
      const updated = [item, ...existing].slice(0, 50); // keep last 50
      await AsyncStorage.setItem(KEYS.HISTORY, JSON.stringify(updated));
    } catch (error) {
      console.warn('Failed to save history:', error);
    }
  },

  async getHistory(): Promise<
    Array<{
      id: number;
      title: string;
      img: string;
      time: string;
      createdAt?: number;
      category: string;
      status: 'Liked' | 'Skipped';
    }>
  > {
    try {
      const val = await AsyncStorage.getItem(KEYS.HISTORY);
      return val ? JSON.parse(val) : [];
    } catch (error) {
      console.warn('Failed to read history:', error);
      return [];
    }
  },

  async setMembershipPlan(plan: 'free' | 'pro' | 'family'): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.MEMBERSHIP_PLAN, plan);
    } catch (error) {
      console.warn('Failed to save membership plan:', error);
    }
  },

  async getMembershipPlan(): Promise<'free' | 'pro' | 'family'> {
    try {
      const val = await AsyncStorage.getItem(KEYS.MEMBERSHIP_PLAN);
      if (val === 'free' || val === 'pro' || val === 'family') return val;
      return 'free';
    } catch (error) {
      console.warn('Failed to read membership plan:', error);
      return 'free';
    }
  },

  async clearAll(): Promise<void> {
    try {
      await AsyncStorage.multiRemove(Object.values(KEYS));
    } catch (error) {
      console.warn('Failed to clear app data:', error);
    }
  },
};
