import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
  withSequence,
  runOnJS,
} from 'react-native-reanimated';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Bell, Zap, X, Info, Heart, Star, MapPin } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { theme, useTheme } from '../theme';
import { SWIPE_CARDS, CATEGORIES, NEARBY_ITEMS } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

const SWIPE_THRESHOLD = 100;

type NavProp = NativeStackNavigationProp<RootStackParamList>;

interface CardData {
  id: number;
  title: string;
  price: string;
  restaurant: string;
  distance: string;
  rating: number;
  tags: string[];
  badge: string;
  image: string;
}

function SwipeCard({ card, onSwipe, screenWidth }: { card: CardData; onSwipe: (dir: 'left' | 'right') => void; screenWidth: number }) {
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  const panGesture = Gesture.Pan()
    .onUpdate((event) => {
      translateX.value = event.translationX;
      translateY.value = event.translationY;
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

  const cardStyle = useAnimatedStyle(() => {
    const rotate = translateX.value / 15;
    return {
      transform: [
        { translateX: translateX.value },
        { translateY: translateY.value },
        { rotate: `${rotate}deg` },
      ],
    };
  });

  const likeOpacity = useAnimatedStyle(() => ({
    opacity: Math.max(0, Math.min(1, translateX.value / 100)),
  }));

  const nopeOpacity = useAnimatedStyle(() => ({
    opacity: Math.max(0, Math.min(1, -translateX.value / 100)),
  }));

  return (
    <GestureDetector gesture={panGesture}>
      <Animated.View style={[styles.card, { width: screenWidth - 32 }, cardStyle]}>
        {/* LIKE badge */}
        <Animated.View style={[styles.badgeLike, likeOpacity]}>
          <Text style={styles.badgeLikeText}>LIKE</Text>
        </Animated.View>
        {/* NOPE badge */}
        <Animated.View style={[styles.badgeNope, nopeOpacity]}>
          <Text style={styles.badgeNopeText}>NOPE</Text>
        </Animated.View>

        <View style={styles.cardImage}>
          <SkeletonImage src={card.image} alt={card.title} />
          <View style={styles.cardImageOverlay} />
          <View style={styles.cardBadges}>
            <View style={styles.badgePill}>
              <Text style={styles.badgePillText}>{card.badge}</Text>
            </View>
            <View style={styles.ratingBadge}>
              <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
              <Text style={styles.ratingText}>{card.rating}</Text>
            </View>
          </View>
        </View>
        <View style={styles.cardBody}>
          <View style={styles.cardTitleRow}>
            <Text style={styles.cardTitle}>{card.title}</Text>
            <Text style={styles.cardPrice}>{card.price}</Text>
          </View>
          <View style={styles.cardMeta}>
            <MapPin size={12} color={theme.colors.muted} />
            <Text style={styles.cardMetaText}>{card.restaurant} · {card.distance}</Text>
          </View>
          <View style={styles.tagRow}>
            {card.tags.map((tag) => (
              <View key={tag} style={styles.tag}>
                <Text style={styles.tagText}>{tag}</Text>
              </View>
            ))}
          </View>
        </View>
      </Animated.View>
    </GestureDetector>
  );
}

function AnimatedActionBtn({
  onPress,
  children,
  style,
}: {
  onPress: () => void;
  children: React.ReactNode;
  style?: any;
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
    <Pressable onPress={handlePress}>
      <Animated.View style={[style, animStyle]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}

export function Home() {
  const navigation = useNavigation<NavProp>();
  const { theme: currentTheme } = useTheme();
  const { recommendationsLeft, addToHistory } = useApp();
  const [cardIndex, setCardIndex] = useState(0);
  const { width: screenWidth } = useWindowDimensions();
  const [localRecsLeft, setLocalRecsLeft] = useState(recommendationsLeft);

  const handleSwipe = useCallback((direction: 'left' | 'right' = 'right') => {
    const currentCard = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];
    setLocalRecsLeft((prev) => Math.max(0, prev - 1));
    addToHistory({
      id: currentCard.id,
      title: currentCard.title,
      img: currentCard.image,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      category: currentCard.tags[0] || 'Other',
      status: direction === 'right' ? 'Liked' : 'Skipped',
    });
    setCardIndex((prev) => prev + 1);
  }, [cardIndex, addToHistory]);

  const currentCard = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];

  const navigateToDetail = (item: { id: number; title: string; image: string }) => {
    navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.image });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav — Brand mode */}
      <View style={styles.topNav}>
        <Text style={styles.logo}>🍽️ ChiShenMe</Text>
        <Pressable
          style={({ pressed }) => [styles.bellBtn, pressed && styles.pressed]}
        >
          <Bell size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Status Bar */}
        <View style={styles.statusBar}>
          <View style={styles.statusLeft}>
            <Zap size={14} color={theme.colors.primary} fill={theme.colors.primary} />
            <Text style={styles.statusText}>
              <Text style={styles.statusBold}>{localRecsLeft}</Text> recommendations left today
            </Text>
          </View>
          <Pressable
            style={({ pressed }) => [styles.proBtn, pressed && styles.pressed]}
            onPress={() => navigation.navigate('Upgrade')}
          >
            <Text style={styles.proBtnText}>Go PRO</Text>
          </Pressable>
        </View>

        {/* Quick Categories */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.categoriesRow}
        >
          {CATEGORIES.map((cat) => (
            <Pressable
              key={cat.label}
              style={({ pressed }) => [styles.categoryItem, pressed && styles.pressed]}
              onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
            >
              <View style={styles.categoryIcon}>
                <Text style={styles.categoryEmoji}>{cat.icon}</Text>
              </View>
              <Text style={styles.categoryLabel}>{cat.label}</Text>
            </Pressable>
          ))}
        </ScrollView>

        {/* Title */}
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>What to Eat Today</Text>
          <Text style={styles.sectionSubtitle}>Swipe right to like, left to skip</Text>
        </View>

        {/* Swipe Card */}
        <View style={styles.cardContainer}>
          {currentCard && (
            <SwipeCard key={`${currentCard.id}-${cardIndex}`} card={currentCard} onSwipe={handleSwipe} screenWidth={screenWidth} />
          )}
        </View>

        {/* Action Buttons */}
        <View style={styles.actionRow}>
          <AnimatedActionBtn
            style={[styles.actionBtn, styles.skipBtn]}
            onPress={() => handleSwipe('left')}
          >
            <X size={24} color={theme.colors.error} strokeWidth={2.5} />
          </AnimatedActionBtn>
          <AnimatedActionBtn
            style={styles.infoBtn}
            onPress={() => navigateToDetail({
              id: currentCard.id,
              title: currentCard.title,
              image: currentCard.image,
            })}
          >
            <Info size={20} color={theme.colors.muted} strokeWidth={1.8} />
          </AnimatedActionBtn>
          <AnimatedActionBtn
            style={[styles.actionBtn, styles.likeBtn]}
            onPress={() => handleSwipe('right')}
          >
            <Heart size={24} color={theme.colors.primary} fill={theme.colors.primary} strokeWidth={0} />
          </AnimatedActionBtn>
        </View>

        {/* Nearby Hot */}
        <View style={styles.nearbySection}>
          <View style={styles.nearbyHeader}>
            <Text style={styles.nearbyTitle}>Nearby Hot</Text>
            <Pressable onPress={() => navigation.navigate('MainTabs')}>
              <Text style={styles.seeAllText}>See all →</Text>
            </Pressable>
          </View>
          <View style={styles.nearbyList}>
            {NEARBY_ITEMS.map((item) => (
              <Pressable
                key={item.id}
                style={({ pressed }) => [styles.nearbyItem, pressed && { opacity: 0.85 }]}
                onPress={() => navigateToDetail({
                  id: item.id,
                  title: item.title,
                  image: item.image,
                })}
              >
                <View style={styles.nearbyImageWrap}>
                  <SkeletonImage src={item.image} alt={item.title} />
                </View>
                <View style={styles.nearbyItemContent}>
                  <Text style={styles.nearbyItemTitle}>{item.title}</Text>
                  <Text style={styles.nearbyItemSubtitle}>{item.subtitle}</Text>
                </View>
                <View style={styles.nearbyItemRight}>
                  <View style={styles.nearbyRatingRow}>
                    <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
                    <Text style={styles.nearbyRating}>{item.rating}</Text>
                  </View>
                  <Text style={styles.nearbyPrice}>{item.price}</Text>
                </View>
              </Pressable>
            ))}
          </View>
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  pressed: { opacity: 0.85, transform: [{ scale: 0.97 }] },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    height: theme.topNavHeight,
  },
  logo: { ...theme.typography.h1, color: theme.colors.foreground },
  bellBtn: {
    width: 40,
    height: 40,
    borderRadius: theme.radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scrollView: { flex: 1 },
  statusBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: theme.colors.surface,
    marginHorizontal: theme.spacing.md,
    marginTop: theme.spacing.xs,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    ...theme.shadows.sm,
  },
  statusLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  statusText: { ...theme.typography.caption, color: theme.colors.muted },
  statusBold: { fontWeight: '700', color: theme.colors.foreground },
  proBtn: {
    backgroundColor: theme.colors.primaryLight,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 4,
    borderRadius: theme.radius.full,
  },
  proBtnText: { ...theme.typography.micro, color: theme.colors.primary, fontWeight: '700' },
  categoriesRow: { paddingHorizontal: theme.spacing.md, paddingVertical: theme.spacing.md, gap: 4 },
  categoryItem: { alignItems: 'center', gap: 4, marginRight: theme.spacing.sm },
  categoryIcon: {
    width: 48,
    height: 48,
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    ...theme.shadows.sm,
  },
  categoryEmoji: { fontSize: 22 },
  categoryLabel: { ...theme.typography.micro, color: theme.colors.muted },
  sectionHeader: { paddingHorizontal: theme.spacing.md, marginBottom: theme.spacing.sm },
  sectionTitle: { ...theme.typography.h1, color: theme.colors.foreground },
  sectionSubtitle: { ...theme.typography.caption, color: theme.colors.subtle, marginTop: 2 },
  cardContainer: { minHeight: 390, alignItems: 'center', paddingHorizontal: theme.spacing.md },
  card: {
    position: 'absolute',
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    ...theme.shadows.md,
  },
  badgeLike: {
    position: 'absolute',
    top: 16,
    left: 16,
    zIndex: 10,
    borderWidth: 3,
    borderColor: theme.colors.success,
    backgroundColor: 'rgba(76, 175, 80, 0.15)',
    borderRadius: theme.radius.sm,
    paddingHorizontal: 16,
    paddingVertical: 6,
    transform: [{ rotate: '-12deg' }],
  },
  badgeLikeText: { ...theme.typography.caption, fontWeight: '700', color: theme.colors.success },
  badgeNope: {
    position: 'absolute',
    top: 16,
    right: 16,
    zIndex: 10,
    borderWidth: 3,
    borderColor: theme.colors.error,
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderRadius: theme.radius.sm,
    paddingHorizontal: 16,
    paddingVertical: 6,
    transform: [{ rotate: '12deg' }],
  },
  badgeNopeText: { ...theme.typography.caption, fontWeight: '700', color: theme.colors.error },
  cardImage: { height: 240, position: 'relative', borderTopLeftRadius: theme.radius.lg, borderTopRightRadius: theme.radius.lg, overflow: 'hidden' },
  cardImageOverlay: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    height: 80,
    backgroundColor: 'rgba(0,0,0,0.08)',
  },
  cardBadges: { position: 'absolute', top: theme.spacing.sm, left: theme.spacing.sm, flexDirection: 'row', gap: 6 },
  badgePill: {
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 4,
    borderRadius: theme.radius.full,
  },
  badgePillText: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.primary, textTransform: 'uppercase', letterSpacing: 0.5 },
  ratingBadge: {
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 4,
    borderRadius: theme.radius.full,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  ratingText: { ...theme.typography.micro, fontWeight: '600', color: theme.colors.foreground },
  cardBody: { padding: theme.spacing.md },
  cardTitleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 },
  cardTitle: { ...theme.typography.h1, color: theme.colors.foreground, flex: 1 },
  cardPrice: { ...theme.typography.h1, color: theme.colors.foreground },
  cardMeta: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: theme.spacing.xs },
  cardMetaText: { ...theme.typography.caption, color: theme.colors.muted },
  tagRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: { backgroundColor: theme.colors.borderLight, paddingHorizontal: theme.spacing.xs, paddingVertical: 4, borderRadius: theme.radius.sm },
  tagText: { ...theme.typography.micro, color: '#4B5563', fontWeight: '500' },
  actionRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: theme.spacing.lg, paddingVertical: theme.spacing.sm },
  actionBtn: {
    width: 56,
    height: 56,
    borderRadius: theme.radius.full,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.colors.surface,
    ...theme.shadows.md,
  },
  skipBtn: {},
  likeBtn: {},
  infoBtn: {
    width: 44,
    height: 44,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    ...theme.shadows.sm,
  },
  nearbySection: { paddingHorizontal: theme.spacing.md, marginTop: theme.spacing.xs },
  nearbyHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: theme.spacing.sm },
  nearbyTitle: { ...theme.typography.h2, color: theme.colors.foreground },
  seeAllText: { ...theme.typography.caption, color: theme.colors.primary, fontWeight: '500' },
  nearbyList: { gap: theme.spacing.xs },
  nearbyItem: {
    flexDirection: 'row',
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    padding: theme.spacing.sm,
    gap: theme.spacing.sm,
    alignItems: 'center',
    ...theme.shadows.sm,
  },
  nearbyImageWrap: { width: 72, height: 72, borderRadius: theme.radius.sm, overflow: 'hidden' },
  nearbyItemContent: { flex: 1 },
  nearbyItemTitle: { ...theme.typography.body, fontWeight: '700', color: theme.colors.foreground },
  nearbyItemSubtitle: { ...theme.typography.caption, color: theme.colors.subtle, marginTop: 2 },
  nearbyItemRight: { alignItems: 'flex-end' },
  nearbyRatingRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  nearbyRating: { ...theme.typography.caption, color: theme.colors.star, fontWeight: '700' },
  nearbyPrice: { ...theme.typography.body, fontWeight: '700', color: theme.colors.primary, marginTop: 2 },
  bottomPadding: { height: theme.spacing['2xl'] },
});
