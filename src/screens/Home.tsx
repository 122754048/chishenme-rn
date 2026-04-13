import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated as NativeAnimated, PanResponder, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { CheckCircle2, Compass, Crown, Heart, MapPin, ScanSearch, Sparkles, Star, X } from 'lucide-react-native';
import { brand } from '../config/brand';
import { useApp } from '../context/AppContext';
import type { MealType, SwipeCardData } from '../data/mockData';
import type { MainTabParamList, RootStackParamList } from '../navigation/types';
import { fetchNearbyRestaurants } from '../services/places';
import { SkeletonImage } from '../components/SkeletonImage';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { getRecommendedDishes } from '../utils/recommendations';
import { formatDistanceMiles, getBestEffortLocationContext } from '../utils/location';

const SWIPE_THRESHOLD = 100;

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type HomeRouteProp = RouteProp<MainTabParamList, 'Home'>;
type HomeTabNavProp = BottomTabNavigationProp<MainTabParamList, 'Home'>;

function inferMealTypeByHour(): MealType {
  const hour = new Date().getHours();
  if (hour < 10) return 'Breakfast';
  if (hour < 15) return 'Lunch';
  if (hour < 18) return 'Snack';
  if (hour < 22) return 'Dinner';
  return 'Late Night';
}

function DecisionCard({
  card,
  reasons,
  rating,
  distanceLabel,
  onSwipe,
  onSwipeStart,
  onOpenDetail,
  onGestureStateChange,
  onBlockedSwipeAttempt,
  screenWidth,
  styles,
  enabled,
  cardHeight,
  swipeRequest,
  canCommitSwipe,
}: {
  card: SwipeCardData;
  reasons: string[];
  rating: string;
  distanceLabel: string;
  onSwipe: (dir: 'left' | 'right') => void;
  onSwipeStart: () => void;
  onOpenDetail: () => void;
  onGestureStateChange: (dragging: boolean) => void;
  onBlockedSwipeAttempt: () => void;
  screenWidth: number;
  styles: ReturnType<typeof makeStyles>;
  enabled: boolean;
  cardHeight: number;
  swipeRequest: { direction: 'left' | 'right'; key: number } | null;
  canCommitSwipe: boolean;
}) {
  const pan = useRef(new NativeAnimated.ValueXY()).current;
  const gestureStartAt = useRef(0);

  const resetCard = useCallback((onComplete?: () => void) => {
    NativeAnimated.spring(pan, {
      toValue: { x: 0, y: 0 },
      useNativeDriver: true,
      speed: 16,
      bounciness: 8,
    }).start(() => {
      onGestureStateChange(false);
      onComplete?.();
    });
  }, [onGestureStateChange, pan]);

  const animateOut = useCallback(
    (direction: 'left' | 'right') => {
      onSwipeStart();
      NativeAnimated.timing(pan, {
        toValue: { x: direction === 'right' ? screenWidth * 1.2 : -screenWidth * 1.2, y: 0 },
        duration: 230,
        useNativeDriver: true,
      }).start(({ finished }) => {
        onGestureStateChange(false);
        if (finished) {
          pan.setValue({ x: 0, y: 0 });
          onSwipe(direction);
        }
      });
    },
    [onGestureStateChange, onSwipe, onSwipeStart, pan, screenWidth]
  );

  useEffect(() => {
    if (!swipeRequest || !enabled) return;
    animateOut(swipeRequest.direction);
  }, [animateOut, enabled, swipeRequest]);

  const rotate = pan.x.interpolate({
    inputRange: [-screenWidth, 0, screenWidth],
    outputRange: ['-10deg', '0deg', '10deg'],
    extrapolate: 'clamp',
  });

  const positiveOpacity = pan.x.interpolate({
    inputRange: [0, 90],
    outputRange: [0, 1],
    extrapolate: 'clamp',
  });

  const negativeOpacity = pan.x.interpolate({
    inputRange: [-90, 0],
    outputRange: [1, 0],
    extrapolate: 'clamp',
  });

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => false,
        onStartShouldSetPanResponderCapture: () => false,
        onMoveShouldSetPanResponder: (_evt, gestureState) =>
          enabled && Math.abs(gestureState.dx) > 8 && Math.abs(gestureState.dx) > Math.abs(gestureState.dy) * 1.15,
        onMoveShouldSetPanResponderCapture: (_evt, gestureState) =>
          enabled && Math.abs(gestureState.dx) > 8 && Math.abs(gestureState.dx) > Math.abs(gestureState.dy) * 1.15,
        onPanResponderGrant: () => {
          gestureStartAt.current = Date.now();
          onGestureStateChange(true);
        },
        onPanResponderMove: (_evt, gestureState) => {
          pan.setValue({ x: gestureState.dx, y: gestureState.dy * 0.12 });
        },
        onPanResponderRelease: (_evt, gestureState) => {
          const gestureDuration = Date.now() - gestureStartAt.current;
          const isTapLike = Math.abs(gestureState.dx) < 8 && Math.abs(gestureState.dy) < 8 && gestureDuration < 220;

          if (isTapLike) {
            resetCard(onOpenDetail);
            return;
          }

          if (gestureState.dx > SWIPE_THRESHOLD || gestureState.vx > 0.5) {
            if (!canCommitSwipe) {
              resetCard(onBlockedSwipeAttempt);
              return;
            }
            animateOut('right');
            return;
          }

          if (gestureState.dx < -SWIPE_THRESHOLD || gestureState.vx < -0.5) {
            if (!canCommitSwipe) {
              resetCard(onBlockedSwipeAttempt);
              return;
            }
            animateOut('left');
            return;
          }

          resetCard();
        },
        onPanResponderTerminationRequest: () => false,
        onPanResponderTerminate: () => resetCard(),
      }),
    [animateOut, canCommitSwipe, enabled, onBlockedSwipeAttempt, onGestureStateChange, onOpenDetail, pan, resetCard]
  );

  return (
    <View style={styles.activeCardShell}>
      <NativeAnimated.View
        {...panResponder.panHandlers}
        style={[
          styles.card,
          styles.activeCard,
          {
            width: screenWidth - 32,
            height: cardHeight,
            transform: [{ translateX: pan.x }, { translateY: pan.y }, { rotate }],
          },
        ]}
      >
        <NativeAnimated.View style={[styles.badgeLike, { opacity: positiveOpacity }]}>
          <Text style={styles.badgeLikeText}>Save</Text>
        </NativeAnimated.View>
        <NativeAnimated.View style={[styles.badgeNope, { opacity: negativeOpacity }]}>
          <Text style={styles.badgeNopeText}>Skip</Text>
        </NativeAnimated.View>

        <Pressable
          onPress={onOpenDetail}
          style={styles.cardTapTarget}
          accessibilityRole="button"
          accessibilityLabel={`Open details for ${card.name}`}
        >
          <View style={styles.cardImage}>
            <SkeletonImage src={card.image} alt={card.name} />
            <View style={styles.cardInfoOverlay}>
              <View style={styles.cardInfoTopRow}>
                <View style={styles.inlinePill}>
                  <Text style={styles.inlinePillText} numberOfLines={1}>
                    {card.restaurantName}
                  </Text>
                </View>
                <View style={styles.ratingBadge}>
                  <Star size={12} color="#F5B74F" fill="#F5B74F" />
                  <Text style={styles.ratingText}>{rating}</Text>
                </View>
              </View>

              <Text style={styles.cardName}>{card.name}</Text>

              {reasons[0] ? (
                <Text style={styles.cardSupportText} numberOfLines={1}>
                  {reasons[0]}
                </Text>
              ) : null}

              <View style={styles.cardMetaRow}>
                <Text style={styles.cardMetaText}>{distanceLabel}</Text>
                <Text style={styles.cardMetaDot}>/</Text>
                <Text style={styles.cardMetaText}>{card.prepTime}</Text>
              </View>
            </View>
          </View>
        </Pressable>
      </NativeAnimated.View>
    </View>
  );
}

function PreviewDeckCard({
  card,
  rating,
  distanceLabel,
  screenWidth,
  cardHeight,
  styles,
  depth,
}: {
  card: SwipeCardData;
  rating: string;
  distanceLabel: string;
  screenWidth: number;
  cardHeight: number;
  styles: ReturnType<typeof makeStyles>;
  depth: number;
}) {
  const topOffset = depth === 1 ? 12 : 24;
  const scale = depth === 1 ? 0.975 : 0.95;

  return (
    <View
      pointerEvents="none"
      style={[
        styles.previewCardShell,
        {
          top: topOffset,
          width: screenWidth - 32,
          height: cardHeight,
          transform: [{ scale }],
          zIndex: depth === 1 ? 1 : 0,
        },
      ]}
    >
      <View style={styles.previewCard}>
        <View style={styles.cardImage}>
          <SkeletonImage src={card.image} alt={card.name} />
          <View style={styles.previewOverlay} />
          <View style={styles.previewCardInfo}>
            <View style={styles.previewTopRow}>
              <Text style={styles.previewRestaurant} numberOfLines={1}>
                {card.restaurantName}
              </Text>
              <View style={styles.previewRatingBadge}>
                <Star size={11} color="#F5B74F" fill="#F5B74F" />
                <Text style={styles.previewRatingText}>{rating}</Text>
              </View>
            </View>
            <Text style={styles.previewName} numberOfLines={1}>
              {card.name}
            </Text>
            <Text style={styles.previewMeta} numberOfLines={1}>
              {distanceLabel} / {card.prepTime}
            </Text>
          </View>
        </View>
      </View>
    </View>
  );
}

function AnimatedActionBtn({
  onPress,
  children,
  disabled,
  accessibilityLabel,
}: {
  onPress: () => void;
  children: React.ReactNode;
  disabled?: boolean;
  accessibilityLabel: string;
}) {
  const scale = useSharedValue(1);
  const animStyle = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  const handlePress = () => {
    if (disabled) return;
    scale.value = withSequence(withTiming(0.96, { duration: 70 }), withSpring(1, { damping: 14, stiffness: 220 }));
    onPress();
  };

  return (
    <Pressable
      onPress={handlePress}
      style={actionBtnStyles.wrapper}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: Boolean(disabled) }}
      hitSlop={8}
    >
      <Animated.View style={[animStyle, disabled && actionBtnStyles.disabled]}>{children}</Animated.View>
    </Pressable>
  );
}

const actionBtnStyles = StyleSheet.create({
  wrapper: { alignItems: 'center', justifyContent: 'center' },
  disabled: { opacity: 0.45 },
});

export function Home() {
  const navigation = useNavigation<NavProp>();
  const tabNavigation = useNavigation<HomeTabNavProp>();
  const route = useRoute<HomeRouteProp>();
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const { height: screenHeight, width: screenWidth } = useWindowDimensions();
  const {
    addToHistory,
    backendToken,
    consumeRecommendation,
    history,
    isFavorite,
    locationContext,
    membershipPlan,
    recommendationsLeft,
    selectedCuisines,
    selectedRestrictions,
    setLocationSelection,
    toggleFavorite,
  } = useApp();

  const [swipeRequest, setSwipeRequest] = useState<{ direction: 'left' | 'right'; key: number } | null>(null);
  const [isResolvingDecision, setIsResolvingDecision] = useState(false);
  const [isCardDragging, setIsCardDragging] = useState(false);
  const [unlockNoticePlan, setUnlockNoticePlan] = useState<'pro' | 'family' | null>(route.params?.justUnlocked ?? null);
  const [nearbyRestaurants, setNearbyRestaurants] = useState<Awaited<ReturnType<typeof fetchNearbyRestaurants>>['restaurants']>([]);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const developerTapCountRef = useRef(0);
  const developerTapTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isUnlimitedPlan = recommendationsLeft < 0;
  const quotaLocked = !isUnlimitedPlan && recommendationsLeft <= 0;
  const canCommitSwipe = membershipPlan !== 'free' || !quotaLocked;
  const cardHeight = Math.min(Math.max(screenHeight * 0.56, 440), 620);
  const preferredMealType = inferMealTypeByHour();

  useEffect(() => {
    return () => {
      if (developerTapTimerRef.current) {
        clearTimeout(developerTapTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const unlocked = route.params?.justUnlocked;
    if (!unlocked) return;
    setUnlockNoticePlan(unlocked);
    tabNavigation.setParams({ justUnlocked: undefined });
  }, [route.params?.justUnlocked, tabNavigation]);

  useEffect(() => {
    if (locationContext) return;
    void getBestEffortLocationContext()
      .then((context) => {
        if (context) {
          return setLocationSelection(context);
        }
        return undefined;
      })
      .catch((error) => {
        console.warn('Failed to resolve best-effort location:', error);
      });
  }, [locationContext, setLocationSelection]);

  useEffect(() => {
    if (!backendToken || !locationContext) {
      setNearbyRestaurants([]);
      return;
    }

    let active = true;
    setIsDiscovering(true);

    const input =
      locationContext.mode === 'live'
        ? { latitude: locationContext.latitude, longitude: locationContext.longitude, radiusMeters: 2200 }
        : { query: locationContext.query ?? locationContext.label };

    void fetchNearbyRestaurants(backendToken, input)
      .then((result) => {
        if (!active) return;
        setNearbyRestaurants(result.restaurants);
      })
      .catch((error) => {
        if (!active) return;
        console.warn('Failed to fetch nearby restaurants:', error);
        setNearbyRestaurants([]);
      })
      .finally(() => {
        if (active) setIsDiscovering(false);
      });

    return () => {
      active = false;
    };
  }, [backendToken, locationContext]);

  const recommendations = useMemo(
    () =>
      getRecommendedDishes({
        selectedCuisines,
        selectedRestrictions,
        preferredMealType,
        nearbyRestaurants,
        history,
      }),
    [history, nearbyRestaurants, preferredMealType, selectedCuisines, selectedRestrictions]
  );

  const currentRecommendation = recommendations[0] ?? null;
  const currentCard = currentRecommendation?.dish ?? null;
  const currentNearby = currentRecommendation?.nearbyRestaurant ?? null;
  const nextRecommendations = recommendations.slice(1, 3);
  const reasons = currentRecommendation?.reasons ?? [];
  const distanceLabel = formatDistanceMiles(currentNearby?.distanceMeters ?? currentCard?.distanceMeters) ?? currentCard?.distance ?? 'Nearby';
  const rating = currentNearby?.rating?.toFixed(1) ?? currentCard?.restaurantRating.toFixed(1) ?? '--';
  const locationLabel = locationContext?.label ?? 'Current area';

  const openDetail = useCallback(() => {
    if (!currentCard) return;
    navigation.navigate('Detail', { itemId: currentCard.id, title: currentCard.name, image: currentCard.image });
  }, [currentCard, navigation]);

  const beginSwipeDecision = useCallback(() => {
    setIsResolvingDecision(true);
  }, []);

  const handleDecision = useCallback(
    async (direction: 'left' | 'right') => {
      if (!currentCard || !currentRecommendation) return;

      try {
        if (direction === 'right' && !isFavorite(currentCard.id)) {
          await toggleFavorite(currentCard.id);
        }

        await addToHistory({
          id: currentCard.id,
          title: currentCard.name,
          img: currentCard.image,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          createdAt: Date.now(),
          category: currentCard.restaurantName,
          status: direction === 'right' ? 'Liked' : 'Skipped',
        });

        if (direction === 'right') {
          consumeRecommendation();
        }
      } finally {
        setSwipeRequest(null);
        setIsResolvingDecision(false);
        setIsCardDragging(false);
      }
    },
    [addToHistory, consumeRecommendation, currentCard, currentRecommendation, isFavorite, toggleFavorite]
  );

  const handleBlockedSwipeAttempt = useCallback(() => {
    setIsCardDragging(false);
    navigation.navigate('Upgrade');
  }, [navigation]);

  const triggerDecision = useCallback(
    (direction: 'left' | 'right') => {
      if (!currentCard || isResolvingDecision) return;
      if (!canCommitSwipe) {
        navigation.navigate('Upgrade');
        return;
      }
      setIsResolvingDecision(true);
      setSwipeRequest({ direction, key: Date.now() });
    },
    [canCommitSwipe, currentCard, isResolvingDecision, navigation]
  );

  const handleBrandTap = useCallback(() => {
    developerTapCountRef.current += 1;

    if (developerTapTimerRef.current) {
      clearTimeout(developerTapTimerRef.current);
    }

    developerTapTimerRef.current = setTimeout(() => {
      developerTapCountRef.current = 0;
      developerTapTimerRef.current = null;
    }, 1200);

    if (developerTapCountRef.current >= 6) {
      developerTapCountRef.current = 0;
      if (developerTapTimerRef.current) {
        clearTimeout(developerTapTimerRef.current);
        developerTapTimerRef.current = null;
      }
      navigation.navigate('DeveloperMode');
    }
  }, [navigation]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topBar}>
        <Pressable
          onPress={handleBrandTap}
          accessibilityRole="button"
          accessibilityLabel={`${brand.appName} hidden menu`}
          hitSlop={8}
        >
          <Text style={styles.brandText}>{brand.appName}</Text>
        </Pressable>
        <Pressable
          style={({ pressed }) => [styles.topBarIconBtn, pressed && styles.pressedChip]}
          onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
          accessibilityRole="button"
          accessibilityLabel="Open explore"
          hitSlop={8}
        >
          <Compass size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        bounces={false}
        scrollEnabled={!isCardDragging}
      >
      <View style={styles.stage}>
        <View style={styles.utilityRow}>
          <Pressable
            style={({ pressed }) => [styles.areaPill, pressed && styles.pressedChip]}
            onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
            accessibilityRole="button"
            accessibilityLabel="Choose area"
          >
            <MapPin size={14} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.areaPillText} numberOfLines={1}>
              {locationLabel}
            </Text>
          </Pressable>
          <Pressable
            style={({ pressed }) => [styles.scanAction, pressed && styles.pressedChip]}
            onPress={() =>
              navigation.navigate('MenuScan', {
                restaurantId: currentCard?.restaurantId,
                restaurantName: currentCard?.restaurantName,
              })
            }
            accessibilityRole="button"
            accessibilityLabel="Scan a menu"
          >
            <View style={styles.scanActionIcon}>
              <ScanSearch size={16} color={theme.colors.primary} strokeWidth={2} />
            </View>
            <Text style={styles.scanActionText}>Scan menu</Text>
          </Pressable>
        </View>

        <View style={styles.statusRow}>
          <View style={[styles.statusPill, membershipPlan !== 'free' && styles.statusPillPremium]}>
            {membershipPlan === 'free' ? (
              <Sparkles size={14} color={theme.colors.primary} strokeWidth={2} />
            ) : (
              <Crown size={14} color={theme.colors.primaryDark} strokeWidth={2} />
            )}
            <Text style={[styles.statusPillText, membershipPlan !== 'free' && styles.statusPillTextPremium]}>
              {membershipPlan === 'free'
                ? `${Math.max(recommendationsLeft, 0)} smart saves left`
                : unlockNoticePlan === 'family'
                  ? 'Family unlocked'
                  : unlockNoticePlan === 'pro'
                    ? 'Pro unlocked'
                    : `${membershipPlan === 'family' ? 'Family' : 'Pro'} active`}
            </Text>
          </View>
          {unlockNoticePlan ? (
            <Pressable
              style={({ pressed }) => [styles.dismissNoticeBtn, pressed && styles.pressedChip]}
              onPress={() => setUnlockNoticePlan(null)}
              accessibilityRole="button"
              accessibilityLabel="Dismiss premium notice"
            >
              <X size={14} color={theme.colors.subtle} strokeWidth={2} />
            </Pressable>
          ) : null}
        </View>

        {unlockNoticePlan ? (
          <View style={styles.unlockCard}>
            <View style={styles.unlockIcon}>
              <CheckCircle2 size={18} color={theme.colors.primary} strokeWidth={2} />
            </View>
            <View style={styles.unlockCopy}>
              <Text style={styles.unlockTitle}>{unlockNoticePlan === 'family' ? 'Family is live' : 'Pro is live'}</Text>
              <Text style={styles.unlockBody}>
                {unlockNoticePlan === 'family'
                  ? 'Shared picks, stronger ranking, and full menu scan are ready now.'
                  : 'Smarter saves, stronger ranking, and full menu scan are ready now.'}
              </Text>
            </View>
          </View>
        ) : null}

        <View style={styles.cardContainer}>
          {currentCard ? (
            <View style={[styles.deckStage, { height: cardHeight + 28 }]}>
              {nextRecommendations
                .slice()
                .reverse()
                .map((recommendation, reverseIndex) => {
                  const depth = nextRecommendations.length - reverseIndex;
                  const previewCard = recommendation.dish;
                  const previewNearby = recommendation.nearbyRestaurant ?? null;
                  const previewDistance =
                    formatDistanceMiles(previewNearby?.distanceMeters ?? previewCard.distanceMeters) ?? previewCard.distance ?? 'Nearby';
                  const previewRating = previewNearby?.rating?.toFixed(1) ?? previewCard.restaurantRating.toFixed(1) ?? '--';

                  return (
                    <PreviewDeckCard
                      key={`preview-${previewCard.id}`}
                      card={previewCard}
                      rating={previewRating}
                      distanceLabel={previewDistance}
                      screenWidth={screenWidth}
                      cardHeight={cardHeight}
                      styles={styles}
                      depth={depth}
                    />
                  );
                })}

              <DecisionCard
                key={currentCard.id}
                card={currentCard}
                reasons={reasons.length > 0 ? reasons : [currentCard.recommendationBlurb]}
                rating={rating}
                distanceLabel={distanceLabel}
                onSwipe={handleDecision}
                onSwipeStart={beginSwipeDecision}
                onOpenDetail={openDetail}
                onGestureStateChange={setIsCardDragging}
                onBlockedSwipeAttempt={handleBlockedSwipeAttempt}
                screenWidth={screenWidth}
                styles={styles}
                enabled={!isResolvingDecision}
                cardHeight={cardHeight}
                swipeRequest={swipeRequest}
                canCommitSwipe={canCommitSwipe}
              />
            </View>
          ) : (
            <View style={styles.emptyState}>
              <Text style={styles.emptyTitle}>Nothing strong right now</Text>
              <Pressable style={styles.emptyButton} onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}>
                <Text style={styles.emptyButtonText}>Explore</Text>
              </Pressable>
            </View>
          )}
        </View>

        <View style={styles.bottomDock}>
        <View style={styles.actionRow}>
            <AnimatedActionBtn onPress={() => triggerDecision('left')} disabled={!currentCard || isResolvingDecision} accessibilityLabel="Skip this pick for today">
              <View style={[styles.actionBtn, styles.skipBtn]}>
                <X size={30} color={theme.colors.muted} strokeWidth={2.5} />
              </View>
            </AnimatedActionBtn>

            <AnimatedActionBtn onPress={() => triggerDecision('right')} disabled={!currentCard || isResolvingDecision} accessibilityLabel="Save this pick">
              <View style={[styles.actionBtn, styles.likeBtn]}>
                <Heart size={30} color="#D65947" fill="#D65947" strokeWidth={0} />
              </View>
            </AnimatedActionBtn>
          </View>

          {quotaLocked ? (
            <Pressable
              style={({ pressed }) => [styles.upgradePill, pressed && styles.pressedChip]}
              onPress={() => navigation.navigate('Upgrade')}
              accessibilityRole="button"
              accessibilityLabel="Upgrade for more picks"
            >
              <Text style={styles.upgradePillText}>Upgrade for more picks</Text>
            </Pressable>
          ) : (
            <View style={styles.swipeHint}>
              <Compass size={16} color={theme.colors.subtle} strokeWidth={1.9} />
              <Text style={styles.swipeHintText}>
                {isDiscovering ? 'Refreshing nearby' : canCommitSwipe ? 'Left to skip, right to save' : 'Swipe to preview, upgrade to act'}
              </Text>
            </View>
          )}
        </View>
      </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.surface },
    pressedChip: { opacity: t.interaction.chipPressedOpacity },
    scrollView: { flex: 1, backgroundColor: t.colors.background },
    scrollContent: { flexGrow: 1, paddingBottom: 112 },
    topBar: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      height: t.topNavHeight,
      backgroundColor: t.colors.surface,
    },
    brandText: { fontSize: 24, fontWeight: '800', color: t.colors.foreground },
    topBarIconBtn: { width: 40, height: 40, borderRadius: t.radius.md, alignItems: 'center', justifyContent: 'center' },
    stage: { flex: 1, paddingHorizontal: t.spacing.md, paddingTop: t.spacing.sm, backgroundColor: t.colors.background },
    utilityRow: { flexDirection: 'row', gap: 10, marginBottom: t.spacing.md },
    areaPill: {
      flex: 1,
      minHeight: 44,
      borderRadius: 22,
      backgroundColor: t.colors.surface,
      paddingHorizontal: 14,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    areaPillText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700', flex: 1 },
    scanAction: {
      minWidth: 132,
      minHeight: 44,
      borderRadius: 22,
      backgroundColor: t.colors.primaryLight,
      paddingHorizontal: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      borderWidth: 1,
      borderColor: 'rgba(201,103,60,0.18)',
    },
    scanActionIcon: {
      width: 26,
      height: 26,
      borderRadius: 13,
      backgroundColor: 'rgba(255,255,255,0.55)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    scanActionText: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    statusRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: t.spacing.sm },
    statusPill: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      minHeight: 34,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.surface,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
      paddingHorizontal: 12,
    },
    statusPillPremium: { backgroundColor: t.colors.primaryLight, borderColor: 'rgba(201,103,60,0.18)' },
    statusPillText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    statusPillTextPremium: { color: t.colors.primaryDark },
    dismissNoticeBtn: {
      width: 34,
      height: 34,
      borderRadius: 17,
      backgroundColor: t.colors.surface,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
      alignItems: 'center',
      justifyContent: 'center',
    },
    unlockCard: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      marginBottom: t.spacing.md,
    },
    unlockIcon: {
      width: 36,
      height: 36,
      borderRadius: 18,
      backgroundColor: 'rgba(255,255,255,0.72)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    unlockCopy: { flex: 1, gap: 2 },
    unlockTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    unlockBody: { ...t.typography.caption, color: t.colors.primaryDark },
    cardContainer: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingBottom: t.spacing.md },
    deckStage: {
      width: '100%',
      alignItems: 'center',
      justifyContent: 'flex-start',
      position: 'relative',
    },
    activeCardShell: {
      position: 'absolute',
      top: 0,
      zIndex: 3,
    },
    cardTapTarget: {
      flex: 1,
    },
    previewCardShell: {
      position: 'absolute',
      alignItems: 'center',
      justifyContent: 'center',
      opacity: 0.94,
    },
    previewCard: {
      width: '100%',
      height: '100%',
      borderRadius: t.surface.cardRadius,
      overflow: 'hidden',
      backgroundColor: t.colors.surface,
      ...t.shadows.sm,
    },
    card: { borderRadius: t.surface.cardRadius, overflow: 'hidden', backgroundColor: t.colors.surface, ...t.shadows.md },
    activeCard: { zIndex: 3 },
    badgeLike: {
      position: 'absolute',
      top: 24,
      left: 20,
      zIndex: 10,
      borderWidth: 2,
      borderColor: '#72B47D',
      backgroundColor: 'rgba(114,180,125,0.22)',
      borderRadius: t.radius.sm,
      paddingHorizontal: 14,
      paddingVertical: 8,
      transform: [{ rotate: '-10deg' }],
    },
    badgeLikeText: { fontSize: 16, fontWeight: '800', color: '#72B47D' },
    badgeNope: {
      position: 'absolute',
      top: 24,
      right: 20,
      zIndex: 10,
      borderWidth: 2,
      borderColor: '#D65947',
      backgroundColor: 'rgba(214,89,71,0.22)',
      borderRadius: t.radius.sm,
      paddingHorizontal: 14,
      paddingVertical: 8,
      transform: [{ rotate: '10deg' }],
    },
    badgeNopeText: { fontSize: 16, fontWeight: '800', color: '#D65947' },
    cardImage: { width: '100%', height: '100%', position: 'relative' },
    previewOverlay: {
      ...StyleSheet.absoluteFillObject,
      backgroundColor: 'rgba(17, 12, 9, 0.22)',
    },
    cardInfoOverlay: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      paddingHorizontal: 20,
      paddingBottom: 24,
      paddingTop: 72,
      backgroundColor: 'rgba(17, 12, 9, 0.42)',
    },
    cardInfoTopRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
    inlinePill: {
      backgroundColor: 'rgba(255,255,255,0.16)',
      paddingHorizontal: 12,
      paddingVertical: 5,
      borderRadius: t.radius.full,
      maxWidth: '74%',
    },
    inlinePillText: { ...t.typography.caption, fontWeight: '700', color: '#FFFFFF' },
    ratingBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: 'rgba(255,255,255,0.16)',
      paddingHorizontal: 8,
      paddingVertical: 5,
      borderRadius: t.radius.full,
    },
    ratingText: { ...t.typography.caption, fontWeight: '700', color: '#FFFFFF' },
    cardName: { fontSize: 30, lineHeight: 36, fontWeight: '800', color: '#FFFFFF', marginBottom: 6 },
    cardSupportText: { ...t.typography.caption, color: 'rgba(255,255,255,0.9)', marginBottom: 12 },
    cardMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
    cardMetaText: { ...t.typography.caption, fontWeight: '600', color: 'rgba(255,255,255,0.88)' },
    cardMetaDot: { fontSize: 13, color: 'rgba(255,255,255,0.42)' },
    previewCardInfo: {
      position: 'absolute',
      left: 16,
      right: 16,
      bottom: 16,
      gap: 6,
    },
    previewTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
    previewRestaurant: { ...t.typography.caption, color: '#FFFFFF', fontWeight: '700', flex: 1 },
    previewRatingBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: 'rgba(255,255,255,0.16)',
      borderRadius: t.radius.full,
      paddingHorizontal: 8,
      paddingVertical: 4,
    },
    previewRatingText: { ...t.typography.micro, color: '#FFFFFF', fontWeight: '700' },
    previewName: { fontSize: 22, lineHeight: 26, color: '#FFFFFF', fontWeight: '800' },
    previewMeta: { ...t.typography.caption, color: 'rgba(255,255,255,0.82)', fontWeight: '600' },
    bottomDock: { paddingTop: t.spacing.md, paddingBottom: 20, backgroundColor: t.colors.background, gap: 12 },
    actionRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 28 },
    actionBtn: {
      width: 76,
      height: 76,
      borderRadius: 38,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.surface,
      borderWidth: 1.5,
      ...t.shadows.sm,
    },
    skipBtn: { borderColor: t.colors.border },
    likeBtn: { borderColor: '#D65947' },
    swipeHint: {
      minHeight: 44,
      borderRadius: 22,
      backgroundColor: t.colors.surface,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
      paddingHorizontal: 14,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
    },
    swipeHintText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '700' },
    upgradePill: {
      minHeight: 44,
      borderRadius: 22,
      backgroundColor: t.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    upgradePillText: { ...t.typography.caption, color: '#FFFFFF', fontWeight: '700' },
    emptyState: {
      width: '100%',
      backgroundColor: t.colors.surface,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.lg,
      alignItems: 'center',
      gap: 8,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    emptyTitle: { ...t.typography.h2, color: t.colors.foreground },
    emptyButton: {
      backgroundColor: t.colors.primary,
      borderRadius: t.radius.full,
      paddingHorizontal: 18,
      paddingVertical: 10,
      marginTop: 8,
    },
    emptyButtonText: { ...t.typography.caption, color: t.colors.surface, fontWeight: '700' },
  });
}
