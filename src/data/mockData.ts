export type MealType = '早餐' | '午餐' | '晚餐' | '下午茶' | '夜宵';
export type BudgetBand = '¥' | '¥¥' | '¥¥¥';
export type GroupFit = 'solo' | 'pair' | 'family' | 'group';

export interface DishNutrition {
  calories: number;
  protein: string;
  carbs: string;
  fat: string;
}

export interface SwipeCardData {
  id: number;
  name: string;
  subtitle: string;
  category: string;
  cuisineId: string;
  cuisineLabel: string;
  rating: number;
  distance: string;
  price: string;
  prepTime: string;
  tags: string[];
  image: string;
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
    name: '炙烤三文鱼能量碗',
    subtitle: '高蛋白、低负担，适合忙碌工作日的稳妥选择',
    category: '今日优先',
    cuisineId: 'JapaneseKorean',
    cuisineLabel: '日式轻食',
    rating: 4.9,
    distance: '0.9km',
    price: '¥58',
    prepTime: '15分钟',
    tags: ['#高蛋白', '#清爽', '#工作午餐'],
    image: 'https://images.unsplash.com/photo-1547592180-85f173990554?w=1200&q=80',
    mealType: '午餐',
    budgetBand: '¥¥',
    decisionTags: ['高效午餐', '低决策成本', '高蛋白'],
    restrictionConflicts: ['seafood'],
    healthTags: ['高蛋白', '低油', '稳态能量'],
    fitMoments: ['午休快选', '健身后补充', '不想犯困'],
    groupFit: 'solo',
    speedScore: 5,
    comfortScore: 3,
    premiumScore: 4,
    recommendationBlurb: '适合想吃得健康又不想牺牲饱腹感的时候。',
    nutrition: { calories: 485, protein: '32g', carbs: '45g', fat: '18g' },
  },
  {
    id: 2,
    name: '黑椒牛排热食盘',
    subtitle: '满足感强，适合晚餐想吃得正式一点',
    category: '犒赏自己',
    cuisineId: 'Western',
    cuisineLabel: '西式热食',
    rating: 4.7,
    distance: '1.8km',
    price: '¥88',
    prepTime: '28分钟',
    tags: ['#满足感', '#正式晚餐', '#约会也稳'],
    image: 'https://images.unsplash.com/photo-1546833999-b9f581a1996d?w=1200&q=80',
    mealType: '晚餐',
    budgetBand: '¥¥¥',
    decisionTags: ['犒赏时刻', '正式晚餐', '高满足'],
    restrictionConflicts: ['beef'],
    healthTags: ['高蛋白'],
    fitMoments: ['下班奖励', '约会晚餐', '周末放松'],
    groupFit: 'pair',
    speedScore: 2,
    comfortScore: 4,
    premiumScore: 5,
    recommendationBlurb: '当你今天值得一顿更像样的晚餐时，它比随便吃一顿更有仪式感。',
    nutrition: { calories: 690, protein: '39g', carbs: '31g', fat: '34g' },
  },
  {
    id: 3,
    name: '松露蘑菇披萨',
    subtitle: '奶香和菌香都在线，适合双人共享',
    category: '共享首选',
    cuisineId: 'Western',
    cuisineLabel: '意式',
    rating: 4.8,
    distance: '1.4km',
    price: '¥76',
    prepTime: '20分钟',
    tags: ['#双人共享', '#奶香', '#下班聚一口'],
    image: 'https://images.unsplash.com/photo-1544982503-9f984c14501a?w=1200&q=80',
    mealType: '晚餐',
    budgetBand: '¥¥',
    decisionTags: ['双人友好', '聚餐不踩雷', '高愉悦'],
    restrictionConflicts: ['dairy'],
    healthTags: [],
    fitMoments: ['情侣晚餐', '朋友来家里', '放松夜晚'],
    groupFit: 'pair',
    speedScore: 3,
    comfortScore: 5,
    premiumScore: 4,
    recommendationBlurb: '如果你今天更想吃得开心一点，这个选项比轻食更有氛围。',
    nutrition: { calories: 620, protein: '24g', carbs: '58g', fat: '28g' },
  },
  {
    id: 4,
    name: '麻婆豆腐定食',
    subtitle: '下饭但不过分重，适合想吃经典中餐的时候',
    category: '稳妥中餐',
    cuisineId: 'Sichuan',
    cuisineLabel: '川菜',
    rating: 4.8,
    distance: '0.8km',
    price: '¥32',
    prepTime: '16分钟',
    tags: ['#经典中餐', '#下饭', '#性价比高'],
    image: 'https://images.unsplash.com/photo-1582878826629-29b7ad1cdc43?w=1200&q=80',
    mealType: '午餐',
    budgetBand: '¥',
    decisionTags: ['低预算友好', '中餐稳妥', '工作日好点'],
    restrictionConflicts: ['spicy'],
    healthTags: ['高蛋白'],
    fitMoments: ['午餐不想踩雷', '想吃热饭', '预算可控'],
    groupFit: 'solo',
    speedScore: 4,
    comfortScore: 5,
    premiumScore: 2,
    recommendationBlurb: '当你只想吃一顿踏实的中餐，它是很少会后悔的选择。',
    nutrition: { calories: 520, protein: '26g', carbs: '51g', fat: '21g' },
  },
  {
    id: 5,
    name: '海南鸡饭',
    subtitle: '温和顺口，适合胃口一般但想吃得舒服',
    category: '轻松不出错',
    cuisineId: 'SoutheastAsian',
    cuisineLabel: '东南亚',
    rating: 4.7,
    distance: '1.1km',
    price: '¥30',
    prepTime: '14分钟',
    tags: ['#温和', '#低压力选择', '#轻松晚餐'],
    image: 'https://images.unsplash.com/photo-1569058242252-623df46b5025?w=1200&q=80',
    mealType: '晚餐',
    budgetBand: '¥',
    decisionTags: ['温和顺口', '晚上不想太重', '低风险'],
    restrictionConflicts: [],
    healthTags: ['均衡'],
    fitMoments: ['晚餐轻松吃', '胃口一般', '今天不想冒险'],
    groupFit: 'solo',
    speedScore: 4,
    comfortScore: 4,
    premiumScore: 2,
    recommendationBlurb: '适合那些“没想法，但不想吃错”的时刻。',
    nutrition: { calories: 468, protein: '28g', carbs: '49g', fat: '15g' },
  },
  {
    id: 6,
    name: '招牌豚骨拉面',
    subtitle: '汤底浓郁，适合想吃热腾腾安慰餐的时候',
    category: '安慰感拉满',
    cuisineId: 'JapaneseKorean',
    cuisineLabel: '日式',
    rating: 4.8,
    distance: '1.3km',
    price: '¥42',
    prepTime: '18分钟',
    tags: ['#汤面', '#安慰餐', '#下班回血'],
    image: 'https://images.unsplash.com/photo-1557872943-16a5ac26437e?w=1200&q=80',
    mealType: '晚餐',
    budgetBand: '¥¥',
    decisionTags: ['热腾腾', '压力释放', '满足感'],
    restrictionConflicts: ['pork', 'dairy'],
    healthTags: [],
    fitMoments: ['加班后', '想吃热的', '情绪补给'],
    groupFit: 'solo',
    speedScore: 3,
    comfortScore: 5,
    premiumScore: 3,
    recommendationBlurb: '当你今天想被一碗热汤面安抚一下，它很懂那个情绪。',
    nutrition: { calories: 635, protein: '27g', carbs: '64g', fat: '26g' },
  },
  {
    id: 7,
    name: '凯撒鸡胸沙拉',
    subtitle: '轻负担、控制热量，适合晚一点也敢吃',
    category: '控卡友好',
    cuisineId: 'Western',
    cuisineLabel: '轻食',
    rating: 4.6,
    distance: '0.7km',
    price: '¥35',
    prepTime: '10分钟',
    tags: ['#低负担', '#轻晚餐', '#控制热量'],
    image: 'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=1200&q=80',
    mealType: '晚餐',
    budgetBand: '¥',
    decisionTags: ['控卡友好', '轻盈', '晚餐不负罪'],
    restrictionConflicts: ['dairy'],
    healthTags: ['低脂', '高纤维', '高蛋白'],
    fitMoments: ['夜间轻晚餐', '运动日', '想吃干净一点'],
    groupFit: 'solo',
    speedScore: 5,
    comfortScore: 2,
    premiumScore: 2,
    recommendationBlurb: '如果你想吃完还能保持轻盈，它比热食更适合今天。',
    nutrition: { calories: 338, protein: '29g', carbs: '18g', fat: '13g' },
  },
  {
    id: 8,
    name: '韩式石锅拌饭',
    subtitle: '层次丰富、热量适中，适合一个人吃得满足',
    category: '一人食常胜',
    cuisineId: 'JapaneseKorean',
    cuisineLabel: '韩式',
    rating: 4.6,
    distance: '1.5km',
    price: '¥32',
    prepTime: '15分钟',
    tags: ['#一人食', '#热乎', '#满足感'],
    image: 'https://images.unsplash.com/photo-1553163147-622ab57be1c7?w=1200&q=80',
    mealType: '午餐',
    budgetBand: '¥',
    decisionTags: ['稳妥一人食', '均衡', '热食满足'],
    restrictionConflicts: ['spicy', 'eggs'],
    healthTags: ['均衡'],
    fitMoments: ['一人午餐', '想吃热饭', '想要食材丰富'],
    groupFit: 'solo',
    speedScore: 4,
    comfortScore: 4,
    premiumScore: 2,
    recommendationBlurb: '想吃热饭、菜肉饭都兼顾的时候，它通常比单一主食更让人满意。',
    nutrition: { calories: 540, protein: '21g', carbs: '67g', fat: '18g' },
  },
  {
    id: 9,
    name: '芒果糯米饭',
    subtitle: '收尾感很强，适合作为甜口满足或者下午茶',
    category: '甜口治愈',
    cuisineId: 'Desserts',
    cuisineLabel: '甜品',
    rating: 4.7,
    distance: '1.2km',
    price: '¥22',
    prepTime: '无需等待',
    tags: ['#下午茶', '#甜口', '#热带风味'],
    image: 'https://images.unsplash.com/photo-1563805042-7684c019e1cb?w=1200&q=80',
    mealType: '下午茶',
    budgetBand: '¥',
    decisionTags: ['甜口满足', '下午茶', '轻社交'],
    restrictionConflicts: ['dairy'],
    healthTags: [],
    fitMoments: ['下午低能量', '想吃甜的', '轻松时刻'],
    groupFit: 'pair',
    speedScore: 5,
    comfortScore: 4,
    premiumScore: 2,
    recommendationBlurb: '想要一点明确的快乐感，它比正餐更直接。',
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
  subtitle: `${item.cuisineLabel} · ${item.prepTime}`,
  category: item.category === '今日优先' ? '推荐' : item.cuisineLabel.includes('日') ? '日料' : '中餐',
  cuisine: item.cuisineLabel,
  mealType: item.mealType,
  priceBand: item.budgetBand,
  dietTag: item.healthTags,
  rating: item.rating,
  reviews: item.rating >= 4.8 ? '120+' : '80+',
  badge: item.category,
  image: item.image,
}));

export const FAVORITES_DATA = SWIPE_CARDS.slice(0, 4).map((item) => ({
  id: item.id,
  title: item.name,
  image: item.image,
  rating: item.rating,
  reviews: Math.round(item.rating * 70),
  category: item.cuisineLabel,
}));

export const HISTORY_DATA = [
  {
    group: '今天',
    items: [
      {
        id: 1,
        title: '炙烤三文鱼能量碗',
        time: '12:45',
        category: '午餐',
        status: 'Liked' as const,
        img: SWIPE_CARDS[0].image,
      },
      {
        id: 6,
        title: '招牌豚骨拉面',
        time: '11:20',
        category: '晚餐备选',
        status: 'Skipped' as const,
        img: SWIPE_CARDS[5].image,
      },
    ],
  },
];

export const CATEGORIES = [
  { icon: '🍜', label: '热食' },
  { icon: '🥗', label: '轻食' },
  { icon: '🍱', label: '便当' },
  { icon: '🍰', label: '甜品' },
  { icon: '🍣', label: '日料' },
  { icon: '🍲', label: '汤面' },
];

export const NEARBY_ITEMS = [
  {
    id: 1,
    title: '午间高蛋白精选',
    subtitle: '适合工作日快速定夺',
    rating: 4.8,
    price: '¥18',
    image: SWIPE_CARDS[0].image,
  },
  {
    id: 2,
    title: '下班热食不踩雷',
    subtitle: '热乎又稳妥',
    rating: 4.7,
    price: '¥9',
    image: SWIPE_CARDS[3].image,
  },
];

export const CUISINES = [
  { id: 'Sichuan', icon: '🌶️', label: '川湘风味' },
  { id: 'Cantonese', icon: '🥟', label: '粤式清鲜' },
  { id: 'Hunan', icon: '🔥', label: '重口热辣' },
  { id: 'JapaneseKorean', icon: '🍱', label: '日韩料理' },
  { id: 'Western', icon: '🍝', label: '西式轻正餐' },
  { id: 'SoutheastAsian', icon: '🥥', label: '东南亚风味' },
  { id: 'Desserts', icon: '🍮', label: '甜品饮品' },
  { id: 'BBQ', icon: '🍢', label: '烧烤小串' },
  { id: 'Northwestern', icon: '🥙', label: '西北面食' },
  { id: 'JiangsuZhejiang', icon: '🦐', label: '江浙清鲜' },
];

export const MEATS = [
  { id: 'pork', icon: '🐷', label: '猪肉' },
  { id: 'beef', icon: '🐮', label: '牛肉' },
  { id: 'seafood', icon: '🦐', label: '海鲜' },
];

export const FLAVORS = [
  { id: 'spicy', icon: '🌶️', label: '重辣' },
  { id: 'eggs', icon: '🥚', label: '蛋类' },
  { id: 'dairy', icon: '🥛', label: '奶制品' },
  { id: 'coriander', icon: '🌿', label: '香菜' },
  { id: 'nuts', icon: '🥜', label: '坚果' },
];
