export type MealType = 'Breakfast' | 'Lunch' | 'Dinner' | 'Snack' | 'Late Night';
export type BudgetBand = '$' | '$$' | '$$$';
export type GroupFit = 'solo' | 'pair' | 'family' | 'group';

export interface DishNutrition {
  calories: number;
  protein: string;
  carbs: string;
  fat: string;
}

export interface SwipeCardData {
  id: number;
  restaurantId: string;
  restaurantName: string;
  restaurantAddress: string;
  restaurantRating: number;
  restaurantReviewCount: number;
  restaurantPriceLevel: BudgetBand;
  name: string;
  subtitle: string;
  category: string;
  cuisineId: string;
  cuisineLabel: string;
  rating: number;
  distance: string;
  distanceMeters: number;
  price: string;
  prepTime: string;
  tags: string[];
  image: string;
  restaurantImage?: string;
  mealType: MealType;
  budgetBand: BudgetBand;
  decisionTags: string[];
  restrictionConflicts: string[];
  healthTags: string[];
  fitMoments: string[];
  groupFit: GroupFit;
  speedScore: number;
  comfortScore: number;
  premiumScore: number;
  recommendationBlurb: string;
  nutrition: DishNutrition;
}

export const SWIPE_CARDS: SwipeCardData[] = [
  {
    id: 1,
    restaurantId: 'maple-thyme',
    restaurantName: 'Maple & Thyme',
    restaurantAddress: '14 King Street',
    restaurantRating: 4.7,
    restaurantReviewCount: 428,
    restaurantPriceLevel: '$$',
    name: 'Seared Salmon Rice Bowl',
    subtitle: 'Bright, filling, and easy to say yes to on a busy lunch break.',
    category: 'Best Near You',
    cuisineId: 'JapaneseKorean',
    cuisineLabel: 'Japanese-inspired',
    rating: 4.8,
    distance: '0.3 mi',
    distanceMeters: 420,
    price: '$18',
    prepTime: '15 min',
    tags: ['High protein', 'Fresh', 'Work lunch'],
    image: 'https://images.unsplash.com/photo-1547592180-85f173990554?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1552566626-52f8b828add9?w=1200&q=80',
    mealType: 'Lunch',
    budgetBand: '$$',
    decisionTags: ['Fast lunch', 'Balanced', 'No drama choice'],
    restrictionConflicts: ['seafood'],
    healthTags: ['High protein', 'Lighter', 'Balanced'],
    fitMoments: ['Easy work lunch', 'Post-workout meal', 'You want something clean but satisfying'],
    groupFit: 'solo',
    speedScore: 5,
    comfortScore: 3,
    premiumScore: 4,
    recommendationBlurb: 'A reliable nearby pick when you want something fresh, filling, and not too heavy.',
    nutrition: { calories: 485, protein: '32g', carbs: '45g', fat: '18g' },
  },
  {
    id: 2,
    restaurantId: 'paper-lantern',
    restaurantName: 'Paper Lantern',
    restaurantAddress: '201 Grant Ave',
    restaurantRating: 4.6,
    restaurantReviewCount: 311,
    restaurantPriceLevel: '$$',
    name: 'Miso Chicken Udon',
    subtitle: 'Warm, savory, and ideal when you want comfort without a huge meal.',
    category: 'Comfort Pick',
    cuisineId: 'JapaneseKorean',
    cuisineLabel: 'Japanese',
    rating: 4.7,
    distance: '0.5 mi',
    distanceMeters: 760,
    price: '$17',
    prepTime: '18 min',
    tags: ['Warm', 'Noodles', 'Weeknight'],
    image: 'https://images.unsplash.com/photo-1557872943-16a5ac26437e?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1200&q=80',
    mealType: 'Dinner',
    budgetBand: '$$',
    decisionTags: ['Comforting', 'Easy dinner', 'Warm and steady'],
    restrictionConflicts: ['dairy'],
    healthTags: [],
    fitMoments: ['Long day', 'Cold weather dinner', 'You want something warm and easy'],
    groupFit: 'solo',
    speedScore: 3,
    comfortScore: 5,
    premiumScore: 3,
    recommendationBlurb: 'A calmer dinner choice when you want warmth and comfort more than variety.',
    nutrition: { calories: 610, protein: '29g', carbs: '63g', fat: '22g' },
  },
  {
    id: 3,
    restaurantId: 'harvest-table',
    restaurantName: 'Harvest Table',
    restaurantAddress: '88 Market Lane',
    restaurantRating: 4.5,
    restaurantReviewCount: 197,
    restaurantPriceLevel: '$$',
    name: 'Charred Chicken Salad',
    subtitle: 'Clean flavors, lighter calories, and still enough to feel like a meal.',
    category: 'Healthy Favorite',
    cuisineId: 'Western',
    cuisineLabel: 'Modern American',
    rating: 4.6,
    distance: '0.6 mi',
    distanceMeters: 980,
    price: '$16',
    prepTime: '10 min',
    tags: ['Lighter', 'Protein', 'Low effort'],
    image: 'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1466978913421-dad2ebd01d17?w=1200&q=80',
    mealType: 'Dinner',
    budgetBand: '$$',
    decisionTags: ['Healthy', 'Simple yes', 'Low-regret dinner'],
    restrictionConflicts: ['dairy'],
    healthTags: ['Lower fat', 'High protein', 'Fiber'],
    fitMoments: ['You want something lighter', 'Late dinner', 'Post-gym meal'],
    groupFit: 'solo',
    speedScore: 5,
    comfortScore: 2,
    premiumScore: 2,
    recommendationBlurb: 'A strong fit for nights when you want to eat well without feeling weighed down.',
    nutrition: { calories: 338, protein: '29g', carbs: '18g', fat: '13g' },
  },
  {
    id: 4,
    restaurantId: 'brick-oven-social',
    restaurantName: 'Brick Oven Social',
    restaurantAddress: '52 Orchard Street',
    restaurantRating: 4.8,
    restaurantReviewCount: 509,
    restaurantPriceLevel: '$$',
    name: 'Mushroom Truffle Pizza',
    subtitle: 'A polished comfort pick when dinner should feel a little more fun.',
    category: 'Treat Yourself',
    cuisineId: 'Western',
    cuisineLabel: 'Italian',
    rating: 4.8,
    distance: '0.8 mi',
    distanceMeters: 1280,
    price: '$22',
    prepTime: '20 min',
    tags: ['Shareable', 'Rich', 'Date-night safe'],
    image: 'https://images.unsplash.com/photo-1544982503-9f984c14501a?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1559339352-11d035aa65de?w=1200&q=80',
    mealType: 'Dinner',
    budgetBand: '$$',
    decisionTags: ['Treat mood', 'Shareable', 'Easy win'],
    restrictionConflicts: ['dairy'],
    healthTags: [],
    fitMoments: ['Casual date night', 'Dinner with a friend', 'You want something fun'],
    groupFit: 'pair',
    speedScore: 3,
    comfortScore: 5,
    premiumScore: 4,
    recommendationBlurb: 'A stronger choice when dinner should feel a little special, not just efficient.',
    nutrition: { calories: 620, protein: '24g', carbs: '58g', fat: '28g' },
  },
  {
    id: 5,
    restaurantId: 'spice-assembly',
    restaurantName: 'Spice Assembly',
    restaurantAddress: '301 8th Avenue',
    restaurantRating: 4.6,
    restaurantReviewCount: 264,
    restaurantPriceLevel: '$',
    name: 'Mapo Tofu Rice Set',
    subtitle: 'Fast, filling, and a very safe answer when you want a classic hot lunch.',
    category: 'Budget Win',
    cuisineId: 'Sichuan',
    cuisineLabel: 'Sichuan',
    rating: 4.7,
    distance: '0.4 mi',
    distanceMeters: 650,
    price: '$14',
    prepTime: '16 min',
    tags: ['Hot meal', 'Classic', 'Affordable'],
    image: 'https://images.unsplash.com/photo-1582878826629-29b7ad1cdc43?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1514933651103-005eec06c04b?w=1200&q=80',
    mealType: 'Lunch',
    budgetBand: '$',
    decisionTags: ['Budget-friendly', 'Fast hot meal', 'Reliable'],
    restrictionConflicts: ['spicy'],
    healthTags: ['High protein'],
    fitMoments: ['You want a real lunch', 'You do not want to overspend', 'You need something hot'],
    groupFit: 'solo',
    speedScore: 4,
    comfortScore: 5,
    premiumScore: 2,
    recommendationBlurb: 'An easy lunch answer when you want something hot, filling, and worth the price.',
    nutrition: { calories: 520, protein: '26g', carbs: '51g', fat: '21g' },
  },
  {
    id: 6,
    restaurantId: 'island-kitchen',
    restaurantName: 'Island Kitchen',
    restaurantAddress: '73 Broadway',
    restaurantRating: 4.7,
    restaurantReviewCount: 228,
    restaurantPriceLevel: '$',
    name: 'Hainan Chicken Rice',
    subtitle: 'Gentle, dependable, and especially good when you want something low-risk.',
    category: 'Low-Effort Favorite',
    cuisineId: 'SoutheastAsian',
    cuisineLabel: 'Southeast Asian',
    rating: 4.7,
    distance: '0.7 mi',
    distanceMeters: 1130,
    price: '$15',
    prepTime: '14 min',
    tags: ['Gentle', 'Balanced', 'Easy dinner'],
    image: 'https://images.unsplash.com/photo-1569058242252-623df46b5025?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=1200&q=80',
    mealType: 'Dinner',
    budgetBand: '$',
    decisionTags: ['Low-risk pick', 'Easy dinner', 'Balanced'],
    restrictionConflicts: [],
    healthTags: ['Balanced'],
    fitMoments: ['You are tired', 'You want a safe dinner', 'Your appetite is normal but not huge'],
    groupFit: 'solo',
    speedScore: 4,
    comfortScore: 4,
    premiumScore: 2,
    recommendationBlurb: 'A dependable dinner when you want to avoid overthinking and still eat well.',
    nutrition: { calories: 468, protein: '28g', carbs: '49g', fat: '15g' },
  },
  {
    id: 7,
    restaurantId: 'ember-grill',
    restaurantName: 'Ember Grill',
    restaurantAddress: '220 Union Square West',
    restaurantRating: 4.7,
    restaurantReviewCount: 402,
    restaurantPriceLevel: '$$$',
    name: 'Steak Frites',
    subtitle: 'A polished dinner answer for nights when you want something more complete.',
    category: 'Night Out',
    cuisineId: 'Western',
    cuisineLabel: 'Steakhouse',
    rating: 4.8,
    distance: '1.1 mi',
    distanceMeters: 1770,
    price: '$36',
    prepTime: '24 min',
    tags: ['Dinner out', 'Classic', 'Reward meal'],
    image: 'https://images.unsplash.com/photo-1546833999-b9f581a1996d?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1559339352-11d035aa65de?w=1200&q=80',
    mealType: 'Dinner',
    budgetBand: '$$$',
    decisionTags: ['Treat meal', 'Date-safe', 'Structured dinner'],
    restrictionConflicts: ['beef'],
    healthTags: ['High protein'],
    fitMoments: ['You want a proper dinner', 'Celebration dinner', 'Date night'],
    groupFit: 'pair',
    speedScore: 2,
    comfortScore: 4,
    premiumScore: 5,
    recommendationBlurb: 'A better fit when you want dinner to feel deliberate instead of purely practical.',
    nutrition: { calories: 690, protein: '39g', carbs: '31g', fat: '34g' },
  },
  {
    id: 8,
    restaurantId: 'seoul-stone',
    restaurantName: 'Seoul Stone',
    restaurantAddress: '90 Madison Ave',
    restaurantRating: 4.6,
    restaurantReviewCount: 289,
    restaurantPriceLevel: '$',
    name: 'Bibimbap Bowl',
    subtitle: 'Layered, hot, and satisfying when you want variety in one bowl.',
    category: 'Reliable Bowl',
    cuisineId: 'JapaneseKorean',
    cuisineLabel: 'Korean',
    rating: 4.6,
    distance: '0.9 mi',
    distanceMeters: 1450,
    price: '$15',
    prepTime: '15 min',
    tags: ['Hot bowl', 'Balanced', 'Solo lunch'],
    image: 'https://images.unsplash.com/photo-1553163147-622ab57be1c7?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=1200&q=80',
    mealType: 'Lunch',
    budgetBand: '$',
    decisionTags: ['Balanced bowl', 'Hot lunch', 'Easy yes'],
    restrictionConflicts: ['spicy', 'eggs'],
    healthTags: ['Balanced'],
    fitMoments: ['Solo lunch', 'You want something hot', 'You want variety without extra effort'],
    groupFit: 'solo',
    speedScore: 4,
    comfortScore: 4,
    premiumScore: 2,
    recommendationBlurb: 'A balanced lunch when you want something warm, complete, and easy to commit to.',
    nutrition: { calories: 540, protein: '21g', carbs: '67g', fat: '18g' },
  },
  {
    id: 9,
    restaurantId: 'sweet-current',
    restaurantName: 'Sweet Current',
    restaurantAddress: '19 Prince Street',
    restaurantRating: 4.7,
    restaurantReviewCount: 154,
    restaurantPriceLevel: '$',
    name: 'Mango Sticky Rice',
    subtitle: 'A clean, bright dessert answer when you want something sweet but not too heavy.',
    category: 'Sweet Ending',
    cuisineId: 'Desserts',
    cuisineLabel: 'Dessert',
    rating: 4.7,
    distance: '0.5 mi',
    distanceMeters: 790,
    price: '$9',
    prepTime: 'Ready now',
    tags: ['Dessert', 'Afternoon', 'Sweet'],
    image: 'https://images.unsplash.com/photo-1563805042-7684c019e1cb?w=1200&q=80',
    restaurantImage: 'https://images.unsplash.com/photo-1481833761820-0509d3217039?w=1200&q=80',
    mealType: 'Snack',
    budgetBand: '$',
    decisionTags: ['Sweet pick', 'Afternoon treat', 'Light finish'],
    restrictionConflicts: ['dairy'],
    healthTags: [],
    fitMoments: ['Afternoon dip', 'You want a treat', 'Dessert after dinner'],
    groupFit: 'pair',
    speedScore: 5,
    comfortScore: 4,
    premiumScore: 2,
    recommendationBlurb: 'A bright dessert pick when you want a clear little reward, not a huge commitment.',
    nutrition: { calories: 312, protein: '4g', carbs: '56g', fat: '7g' },
  },
];

export interface ExploreCard {
  id: number;
  title: string;
  subtitle: string;
  category: string;
  cuisine: string;
  mealType: MealType;
  priceBand: BudgetBand;
  dietTag: string[];
  rating: number;
  reviews: string;
  badge: string | null;
  image: string;
}

export const EXPLORE_CARDS: ExploreCard[] = SWIPE_CARDS.map((item) => ({
  id: item.id,
  title: item.name,
  subtitle: `${item.restaurantName} · ${item.prepTime}`,
  category: item.category,
  cuisine: item.cuisineLabel,
  mealType: item.mealType,
  priceBand: item.budgetBand,
  dietTag: item.healthTags,
  rating: item.restaurantRating,
  reviews: item.restaurantReviewCount >= 400 ? '400+' : '150+',
  badge: item.category,
  image: item.image,
}));

export const FAVORITES_DATA = SWIPE_CARDS.slice(0, 4).map((item) => ({
  id: item.id,
  title: item.name,
  image: item.image,
  rating: item.restaurantRating,
  reviews: item.restaurantReviewCount,
  category: item.cuisineLabel,
  restaurantName: item.restaurantName,
}));

export const HISTORY_DATA = [
  {
    group: 'Today',
    items: [
      {
        id: 1,
        title: 'Seared Salmon Rice Bowl',
        time: '12:45 PM',
        category: 'Lunch',
        status: 'Liked' as const,
        img: SWIPE_CARDS[0].image,
      },
      {
        id: 6,
        title: 'Hainan Chicken Rice',
        time: '6:20 PM',
        category: 'Dinner candidate',
        status: 'Skipped' as const,
        img: SWIPE_CARDS[5].image,
      },
    ],
  },
];

export const CATEGORIES = [
  { icon: '🍜', label: 'Comfort' },
  { icon: '🥗', label: 'Healthy' },
  { icon: '🥘', label: 'Dinner' },
  { icon: '🍰', label: 'Dessert' },
  { icon: '☕', label: 'Coffee break' },
  { icon: '🍳', label: 'Breakfast' },
];

export const NEARBY_ITEMS = [
  {
    id: 1,
    title: 'Best fast lunch nearby',
    subtitle: 'Strong fit for workday meals',
    rating: 4.8,
    price: '$18',
    image: SWIPE_CARDS[0].image,
  },
  {
    id: 2,
    title: 'Reliable comfort dinner',
    subtitle: 'Warm, fast, and low-risk',
    rating: 4.7,
    price: '$17',
    image: SWIPE_CARDS[1].image,
  },
];

export const CUISINES = [
  { id: 'Sichuan', icon: '🌶️', label: 'Bold Chinese' },
  { id: 'Cantonese', icon: '🥢', label: 'Cantonese' },
  { id: 'Hunan', icon: '🔥', label: 'Spicy comfort' },
  { id: 'JapaneseKorean', icon: '🍱', label: 'Japanese & Korean' },
  { id: 'Western', icon: '🍽️', label: 'Modern Western' },
  { id: 'SoutheastAsian', icon: '🥥', label: 'Southeast Asian' },
  { id: 'Desserts', icon: '🍨', label: 'Desserts' },
  { id: 'BBQ', icon: '🍖', label: 'BBQ' },
  { id: 'Northwestern', icon: '🥟', label: 'Noodles & dumplings' },
  { id: 'JiangsuZhejiang', icon: '🐟', label: 'Light Chinese' },
];

export const MEATS = [
  { id: 'pork', icon: '🐖', label: 'Pork' },
  { id: 'beef', icon: '🥩', label: 'Beef' },
  { id: 'seafood', icon: '🦐', label: 'Seafood' },
];

export const FLAVORS = [
  { id: 'spicy', icon: '🌶️', label: 'Spicy heat' },
  { id: 'eggs', icon: '🥚', label: 'Eggs' },
  { id: 'dairy', icon: '🥛', label: 'Dairy' },
  { id: 'coriander', icon: '🌿', label: 'Cilantro' },
  { id: 'nuts', icon: '🥜', label: 'Nuts' },
];
