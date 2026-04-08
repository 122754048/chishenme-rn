import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Dimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
  withSequence,
  runOnJS,
  interpolate,
  Extrapolation,
} from 'react-native-reanimated';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { X, Heart, Star, MapPin, SlidersHorizontal, Search } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { SWIPE_CARDS } from '../data/mockData';
import type { SwipeCardData } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { OnboardingGuide } from '../components/OnboardingGuide';
import { useApp } from '../context/AppContext';
import { SearchOverlay } from '../components/SearchOverlay';

const { height: SCREEN_HEIGHT, width: SCREEN_WIDTH } = Dimensions.get('window');
const CARD_HEIGHT = Math.max(SCREEN_HEIGHT * 0.65, 520);
const SWIPE_THRESHOLD = 100;

type NavProp = NativeStackNavigationProp<RootStackParamList>;

/* ─── Swipe Card ─── */
function SwipeCard({
  card,
  onSwipe,
  screenWidth,
  styles,
}: {
  card: SwipeCardData;
  onSwipe: (dir: 'left' | 'right') => void;
  screenWidth: number;
  styles: ReturnType<typeof makeStyles>;
}) {
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  const panGesture = Gesture.Pan()
    .onUpdate((event) => {
      translateX.value = event.translationX;
      translateY.value = event.translationY * 0.4;
    })
    .onEnd((event) => {
      if (event.translationX > SWIPE_THRESHOLD || event.velocityX > 500) {
        translateX.value = withTiming(screenWidth * 1.5, { duration: 300 });
        runOnJS(onSwipe)('right');
      } else if (event.translationX < -SWIPE_THRESHOLD || event.velocityX < -500) {
        translateX.value = withTiming(-screenWidth * 1.5, { duration: 300 });
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
      { rotate: `${translateX.value / 20}deg` },
    ],
  }));

  const likeOpacity = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [0, 80], [0, 1], Extrapolation.CLAMP),
  }));

  const nopeOpacity = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [-80, 0], [1, 0], Extrapolation.CLAMP),
  }));

  return (
    <GestureDetector gesture={panGesture}>
      <Animated.View style={[styles.card, { width: screenWidth - 32 }, cardAnimStyle]}>
        {/* LIKE / NOPE overlays */}
        <Animated.View style={[styles.badgeLike, likeOpacity]}>
          <Text style={styles.badgeLikeText}>喜欢</Text>
        </Animated.View>
        <Animated.View style={[styles.badgeNope, nopeOpacity]}>
          <Text style={styles.badgeNopeText}>跳过</Text>
        </Animated.View>

        {/* Full-height image with overlay info */}
        <View style={styles.cardImage}>
          <SkeletonImage src={card.image} alt={card.name} />
          {/* Gradient overlay - bottom half */}
          <View style={styles.cardGradientOverlay} />

          {/* Info overlaid on image bottom */}
          <View style={styles.cardInfoOverlay}>
            {/* Category pill + Rating */}
            <View style={styles.cardInfoTopRow}>
              <View style={styles.categoryPill}>
                <Text style={styles.categoryPillText}>{card.category}</Text>
              </View>
              <View style={styles.ratingBadge}>
                <Star size={12} color="#FFD700" fill="#FFD700" />
                <Text style={styles.ratingText}>{card.rating}</Text>
              </View>
            </View>

            {/* Dish Name */}
            <Text style={styles.cardName}>{card.name}</Text>

            {/* Distance + Price + PrepTime */}
            <View style={styles.cardMetaRow}>
              <MapPin size={12} color="rgba(255,255,255,0.85)" />
              <Text style={styles.cardMetaText}>{card.distance}</Text>
              <Text style={styles.cardMetaDot}>·</Text>
              <Text style={styles.cardMetaText}>{card.price}</Text>
              <Text style={styles.cardMetaDot}>·</Text>
              <Text style={styles.cardMetaText}>{card.prepTime}</Text>
            </View>

            {/* Tags */}
            <View style={styles.cardTagRow}>
              {card.tags.map((tag) => (
                <Text key={tag} style={styles.cardTag}>{tag}</Text>
              ))}
            </View>
          </View>
        </View>
      </Animated.View>
    </GestureDetector>
  );
}

/* ─── Animated Action Button ─── */
function AnimatedActionBtn({
  onPress,
  children,
  style,
  label,
}: {
  onPress: () => void;
  children: React.ReactNode;
  style?: object;
  label?: string;
}) {
  const scale = useSharedValue(1);
  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const handlePress = () => {
    scale.value = withSequence(
      withSpring(0.85, { damping: 8 }),
      withSpring(1.1, { damping: 6 }),
      withSpring(1, { damping: 10 })
    );
    onPress();
  };

  return (
    <Pressable onPress={handlePress} style={actionBtnStyles.wrapper}>
      <Animated.View style={[style, animStyle]}>{children}</Animated.View>
      {label ? <Text style={actionBtnStyles.label}>{label}</Text> : null}
    </Pressable>
  );
}

/* Static styles for sub-component (avoids scope issues with makeStyles) */
const actionBtnStyles = StyleSheet.create({
  wrapper: { alignItems: 'center', gap: 6 },
  label: { fontSize: 11, fontWeight: '500', color: '#9CA3AF', marginTop: 2 },
});

/* ═══════════ Home Screen ═══════════ */
export function Home() {
  const navigation = useNavigation<NavProp>();
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const {
    addToHistory,
    toggleFavorite,
    recommendationsLeft,
    refreshRecommendations,
    consumeRecommendation,
    selectedCuisines,
    selectedRestrictions,
  } = useApp();
  const [cardIndex, setCardIndex] = useState(0);
  const [showSearch, setShowSearch] = useState(false);

  const handleSwipe = useCallback(
    (direction: 'left' | 'right' = 'right') => {
      const currentCard = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];
      addToHistory({
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
    [cardIndex, addToHistory, consumeRecommendation]
  );

  const handleFavorite = useCallback(() => {
    const currentCard = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];
    addToHistory({
      id: currentCard.id,
      title: currentCard.name,
      img: currentCard.image,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      createdAt: Date.now(),
      category: currentCard.category,
      status: 'Liked',
    });
    toggleFavorite(currentCard.id);
    consumeRecommendation();
    setCardIndex((prev) => prev + 1);
  }, [cardIndex, addToHistory, toggleFavorite, consumeRecommendation]);

  const currentCard = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* ─── Minimal Top Bar ─── */}
      <View style={styles.topBar}>
        <View>
          <Text style={styles.brandText}>🍊 吃什么</Text>
          <Text style={styles.recommendationsHint}>今日推荐剩余 {recommendationsLeft} 次</Text>
        </View>
        <View style={styles.topBarRight}>
          <Pressable
            style={({ pressed }) => [styles.topBarIconBtn, pressed && styles.pressed]}
            onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
          >
            <SlidersHorizontal size={20} color={theme.colors.foreground} strokeWidth={1.8} />
          </Pressable>
          <Pressable
            style={({ pressed }) => [styles.topBarIconBtn, pressed && styles.pressed]}
            onPress={() => setShowSearch(true)}
          >
            <Search size={20} color={theme.colors.foreground} strokeWidth={1.8} />
          </Pressable>
        </View>
      </View>

      {recommendationsLeft === 0 && (
        <View style={styles.limitBar}>
          <Text style={styles.limitText}>今日推荐已用完，点击刷新继续探索</Text>
          <Pressable onPress={refreshRecommendations}>
            <Text style={styles.limitAction}>立即刷新</Text>
          </Pressable>
        </View>
      )}

      {recommendationsLeft <= 4 && selectedCuisines.length === 0 && selectedRestrictions.length === 0 && (
        <Pressable style={styles.profilePrompt} onPress={() => navigation.navigate('OnboardingCuisines')}>
          <Text style={styles.profilePromptText}>完善口味偏好，可显著提升推荐命中率</Text>
        </Pressable>
      )}

      {/* ─── Full-screen Card Area ─── */}
      <View style={styles.cardContainer}>
        {currentCard && (
          <SwipeCard
            key={`${currentCard.id}-${cardIndex}`}
            card={currentCard}
            onSwipe={handleSwipe}
            screenWidth={SCREEN_WIDTH}
            styles={styles}
          />
        )}
      </View>

      {/* ─── Action Buttons ─── */}
      <View style={styles.actionRow}>
        <AnimatedActionBtn
          style={[styles.actionBtn, styles.skipBtn]}
          onPress={() => handleSwipe('left')}
          label="跳过"
        >
          <X size={26} color={theme.colors.muted} strokeWidth={2.5} />
        </AnimatedActionBtn>

        <AnimatedActionBtn
          style={[styles.actionBtn, styles.favoriteBtn]}
          onPress={handleFavorite}
          label="收藏"
        >
          <Star size={26} color={theme.colors.primary} strokeWidth={2} />
        </AnimatedActionBtn>

        <AnimatedActionBtn
          style={[styles.actionBtn, styles.likeBtn]}
          onPress={() => handleSwipe('right')}
          label="喜欢"
        >
          <Heart size={26} color="#EF4444" fill="#EF4444" strokeWidth={0} />
        </AnimatedActionBtn>
      </View>

      {/* ─── First-use Onboarding Guide ─── */}
      <OnboardingGuide />
      <SearchOverlay visible={showSearch} onClose={() => setShowSearch(false)} />
    </SafeAreaView>
  );
}

/* ═══════════ Styles ═══════════ */
function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    pressed: { opacity: 0.85, transform: [{ scale: 0.97 }] },

    /* ── Top Bar ── */
    topBar: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      height: 48,
    },
    brandText: {
      fontSize: 22,
      fontWeight: '800',
      color: t.colors.primary,
    },
    recommendationsHint: {
      ...t.typography.micro,
      color: t.colors.subtle,
      marginTop: -2,
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
    limitBar: {
      marginHorizontal: t.spacing.md,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.xs,
      backgroundColor: t.colors.warningLight,
      borderRadius: t.radius.md,
      paddingHorizontal: t.spacing.sm,
      paddingVertical: t.spacing.xs,
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
    },
    limitText: { ...t.typography.caption, color: t.colors.foreground, flex: 1, marginRight: t.spacing.xs },
    limitAction: { ...t.typography.caption, color: t.colors.primary, fontWeight: '700' },
    profilePrompt: {
      marginHorizontal: t.spacing.md,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.xs,
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.radius.md,
      paddingHorizontal: t.spacing.sm,
      paddingVertical: t.spacing.xs,
    },
    profilePromptText: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '600' },

    /* ── Card Container ── */
    cardContainer: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: t.spacing.md,
    },

    /* ── Card ── */
    card: {
      height: CARD_HEIGHT,
      borderRadius: 16,
      overflow: 'hidden',
      backgroundColor: t.colors.surface,
      ...t.shadows.lg,
    },

    /* LIKE / NOPE badges */
    badgeLike: {
      position: 'absolute',
      top: 24,
      left: 20,
      zIndex: 10,
      borderWidth: 3,
      borderColor: '#4CAF50',
      backgroundColor: 'rgba(76,175,80,0.2)',
      borderRadius: t.radius.sm,
      paddingHorizontal: 20,
      paddingVertical: 8,
      transform: [{ rotate: '-15deg' }],
    },
    badgeLikeText: {
      fontSize: 20,
      fontWeight: '800',
      color: '#4CAF50',
      letterSpacing: 2,
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
      paddingHorizontal: 20,
      paddingVertical: 8,
      transform: [{ rotate: '15deg' }],
    },
    badgeNopeText: {
      fontSize: 20,
      fontWeight: '800',
      color: '#EF4444',
      letterSpacing: 2,
    },

    /* ── Image area (full card) ── */
    cardImage: {
      width: '100%',
      height: '100%',
      position: 'relative',
    },

    /* Gradient overlay placeholder */
    cardGradientOverlay: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      height: '55%',
      backgroundColor: 'transparent',
    },

    /* ── Info overlay on image ── */
    cardInfoOverlay: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      paddingHorizontal: 20,
      paddingBottom: 24,
      paddingTop: 60,
      backgroundColor: 'rgba(0,0,0,0.45)',
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
      marginBottom: 6,
    },

    cardMetaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      marginBottom: 8,
    },
    cardMetaText: {
      fontSize: 13,
      fontWeight: '500',
      color: 'rgba(255,255,255,0.85)',
    },
    cardMetaDot: {
      fontSize: 13,
      color: 'rgba(255,255,255,0.5)',
    },

    cardTagRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
    },
    cardTag: {
      fontSize: 12,
      fontWeight: '500',
      color: 'rgba(255,255,255,0.8)',
    },

    /* ── Action Buttons ── */
    actionRow: {
      flexDirection: 'row',
      justifyContent: 'center',
      alignItems: 'center',
      gap: 32,
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
  });
}
