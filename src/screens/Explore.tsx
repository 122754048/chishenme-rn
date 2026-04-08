import React, { useState } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import { Menu, User, Search, Star, Plus } from 'lucide-react-native';
import type { RootStackParamList, MainTabParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { EXPLORE_CARDS, FAVORITES_DATA } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { SearchOverlay } from '../components/SearchOverlay';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type ExploreRouteProp = RouteProp<MainTabParamList, 'Explore'>;
type ExploreTabNavProp = BottomTabNavigationProp<MainTabParamList, 'Explore'>;

const CATEGORIES = ['推荐', '中餐', '日料'];

const SEASONAL_ITEMS = [
  {
    id: 1,
    title: '肉桂苹果挞',
    subtitle: '温暖酥脆，甜蜜可口',
    price: '¥9.00',
    image: 'https://images.unsplash.com/photo-1620991565081-82743a5a499c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxibHVlYmVycnklMjBwYW5jYWtlc3xlbnwxfHx8fDE3NzQ2ODQxOTh8MA&ixlib=rb-4.1.0&q=80&w=1080',
  },
];

export function Explore() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const route = useRoute<ExploreRouteProp>();
  const navigation = useNavigation<NavProp>();
  const tabNavigation = useNavigation<ExploreTabNavProp>();
  const [activeCategory, setActiveCategory] = useState(0);
  const [showSearch, setShowSearch] = useState(false);
  const initialQuery = route.params?.initialQuery ?? '';
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const { history, favorites } = useApp();

  const navigateToDetail = (item: { id: number; title: string; image: string }) => {
    navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.image });
  };

  const activeCategoryName = CATEGORIES[activeCategory];
  const visibleCards = EXPLORE_CARDS.filter((item) => {
    const keyword = searchQuery.trim().toLowerCase();
    const matchesSearch =
      keyword.length === 0
        || item.title.toLowerCase().includes(keyword)
        || item.subtitle.toLowerCase().includes(keyword);
    const matchesCategory = activeCategoryName === '推荐' || item.category === activeCategoryName;
    return matchesSearch && matchesCategory;
  });
  const visibleSeasonal = SEASONAL_ITEMS.filter((item) => {
    const keyword = searchQuery.trim().toLowerCase();
    if (!keyword) return true;
    return item.title.toLowerCase().includes(keyword) || item.subtitle.toLowerCase().includes(keyword);
  });
  const matchedHistory = history.filter((item) =>
    item.title.toLowerCase().includes(searchQuery.trim().toLowerCase())
  ).slice(0, 3);
  const matchedFavorites = FAVORITES_DATA
    .filter((item) => favorites.includes(item.id))
    .filter((item) => item.title.toLowerCase().includes(searchQuery.trim().toLowerCase()))
    .slice(0, 3);
  const isSearching = searchQuery.trim().length > 0;

  React.useEffect(() => {
    const nextQuery = route.params?.initialQuery;
    if (typeof nextQuery === 'string') {
      setSearchQuery(nextQuery);
      tabNavigation.setParams({ initialQuery: undefined });
    }
  }, [route.params?.initialQuery, tabNavigation]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav — Page mode */}
      <View style={styles.topNav}>
        <Pressable
          style={({ pressed }) => [styles.navBtn, pressed && styles.pressed]}
          onPress={() => navigation.navigate('History')}
        >
          <Menu size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
        <Text style={styles.navTitle}>发现美食</Text>
        <Pressable
          style={({ pressed }) => [styles.navBtn, pressed && styles.pressed]}
          onPress={() => navigation.navigate('MainTabs', { screen: 'Profile' })}
        >
          <User size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      {/* Sticky Search + Categories */}
      <View style={styles.stickyBar}>
        <Pressable
          style={({ pressed }) => [styles.searchBar, pressed && { opacity: 0.85 }]}
          onPress={() => setShowSearch(true)}
        >
          <Search size={16} color={theme.colors.subtle} strokeWidth={1.8} />
          <Text style={styles.searchPlaceholder}>搜索美食或餐厅</Text>
        </Pressable>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.categoryScroll}
        >
          {CATEGORIES.map((cat, idx) => (
            <Pressable
              key={cat}
              style={({ pressed }) => [
                styles.categoryPill,
                idx === activeCategory && styles.categoryPillActive,
                pressed && { opacity: 0.85 },
              ]}
              onPress={() => setActiveCategory(idx)}
            >
              <Text
                style={[
                  styles.categoryPillText,
                  idx === activeCategory && styles.categoryPillTextActive,
                ]}
              >
                {cat}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Today's Picks */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>今日精选</Text>
            <Pressable onPress={() => setShowSearch(true)}>
              <Text style={styles.seeAllText}>查看全部</Text>
            </Pressable>
          </View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.picksScroll}
          >
            {visibleCards.length === 0 ? (
              <View style={styles.emptySearchState}>
                <Text style={styles.emptySearchTitle}>没有找到匹配结果</Text>
                <Text style={styles.emptySearchBody}>试试更短的关键词，或切换分类。</Text>
              </View>
            ) : (
              visibleCards.map((item) => (
                <Pressable
                  key={item.id}
                  style={({ pressed }) => [styles.pickCard, pressed && { opacity: 0.85 }]}
                  onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
                >
                  <View style={styles.pickImageWrap}>
                    <SkeletonImage src={item.image} alt={item.title} />
                    {item.badge && (
                      <View style={styles.pickBadge}>
                        <Text style={styles.pickBadgeText}>{item.badge}</Text>
                      </View>
                    )}
                  </View>
                  <Text style={styles.pickTitle}>{item.title}</Text>
                  <View style={styles.pickMetaRow}>
                    <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
                    <Text style={styles.pickMeta}>{item.rating} ({item.reviews}) · {item.subtitle}</Text>
                  </View>
                </Pressable>
              ))
            )}
          </ScrollView>
        </View>

        {isSearching && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>搜索到的历史记录</Text>
            {matchedHistory.length === 0 ? (
              <Text style={styles.searchSubtle}>暂无匹配历史</Text>
            ) : (
              matchedHistory.map((item) => (
                <Pressable
                  key={`history-${item.id}-${item.time}`}
                  style={({ pressed }) => [styles.searchHistoryItem, pressed && { opacity: 0.85 }]}
                  onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.img })}
                >
                  <Text style={styles.searchHistoryTitle}>{item.title}</Text>
                  <Text style={styles.searchHistoryMeta}>{item.category} · {item.time}</Text>
                </Pressable>
              ))
            )}
          </View>
        )}

        {isSearching && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>搜索到的收藏内容</Text>
            {matchedFavorites.length === 0 ? (
              <Text style={styles.searchSubtle}>暂无匹配收藏</Text>
            ) : (
              matchedFavorites.map((item) => (
                <Pressable
                  key={`favorite-${item.id}`}
                  style={({ pressed }) => [styles.searchHistoryItem, pressed && { opacity: 0.85 }]}
                  onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
                >
                  <Text style={styles.searchHistoryTitle}>{item.title}</Text>
                  <Text style={styles.searchHistoryMeta}>收藏夹内容</Text>
                </Pressable>
              ))
            )}
          </View>
        )}

        {/* Seasonal */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{isSearching ? '搜索到的时令推荐' : '时令推荐'}</Text>

          <Pressable
            style={({ pressed }) => [styles.seasonalHero, pressed && { opacity: 0.9 }]}
            onPress={() => navigateToDetail({ id: 100, title: '枫糖烤南瓜', image: 'https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?w=1080' })}
          >
            <SkeletonImage
              src="https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?w=1080"
              alt="Autumn Special"
            />
            <View style={styles.seasonalHeroOverlay}>
              <View style={styles.autumnBadge}>
                <Text style={styles.autumnBadgeText}>秋季限定</Text>
              </View>
              <Text style={styles.seasonalHeroTitle}>枫糖烤南瓜</Text>
              <Text style={styles.seasonalHeroSubtitle}>在每一口中感受季节的温暖</Text>
            </View>
          </Pressable>

          {visibleSeasonal.map((item) => (
            <Pressable
              key={item.id}
              style={({ pressed }) => [styles.listItem, pressed && { opacity: 0.85 }]}
              onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
            >
              <View style={styles.listItemImage}>
                <SkeletonImage src={item.image} alt={item.title} />
              </View>
              <View style={styles.listItemContent}>
                <Text style={styles.listItemTitle}>{item.title}</Text>
                <Text style={styles.listItemSubtitle}>{item.subtitle}</Text>
              </View>
              <View style={styles.listItemRight}>
                <Text style={styles.listItemPrice}>{item.price}</Text>
                <Pressable
                  style={({ pressed }) => [styles.addBtn, pressed && { backgroundColor: theme.colors.primaryLight }]}
                  onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
                >
                  <Plus size={16} color={theme.colors.primary} strokeWidth={2.5} />
                </Pressable>
              </View>
            </Pressable>
          ))}
          {isSearching && visibleSeasonal.length === 0 && (
            <Text style={styles.searchSubtle}>时令推荐暂无匹配结果</Text>
          )}
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>

      <SearchOverlay
        visible={showSearch}
        onClose={() => setShowSearch(false)}
        onSearch={(query) => {
          setSearchQuery(query);
          setShowSearch(false);
        }}
      />
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
  container: { flex: 1, backgroundColor: t.colors.background },
  pressed: { opacity: 0.85, transform: [{ scale: 0.97 }] },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    height: t.topNavHeight,
    backgroundColor: t.colors.surface,
  },
  navBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: t.radius.md },
  navTitle: { ...t.typography.h2, color: t.colors.foreground },
  stickyBar: {
    backgroundColor: t.colors.surface,
    paddingHorizontal: t.spacing.md,
    paddingTop: t.spacing.xs,
    paddingBottom: t.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
    gap: t.spacing.xs,
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: t.colors.borderLight,
    borderRadius: t.radius.md,
    paddingHorizontal: t.spacing.sm,
    height: 40,
    gap: t.spacing.xs,
  },
  searchPlaceholder: { ...t.typography.body, color: t.colors.subtle },
  categoryScroll: { flexDirection: 'row', gap: t.spacing.xs },
  categoryPill: {
    paddingHorizontal: t.spacing.md,
    paddingVertical: 6,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.borderLight,
  },
  categoryPillActive: { backgroundColor: t.colors.primary },
  categoryPillText: { ...t.typography.caption, fontWeight: '500', color: t.colors.muted },
  categoryPillTextActive: { color: t.colors.surface },
  scrollView: { flex: 1 },
  section: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.lg },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: t.spacing.sm },
  sectionTitle: { ...t.typography.h2, color: t.colors.foreground, marginBottom: t.spacing.sm },
  seeAllText: { ...t.typography.caption, color: t.colors.primary, fontWeight: '500' },
  picksScroll: { paddingRight: t.spacing.md, gap: t.spacing.sm },
  pickCard: { width: 200 },
  pickImageWrap: { height: 140, borderRadius: t.radius.md, overflow: 'hidden', marginBottom: t.spacing.xs, position: 'relative' },
  pickBadge: {
    position: 'absolute',
    top: t.spacing.xs,
    right: t.spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 3,
    borderRadius: t.radius.sm,
  },
  pickBadgeText: { ...t.typography.micro, fontWeight: '700', color: t.colors.foreground },
  pickTitle: { ...t.typography.body, fontWeight: '600', color: t.colors.foreground, marginBottom: 2 },
  pickMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  pickMeta: { ...t.typography.micro, color: t.colors.subtle },
  searchSubtle: { ...t.typography.caption, color: t.colors.subtle },
  searchHistoryItem: {
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.sm,
    marginBottom: t.spacing.xs,
    ...t.shadows.sm,
  },
  searchHistoryTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
  searchHistoryMeta: { ...t.typography.micro, color: t.colors.subtle, marginTop: 2 },
  emptySearchState: {
    width: 220,
    height: 140,
    borderRadius: t.radius.md,
    backgroundColor: t.colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: t.spacing.sm,
    ...t.shadows.sm,
  },
  emptySearchTitle: { ...t.typography.caption, fontWeight: '700', color: t.colors.foreground, marginBottom: 4, textAlign: 'center' },
  emptySearchBody: { ...t.typography.micro, color: t.colors.subtle, textAlign: 'center' },
  seasonalHero: {
    height: 180,
    borderRadius: t.radius.lg,
    overflow: 'hidden',
    marginBottom: t.spacing.sm,
    position: 'relative',
  },
  seasonalHeroOverlay: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    padding: t.spacing.md,
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  autumnBadge: {
    backgroundColor: t.colors.warning,
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 3,
    borderRadius: t.radius.sm,
    alignSelf: 'flex-start',
    marginBottom: 6,
  },
  autumnBadgeText: { ...t.typography.micro, fontWeight: '700', color: t.colors.surface },
  seasonalHeroTitle: { ...t.typography.h2, fontWeight: '700', color: t.colors.surface },
  seasonalHeroSubtitle: { ...t.typography.caption, color: 'rgba(255,255,255,0.8)', marginTop: 2 },
  listItem: {
    flexDirection: 'row',
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.sm,
    gap: t.spacing.sm,
    marginBottom: t.spacing.xs,
    alignItems: 'center',
    ...t.shadows.sm,
  },
  listItemImage: { width: 56, height: 56, borderRadius: t.radius.sm, overflow: 'hidden' },
  listItemContent: { flex: 1 },
  listItemTitle: { ...t.typography.body, fontWeight: '700', color: t.colors.foreground },
  listItemSubtitle: { ...t.typography.caption, color: t.colors.subtle, marginTop: 2 },
  listItemRight: { alignItems: 'flex-end', justifyContent: 'space-between', height: 56 },
  listItemPrice: { ...t.typography.body, fontWeight: '700', color: t.colors.primary },
  addBtn: {
    width: 28,
    height: 28,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.borderLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bottomPadding: { height: t.spacing['2xl'] },
});
}
