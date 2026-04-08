export interface SwipeCardData {
  id: number;
  name: string;
  category: string;
  rating: number;
  distance: string;
  price: string;
  prepTime: string;
  tags: string[];
  image: string;
}

export const SWIPE_CARDS: SwipeCardData[] = [
  {
    id: 1,
    name: '麻婆豆腐',
    category: '川菜',
    rating: 4.8,
    distance: '0.8km',
    price: '¥28',
    prepTime: '15分钟',
    tags: ['#下饭神器', '#经典川菜'],
    image: 'https://images.unsplash.com/photo-1582878826629-29b7ad1cdc43?w=800&q=80',
  },
  {
    id: 2,
    name: '白切鸡',
    category: '粤菜',
    rating: 4.7,
    distance: '1.2km',
    price: '¥45',
    prepTime: '25分钟',
    tags: ['#鲜嫩多汁', '#广式经典'],
    image: 'https://images.unsplash.com/photo-1598515214211-89d3c73ae83b?w=800&q=80',
  },
  {
    id: 3,
    name: '三文鱼刺身',
    category: '日料',
    rating: 4.9,
    distance: '0.5km',
    price: '¥68',
    prepTime: '10分钟',
    tags: ['#新鲜直送', '#高蛋白'],
    image: 'https://images.unsplash.com/photo-1579871494447-9811cf80d66c?w=800&q=80',
  },
  {
    id: 4,
    name: '黑椒牛排',
    category: '西餐',
    rating: 4.6,
    distance: '2.0km',
    price: '¥88',
    prepTime: '30分钟',
    tags: ['#约会首选', '#高级感'],
    image: 'https://images.unsplash.com/photo-1546833999-b9f581a1996d?w=800&q=80',
  },
  {
    id: 5,
    name: '石锅拌饭',
    category: '韩餐',
    rating: 4.5,
    distance: '1.5km',
    price: '¥32',
    prepTime: '15分钟',
    tags: ['#锅巴脆脆', '#拌饭灵魂'],
    image: 'https://images.unsplash.com/photo-1553163147-622ab57be1c7?w=800&q=80',
  },
  {
    id: 6,
    name: '冬阴功汤',
    category: '东南亚',
    rating: 4.8,
    distance: '0.9km',
    price: '¥38',
    prepTime: '20分钟',
    tags: ['#酸辣开胃', '#泰式风味'],
    image: 'https://images.unsplash.com/photo-1548943487-a2e4e43b4853?w=800&q=80',
  },
  {
    id: 7,
    name: '煎饼果子',
    category: '小吃',
    rating: 4.4,
    distance: '0.3km',
    price: '¥12',
    prepTime: '5分钟',
    tags: ['#街头美味', '#早餐必备'],
    image: 'https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?w=800&q=80',
  },
  {
    id: 8,
    name: '提拉米苏',
    category: '甜品',
    rating: 4.7,
    distance: '1.0km',
    price: '¥36',
    prepTime: '无需等待',
    tags: ['#下午茶', '#意式经典'],
    image: 'https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?w=800&q=80',
  },
  {
    id: 9,
    name: '水煮鱼',
    category: '川菜',
    rating: 4.9,
    distance: '1.8km',
    price: '¥58',
    prepTime: '20分钟',
    tags: ['#麻辣鲜香', '#聚餐必点'],
    image: 'https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?w=800&q=80',
  },
  {
    id: 10,
    name: '叉烧饭',
    category: '粤菜',
    rating: 4.6,
    distance: '0.6km',
    price: '¥25',
    prepTime: '10分钟',
    tags: ['#蜜汁诱惑', '#快速出餐'],
    image: 'https://images.unsplash.com/photo-1569058242253-92a9c755a0ec?w=800&q=80',
  },
  {
    id: 11,
    name: '豚骨拉面',
    category: '日料',
    rating: 4.8,
    distance: '1.3km',
    price: '¥42',
    prepTime: '15分钟',
    tags: ['#浓郁汤底', '#日式灵魂'],
    image: 'https://images.unsplash.com/photo-1557872943-16a5ac26437e?w=800&q=80',
  },
  {
    id: 12,
    name: '凯撒沙拉',
    category: '西餐',
    rating: 4.3,
    distance: '0.7km',
    price: '¥35',
    prepTime: '10分钟',
    tags: ['#轻食健康', '#减脂必选'],
    image: 'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=80',
  },
  {
    id: 13,
    name: '炸鸡啤酒',
    category: '韩餐',
    rating: 4.7,
    distance: '2.1km',
    price: '¥55',
    prepTime: '20分钟',
    tags: ['#追剧搭配', '#外酥里嫩'],
    image: 'https://images.unsplash.com/photo-1626645738196-c2a72c78a2b7?w=800&q=80',
  },
  {
    id: 14,
    name: '海南鸡饭',
    category: '东南亚',
    rating: 4.6,
    distance: '1.1km',
    price: '¥30',
    prepTime: '15分钟',
    tags: ['#南洋风情', '#鸡饭飘香'],
    image: 'https://images.unsplash.com/photo-1569058242252-623df46b5025?w=800&q=80',
  },
  {
    id: 15,
    name: '臭豆腐',
    category: '小吃',
    rating: 4.5,
    distance: '0.4km',
    price: '¥15',
    prepTime: '8分钟',
    tags: ['#闻着臭吃着香', '#长沙名吃'],
    image: 'https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=800&q=80',
  },
  {
    id: 16,
    name: '芒果糯米饭',
    category: '甜品',
    rating: 4.8,
    distance: '1.4km',
    price: '¥22',
    prepTime: '无需等待',
    tags: ['#热带甜蜜', '#泰式甜品'],
    image: 'https://images.unsplash.com/photo-1563805042-7684c019e1cb?w=800&q=80',
  },
  {
    id: 17,
    name: '宫保鸡丁',
    category: '川菜',
    rating: 4.7,
    distance: '0.9km',
    price: '¥32',
    prepTime: '15分钟',
    tags: ['#酸甜微辣', '#国民家常'],
    image: 'https://images.unsplash.com/photo-1525755662778-989d0524087e?w=800&q=80',
  },
  {
    id: 18,
    name: '虾饺皇',
    category: '粤菜',
    rating: 4.9,
    distance: '1.6km',
    price: '¥48',
    prepTime: '20分钟',
    tags: ['#早茶必点', '#晶莹剔透'],
    image: 'https://images.unsplash.com/photo-1496116218417-1a781b1c416c?w=800&q=80',
  },
];

export const CATEGORIES = [
  { icon: '🍜', label: '面条' },
  { icon: '🍕', label: '披萨' },
  { icon: '🥗', label: '沙拉' },
  { icon: '🍰', label: '甜品' },
  { icon: '🍣', label: '寿司' },
  { icon: '🥘', label: '火锅' },
];

export const NEARBY_ITEMS = [
  {
    id: 1,
    title: '精选寿司拼盘',
    subtitle: '樱花寿司屋',
    rating: 4.8,
    price: '¥18',
    image:
      'https://images.unsplash.com/photo-1579871494447-9811cf80d66c?w=800&q=80',
  },
  {
    id: 2,
    title: '提拉米苏特供',
    subtitle: '甜蜜生活咖啡馆',
    rating: 4.7,
    price: '¥9',
    image:
      'https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?w=800&q=80',
  },
];

export const CUISINES = [
  { id: 'Sichuan', icon: '🍽️', label: '川菜' },
  { id: 'Cantonese', icon: '🥢', label: '粤菜' },
  { id: 'Hunan', icon: '🥘', label: '湘菜' },
  { id: 'JapaneseKorean', icon: '🍜', label: '日韩料理' },
  { id: 'Western', icon: '🍕', label: '西餐' },
  { id: 'SoutheastAsian', icon: '🥥', label: '东南亚' },
  { id: 'Desserts', icon: '🍰', label: '甜品饮品' },
  { id: 'BBQ', icon: '🥩', label: '烧烤' },
  { id: 'Northwestern', icon: '🍢', label: '西北菜' },
  { id: 'JiangsuZhejiang', icon: '🥟', label: '江浙菜' },
];

export const MEATS = [
  { id: 'pork', icon: '🐷', label: '猪肉' },
  { id: 'beef', icon: '🐮', label: '牛肉' },
  { id: 'seafood', icon: '🐟', label: '海鲜' },
];

export const FLAVORS = [
  { id: 'spicy', icon: '🌶️', label: '辣' },
  { id: 'eggs', icon: '🥚', label: '蛋类' },
  { id: 'dairy', icon: '🥛', label: '乳制品' },
  { id: 'coriander', icon: '🌿', label: '香菜' },
  { id: 'nuts', icon: '🥜', label: '坚果' },
];

export const FAVORITES_DATA = [
  {
    id: 1,
    title: '牛油果活力沙拉',
    image:
      'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=80',
    rating: 4.8,
    reviews: 124,
    category: '西餐',
  },
  {
    id: 2,
    title: '招牌烤串',
    image:
      'https://images.unsplash.com/photo-1544982503-9f984c14501a?w=800&q=80',
    rating: 4.9,
    reviews: 89,
    category: '川菜',
  },
  {
    id: 3,
    title: '蓝莓舒芙蕾松饼',
    image:
      'https://images.unsplash.com/photo-1620991565081-82743a5a499c?w=800&q=80',
    rating: 4.7,
    reviews: 256,
    category: '甜品',
  },
  {
    id: 4,
    title: '浓郁豚骨拉面',
    image:
      'https://images.unsplash.com/photo-1557872943-16a5ac26437e?w=800&q=80',
    rating: 4.8,
    reviews: 312,
    category: '日料',
  },
];

export const HISTORY_DATA = [
  {
    group: '今天',
    items: [
      {
        id: 1,
        title: '牛油果花园沙拉',
        time: '12:45',
        category: '轻食',
        status: 'Liked' as const,
        img: 'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=80',
      },
      {
        id: 2,
        title: '经典芝士汉堡',
        time: '11:20',
        category: '西式快餐',
        status: 'Skipped' as const,
        img: 'https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=800&q=80',
      },
    ],
  },
  {
    group: '昨天',
    items: [
      {
        id: 3,
        title: '豚骨叉烧拉面',
        time: '19:15',
        category: '日本料理',
        status: 'Liked' as const,
        img: 'https://images.unsplash.com/photo-1557872943-16a5ac26437e?w=800&q=80',
      },
      {
        id: 4,
        title: '意式辣肠披萨',
        time: '13:30',
        category: '意式披萨',
        status: 'Skipped' as const,
        img: 'https://images.unsplash.com/photo-1544982503-9f984c14501a?w=800&q=80',
      },
    ],
  },
];

export const EXPLORE_CARDS = [
  {
    id: 1,
    title: '禅意花园沙拉碗',
    rating: 4.9,
    reviews: '120+',
    subtitle: '健康 · 15分钟',
    badge: '好评榜首',
    image:
      'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=80',
  },
  {
    id: 2,
    title: '松露蘑菇披萨',
    rating: 4.7,
    reviews: '65+',
    subtitle: '意式 · 20分钟',
    badge: null,
    image:
      'https://images.unsplash.com/photo-1544982503-9f984c14501a?w=800&q=80',
  },
];
