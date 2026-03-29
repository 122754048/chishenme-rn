import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
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
  refreshRecommendations: () => void;
  consumeRecommendation: () => void;
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
    async function load() {
      try {
        const [oc, cuisines, restrictions, favs, hist] = await Promise.all([
          storage.getOnboardingComplete(),
          storage.getSelectedCuisines(),
          storage.getSelectedRestrictions(),
          storage.getFavorites(),
          storage.getHistory(),
        ]);
        setOnboardingComplete(oc);
        setSelectedCuisines(cuisines);
        setSelectedRestrictions(restrictions);
        setFavorites(favs);
        setHistory(hist);
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, []);

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
    const updated = favorites.includes(id)
      ? favorites.filter((f) => f !== id)
      : [...favorites, id];
    await storage.setFavorites(updated);
    setFavorites(updated);
  };

  const isFavorite = (id: number) => favorites.includes(id);

  const addToHistory = async (item: AppState['history'][0]) => {
    await storage.addToHistory(item);
    setHistory((prev) => [item, ...prev].slice(0, 50));
  };

  const refreshRecommendations = () => {
    setRecommendationsLeft(7);
  };

  const consumeRecommendation = () => {
    setRecommendationsLeft((prev) => Math.max(0, prev - 1));
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
        isLoading,
        completeOnboarding,
        setCuisines,
        setRestrictions,
        toggleFavorite,
        isFavorite,
        addToHistory,
        refreshRecommendations,
        consumeRecommendation,
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
