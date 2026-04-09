import React, { useMemo, useState } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import { Compass, Search, Sparkles, User } from 'lucide-react-native';
import type { MainTabParamList, RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { SkeletonImage } from '../components/SkeletonImage';
import { SearchOverlay } from '../components/SearchOverlay';
import { useApp } from '../context/AppContext';
import { getRecommendedDishes, getScenarioBuckets } from '../utils/recommendations';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type ExploreRouteProp = RouteProp<MainTabParamList, 'Explore'>;
type ExploreTabNavProp = BottomTabNavigationProp<MainTabParamList, 'Explore'>;

const SCENARIOS = ['全部', '快速决定', '轻负担', '安慰感'] as const;

export function Explore() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const route = useRoute<ExploreRouteProp>();
  const navigation = useNavigation<NavProp>();
  const tabNavigation = useNavigation<ExploreTabNavProp>();
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]>('全部');
  const [showSearch, setShowSearch] = useState(false);
  const initialQuery = route.params?.initialQuery ?? '';
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const { favorites, history, selectedCuisines, selectedRestrictions } = useApp();

  const recommendations = useMemo(
    () => getRecommendedDishes({ selectedCuisines, selectedRestrictions }),
    [selectedCuisines, selectedRestrictions],
  );
  const scenarioBuckets = useMemo(
    () => getScenarioBuckets({ selectedCuisines, selectedRestrictions }),
    [selectedCuisines, selectedRestrictions],
  );

  React.useEffect(() => {
    const nextQuery = route.params?.initialQuery;
    if (typeof nextQuery === 'string') {
      setSearchQuery(nextQuery);
      tabNavigation.setParams({ initialQuery: undefined });
    }
  }, [route.params?.initialQuery, tabNavigation]);

  const visibleCards = useMemo(() => {
    const keyword = searchQuery.trim().toLowerCase();
    const source =
      scenario === '快速决定'
        ? scenarioBuckets.quick
        : scenario === '轻负担'
          ? scenarioBuckets.healthy
          : scenario === '安慰感'
            ? scenarioBuckets.comfort
            : recommendations;

    return source.filter(({ dish }) => {
      if (keyword.length === 0) return true;
      return [
        dish.name,
        dish.subtitle,
        dish.cuisineLabel,
        ...dish.decisionTags,
        ...dish.healthTags,
      ].some((part) => part.toLowerCase().includes(keyword));
    });
  }, [recommendations, scenario, scenarioBuckets, searchQuery]);

  const matchedHistory = history
    .filter((item) => item.title.toLowerCase().includes(searchQuery.trim().toLowerCase()))
    .slice(0, 3);
  const matchedFavorites = recommendations
    .filter(({ dish }) => favorites.includes(dish.id))
    .filter(({ dish }) => dish.name.toLowerCase().includes(searchQuery.trim().toLowerCase()))
    .slice(0, 3);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <View>
          <Text style={styles.navTitle}>探索更多可行选择</Text>
          <Text style={styles.navSubtitle}>按场景而不是按随机图片来找吃的</Text>
        </View>
        <Pressable style={styles.navBtn} onPress={() => navigation.navigate('MainTabs', { screen: 'Profile' })}>
          <User size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      <View style={styles.stickyBar}>
        <Pressable style={styles.searchBar} onPress={() => setShowSearch(true)}>
          <Search size={16} color={theme.colors.subtle} strokeWidth={1.8} />
          <Text style={styles.searchPlaceholder}>{searchQuery || '按菜品、场景、口味、健康标签搜索'}</Text>
        </Pressable>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.categoryScroll}>
          {SCENARIOS.map((item) => (
            <Pressable
              key={item}
              style={[styles.categoryPill, scenario === item && styles.categoryPillActive]}
              onPress={() => setScenario(item)}
            >
              <Text style={[styles.categoryPillText, scenario === item && styles.categoryPillTextActive]}>{item}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        <View style={styles.heroSection}>
          <View style={styles.heroCard}>
            <View style={styles.heroHeader}>
              <Sparkles size={16} color={theme.colors.primary} strokeWidth={2} />
              <Text style={styles.heroTitle}>系统会优先把这些候选放到前面</Text>
            </View>
            <Text style={styles.heroBody}>
              {selectedCuisines.length > 0 || selectedRestrictions.length > 0
                ? '已结合你的口味与忌口，优先显示更像“现在就能决定”的选项。'
                : '你还没告诉系统太多偏好，所以这里先按大众友好、低后悔成本和当前时段组织内容。'}
            </Text>
          </View>
        </View>

        {searchQuery.trim().length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>与你搜索相关的历史选择</Text>
            {matchedHistory.length === 0 ? (
              <Text style={styles.searchSubtle}>暂无匹配历史</Text>
            ) : (
              matchedHistory.map((item) => (
                <View key={`${item.id}-${item.time}`} style={styles.inlineItem}>
                  <Text style={styles.inlineItemTitle}>{item.title}</Text>
                  <Text style={styles.inlineItemMeta}>{item.category} · {item.time}</Text>
                </View>
              ))
            )}
          </View>
        )}

        {searchQuery.trim().length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>与你搜索相关的已收藏内容</Text>
            {matchedFavorites.length === 0 ? (
              <Text style={styles.searchSubtle}>暂无匹配收藏</Text>
            ) : (
              matchedFavorites.map(({ dish }) => (
                <View key={dish.id} style={styles.inlineItem}>
                  <Text style={styles.inlineItemTitle}>{dish.name}</Text>
                  <Text style={styles.inlineItemMeta}>{dish.cuisineLabel} · {dish.price}</Text>
                </View>
              ))
            )}
          </View>
        )}

        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>{scenario === '全部' ? '今天适合深入看的候选' : `${scenario}候选`}</Text>
            <Pressable onPress={() => navigation.navigate('MainTabs', { screen: 'Home' })}>
              <View style={styles.secondaryLink}>
                <Compass size={14} color={theme.colors.primary} strokeWidth={2} />
                <Text style={styles.secondaryLinkText}>回到首页决策</Text>
              </View>
            </Pressable>
          </View>

          {visibleCards.length === 0 ? (
            <View style={styles.emptySearchState}>
              <Text style={styles.emptySearchTitle}>没有找到更合适的结果</Text>
              <Text style={styles.emptySearchBody}>换个关键词，或者回到首页继续滑动推荐，系统会根据你的操作持续调整排序。</Text>
            </View>
          ) : (
            visibleCards.map(({ dish, reasons }) => (
              <Pressable
                key={dish.id}
                style={styles.decisionRow}
                onPress={() => navigation.navigate('Detail', { itemId: dish.id, title: dish.name, image: dish.image })}
              >
                <View style={styles.decisionImage}>
                  <SkeletonImage src={dish.image} alt={dish.name} />
                </View>
                <View style={styles.decisionContent}>
                  <Text style={styles.decisionTitle}>{dish.name}</Text>
                  <Text style={styles.decisionSubtitle}>{dish.subtitle}</Text>
                  <View style={styles.reasonList}>
                    {reasons.slice(0, 2).map((reason) => (
                      <Text key={reason} style={styles.reasonItem}>• {reason}</Text>
                    ))}
                  </View>
                  <Text style={styles.decisionMeta}>{dish.price} · {dish.prepTime} · {dish.cuisineLabel}</Text>
                </View>
              </Pressable>
            ))
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
    topNav: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      paddingTop: t.spacing.xs,
      paddingBottom: t.spacing.sm,
      backgroundColor: t.colors.surface,
    },
    navTitle: { ...t.typography.h2, color: t.colors.foreground },
    navSubtitle: { ...t.typography.caption, color: t.colors.subtle, marginTop: 2 },
    navBtn: {
      width: 40,
      height: 40,
      borderRadius: t.radius.md,
      alignItems: 'center',
      justifyContent: 'center',
    },
    stickyBar: {
      backgroundColor: t.colors.surface,
      paddingHorizontal: t.spacing.md,
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
    searchPlaceholder: { ...t.typography.body, color: searchPlaceholderColor(t) },
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
    heroSection: {
      paddingHorizontal: t.spacing.md,
      paddingTop: t.spacing.lg,
    },
    heroCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.md,
      ...t.shadows.sm,
    },
    heroHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      marginBottom: 8,
    },
    heroTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    heroBody: { ...t.typography.caption, color: t.colors.muted, lineHeight: 18 },
    section: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.lg },
    sectionHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: t.spacing.sm,
    },
    sectionTitle: { ...t.typography.h2, color: t.colors.foreground },
    secondaryLink: { flexDirection: 'row', alignItems: 'center', gap: 4 },
    secondaryLinkText: { ...t.typography.caption, color: t.colors.primary, fontWeight: '700' },
    searchSubtle: { ...t.typography.caption, color: t.colors.subtle },
    inlineItem: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.sm,
      marginBottom: t.spacing.xs,
      ...t.shadows.sm,
    },
    inlineItemTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    inlineItemMeta: { ...t.typography.micro, color: t.colors.subtle, marginTop: 2 },
    decisionRow: {
      flexDirection: 'row',
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.sm,
      gap: t.spacing.sm,
      marginBottom: t.spacing.sm,
      ...t.shadows.sm,
    },
    decisionImage: {
      width: 88,
      height: 88,
      borderRadius: t.radius.sm,
      overflow: 'hidden',
    },
    decisionContent: { flex: 1 },
    decisionTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700', marginBottom: 2 },
    decisionSubtitle: { ...t.typography.caption, color: t.colors.muted, marginBottom: 6, lineHeight: 18 },
    reasonList: { gap: 4, marginBottom: 6 },
    reasonItem: { ...t.typography.micro, color: t.colors.primaryDark },
    decisionMeta: { ...t.typography.micro, color: t.colors.subtle },
    emptySearchState: {
      borderRadius: t.radius.md,
      backgroundColor: t.colors.surface,
      padding: t.spacing.md,
      ...t.shadows.sm,
    },
    emptySearchTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700', marginBottom: 4 },
    emptySearchBody: { ...t.typography.caption, color: t.colors.subtle, lineHeight: 18 },
    bottomPadding: { height: t.spacing['2xl'] },
  });
}

function searchPlaceholderColor(t: AppTheme) {
  return t.colors.subtle;
}
