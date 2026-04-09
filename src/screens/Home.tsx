import React, { useCallback, useMemo, useState } from 'react';
import { View, Text, Pressable, StyleSheet, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, {
  Extrapolation,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { CheckCircle2, ChevronRight, Compass, Heart, Search, Sparkles, Star, X } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { SkeletonImage } from '../components/SkeletonImage';
import { OnboardingGuide } from '../components/OnboardingGuide';
import { SearchOverlay } from '../components/SearchOverlay';
import { useApp } from '../context/AppContext';
import type { SwipeCardData } from '../data/mockData';
import { getRecommendedDishes } from '../utils/recommendations';

const SWIPE_THRESHOLD = 100;

type NavProp = NativeStackNavigationProp<RootStackParamList>;

function inferMealTypeByHour() {
  const hour = new Date().getHours();
  if (hour < 10) return '早餐' as const;
  if (hour < 15) return '午餐' as const;
  if (hour < 18) return '下午茶' as const;
  if (hour < 22) return '晚餐' as const;
  return '夜宵' as const;
}

function DecisionCard({
  card,
  reasons,
  onSwipe,
  onOpenDetail,
  screenWidth,
  styles,
  enabled,
  cardHeight,
}: {
  card: SwipeCardData;
  reasons: string[];
  onSwipe: (dir: 'left' | 'right') => void;
  onOpenDetail: () => void;
  screenWidth: number;
  styles: ReturnType<typeof makeStyles>;
  enabled: boolean;
  cardHeight: number;
}) {
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  const panGesture = Gesture.Pan()
    .enabled(enabled)
    .onUpdate((event) => {
      translateX.value = event.translationX;
      translateY.value = event.translationY * 0.2;
    })
    .onEnd((event) => {
      if (event.translationX > SWIPE_THRESHOLD || event.velocityX > 500) {
        translateX.value = withTiming(screenWidth * 1.5, { duration: 240 });
        runOnJS(onSwipe)('right');
      } else if (event.translationX < -SWIPE_THRESHOLD || event.velocityX < -500) {
        translateX.value = withTiming(-screenWidth * 1.5, { duration: 240 });
        runOnJS(onSwipe)('left');
      } else {
        translateX.value = withSpring(0);
        translateY.value = withSpring(0);
      }
    });

  const cardAnimStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { rotate: `${translateX.value / 28}deg` },
    ],
  }));

  const positiveOpacity = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [0, 80], [0, 1], Extrapolation.CLAMP),
  }));

  const negativeOpacity = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [-80, 0], [1, 0], Extrapolation.CLAMP),
  }));

  return (
    <GestureDetector gesture={panGesture}>
      <Animated.View style={[styles.card, { width: screenWidth - 32, height: cardHeight }, cardAnimStyle]}>
        <Animated.View style={[styles.badgeLike, positiveOpacity]}>
          <Text style={styles.badgeLikeText}>今天吃这个</Text>
        </Animated.View>
        <Animated.View style={[styles.badgeNope, negativeOpacity]}>
          <Text style={styles.badgeNopeText}>先看看别的</Text>
        </Animated.View>

        <Pressable style={styles.cardImage} onPress={onOpenDetail}>
          <SkeletonImage src={card.image} alt={card.name} />
          <View style={styles.cardInfoOverlay}>
            <View style={styles.cardInfoTopRow}>
              <View style={styles.categoryPill}>
                <Text style={styles.categoryPillText}>{card.category}</Text>
              </View>
              <View style={styles.ratingBadge}>
                <Star size={12} color="#FFD700" fill="#FFD700" />
                <Text style={styles.ratingText}>{card.rating}</Text>
              </View>
            </View>

            <Text style={styles.cardName}>{card.name}</Text>
            <Text style={styles.cardSubtitle}>{card.subtitle}</Text>

            <View style={styles.cardMetaRow}>
              <Text style={styles.cardMetaText}>{card.cuisineLabel}</Text>
              <Text style={styles.cardMetaDot}>·</Text>
              <Text style={styles.cardMetaText}>{card.price}</Text>
              <Text style={styles.cardMetaDot}>·</Text>
              <Text style={styles.cardMetaText}>{card.prepTime}</Text>
            </View>

            <View style={styles.reasonPanel}>
              <View style={styles.reasonHeader}>
                <Sparkles size={14} color="#FFFFFF" strokeWidth={2} />
                <Text style={styles.reasonTitle}>为什么现在推荐它</Text>
              </View>
              {reasons.map((reason) => (
                <View key={reason} style={styles.reasonRow}>
                  <CheckCircle2 size={12} color="#FFFFFF" strokeWidth={2.4} />
                  <Text style={styles.reasonText}>{reason}</Text>
                </View>
              ))}
            </View>

            <View style={styles.cardTagRow}>
              {card.decisionTags.slice(0, 3).map((tag) => (
                <Text key={tag} style={styles.cardTag}>{tag}</Text>
              ))}
            </View>

            <Pressable style={styles.detailLink} onPress={onOpenDetail}>
              <Text style={styles.detailLinkText}>查看完整决策理由</Text>
              <ChevronRight size={14} color="#FFFFFF" strokeWidth={2} />
            </Pressable>
          </View>
        </Pressable>
      </Animated.View>
    </GestureDetector>
  );
}

function AnimatedActionBtn({
  onPress,
  children,
  style,
  label,
  disabled,
}: {
  onPress: () => void;
  children: React.ReactNode;
  style?: object;
  label?: string;
  disabled?: boolean;
}) {
  const scale = useSharedValue(1);
  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const handlePress = () => {
    if (disabled) return;
    scale.value = withSequence(
      withSpring(0.88, { damping: 8 }),
      withSpring(1.06, { damping: 7 }),
      withSpring(1, { damping: 10 }),
    );
    onPress();
  };

  return (
    <Pressable
      onPress={handlePress}
      style={actionBtnStyles.wrapper}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: Boolean(disabled) }}
      hitSlop={8}
    >
      <Animated.View style={[style, animStyle, disabled && actionBtnStyles.disabled]}>{children}</Animated.View>
      {label ? <Text style={actionBtnStyles.label}>{label}</Text> : null}
    </Pressable>
  );
}

const actionBtnStyles = StyleSheet.create({
  wrapper: { alignItems: 'center', gap: 6 },
  label: { fontSize: 11, fontWeight: '500', color: '#9CA3AF', marginTop: 2 },
  disabled: { opacity: 0.45 },
});

export function Home() {
  const navigation = useNavigation<NavProp>();
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const { height: screenHeight, width: screenWidth } = useWindowDimensions();
  const {
    addToHistory,
    toggleFavorite,
    recommendationsLeft,
    consumeRecommendation,
    selectedCuisines,
    selectedRestrictions,
  } = useApp();
  const [cardIndex, setCardIndex] = useState(0);
  const [showSearch, setShowSearch] = useState(false);

  const isUnlimitedPlan = recommendationsLeft < 0;
  const quotaLocked = !isUnlimitedPlan && recommendationsLeft <= 0;
  const cardHeight = Math.min(Math.max(screenHeight * 0.62, 468), 620);
  const preferredMealType = inferMealTypeByHour();

  const recommendations = useMemo(
    () => getRecommendedDishes({ selectedCuisines, selectedRestrictions, preferredMealType }),
    [selectedCuisines, selectedRestrictions, preferredMealType],
  );

  const currentRecommendation = recommendations[cardIndex % Math.max(recommendations.length, 1)];
  const currentCard = currentRecommendation?.dish ?? null;
  const reasons = currentRecommendation?.reasons ?? [];

  const openDetail = useCallback(() => {
    if (!currentCard) return;
    navigation.navigate('Detail', { itemId: currentCard.id, title: currentCard.name, image: currentCard.image });
  }, [currentCard, navigation]);

  const handleDecision = useCallback(
    (direction: 'left' | 'right') => {
      if (quotaLocked || !currentCard) return;
      void addToHistory({
        id: currentCard.id,
        title: currentCard.name,
        img: currentCard.image,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        createdAt: Date.now(),
        category: currentCard.category,
        status: direction === 'right' ? 'Liked' : 'Skipped',
      });
      consumeRecommendation();
      setCardIndex((prev) => prev + 1);
    },
    [addToHistory, consumeRecommendation, currentCard, quotaLocked],
  );

  const handleSave = useCallback(() => {
    if (quotaLocked || !currentCard) return;
    void toggleFavorite(currentCard.id);
    handleDecision('right');
  }, [currentCard, handleDecision, quotaLocked, toggleFavorite]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topBar}>
        <View>
          <Text style={styles.brandText}>ChiShenMe</Text>
          <Text style={styles.recommendationsHint}>
            {isUnlimitedPlan ? '无限次做出今天这顿饭的决定' : `今日还可做 ${recommendationsLeft} 次智能推荐决策`}
          </Text>
        </View>
        <View style={styles.topBarRight}>
          <Pressable
            style={({ pressed }) => [styles.topBarIconBtn, pressed && styles.pressed]}
            onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
            accessibilityRole="button"
            accessibilityLabel="去发现更多选择"
            hitSlop={8}
          >
            <Compass size={20} color={theme.colors.foreground} strokeWidth={1.8} />
          </Pressable>
          <Pressable
            style={({ pressed }) => [styles.topBarIconBtn, pressed && styles.pressed]}
            onPress={() => setShowSearch(true)}
            accessibilityRole="button"
            accessibilityLabel="搜索美食或餐厅"
            hitSlop={8}
          >
            <Search size={20} color={theme.colors.foreground} strokeWidth={1.8} />
          </Pressable>
        </View>
      </View>

      <View style={styles.contextStrip}>
        <Text style={styles.contextTitle}>现在更适合的决策方向</Text>
        <View style={styles.contextChips}>
          <View style={styles.contextChip}>
            <Text style={styles.contextChipText}>{preferredMealType}</Text>
          </View>
          {selectedCuisines.length > 0 ? (
            <View style={styles.contextChip}>
              <Text style={styles.contextChipText}>已读懂你的口味偏好</Text>
            </View>
          ) : (
            <Pressable style={styles.contextChip} onPress={() => navigation.navigate('OnboardingCuisines')}>
              <Text style={styles.contextChipText}>先完善口味偏好</Text>
            </Pressable>
          )}
        </View>
      </View>

      {quotaLocked && (
        <View style={styles.limitBar}>
          <Text style={styles.limitText}>基础版今日决策次数已用完。升级后可获得更精准的推荐解释、更多备选方案和不限次决策。</Text>
          <Pressable
            onPress={() => navigation.navigate('Upgrade')}
            accessibilityRole="button"
            accessibilityLabel="升级为更强的智能决策体验"
            hitSlop={8}
          >
            <Text style={styles.limitAction}>去升级</Text>
          </Pressable>
        </View>
      )}

      {!quotaLocked && selectedCuisines.length === 0 && selectedRestrictions.length === 0 && (
        <Pressable
          style={styles.profilePrompt}
          onPress={() => navigation.navigate('OnboardingCuisines')}
          accessibilityRole="button"
          accessibilityLabel="完善口味偏好以提升命中率"
        >
          <Text style={styles.profilePromptText}>先补齐口味和忌口，推荐会更像真正懂你的决策助手。</Text>
        </Pressable>
      )}

      <View style={styles.cardContainer}>
        {currentCard ? (
          <DecisionCard
            key={`${currentCard.id}-${cardIndex}`}
            card={currentCard}
            reasons={reasons}
            onSwipe={handleDecision}
            onOpenDetail={openDetail}
            screenWidth={screenWidth}
            styles={styles}
            enabled={!quotaLocked}
            cardHeight={cardHeight}
          />
        ) : (
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>还没有适合当前偏好的推荐</Text>
            <Text style={styles.emptyBody}>调整一下口味偏好或探索更多分类，系统会重新帮你组织候选项。</Text>
          </View>
        )}
      </View>

      <View style={styles.actionRow}>
        <AnimatedActionBtn
          style={[styles.actionBtn, styles.skipBtn]}
          onPress={() => handleDecision('left')}
          label="先跳过"
          disabled={quotaLocked || !currentCard}
        >
          <X size={24} color={theme.colors.muted} strokeWidth={2.5} />
        </AnimatedActionBtn>

        <AnimatedActionBtn
          style={[styles.actionBtn, styles.favoriteBtn]}
          onPress={handleSave}
          label="存起来"
          disabled={quotaLocked || !currentCard}
        >
          <Star size={24} color={theme.colors.primary} strokeWidth={2} />
        </AnimatedActionBtn>

        <AnimatedActionBtn
          style={[styles.actionBtn, styles.likeBtn]}
          onPress={() => handleDecision('right')}
          label="今天吃这个"
          disabled={quotaLocked || !currentCard}
        >
          <Heart size={24} color="#EF4444" fill="#EF4444" strokeWidth={0} />
        </AnimatedActionBtn>
      </View>

      <OnboardingGuide />
      <SearchOverlay
        visible={showSearch}
        onClose={() => setShowSearch(false)}
        onSearch={(query) => {
          navigation.navigate('MainTabs', { screen: 'Explore', params: { initialQuery: query } });
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
    topBar: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      height: 56,
    },
    brandText: {
      fontSize: 22,
      fontWeight: '800',
      color: t.colors.primary,
    },
    recommendationsHint: {
      ...t.typography.micro,
      color: t.colors.subtle,
      marginTop: 2,
    },
    topBarRight: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
    },
    topBarIconBtn: {
      width: 40,
      height: 40,
      borderRadius: t.radius.md,
      alignItems: 'center',
      justifyContent: 'center',
    },
    contextStrip: {
      paddingHorizontal: t.spacing.md,
      marginBottom: t.spacing.xs,
    },
    contextTitle: {
      ...t.typography.caption,
      color: t.colors.subtle,
      marginBottom: 8,
      fontWeight: '600',
    },
    contextChips: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
    },
    contextChip: {
      backgroundColor: t.colors.borderLight,
      borderRadius: t.radius.full,
      paddingHorizontal: 12,
      paddingVertical: 6,
    },
    contextChipText: {
      ...t.typography.caption,
      color: t.colors.foreground,
      fontWeight: '600',
    },
    limitBar: {
      marginHorizontal: t.spacing.md,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.xs,
      backgroundColor: t.colors.warningLight,
      borderRadius: t.radius.md,
      paddingHorizontal: t.spacing.sm,
      paddingVertical: t.spacing.sm,
      gap: 8,
    },
    limitText: {
      ...t.typography.caption,
      color: t.colors.foreground,
      lineHeight: 18,
    },
    limitAction: {
      ...t.typography.caption,
      color: t.colors.primary,
      fontWeight: '700',
    },
    profilePrompt: {
      marginHorizontal: t.spacing.md,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.xs,
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.radius.md,
      paddingHorizontal: t.spacing.sm,
      paddingVertical: t.spacing.sm,
    },
    profilePromptText: {
      ...t.typography.caption,
      color: t.colors.primaryDark,
      fontWeight: '600',
      lineHeight: 18,
    },
    cardContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: t.spacing.md,
    },
    card: {
      borderRadius: 16,
      overflow: 'hidden',
      backgroundColor: t.colors.surface,
      ...t.shadows.lg,
    },
    badgeLike: {
      position: 'absolute',
      top: 24,
      left: 20,
      zIndex: 10,
      borderWidth: 3,
      borderColor: '#4CAF50',
      backgroundColor: 'rgba(76,175,80,0.2)',
      borderRadius: t.radius.sm,
      paddingHorizontal: 16,
      paddingVertical: 8,
      transform: [{ rotate: '-12deg' }],
    },
    badgeLikeText: {
      fontSize: 18,
      fontWeight: '800',
      color: '#4CAF50',
    },
    badgeNope: {
      position: 'absolute',
      top: 24,
      right: 20,
      zIndex: 10,
      borderWidth: 3,
      borderColor: '#EF4444',
      backgroundColor: 'rgba(239,68,68,0.2)',
      borderRadius: t.radius.sm,
      paddingHorizontal: 16,
      paddingVertical: 8,
      transform: [{ rotate: '12deg' }],
    },
    badgeNopeText: {
      fontSize: 18,
      fontWeight: '800',
      color: '#EF4444',
    },
    cardImage: {
      width: '100%',
      height: '100%',
      position: 'relative',
    },
    cardInfoOverlay: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      paddingHorizontal: 20,
      paddingBottom: 24,
      paddingTop: 76,
      backgroundColor: 'rgba(0,0,0,0.48)',
    },
    cardInfoTopRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      marginBottom: 8,
    },
    categoryPill: {
      backgroundColor: t.colors.primary,
      paddingHorizontal: 12,
      paddingVertical: 4,
      borderRadius: t.radius.full,
    },
    categoryPillText: {
      fontSize: 12,
      fontWeight: '700',
      color: '#FFFFFF',
    },
    ratingBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: 'rgba(255,255,255,0.2)',
      paddingHorizontal: 8,
      paddingVertical: 4,
      borderRadius: t.radius.full,
    },
    ratingText: {
      fontSize: 12,
      fontWeight: '600',
      color: '#FFFFFF',
    },
    cardName: {
      fontSize: 24,
      fontWeight: '700',
      color: '#FFFFFF',
      marginBottom: 4,
    },
    cardSubtitle: {
      ...t.typography.caption,
      color: 'rgba(255,255,255,0.88)',
      lineHeight: 18,
      marginBottom: 8,
    },
    cardMetaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      marginBottom: 12,
    },
    cardMetaText: {
      fontSize: 13,
      fontWeight: '500',
      color: 'rgba(255,255,255,0.9)',
    },
    cardMetaDot: {
      fontSize: 13,
      color: 'rgba(255,255,255,0.5)',
    },
    reasonPanel: {
      backgroundColor: 'rgba(255,255,255,0.14)',
      borderRadius: t.radius.md,
      padding: 12,
      marginBottom: 12,
      gap: 8,
    },
    reasonHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    reasonTitle: {
      ...t.typography.caption,
      color: '#FFFFFF',
      fontWeight: '700',
    },
    reasonRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    reasonText: {
      ...t.typography.caption,
      color: 'rgba(255,255,255,0.92)',
      flex: 1,
      lineHeight: 18,
    },
    cardTagRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
      marginBottom: 10,
    },
    cardTag: {
      fontSize: 12,
      fontWeight: '600',
      color: 'rgba(255,255,255,0.88)',
    },
    detailLink: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      alignSelf: 'flex-start',
    },
    detailLinkText: {
      ...t.typography.caption,
      color: '#FFFFFF',
      fontWeight: '700',
    },
    actionRow: {
      flexDirection: 'row',
      justifyContent: 'center',
      alignItems: 'center',
      gap: 28,
      paddingVertical: 16,
      paddingBottom: 8,
    },
    actionBtn: {
      width: 60,
      height: 60,
      borderRadius: 30,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.surface,
      borderWidth: 2,
      ...t.shadows.md,
    },
    skipBtn: {
      borderColor: t.colors.border,
    },
    favoriteBtn: {
      borderColor: t.colors.primary,
    },
    likeBtn: {
      borderColor: '#EF4444',
    },
    emptyState: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.lg,
      padding: t.spacing.lg,
      alignItems: 'center',
      gap: 8,
      ...t.shadows.sm,
    },
    emptyTitle: {
      ...t.typography.h2,
      color: t.colors.foreground,
    },
    emptyBody: {
      ...t.typography.body,
      color: t.colors.subtle,
      textAlign: 'center',
      lineHeight: 22,
    },
  });
}
