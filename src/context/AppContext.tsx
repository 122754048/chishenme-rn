import React, { createContext, useContext, useEffect, useState, ReactNode, useCallback, useMemo } from 'react';
import { storage } from '../storage';

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
    category: string;
    status: 'Liked' | 'Skipped';
  }>;
  recommendationsLeft: number;
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
  refreshRecommendations: () => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [onboardingComplete, setOnboardingComplete] = useState(false);
  const [selectedCuisines, setSelectedCuisines] = useState<string[]>([]);
  const [selectedRestrictions, setSelectedRestrictions] = useState<string[]>([]);
  const [favorites, setFavorites] = useState<number[]>([]);
  const [history, setHistory] = useState<AppState['history']>([]);
  const [recommendationsLeft, setRecommendationsLeft] = useState(7);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    async function load() {
      try {
        const [oc, cuisines, restrictions, favs, hist] = await Promise.all([
          storage.getOnboardingComplete(),
          storage.getSelectedCuisines(),
          storage.getSelectedRestrictions(),
          storage.getFavorites(),
          storage.getHistory(),
        ]);
        if (!isMounted) return;
        setOnboardingComplete(oc);
        setSelectedCuisines(cuisines);
        setSelectedRestrictions(restrictions);
        setFavorites(favs);
        setHistory(hist);
      } catch (error) {
        console.warn('Failed to load app data:', error);
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }
    load();

    return () => {
      isMounted = false;
    };
  }, []);

  const completeOnboarding = useCallback(async () => {
    await storage.setOnboardingComplete(true);
    setOnboardingComplete(true);
  }, []);

  const setCuisines = useCallback(async (cuisines: string[]) => {
    await storage.setSelectedCuisines(cuisines);
    setSelectedCuisines(cuisines);
  }, []);

  const setRestrictions = useCallback(async (restrictions: string[]) => {
    await storage.setSelectedRestrictions(restrictions);
    setSelectedRestrictions(restrictions);
  }, []);

  const toggleFavorite = useCallback(async (id: number) => {
    const updated = favorites.includes(id) ? favorites.filter((f) => f !== id) : [...favorites, id];
    await storage.setFavorites(updated);
    setFavorites(updated);
  }, [favorites]);

  const isFavorite = useCallback((id: number) => favorites.includes(id), [favorites]);

  const addToHistory = useCallback(async (item: AppState['history'][0]) => {
    await storage.addToHistory(item);
    setHistory((prev) => [item, ...prev].slice(0, 50));
  }, []);

  const consumeRecommendation = useCallback(() => {
    setRecommendationsLeft((prev) => Math.max(0, prev - 1));
  }, []);

  const refreshRecommendations = useCallback(() => {
    setRecommendationsLeft(7);
  }, []);

  const value = useMemo(
    () => ({
      onboardingComplete,
      selectedCuisines,
      selectedRestrictions,
      favorites,
      history,
      recommendationsLeft,
      isLoading,
      completeOnboarding,
      setCuisines,
      setRestrictions,
      toggleFavorite,
      isFavorite,
      addToHistory,
      consumeRecommendation,
      refreshRecommendations,
    }),
    [
      onboardingComplete,
      selectedCuisines,
      selectedRestrictions,
      favorites,
      history,
      recommendationsLeft,
      isLoading,
      completeOnboarding,
      setCuisines,
      setRestrictions,
      toggleFavorite,
      isFavorite,
      addToHistory,
      consumeRecommendation,
      refreshRecommendations,
    ]
  );

  return (
    <AppContext.Provider value={value}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
