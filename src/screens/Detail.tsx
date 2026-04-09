import React from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView, Share, Alert, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, { useAnimatedScrollHandler, useAnimatedStyle, useSharedValue } from 'react-native-reanimated';
import { ArrowLeft, CheckCircle2, Clock, Heart, Share2, ShieldCheck, Sparkles, Star } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';
import { SWIPE_CARDS } from '../data/mockData';
import { buildDecisionSnapshot, getRecommendationById, getRelatedRecommendations } from '../utils/recommendations';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type DetailRouteProp = RouteProp<RootStackParamList, 'Detail'>;

export function Detail() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const route = useRoute<DetailRouteProp>();
  const { width: screenWidth } = useWindowDimensions();
  const { addToHistory, isFavorite, selectedCuisines, selectedRestrictions, toggleFavorite } = useApp();

  const itemId = route.params?.itemId ?? SWIPE_CARDS[0].id;
  const fallbackDish = SWIPE_CARDS.find((item) => item.id === itemId) ?? SWIPE_CARDS[0];
  const recommendation = getRecommendationById(itemId, { selectedCuisines, selectedRestrictions });
  const dish = recommendation?.dish ?? fallbackDish;
  const reasons = recommendation?.reasons ?? [dish.recommendationBlurb];
  const decisionSnapshot = buildDecisionSnapshot(dish);
  const related = getRelatedRecommendations(dish.id, { selectedCuisines, selectedRestrictions });
  const liked = isFavorite(dish.id);

  const scrollY = useSharedValue(0);
  const scrollHandler = useAnimatedScrollHandler({
    onScroll: (event) => {
      scrollY.value = event.contentOffset.y;
    },
  });

  const navBarStyle = useAnimatedStyle(() => {
    const opacity = Math.min(1, Math.max(0, (scrollY.value - 120) / 90));
    return { backgroundColor: `rgba(250,250,248,${opacity})` };
  });

  const heroImageStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: scrollY.value * 0.35 }, { scale: 1 + scrollY.value * 0.0006 }],
  }));

  const handleShare = async () => {
    await Share.share({
      message: `我刚在 ChiShenMe 里看到一个很适合现在的选择：${dish.name}`,
    });
  };

  const handleChoose = async () => {
    await addToHistory({
      id: dish.id,
      title: dish.name,
      img: dish.image,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      createdAt: Date.now(),
      category: '今日已定',
      status: 'Liked',
    });
    Alert.alert('已为你记下', `${dish.name} 已加入今天的决策记录，晚点回来也能快速找到。`);
  };

  const compatibility =
    selectedRestrictions.length === 0
      ? '你还没有设置忌口，当前推荐以普适口味和场景优先。'
      : dish.restrictionConflicts.length === 0
        ? `已避开你设置的忌口：${selectedRestrictions.join('、')}。`
        : `需要注意：这道菜可能包含 ${dish.restrictionConflicts.join('、')}。`;

  return (
    <View style={styles.container}>
      <SafeAreaView edges={['top']} style={styles.navBarOuter}>
        <Animated.View style={[styles.navBar, navBarStyle]}>
          <Pressable style={styles.navCircle} onPress={() => navigation.goBack()}>
            <ArrowLeft size={18} color={theme.colors.foreground} strokeWidth={2} />
          </Pressable>
          <View style={styles.navRight}>
            <Pressable style={styles.navCircle} onPress={handleShare}>
              <Share2 size={16} color={theme.colors.foreground} strokeWidth={2} />
            </Pressable>
            <Pressable style={styles.navCircle} onPress={() => toggleFavorite(dish.id)}>
              <Heart size={16} color={liked ? theme.colors.error : theme.colors.foreground} fill={liked ? theme.colors.error : 'transparent'} strokeWidth={2} />
            </Pressable>
          </View>
        </Animated.View>
      </SafeAreaView>

      <Animated.ScrollView style={styles.scrollView} onScroll={scrollHandler} scrollEventThrottle={16} showsVerticalScrollIndicator={false}>
        <View style={styles.heroWrap}>
          <Animated.View style={[styles.heroImage, { width: screenWidth, height: 360 }, heroImageStyle]}>
            <SkeletonImage src={dish.image} alt={dish.name} />
          </Animated.View>
        </View>

        <View style={styles.content}>
          <View style={styles.titleCard}>
            <View style={styles.topline}>
              <View style={styles.categoryPill}>
                <Text style={styles.categoryPillText}>{dish.category}</Text>
              </View>
              <View style={styles.ratingBadge}>
                <Star size={12} color="#FFD700" fill="#FFD700" />
                <Text style={styles.ratingText}>{dish.rating}</Text>
              </View>
            </View>
            <Text style={styles.dishTitle}>{dish.name}</Text>
            <Text style={styles.dishSubtitle}>{dish.subtitle}</Text>
            <View style={styles.aiBadge}>
              <Sparkles size={12} color={theme.colors.primary} strokeWidth={2} />
              <Text style={styles.aiBadgeText}>现在推荐它，是因为它和你的当前情境更匹配</Text>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>为什么它适合你</Text>
            <View style={styles.reasonCard}>
              {reasons.map((reason) => (
                <View key={reason} style={styles.reasonRow}>
                  <CheckCircle2 size={14} color={theme.colors.primary} strokeWidth={2.3} />
                  <Text style={styles.reasonText}>{reason}</Text>
                </View>
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>做决定前的快照</Text>
            <View style={styles.snapshotGrid}>
              {decisionSnapshot.map((item) => (
                <View key={item.label} style={styles.snapshotCard}>
                  <Text style={styles.snapshotLabel}>{item.label}</Text>
                  <Text style={styles.snapshotValue}>{item.value}</Text>
                </View>
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>忌口与健康判断</Text>
            <View style={styles.compatibilityCard}>
              <View style={styles.compatibilityHeader}>
                <ShieldCheck size={16} color={theme.colors.primary} strokeWidth={2} />
                <Text style={styles.compatibilityTitle}>兼容性判断</Text>
              </View>
              <Text style={styles.compatibilityBody}>{compatibility}</Text>
              <View style={styles.nutritionRow}>
                <View style={styles.nutritionCell}>
                  <Text style={styles.nutritionLabel}>热量</Text>
                  <Text style={styles.nutritionValue}>{dish.nutrition.calories} kcal</Text>
                </View>
                <View style={styles.nutritionCell}>
                  <Text style={styles.nutritionLabel}>蛋白质</Text>
                  <Text style={styles.nutritionValue}>{dish.nutrition.protein}</Text>
                </View>
                <View style={styles.nutritionCell}>
                  <Text style={styles.nutritionLabel}>脂肪</Text>
                  <Text style={styles.nutritionValue}>{dish.nutrition.fat}</Text>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>如果你还没完全决定</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.relatedScroll}>
              {related.map(({ dish: alternative }) => (
                <Pressable
                  key={alternative.id}
                  style={styles.relatedCard}
                  onPress={() => navigation.replace('Detail', { itemId: alternative.id, title: alternative.name, image: alternative.image })}
                >
                  <View style={styles.relatedImage}>
                    <SkeletonImage src={alternative.image} alt={alternative.name} />
                  </View>
                  <Text style={styles.relatedTitle}>{alternative.name}</Text>
                  <Text style={styles.relatedMeta}>{alternative.price} · {alternative.prepTime}</Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>

          <View style={styles.bottomPadding} />
        </View>
      </Animated.ScrollView>

      <SafeAreaView edges={['bottom']} style={styles.actionBar}>
        <View>
          <Text style={styles.actionLabel}>当前决策建议</Text>
          <Text style={styles.actionSummary}>{dish.recommendationBlurb}</Text>
        </View>
        <View style={styles.actionButtons}>
          <Pressable style={[styles.secondaryButton, liked && styles.secondaryButtonActive]} onPress={() => toggleFavorite(dish.id)}>
            <Text style={[styles.secondaryButtonText, liked && styles.secondaryButtonTextActive]}>{liked ? '已收藏' : '先收藏'}</Text>
          </Pressable>
          <Pressable style={styles.primaryButton} onPress={handleChoose}>
            <Clock size={16} color={theme.colors.surface} strokeWidth={2.3} />
            <Text style={styles.primaryButtonText}>今天吃这个</Text>
          </Pressable>
        </View>
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
      backgroundColor: 'rgba(255,255,255,0.9)',
    },
    navRight: { flexDirection: 'row', gap: t.spacing.xs },
    scrollView: { flex: 1 },
    heroWrap: { height: 360, overflow: 'hidden' },
    heroImage: {},
    content: { paddingHorizontal: t.spacing.md, marginTop: -t.spacing.md },
    titleCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.lg,
      padding: t.spacing.lg,
      marginBottom: t.spacing.md,
      ...t.shadows.md,
    },
    topline: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: t.spacing.sm,
    },
    categoryPill: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.radius.full,
      paddingHorizontal: 12,
      paddingVertical: 4,
    },
    categoryPillText: {
      ...t.typography.caption,
      color: t.colors.primaryDark,
      fontWeight: '700',
    },
    ratingBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: t.colors.borderLight,
      borderRadius: t.radius.full,
      paddingHorizontal: 8,
      paddingVertical: 4,
    },
    ratingText: {
      ...t.typography.caption,
      color: t.colors.foreground,
      fontWeight: '700',
    },
    dishTitle: {
      fontSize: 24,
      lineHeight: 32,
      fontWeight: '700',
      color: t.colors.foreground,
      marginBottom: 6,
    },
    dishSubtitle: {
      ...t.typography.body,
      color: t.colors.muted,
      lineHeight: 22,
      marginBottom: t.spacing.sm,
    },
    aiBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    aiBadgeText: {
      ...t.typography.caption,
      color: t.colors.primary,
      fontWeight: '700',
      flex: 1,
    },
    section: { marginBottom: t.spacing.lg },
    sectionTitle: {
      ...t.typography.h2,
      color: t.colors.foreground,
      marginBottom: t.spacing.sm,
    },
    reasonCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.md,
      gap: t.spacing.sm,
      ...t.shadows.sm,
    },
    reasonRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 8,
    },
    reasonText: {
      ...t.typography.body,
      color: t.colors.foreground,
      flex: 1,
      lineHeight: 22,
    },
    snapshotGrid: {
      flexDirection: 'row',
      gap: t.spacing.xs,
    },
    snapshotCard: {
      flex: 1,
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.md,
      ...t.shadows.sm,
    },
    snapshotLabel: {
      ...t.typography.caption,
      color: t.colors.subtle,
      marginBottom: 4,
    },
    snapshotValue: {
      ...t.typography.body,
      color: t.colors.foreground,
      fontWeight: '700',
    },
    compatibilityCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.md,
      gap: t.spacing.sm,
      ...t.shadows.sm,
    },
    compatibilityHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    compatibilityTitle: {
      ...t.typography.body,
      color: t.colors.foreground,
      fontWeight: '700',
    },
    compatibilityBody: {
      ...t.typography.body,
      color: t.colors.muted,
      lineHeight: 22,
    },
    nutritionRow: {
      flexDirection: 'row',
      gap: t.spacing.xs,
    },
    nutritionCell: {
      flex: 1,
      backgroundColor: t.colors.borderLight,
      borderRadius: t.radius.md,
      padding: t.spacing.sm,
    },
    nutritionLabel: {
      ...t.typography.micro,
      color: t.colors.subtle,
      marginBottom: 2,
    },
    nutritionValue: {
      ...t.typography.caption,
      color: t.colors.foreground,
      fontWeight: '700',
    },
    relatedScroll: {
      paddingRight: t.spacing.md,
      gap: t.spacing.sm,
    },
    relatedCard: {
      width: 170,
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.sm,
      ...t.shadows.sm,
    },
    relatedImage: {
      height: 110,
      borderRadius: t.radius.sm,
      overflow: 'hidden',
      marginBottom: t.spacing.xs,
    },
    relatedTitle: {
      ...t.typography.body,
      color: t.colors.foreground,
      fontWeight: '700',
      marginBottom: 2,
    },
    relatedMeta: {
      ...t.typography.caption,
      color: t.colors.subtle,
    },
    bottomPadding: { height: 120 },
    actionBar: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      backgroundColor: t.colors.surface,
      paddingHorizontal: t.spacing.md,
      paddingTop: t.spacing.sm,
      paddingBottom: 8,
      gap: t.spacing.sm,
      ...t.shadows.lg,
    },
    actionLabel: {
      ...t.typography.micro,
      color: t.colors.subtle,
    },
    actionSummary: {
      ...t.typography.caption,
      color: t.colors.foreground,
      lineHeight: 18,
    },
    actionButtons: {
      flexDirection: 'row',
      gap: t.spacing.xs,
    },
    secondaryButton: {
      flex: 1,
      borderWidth: 1,
      borderColor: t.colors.border,
      borderRadius: t.radius.full,
      height: 46,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.surface,
    },
    secondaryButtonActive: {
      borderColor: t.colors.primary,
      backgroundColor: t.colors.primaryLight,
    },
    secondaryButtonText: {
      ...t.typography.body,
      color: t.colors.foreground,
      fontWeight: '700',
    },
    secondaryButtonTextActive: {
      color: t.colors.primaryDark,
    },
    primaryButton: {
      flex: 1.5,
      backgroundColor: t.colors.primary,
      borderRadius: t.radius.full,
      height: 46,
      alignItems: 'center',
      justifyContent: 'center',
      flexDirection: 'row',
      gap: 6,
    },
    primaryButtonText: {
      ...t.typography.body,
      color: t.colors.surface,
      fontWeight: '700',
    },
  });
}
