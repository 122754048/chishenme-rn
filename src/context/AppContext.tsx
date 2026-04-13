import React, { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { AppState as RNAppState } from 'react-native';
import { backendApi } from '../api/backend';
import { subscriptionService } from '../services/subscriptions';
import { storage, type DecisionSettings, type SavedAreas } from '../storage';
import { DAILY_FREE_QUOTA, consumeQuota, getQuotaForToday, getResetQuotaForFree } from '../utils/quota';
import type { LocationContext, SavedAreaContext, SavedAreaKey } from '../utils/location';

function normalizeStoredLocationContext(context: Awaited<ReturnType<typeof storage.getLocationContext>>): LocationContext | null {
  if (!context) return null;
  if (context.mode === 'live' && typeof context.latitude === 'number' && typeof context.longitude === 'number') {
    return {
      mode: 'live',
      label: context.label,
      latitude: context.latitude,
      longitude: context.longitude,
      updatedAt: context.updatedAt,
    };
  }
  if (context.mode === 'manual' && typeof context.query === 'string') {
    return {
      mode: 'manual',
      label: context.label,
      query: context.query,
      latitude: context.latitude,
      longitude: context.longitude,
      updatedAt: context.updatedAt,
    };
  }
  return null;
}

interface AppState {
  onboardingComplete: boolean;
  selectedCuisines: string[];
  selectedRestrictions: string[];
  favorites: number[];
  history: Array<{
    id: number;
    title: string;
    img: string;
    time: string;
    createdAt?: number;
    category: string;
    status: 'Liked' | 'Skipped';
  }>;
  recommendationsLeft: number;
  membershipPlan: 'free' | 'pro' | 'family';
  isLoading: boolean;
  backendToken: string | null;
  locationContext: LocationContext | null;
  savedAreas: SavedAreas;
  decisionSettings: DecisionSettings;
}

interface AppContextType extends AppState {
  completeOnboarding: () => Promise<void>;
  setCuisines: (cuisines: string[]) => Promise<void>;
  setRestrictions: (restrictions: string[]) => Promise<void>;
  toggleFavorite: (id: number) => Promise<void>;
  isFavorite: (id: number) => boolean;
  addToHistory: (item: AppState['history'][0]) => Promise<void>;
  consumeRecommendation: () => void;
  resetApp: () => Promise<void>;
  setMembershipPlan: (plan: 'free' | 'pro' | 'family') => Promise<void>;
  activateDeveloperMembership: (plan: 'pro' | 'family', durationMinutes?: number) => Promise<void>;
  clearDeveloperMembershipOverride: () => Promise<void>;
  developerOverrideExpiresAt: number | null;
  setLocationSelection: (context: LocationContext | null) => Promise<void>;
  saveAreaPreset: (key: SavedAreaKey, area: SavedAreaContext | null) => Promise<void>;
  updateDecisionSettings: (patch: Partial<DecisionSettings>) => Promise<void>;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [onboardingComplete, setOnboardingComplete] = useState(false);
  const [selectedCuisines, setSelectedCuisines] = useState<string[]>([]);
  const [selectedRestrictions, setSelectedRestrictions] = useState<string[]>([]);
  const [favorites, setFavorites] = useState<number[]>([]);
  const [history, setHistory] = useState<AppState['history']>([]);
  const [recommendationsLeft, setRecommendationsLeft] = useState(DAILY_FREE_QUOTA);
  const [membershipPlan, setMembershipPlanState] = useState<'free' | 'pro' | 'family'>('free');
  const [isLoading, setIsLoading] = useState(true);
  const [backendToken, setBackendToken] = useState<string | null>(null);
  const [developerOverrideExpiresAt, setDeveloperOverrideExpiresAt] = useState<number | null>(null);
  const [locationContext, setLocationContextState] = useState<LocationContext | null>(null);
  const [savedAreas, setSavedAreasState] = useState<SavedAreas>({});
  const [decisionSettings, setDecisionSettingsState] = useState<DecisionSettings>({
    keepItFresh: false,
    forTwo: false,
  });

  const getTodayKey = () => new Date().toISOString().slice(0, 10);

  const syncDailyQuota = useCallback(async (plan: 'free' | 'pro' | 'family') => {
    const todayKey = getTodayKey();
    const savedQuota = await storage.getRecommendationQuota();
    const nextQuota = getQuotaForToday(plan, todayKey, savedQuota);
    setRecommendationsLeft(nextQuota.left);
    await storage.setRecommendationQuota(nextQuota);
  }, []);

  const getActiveDeveloperOverride = useCallback(async () => {
    const override = await storage.getDeveloperMembershipOverride();
    if (!override) return null;
    if (override.expiresAt <= Date.now()) {
      await storage.clearDeveloperMembershipOverride();
      return null;
    }
    return override;
  }, []);

  useEffect(() => {
    async function load() {
      try {
        const [oc, cuisines, restrictions, favs, hist, plan, storedLocation, storedAreas, storedDecisionSettings] = await Promise.all([
          storage.getOnboardingComplete(),
          storage.getSelectedCuisines(),
          storage.getSelectedRestrictions(),
          storage.getFavorites(),
          storage.getHistory(),
          storage.getMembershipPlan(),
          storage.getLocationContext(),
          storage.getSavedAreas(),
          storage.getDecisionSettings(),
        ]);

        setOnboardingComplete(oc);
        setSelectedCuisines(cuisines);
        setSelectedRestrictions(restrictions);
        setFavorites(favs);
        setHistory(hist);
        setLocationContextState(normalizeStoredLocationContext(storedLocation));
        setSavedAreasState(storedAreas);
        setDecisionSettingsState(storedDecisionSettings);

        let effectivePlan = plan;
        let token: string | null = null;

        if (backendApi.isEnabled()) {
          token = await backendApi.ensureToken();
          setBackendToken(token);
        }

        const revenueCatUserId = await storage.ensureBackendUserId();
        const iapPlan = await subscriptionService.syncCustomerPlan(revenueCatUserId);

        if (iapPlan !== null) {
          effectivePlan = iapPlan;
        } else if (token) {
          const [serverMembership, serverQuota] = await Promise.all([
            backendApi.getMembership(token),
            backendApi.getQuotaToday(token),
          ]);
          effectivePlan = serverMembership.plan;
          setRecommendationsLeft(serverQuota.left);
          await storage.setRecommendationQuota(serverQuota);
        }

        const developerOverride = await getActiveDeveloperOverride();
        const resolvedPlan = developerOverride?.plan ?? effectivePlan;

        setDeveloperOverrideExpiresAt(developerOverride?.expiresAt ?? null);
        setMembershipPlanState(resolvedPlan);
        await syncDailyQuota(resolvedPlan);
      } catch (error) {
        console.warn('Failed to load app data:', error);
      } finally {
        setIsLoading(false);
      }
    }

    void load();
  }, [syncDailyQuota]);

  useEffect(() => {
    const sub = RNAppState.addEventListener('change', (status) => {
      if (status !== 'active') return;

      void (async () => {
        const userId = await storage.ensureBackendUserId();
        const iapPlan = await subscriptionService.syncCustomerPlan(userId);
        const developerOverride = await getActiveDeveloperOverride();

        if (iapPlan !== null) {
          const resolvedPlan = developerOverride?.plan ?? iapPlan;
          setDeveloperOverrideExpiresAt(developerOverride?.expiresAt ?? null);
          setMembershipPlanState(resolvedPlan);
          await storage.setMembershipPlan(iapPlan);
          await syncDailyQuota(resolvedPlan);
          return;
        }

        if (backendApi.isEnabled() && backendToken) {
          const [membership, quota] = await Promise.all([
            backendApi.getMembership(backendToken),
            backendApi.getQuotaToday(backendToken),
          ]);
          const resolvedPlan = developerOverride?.plan ?? membership.plan;
          setDeveloperOverrideExpiresAt(developerOverride?.expiresAt ?? null);
          setMembershipPlanState(resolvedPlan);
          setRecommendationsLeft(quota.left);
          await storage.setMembershipPlan(membership.plan);
          await storage.setRecommendationQuota(quota);
          await syncDailyQuota(resolvedPlan);
          return;
        }

        const resolvedPlan = developerOverride?.plan ?? membershipPlan;
        setDeveloperOverrideExpiresAt(developerOverride?.expiresAt ?? null);
        setMembershipPlanState(resolvedPlan);
        await syncDailyQuota(resolvedPlan);
      })().catch((error) => {
        console.warn('Failed to sync active app membership/quota:', error);
      });
    });

    return () => sub.remove();
  }, [backendToken, getActiveDeveloperOverride, membershipPlan, syncDailyQuota]);

  const completeOnboarding = async () => {
    await storage.setOnboardingComplete(true);
    setOnboardingComplete(true);
  };

  const setCuisines = async (cuisines: string[]) => {
    await storage.setSelectedCuisines(cuisines);
    setSelectedCuisines(cuisines);
  };

  const setRestrictions = async (restrictions: string[]) => {
    await storage.setSelectedRestrictions(restrictions);
    setSelectedRestrictions(restrictions);
  };

  const toggleFavorite = async (id: number) => {
    setFavorites((prev) => {
      const updated = prev.includes(id) ? prev.filter((value) => value !== id) : [...prev, id];
      void storage.setFavorites(updated);
      return updated;
    });
  };

  const isFavorite = (id: number) => favorites.includes(id);

  const addToHistory = async (item: AppState['history'][0]) => {
    await storage.addToHistory(item);
    setHistory((prev) => [item, ...prev].slice(0, 50));
  };

  const consumeRecommendation = () => {
    if (membershipPlan !== 'free') {
      void syncDailyQuota(membershipPlan);
      return;
    }

    if (backendApi.isEnabled() && backendToken) {
      void backendApi
        .consumeQuota(backendToken)
        .then((result) => {
          setRecommendationsLeft(result.left);
          void storage.setRecommendationQuota({ date: result.date, left: result.left });
        })
        .catch((error) => {
          console.warn('Failed to consume quota from backend:', error);
        });
      return;
    }

    const todayKey = getTodayKey();
    setRecommendationsLeft((prev) => {
      const next = consumeQuota(prev);
      void storage.setRecommendationQuota({ date: todayKey, left: next });
      return next;
    });
  };

  const setMembershipPlan = async (plan: 'free' | 'pro' | 'family') => {
    await storage.setMembershipPlan(plan);
    const developerOverride = await getActiveDeveloperOverride();
    const resolvedPlan = developerOverride?.plan ?? plan;
    setDeveloperOverrideExpiresAt(developerOverride?.expiresAt ?? null);
    setMembershipPlanState(resolvedPlan);
    await syncDailyQuota(resolvedPlan);
  };

  const activateDeveloperMembership = async (plan: 'pro' | 'family', durationMinutes = 10) => {
    const expiresAt = Date.now() + durationMinutes * 60 * 1000;
    await storage.setDeveloperMembershipOverride({ plan, expiresAt });
    setDeveloperOverrideExpiresAt(expiresAt);
    setMembershipPlanState(plan);
    await syncDailyQuota(plan);
  };

  const clearDeveloperMembershipOverride = async () => {
    await storage.clearDeveloperMembershipOverride();
    setDeveloperOverrideExpiresAt(null);

    const storedPlan = await storage.getMembershipPlan();
    setMembershipPlanState(storedPlan);
    await syncDailyQuota(storedPlan);
  };

  const setLocationSelection = async (context: LocationContext | null) => {
    await storage.setLocationContext(context);
    setLocationContextState(context);
  };

  const saveAreaPreset = async (key: SavedAreaKey, area: SavedAreaContext | null) => {
    const nextAreas = {
      ...savedAreas,
      [key]: area ?? undefined,
    };
    await storage.setSavedAreas(nextAreas);
    setSavedAreasState(nextAreas);
  };

  const updateDecisionSettings = async (patch: Partial<DecisionSettings>) => {
    setDecisionSettingsState((prev) => {
      const next = { ...prev, ...patch };
      void storage.setDecisionSettings(next);
      return next;
    });
  };

  const resetApp = async () => {
    const todayKey = getTodayKey();
    const existingQuota = await storage.getRecommendationQuota();
    const preservedFreeQuota = getResetQuotaForFree(todayKey, existingQuota);

    await storage.clearAll();

    setOnboardingComplete(false);
    setSelectedCuisines([]);
    setSelectedRestrictions([]);
    setFavorites([]);
    setHistory([]);
    setRecommendationsLeft(preservedFreeQuota.left);
    setMembershipPlanState('free');
    setBackendToken(null);
    setLocationContextState(null);
    setSavedAreasState({});
    setDecisionSettingsState({ keepItFresh: false, forTwo: false });

    void storage.setRecommendationQuota(preservedFreeQuota);
  };

  return (
    <AppContext.Provider
      value={{
        onboardingComplete,
        selectedCuisines,
        selectedRestrictions,
        favorites,
        history,
        recommendationsLeft,
        membershipPlan,
        isLoading,
        backendToken,
        developerOverrideExpiresAt,
        locationContext,
        savedAreas,
        decisionSettings,
        completeOnboarding,
        setCuisines,
        setRestrictions,
        toggleFavorite,
        isFavorite,
        addToHistory,
        consumeRecommendation,
        resetApp,
        setMembershipPlan,
        activateDeveloperMembership,
        clearDeveloperMembershipOverride,
        setLocationSelection,
        saveAreaPreset,
        updateDecisionSettings,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
