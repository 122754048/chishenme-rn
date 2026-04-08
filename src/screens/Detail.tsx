import React from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  useWindowDimensions,
  Share,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, { useAnimatedStyle, useSharedValue, useAnimatedScrollHandler } from 'react-native-reanimated';
import { ArrowLeft, Share2, Heart, Zap, Clock, UtensilsCrossed, Star, Plus } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type DetailRouteProp = RouteProp<RootStackParamList, 'Detail'>;

const PAIRINGS = [
  {
    id: 1,
    title: '羽衣甘蓝青葡萄汁',
    price: '¥28',
    badge: '清爽',
    image: 'https://images.unsplash.com/photo-1611497426695-412abe2f287b?w=400',
  },
  {
    id: 2,
    title: '日式味噌汤',
    price: '¥12',
    badge: '暖心',
    image: 'https://images.unsplash.com/photo-1763470260619-f971902b20db?w=400',
  },
];

export function Detail() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { toggleFavorite, isFavorite } = useApp();
  const { width: screenWidth } = useWindowDimensions();
  const route = useRoute<DetailRouteProp>();
  const itemId = route.params?.itemId ?? 0;
  const itemTitle = route.params?.title ?? 'Salmon Energy Bowl';
  const itemImage = route.params?.image ?? 'https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?w=1080';
  const liked = itemId > 0 && isFavorite(itemId);

  const scrollY = useSharedValue(0);

  const scrollHandler = useAnimatedScrollHandler({
    onScroll: (event) => {
      scrollY.value = event.contentOffset.y;
    },
  });

  const navBarStyle = useAnimatedStyle(() => {
    const opacity = Math.min(1, Math.max(0, (scrollY.value - 100) / 80));
    return {
      backgroundColor: `rgba(250,250,248,${opacity})`,
    };
  });

  const navBtnStyle = useAnimatedStyle(() => {
    const navOpaque = scrollY.value > 150;
    return {
      backgroundColor: navOpaque ? 'rgba(255,255,255,0.92)' : 'rgba(255,255,255,0.85)',
    };
  });

  const heroImageStyle = useAnimatedStyle(() => {
    return {
      transform: [
        { translateY: scrollY.value * 0.4 },
        { scale: 1 + scrollY.value * 0.0008 },
      ],
    };
  });

  const handleShare = async () => {
    await Share.share({
      message: `${itemTitle}\n${itemImage}`,
    });
  };

  return (
    <View style={styles.container}>
      {/* Overlay Nav Bar */}
      <SafeAreaView edges={['top']} style={styles.navBarOuter}>
        <Animated.View style={[styles.navBar, navBarStyle]}>
          <Pressable style={({ pressed }) => [pressed && { opacity: 0.7 }]} onPress={() => navigation.goBack()}>
            <Animated.View style={[styles.navCircle, navBtnStyle]}>
              <ArrowLeft size={18} color={theme.colors.foreground} strokeWidth={2} />
            </Animated.View>
          </Pressable>
          <View style={styles.navRight}>
            <Pressable style={({ pressed }) => [pressed && { opacity: 0.7 }]} onPress={handleShare}>
              <Animated.View style={[styles.navCircle, navBtnStyle]}>
                <Share2 size={16} color={theme.colors.foreground} strokeWidth={2} />
              </Animated.View>
            </Pressable>
            <Pressable
              style={({ pressed }) => [pressed && { opacity: 0.7 }]}
              onPress={() => {
                if (itemId > 0) toggleFavorite(itemId);
              }}
            >
              <Animated.View style={[styles.navCircle, navBtnStyle]}>
                <Heart
                  size={16}
                  color={liked ? theme.colors.error : theme.colors.foreground}
                  fill={liked ? theme.colors.error : 'transparent'}
                  strokeWidth={2}
                />
              </Animated.View>
            </Pressable>
          </View>
        </Animated.View>
      </SafeAreaView>

      <Animated.ScrollView
        style={styles.scrollView}
        onScroll={scrollHandler}
        scrollEventThrottle={16}
        showsVerticalScrollIndicator={false}
      >
        {/* Hero Image with parallax */}
        <View style={styles.heroWrap}>
          <Animated.View style={[styles.heroImage, { width: screenWidth, height: 360 }, heroImageStyle]}>
            <SkeletonImage src={itemImage} alt={itemTitle} />
          </Animated.View>
        </View>

        {/* Content */}
        <View style={styles.content}>
          {/* Title Card */}
          <View style={styles.titleCard}>
            <View style={styles.titleRow}>
              <Text style={styles.dishTitle}>{itemTitle}</Text>
              <View style={styles.calorieBadge}>
                <Text style={styles.calorieNum}>485</Text>
                <Text style={styles.calorieUnit}>千卡</Text>
              </View>
            </View>
            <View style={styles.aiBadge}>
              <Zap size={12} color={theme.colors.primary} fill={theme.colors.primary} />
              <Text style={styles.aiBadgeText}>AI 营养分析</Text>
            </View>
            <Text style={styles.aiDescription}>
              吃什么 AI 推荐：这道菜富含优质蛋白和 Omega-3 脂肪酸，低升糖指数的食材可以持续供能约 4 小时，非常适合午餐食用，帮助你保持下午的工作效率。
            </Text>
          </View>

          {/* Nutritional Facts */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>营养信息</Text>
            <View style={styles.nutriGrid}>
              {[
                { label: '蛋白质', value: '32g' },
                { label: '脂肪', value: '18g' },
                { label: '碳水', value: '45g' },
              ].map((n) => (
                <View key={n.label} style={styles.nutriCard}>
                  <Text style={styles.nutriLabel}>{n.label}</Text>
                  <Text style={styles.nutriValue}>{n.value}</Text>
                </View>
              ))}
            </View>
          </View>

          {/* Best Pairings */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>最佳搭配</Text>
              <Pressable>
                <Text style={styles.viewMore}>查看更多</Text>
              </Pressable>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.pairingsScroll}>
              {PAIRINGS.map((p) => (
                <View key={p.id} style={styles.pairingCard}>
                  <View style={styles.pairingImageWrap}>
                    <SkeletonImage src={p.image} alt={p.title} />
                    <View style={styles.pairingBadge}>
                      <Text style={styles.pairingBadgeText}>{p.badge}</Text>
                    </View>
                  </View>
                  <Text style={styles.pairingTitle}>{p.title}</Text>
                  <Text style={styles.pairingPrice}>{p.price}</Text>
                </View>
              ))}
            </ScrollView>
          </View>

          {/* Meal Prep */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>备餐详情</Text>
            <View style={styles.mealPrepCard}>
              <View style={styles.mealPrepRow}>
                <View style={[styles.mealPrepIconWrap, { backgroundColor: theme.colors.warningLight }]}>
                  <Clock size={16} color={theme.colors.warning} strokeWidth={2} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.mealPrepRowTitle}>准备时间</Text>
                  <Text style={styles.mealPrepRowBody}>预计 15-20 分钟</Text>
                </View>
              </View>
              <View style={styles.mealPrepRow}>
                <View style={[styles.mealPrepIconWrap, { backgroundColor: theme.colors.primaryLight }]}>
                  <UtensilsCrossed size={16} color={theme.colors.primary} strokeWidth={2} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.mealPrepRowTitle}>主厨贴士</Text>
                  <Text style={styles.mealPrepRowBody}>生鲑鱼建议在 30 分钟内食用，口感最佳。</Text>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.bottomPadding} />
        </View>
      </Animated.ScrollView>

      {/* Floating Action Bar */}
      <SafeAreaView edges={['bottom']} style={styles.actionBar}>
        <View>
          <Text style={styles.estimatedLabel}>预估总价</Text>
          <Text style={styles.estimatedPrice}>¥ 68.00</Text>
        </View>
        <Pressable style={({ pressed }) => [styles.addButton, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]}>
          <Plus size={18} color={theme.colors.surface} strokeWidth={2.5} />
          <Text style={styles.addButtonText}>加入菜单</Text>
        </Pressable>
      </SafeAreaView>
    </View>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
  container: { flex: 1, backgroundColor: t.colors.background },
  navBarOuter: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 100,
  },
  navBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    paddingBottom: t.spacing.xs,
  },
  navCircle: {
    width: 36,
    height: 36,
    borderRadius: t.radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  navRight: { flexDirection: 'row', gap: t.spacing.xs },
  scrollView: { flex: 1 },
  heroWrap: { height: 360, overflow: 'hidden', position: 'relative' },
  heroImage: {},
  content: { paddingHorizontal: t.spacing.md, marginTop: -t.spacing.md },
  titleCard: {
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.lg,
    padding: t.spacing.lg,
    marginBottom: t.spacing.md,
    ...t.shadows.md,
  },
  titleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: t.spacing.sm },
  dishTitle: { fontSize: 22, lineHeight: 30, fontWeight: '700', color: t.colors.foreground, flex: 1 },
  calorieBadge: {
    backgroundColor: t.colors.success,
    borderRadius: t.radius.md,
    paddingHorizontal: t.spacing.sm,
    paddingVertical: 6,
    alignItems: 'center',
  },
  calorieNum: { ...t.typography.h2, fontWeight: '700', color: t.colors.surface },
  calorieUnit: { ...t.typography.micro, color: t.colors.surface },
  aiBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: t.spacing.xs },
  aiBadgeText: { ...t.typography.caption, color: t.colors.primary, fontWeight: '600' },
  aiDescription: { ...t.typography.body, color: t.colors.muted, lineHeight: 20 },
  section: { marginBottom: t.spacing.lg },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: t.spacing.sm },
  sectionTitle: { ...t.typography.h2, color: t.colors.foreground, marginBottom: t.spacing.sm },
  viewMore: { ...t.typography.caption, color: t.colors.primary, fontWeight: '500' },
  nutriGrid: { flexDirection: 'row', gap: t.spacing.xs },
  nutriCard: {
    flex: 1,
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.md,
    alignItems: 'center',
    ...t.shadows.sm,
  },
  nutriLabel: { ...t.typography.caption, color: t.colors.subtle, marginBottom: 4 },
  nutriValue: { fontSize: 17, lineHeight: 24, fontWeight: '700', color: t.colors.foreground },
  pairingsScroll: { paddingRight: t.spacing.md, gap: t.spacing.sm },
  pairingCard: { width: 140 },
  pairingImageWrap: { height: 140, borderRadius: t.radius.md, overflow: 'hidden', marginBottom: t.spacing.xs, position: 'relative' },
  pairingBadge: {
    position: 'absolute',
    top: t.spacing.xs,
    right: t.spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: t.radius.sm,
  },
  pairingBadgeText: { ...t.typography.micro, fontWeight: '700', color: t.colors.foreground },
  pairingTitle: { ...t.typography.body, fontWeight: '600', color: t.colors.foreground, marginBottom: 2 },
  pairingPrice: { ...t.typography.caption, color: t.colors.subtle },
  mealPrepCard: {
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.md,
    gap: t.spacing.md,
    ...t.shadows.sm,
  },
  mealPrepRow: { flexDirection: 'row', gap: t.spacing.sm, alignItems: 'flex-start' },
  mealPrepIconWrap: {
    width: 40,
    height: 40,
    borderRadius: t.radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mealPrepRowTitle: { ...t.typography.body, fontWeight: '700', color: t.colors.foreground, marginBottom: 2 },
  mealPrepRowBody: { ...t.typography.caption, color: t.colors.subtle, lineHeight: 18 },
  bottomPadding: { height: 100 },
  actionBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: t.colors.surface,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: t.spacing.lg,
    paddingTop: t.spacing.sm,
    paddingBottom: 4,
    ...t.shadows.lg,
  },
  estimatedLabel: { ...t.typography.micro, color: t.colors.subtle, letterSpacing: 0.5 },
  estimatedPrice: { ...t.typography.h1, color: t.colors.foreground, marginTop: 2 },
  addButton: {
    backgroundColor: t.colors.primary,
    borderRadius: t.radius.full,
    paddingHorizontal: t.spacing.lg,
    height: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    ...t.shadows.md,
  },
  addButtonText: { ...t.typography.body, fontWeight: '700', color: t.colors.surface },
});
}
