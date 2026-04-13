import { brand, type HomeFilter } from '../config/brand';
import { SWIPE_CARDS, type SwipeCardData, type BudgetBand, type GroupFit, type MealType } from '../data/mockData';
import type { NearbyRestaurant } from '../api/backend';

export interface RecommendationInput {
  selectedCuisines: string[];
  selectedRestrictions: string[];
  preferredMealType?: MealType | null;
  preferredBudgetBand?: BudgetBand | null;
  nearbyRestaurants?: NearbyRestaurant[];
  activeFilter?: HomeFilter | null;
  history?: RecommendationHistoryEntry[];
  keepItFresh?: boolean;
  forTwo?: boolean;
}

export interface RecommendationResult {
  dish: SwipeCardData;
  score: number;
  reasons: string[];
  nearbyRestaurant?: NearbyRestaurant | null;
}

export interface RecommendationHistoryEntry {
  id: number;
  category: string;
  status: 'Liked' | 'Skipped';
  createdAt?: number;
}

function isFromToday(entry: RecommendationHistoryEntry) {
  if (!entry.createdAt) return false;
  return new Date(entry.createdAt).toDateString() === new Date().toDateString();
}

const CUISINE_LABELS: Record<string, string> = {
  Sichuan: 'bold Chinese',
  Cantonese: 'Cantonese',
  Hunan: 'spicy comfort food',
  JapaneseKorean: 'Japanese and Korean food',
  Western: 'modern Western food',
  SoutheastAsian: 'Southeast Asian food',
  Desserts: 'desserts',
  BBQ: 'barbecue',
  Northwestern: 'dumplings and noodles',
  JiangsuZhejiang: 'lighter Chinese dishes',
};

const RESTRICTION_LABELS: Record<string, string> = {
  pork: 'pork',
  beef: 'beef',
  seafood: 'seafood',
  spicy: 'spicy dishes',
  eggs: 'eggs',
  dairy: 'dairy',
  coriander: 'cilantro',
  nuts: 'nuts',
};

const BUDGET_SCORES: Record<BudgetBand, number> = { '$': 1, '$$': 2, '$$$': 3 };

function scoreCuisine(dish: SwipeCardData, selectedCuisines: string[]) {
  if (selectedCuisines.length === 0) return 1;
  return selectedCuisines.includes(dish.cuisineId) ? 10 : -2;
}

function scoreRestrictions(dish: SwipeCardData, selectedRestrictions: string[]) {
  const conflicts = selectedRestrictions.filter((item) => dish.restrictionConflicts.includes(item));
  return conflicts.length > 0 ? -25 * conflicts.length : 5;
}

function scoreBudget(dish: SwipeCardData, preferredBudgetBand?: BudgetBand | null) {
  if (!preferredBudgetBand) return 0;
  return Math.abs(BUDGET_SCORES[dish.budgetBand] - BUDGET_SCORES[preferredBudgetBand]) === 0 ? 4 : -2;
}

function scoreMealType(dish: SwipeCardData, preferredMealType?: MealType | null) {
  if (!preferredMealType) return 0;
  return dish.mealType === preferredMealType ? 6 : -1;
}

function scoreActiveFilter(dish: SwipeCardData, activeFilter?: HomeFilter | null) {
  if (!activeFilter) return 0;
  switch (activeFilter) {
    case 'Quick':
      return dish.speedScore >= 4 ? 8 : -1;
    case 'Comfort':
      return dish.comfortScore >= 4 ? 8 : -1;
    case 'Healthy':
      return dish.healthTags.length > 0 ? 8 : -2;
    case 'Budget':
      return dish.budgetBand === '$' ? 8 : dish.budgetBand === '$$' ? 2 : -4;
    case 'Treat':
      return dish.premiumScore >= 4 ? 8 : 0;
    default:
      return 0;
  }
}

function scoreDecisionMode(groupFit: GroupFit, forTwo?: boolean) {
  if (!forTwo) {
    return groupFit === 'solo' ? 3 : groupFit === 'pair' ? 1 : 0;
  }

  if (groupFit === 'pair') return 8;
  if (groupFit === 'group' || groupFit === 'family') return 4;
  return -3;
}

function scoreFreshness(dish: SwipeCardData, history?: RecommendationHistoryEntry[], keepItFresh?: boolean) {
  if (!keepItFresh || !history || history.length === 0) return 0;

  const recentHistory = history.slice(0, 8);
  let penalty = 0;

  recentHistory.forEach((entry, index) => {
    const weight = Math.max(1, 5 - index);
    if (entry.id === dish.id) {
      penalty += weight * 5;
      return;
    }
    if (entry.category.trim().toLowerCase() === dish.restaurantName.trim().toLowerCase()) {
      penalty += weight * 3;
      return;
    }

    const historyDish = SWIPE_CARDS.find((item) => item.id === entry.id);
    if (historyDish?.cuisineId === dish.cuisineId) {
      penalty += weight;
    }
  });

  return -penalty;
}

function scoreTodayFeedback(dish: SwipeCardData, history?: RecommendationHistoryEntry[]) {
  if (!history || history.length === 0) return 0;

  const todaysFeedback = history.filter(isFromToday).slice(0, 20);
  let adjustment = 0;

  todaysFeedback.forEach((entry) => {
    if (entry.id === dish.id) {
      adjustment += entry.status === 'Skipped' ? -40 : -14;
      return;
    }

    if (entry.category.trim().toLowerCase() === dish.restaurantName.trim().toLowerCase()) {
      adjustment += entry.status === 'Skipped' ? -10 : -2;
    }
  });

  return adjustment;
}

function scoreNearbyRestaurant(dish: SwipeCardData, nearbyRestaurants?: NearbyRestaurant[]) {
  if (!nearbyRestaurants || nearbyRestaurants.length === 0) return 0;
  const exactMatch = nearbyRestaurants.find(
    (restaurant) => restaurant.name.trim().toLowerCase() === dish.restaurantName.trim().toLowerCase()
  );
  if (exactMatch) {
    return 12;
  }
  return 1;
}

function pickNearbyRestaurant(dish: SwipeCardData, nearbyRestaurants?: NearbyRestaurant[]) {
  if (!nearbyRestaurants || nearbyRestaurants.length === 0) return null;
  return (
    nearbyRestaurants.find(
      (restaurant) => restaurant.name.trim().toLowerCase() === dish.restaurantName.trim().toLowerCase()
    ) ?? nearbyRestaurants[0]
  );
}

function buildReasons(dish: SwipeCardData, input: RecommendationInput, nearbyRestaurant?: NearbyRestaurant | null): string[] {
  const reasons: string[] = [];
  if (input.selectedCuisines.includes(dish.cuisineId)) {
    reasons.push(`Matches your usual ${CUISINE_LABELS[dish.cuisineId] ?? dish.cuisineLabel} picks.`);
  }
  if (input.selectedRestrictions.length > 0) {
    const conflicts = input.selectedRestrictions.filter((item) => dish.restrictionConflicts.includes(item));
    if (conflicts.length === 0) {
      reasons.push(
        `Avoids ${input.selectedRestrictions.map((item) => RESTRICTION_LABELS[item] ?? item).join(', ')}.`
      );
    }
  }
  if (input.preferredMealType && dish.mealType === input.preferredMealType) {
    reasons.push(`Fits a ${input.preferredMealType.toLowerCase()} decision right now.`);
  } else if (dish.fitMoments.length > 0) {
    reasons.push(dish.fitMoments[0]);
  }
  if (nearbyRestaurant?.rating) {
    reasons.push(`${nearbyRestaurant.rating.toFixed(1)} stars nearby with solid review volume.`);
  } else if (dish.healthTags.length > 0) {
    reasons.push(`${dish.healthTags[0]} and easier to feel good about after eating.`);
  }
  if (input.keepItFresh) {
    reasons.push('Downranked your recent repeats to keep this week feeling less samey.');
  }
  if (input.forTwo && dish.groupFit !== 'solo') {
    reasons.push('A better call when two people need an easy yes.');
  }
  return reasons.slice(0, 3);
}

function scoreDish(dish: SwipeCardData, input: RecommendationInput): RecommendationResult {
  const nearbyRestaurant = pickNearbyRestaurant(dish, input.nearbyRestaurants);
  const score =
    scoreCuisine(dish, input.selectedCuisines) +
    scoreRestrictions(dish, input.selectedRestrictions) +
    scoreMealType(dish, input.preferredMealType) +
    scoreBudget(dish, input.preferredBudgetBand) +
    scoreActiveFilter(dish, input.activeFilter) +
    scoreDecisionMode(dish.groupFit, input.forTwo) +
    scoreFreshness(dish, input.history, input.keepItFresh) +
    scoreTodayFeedback(dish, input.history) +
    scoreNearbyRestaurant(dish, input.nearbyRestaurants) +
    dish.speedScore +
    dish.comfortScore +
    dish.premiumScore;

  return {
    dish,
    score,
    reasons: buildReasons(dish, input, nearbyRestaurant),
    nearbyRestaurant,
  };
}

export function getRecommendedDishes(input: RecommendationInput): RecommendationResult[] {
  const todaysHiddenIds = new Set((input.history ?? []).filter(isFromToday).map((entry) => entry.id));

  return SWIPE_CARDS
    .filter((dish) => !todaysHiddenIds.has(dish.id))
    .map((dish) => scoreDish(dish, input))
    .filter((item) => item.score > -20)
    .sort((a, b) => b.score - a.score);
}

export function getRecommendationById(id: number, input: RecommendationInput): RecommendationResult | null {
  return getRecommendedDishes(input).find((item) => item.dish.id === id) ?? null;
}

export function getRelatedRecommendations(id: number, input: RecommendationInput, limit = 3): RecommendationResult[] {
  const primary = SWIPE_CARDS.find((item) => item.id === id);
  if (!primary) return [];
  return getRecommendedDishes(input)
    .filter((item) => item.dish.id !== id)
    .filter(
      (item) =>
        item.dish.restaurantId === primary.restaurantId ||
        item.dish.cuisineId === primary.cuisineId ||
        item.dish.mealType === primary.mealType
    )
    .slice(0, limit);
}

export function buildDecisionSnapshot(dish: SwipeCardData) {
  return [
    { label: 'Best for', value: dish.mealType },
    { label: 'Budget', value: dish.budgetBand },
    { label: 'Ready in', value: dish.prepTime },
  ];
}

export function getScenarioBuckets(input: RecommendationInput) {
  const recommendations = getRecommendedDishes(input);
  return {
    quick: recommendations.filter((item) => item.dish.speedScore >= 4).slice(0, 4),
    comfort: recommendations.filter((item) => item.dish.comfortScore >= 4).slice(0, 4),
    healthy: recommendations.filter((item) => item.dish.healthTags.length > 0).slice(0, 4),
    treat: recommendations.filter((item) => item.dish.premiumScore >= 4).slice(0, 4),
  };
}

export function getHomeFilters() {
  return [...brand.homeFilters];
}

export function getTodaysTopPicks(input: RecommendationInput, limit = 3): RecommendationResult[] {
  const seenRestaurants = new Set<string>();
  return getRecommendedDishes(input).filter((item) => {
    if (seenRestaurants.has(item.dish.restaurantId)) {
      return false;
    }
    seenRestaurants.add(item.dish.restaurantId);
    return true;
  }).slice(0, limit);
}

export function getDecisivePick(input: RecommendationInput): RecommendationResult | null {
  return getRecommendedDishes(input)[0] ?? null;
}
