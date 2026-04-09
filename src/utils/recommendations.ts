import { SWIPE_CARDS, type SwipeCardData, type BudgetBand, type MealType } from '../data/mockData';

export interface RecommendationInput {
  selectedCuisines: string[];
  selectedRestrictions: string[];
  preferredMealType?: MealType | null;
  preferredBudgetBand?: BudgetBand | null;
}

export interface RecommendationResult {
  dish: SwipeCardData;
  score: number;
  reasons: string[];
}

const CUISINE_LABELS: Record<string, string> = {
  Sichuan: '川湘风味',
  Cantonese: '粤式清鲜',
  Hunan: '重口热辣',
  JapaneseKorean: '日韩料理',
  Western: '西式轻正餐',
  SoutheastAsian: '东南亚风味',
  Desserts: '甜品饮品',
  BBQ: '烧烤小串',
  Northwestern: '西北面食',
  JiangsuZhejiang: '江浙清鲜',
};

const RESTRICTION_LABELS: Record<string, string> = {
  pork: '猪肉',
  beef: '牛肉',
  seafood: '海鲜',
  spicy: '重辣',
  eggs: '蛋类',
  dairy: '奶制品',
  coriander: '香菜',
  nuts: '坚果',
};

const BUDGET_SCORES: Record<BudgetBand, number> = { '¥': 1, '¥¥': 2, '¥¥¥': 3 };

function scoreCuisine(dish: SwipeCardData, selectedCuisines: string[]) {
  if (selectedCuisines.length === 0) return 1;
  return selectedCuisines.includes(dish.cuisineId) ? 10 : -2;
}

function scoreRestrictions(dish: SwipeCardData, selectedRestrictions: string[]) {
  const conflicts = selectedRestrictions.filter((item) => dish.restrictionConflicts.includes(item) || dish.decisionTags.includes(item));
  return conflicts.length > 0 ? -25 * conflicts.length : 4;
}

function scoreBudget(dish: SwipeCardData, preferredBudgetBand?: BudgetBand | null) {
  if (!preferredBudgetBand) return 0;
  return Math.abs(BUDGET_SCORES[dish.budgetBand] - BUDGET_SCORES[preferredBudgetBand]) === 0 ? 4 : -2;
}

function scoreMealType(dish: SwipeCardData, preferredMealType?: MealType | null) {
  if (!preferredMealType) return 0;
  return dish.mealType === preferredMealType ? 6 : -1;
}

function buildReasons(dish: SwipeCardData, input: RecommendationInput): string[] {
  const reasons: string[] = [];
  if (input.selectedCuisines.includes(dish.cuisineId)) {
    reasons.push(`匹配你偏好的${CUISINE_LABELS[dish.cuisineId] ?? dish.cuisineLabel}`);
  }
  if (input.selectedRestrictions.length > 0) {
    const conflicts = input.selectedRestrictions.filter((item) => dish.restrictionConflicts.includes(item));
    if (conflicts.length === 0) {
      reasons.push(`已避开你的忌口：${input.selectedRestrictions.map((item) => RESTRICTION_LABELS[item] ?? item).join('、')}`);
    }
  }
  if (input.preferredMealType && dish.mealType === input.preferredMealType) {
    reasons.push(`很适合现在的${input.preferredMealType}场景`);
  }
  if (!input.preferredMealType && dish.fitMoments.length > 0) {
    reasons.push(dish.fitMoments[0]);
  }
  if (dish.healthTags.length > 0) {
    reasons.push(`${dish.healthTags[0]}，更容易做出不后悔的选择`);
  }
  return reasons.slice(0, 3);
}

function scoreDish(dish: SwipeCardData, input: RecommendationInput): RecommendationResult {
  const score =
    scoreCuisine(dish, input.selectedCuisines) +
    scoreRestrictions(dish, input.selectedRestrictions) +
    scoreMealType(dish, input.preferredMealType) +
    scoreBudget(dish, input.preferredBudgetBand) +
    dish.speedScore +
    dish.comfortScore +
    dish.premiumScore;

  return {
    dish,
    score,
    reasons: buildReasons(dish, input),
  };
}

export function getRecommendedDishes(input: RecommendationInput): RecommendationResult[] {
  return SWIPE_CARDS
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
    .filter((item) => item.dish.cuisineId === primary.cuisineId || item.dish.mealType === primary.mealType)
    .slice(0, limit);
}

export function buildDecisionSnapshot(dish: SwipeCardData) {
  return [
    { label: '适合时段', value: dish.mealType },
    { label: '预算级别', value: dish.budgetBand },
    { label: '准备时间', value: dish.prepTime },
  ];
}

export function getScenarioBuckets(input: RecommendationInput) {
  const recommendations = getRecommendedDishes(input);
  return {
    quick: recommendations.filter((item) => item.dish.speedScore >= 4).slice(0, 4),
    comfort: recommendations.filter((item) => item.dish.comfortScore >= 4).slice(0, 4),
    healthy: recommendations.filter((item) => item.dish.healthTags.length > 0).slice(0, 4),
  };
}
