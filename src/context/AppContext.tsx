import React, { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { AppState as RNAppState } from 'react-native';
import { storage } from '../storage';
import { consumeQuota, DAILY_FREE_QUOTA, getQuotaByPlan, getQuotaForToday, getResetQuotaForFree } from '../utils/quota';
import { backendApi } from '../api/backend';

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
  const getTodayKey = () => new Date().toISOString().slice(0, 10);

  const syncDailyQuota = useCallback(async (plan: 'free' | 'pro' | 'family') => {
    const todayKey = getTodayKey();
    const savedQuota = await storage.getRecommendationQuota();
    const nextQuota = getQuotaForToday(plan, todayKey, savedQuota);
    setRecommendationsLeft(nextQuota.left);
    await storage.setRecommendationQuota(nextQuota);
  }, []);

  useEffect(() => {
    async function load() {
      try {
        const [oc, cuisines, restrictions, favs, hist, plan] = await Promise.all([
          storage.getOnboardingComplete(),
          storage.getSelectedCuisines(),
          storage.getSelectedRestrictions(),
          storage.getFavorites(),
          storage.getHistory(),
          storage.getMembershipPlan(),
        ]);
        setOnboardingComplete(oc);
        setSelectedCuisines(cuisines);
        setSelectedRestrictions(restrictions);
        setFavorites(favs);
        setHistory(hist);
        let effectivePlan = plan;
        if (backendApi.isEnabled()) {
          const token = await backendApi.ensureToken();
          setBackendToken(token);
          if (token) {
            const [serverMembership, serverQuota] = await Promise.all([
              backendApi.getMembership(token),
              backendApi.getQuotaToday(token),
            ]);
            effectivePlan = serverMembership.plan;
            setMembershipPlanState(serverMembership.plan);
            setRecommendationsLeft(serverQuota.left);
            await storage.setRecommendationQuota(serverQuota);
          }
        }
        setMembershipPlanState(effectivePlan);
        await syncDailyQuota(effectivePlan);
      } catch (error) {
        console.warn('Failed to load app data:', error);
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [syncDailyQuota]);

  useEffect(() => {
    const sub = RNAppState.addEventListener('change', (status) => {
      if (status === 'active') {
        if (backendApi.isEnabled() && backendToken) {
          void Promise.all([
            backendApi.getMembership(backendToken),
            backendApi.getQuotaToday(backendToken),
          ]).then(([membership, quota]) => {
            setMembershipPlanState(membership.plan);
            setRecommendationsLeft(quota.left);
            void storage.setMembershipPlan(membership.plan);
            void storage.setRecommendationQuota(quota);
          }).catch((error) => {
            console.warn('Failed to sync membership/quota from backend:', error);
          });
          return;
        }
        void syncDailyQuota(membershipPlan);
      }
    });
    return () => sub.remove();
  }, [membershipPlan, syncDailyQuota, backendToken]);

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
      const updated = prev.includes(id) ? prev.filter((f) => f !== id) : [...prev, id];
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
    if (backendApi.isEnabled() && backendToken) {
      void backendApi.consumeQuota(backendToken).then((result) => {
        setRecommendationsLeft(result.left);
        void storage.setRecommendationQuota({ date: result.date, left: result.left });
      }).catch((error) => {
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
    setMembershipPlanState(plan);
    await syncDailyQuota(plan);
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
        completeOnboarding,
        setCuisines,
        setRestrictions,
        toggleFavorite,
        isFavorite,
        addToHistory,
        consumeRecommendation,
        resetApp,
        setMembershipPlan,
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
