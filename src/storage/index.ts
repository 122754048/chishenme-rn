import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  ONBOARDING_COMPLETE: '@teller/onboarding_complete',
  SELECTED_CUISINES: '@teller/selected_cuisines',
  SELECTED_RESTRICTIONS: '@teller/selected_restrictions',
  FAVORITES: '@teller/favorites',
  HISTORY: '@teller/history',
  MEMBERSHIP_PLAN: '@teller/membership_plan',
  RECENT_SEARCHES: '@teller/recent_searches',
  RECOMMENDATION_QUOTA: '@teller/recommendation_quota',
  PAYMENT_EVENTS: '@teller/payment_events',
  BACKEND_TOKEN: '@teller/backend_token',
  BACKEND_USER_ID: '@teller/backend_user_id',
  LOCATION_CONTEXT: '@teller/location_context',
  SAVED_AREAS: '@teller/saved_areas',
  DECISION_SETTINGS: '@teller/decision_settings',
  DEVELOPER_MEMBERSHIP_OVERRIDE: '@teller/developer_membership_override',
};

const LEGACY_PREFIX = '@chishenme/';
const CURRENT_PREFIX = '@teller/';
let _migrated = false;

/** Migrate data from legacy @chishenme/ keys to @teller/ keys (one-time). */
async function migrateFromLegacyKeys(): Promise<void> {
  if (_migrated) return;
  _migrated = true;
  try {
    const allKeys = await AsyncStorage.getAllKeys();
    const legacyKeys = allKeys.filter((k) => k.startsWith(LEGACY_PREFIX));
    if (legacyKeys.length === 0) return;

    const pairs = await AsyncStorage.multiGet(legacyKeys);
    const writes: Array<[string, string]> = [];
    for (const [oldKey, value] of pairs) {
      if (value == null) continue;
      const newKey = CURRENT_PREFIX + oldKey.slice(LEGACY_PREFIX.length);
      writes.push([newKey, value]);
    }
    if (writes.length > 0) {
      await AsyncStorage.multiSet(writes);
      await AsyncStorage.multiRemove(legacyKeys);
    }
  } catch (error) {
    console.warn('[Teller]', 'Storage migration from legacy keys failed:', error);
  }
}

/** Must be called once at app startup before any storage reads. */
export async function ensureStorageMigrated(): Promise<void> {
  await migrateFromLegacyKeys();
}

export interface PaymentEvent {
  id: string;
  plan: 'pro' | 'family';
  flow: 'pay' | 'trial';
  status: 'processing' | 'success' | 'failed';
  createdAt: number;
  reason?: string;
}

export interface StoredLocationContext {
  mode: 'live' | 'manual';
  label: string;
  updatedAt: number;
  latitude?: number;
  longitude?: number;
  query?: string;
}

export interface SavedAreas {
  home?: {
    label: string;
    query: string;
    latitude?: number;
    longitude?: number;
  };
  work?: {
    label: string;
    query: string;
    latitude?: number;
    longitude?: number;
  };
}

export interface DecisionSettings {
  keepItFresh: boolean;
  forTwo: boolean;
}

export interface DeveloperMembershipOverride {
  plan: 'pro' | 'family';
  expiresAt: number;
}

const DEFAULT_DECISION_SETTINGS: DecisionSettings = {
  keepItFresh: false,
  forTwo: false,
};

export const storage = {
  async setOnboardingComplete(value: boolean): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.ONBOARDING_COMPLETE, JSON.stringify(value));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save onboarding status:', error);
    }
  },

  async getOnboardingComplete(): Promise<boolean> {
    try {
      const val = await AsyncStorage.getItem(KEYS.ONBOARDING_COMPLETE);
      if (val === null) return false;
      return JSON.parse(val) === true;
    } catch (error) {
      console.warn('[Teller]', 'Failed to read onboarding status:', error);
      return false;
    }
  },

  async setSelectedCuisines(cuisines: string[]): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.SELECTED_CUISINES, JSON.stringify(cuisines));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save cuisines:', error);
    }
  },

  async getSelectedCuisines(): Promise<string[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.SELECTED_CUISINES);
      return val ? JSON.parse(val) : [];
    } catch (error) {
      console.warn('[Teller]', 'Failed to read cuisines:', error);
      return [];
    }
  },

  async setSelectedRestrictions(restrictions: string[]): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.SELECTED_RESTRICTIONS, JSON.stringify(restrictions));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save restrictions:', error);
    }
  },

  async getSelectedRestrictions(): Promise<string[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.SELECTED_RESTRICTIONS);
      return val ? JSON.parse(val) : [];
    } catch (error) {
      console.warn('[Teller]', 'Failed to read restrictions:', error);
      return [];
    }
  },

  async setFavorites(favorites: number[]): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.FAVORITES, JSON.stringify(favorites));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save favorites:', error);
    }
  },

  async getFavorites(): Promise<number[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.FAVORITES);
      return val ? JSON.parse(val) : [];
    } catch (error) {
      console.warn('[Teller]', 'Failed to read favorites:', error);
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
      console.warn('[Teller]', 'Failed to save history:', error);
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
      console.warn('[Teller]', 'Failed to read history:', error);
      return [];
    }
  },

  async setMembershipPlan(plan: 'free' | 'pro' | 'family'): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.MEMBERSHIP_PLAN, plan);
    } catch (error) {
      console.warn('[Teller]', 'Failed to save membership plan:', error);
    }
  },

  async setRecentSearches(searches: string[]): Promise<void> {
    try {
      const normalized = searches
        .map((item) => item.trim())
        .filter((item) => item.length > 0)
        .filter((item, index, arr) => arr.indexOf(item) === index)
        .slice(0, 10);
      await AsyncStorage.setItem(KEYS.RECENT_SEARCHES, JSON.stringify(normalized));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save recent searches:', error);
    }
  },

  async getRecentSearches(): Promise<string[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.RECENT_SEARCHES);
      const parsed = val ? JSON.parse(val) : [];
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((item) => typeof item === 'string')
        .map((item) => item.trim())
        .filter((item) => item.length > 0)
        .filter((item, index, arr) => arr.indexOf(item) === index)
        .slice(0, 10);
    } catch (error) {
      console.warn('[Teller]', 'Failed to read recent searches:', error);
      return [];
    }
  },

  async getMembershipPlan(): Promise<'free' | 'pro' | 'family'> {
    try {
      const val = await AsyncStorage.getItem(KEYS.MEMBERSHIP_PLAN);
      if (val === 'free' || val === 'pro' || val === 'family') return val;
      return 'free';
    } catch (error) {
      console.warn('[Teller]', 'Failed to read membership plan:', error);
      return 'free';
    }
  },

  async setDeveloperMembershipOverride(override: DeveloperMembershipOverride): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.DEVELOPER_MEMBERSHIP_OVERRIDE, JSON.stringify(override));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save developer membership override:', error);
    }
  },

  async getDeveloperMembershipOverride(): Promise<DeveloperMembershipOverride | null> {
    try {
      const val = await AsyncStorage.getItem(KEYS.DEVELOPER_MEMBERSHIP_OVERRIDE);
      if (!val) return null;
      const parsed = JSON.parse(val);
      if ((parsed?.plan === 'pro' || parsed?.plan === 'family') && typeof parsed?.expiresAt === 'number') {
        return parsed;
      }
      return null;
    } catch (error) {
      console.warn('[Teller]', 'Failed to read developer membership override:', error);
      return null;
    }
  },

  async clearDeveloperMembershipOverride(): Promise<void> {
    try {
      await AsyncStorage.removeItem(KEYS.DEVELOPER_MEMBERSHIP_OVERRIDE);
    } catch (error) {
      console.warn('[Teller]', 'Failed to clear developer membership override:', error);
    }
  },

  async setLocationContext(context: StoredLocationContext | null): Promise<void> {
    try {
      if (!context) {
        await AsyncStorage.removeItem(KEYS.LOCATION_CONTEXT);
        return;
      }
      await AsyncStorage.setItem(KEYS.LOCATION_CONTEXT, JSON.stringify(context));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save location context:', error);
    }
  },

  async getLocationContext(): Promise<StoredLocationContext | null> {
    try {
      const val = await AsyncStorage.getItem(KEYS.LOCATION_CONTEXT);
      if (!val) return null;
      const parsed = JSON.parse(val);
      if (
        (parsed?.mode === 'live' || parsed?.mode === 'manual') &&
        typeof parsed?.label === 'string' &&
        typeof parsed?.updatedAt === 'number'
      ) {
        return parsed;
      }
      return null;
    } catch (error) {
      console.warn('[Teller]', 'Failed to read location context:', error);
      return null;
    }
  },

  async setSavedAreas(savedAreas: SavedAreas): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.SAVED_AREAS, JSON.stringify(savedAreas));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save areas:', error);
    }
  },

  async getSavedAreas(): Promise<SavedAreas> {
    try {
      const val = await AsyncStorage.getItem(KEYS.SAVED_AREAS);
      const parsed = val ? JSON.parse(val) : {};
      return typeof parsed === 'object' && parsed ? parsed : {};
    } catch (error) {
      console.warn('[Teller]', 'Failed to read saved areas:', error);
      return {};
    }
  },

  async setDecisionSettings(settings: DecisionSettings): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.DECISION_SETTINGS, JSON.stringify(settings));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save decision settings:', error);
    }
  },

  async getDecisionSettings(): Promise<DecisionSettings> {
    try {
      const val = await AsyncStorage.getItem(KEYS.DECISION_SETTINGS);
      if (!val) return DEFAULT_DECISION_SETTINGS;
      const parsed = JSON.parse(val);
      return {
        keepItFresh: parsed?.keepItFresh === true,
        forTwo: parsed?.forTwo === true,
      };
    } catch (error) {
      console.warn('[Teller]', 'Failed to read decision settings:', error);
      return DEFAULT_DECISION_SETTINGS;
    }
  },

  async setRecommendationQuota(payload: { date: string; left: number }): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.RECOMMENDATION_QUOTA, JSON.stringify(payload));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save recommendation quota:', error);
    }
  },

  async getRecommendationQuota(): Promise<{ date: string; left: number } | null> {
    try {
      const val = await AsyncStorage.getItem(KEYS.RECOMMENDATION_QUOTA);
      if (!val) return null;
      const parsed = JSON.parse(val);
      if (typeof parsed?.date === 'string' && typeof parsed?.left === 'number') {
        return parsed;
      }
      return null;
    } catch (error) {
      console.warn('[Teller]', 'Failed to read recommendation quota:', error);
      return null;
    }
  },

  async appendPaymentEvent(event: PaymentEvent): Promise<void> {
    try {
      const existing = await this.getPaymentEvents();
      const updated = [event, ...existing].slice(0, 30);
      await AsyncStorage.setItem(KEYS.PAYMENT_EVENTS, JSON.stringify(updated));
    } catch (error) {
      console.warn('[Teller]', 'Failed to save payment event:', error);
    }
  },

  async getPaymentEvents(): Promise<PaymentEvent[]> {
    try {
      const val = await AsyncStorage.getItem(KEYS.PAYMENT_EVENTS);
      if (!val) return [];
      const parsed = JSON.parse(val);
      if (!Array.isArray(parsed)) return [];
      return parsed;
    } catch (error) {
      console.warn('[Teller]', 'Failed to read payment events:', error);
      return [];
    }
  },

  async setBackendToken(token: string): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.BACKEND_TOKEN, token);
    } catch (error) {
      console.warn('[Teller]', 'Failed to save backend token:', error);
    }
  },

  async getBackendToken(): Promise<string | null> {
    try {
      return await AsyncStorage.getItem(KEYS.BACKEND_TOKEN);
    } catch (error) {
      console.warn('[Teller]', 'Failed to read backend token:', error);
      return null;
    }
  },

  async setBackendUserId(userId: string): Promise<void> {
    try {
      await AsyncStorage.setItem(KEYS.BACKEND_USER_ID, userId);
    } catch (error) {
      console.warn('[Teller]', 'Failed to save backend user id:', error);
    }
  },

  async getBackendUserId(): Promise<string | null> {
    try {
      return await AsyncStorage.getItem(KEYS.BACKEND_USER_ID);
    } catch (error) {
      console.warn('[Teller]', 'Failed to read backend user id:', error);
      return null;
    }
  },

  async ensureBackendUserId(): Promise<string> {
    const cached = await this.getBackendUserId();
    if (cached) return cached;
    const created = `rn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    await this.setBackendUserId(created);
    return created;
  },

  async clearAll(): Promise<void> {
    try {
      await AsyncStorage.multiRemove(Object.values(KEYS));
    } catch (error) {
      console.warn('[Teller]', 'Failed to clear app data:', error);
    }
  },
};
