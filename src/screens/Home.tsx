import React, { useState, useCallback, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Dimensions,
  PanResponder,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
  runOnJS,
} from 'react-native-reanimated';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { theme } from '../theme';
import { SWIPE_CARDS, CATEGORIES, NEARBY_ITEMS } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const SWIPE_THRESHOLD = 100;

type NavProp = NativeStackNavigationProp<any>;

type SwipeDirection = 'left' | 'right';

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

function SwipeCard({
  card,
  onSwipe,
  externalSwipe,
}: {
  card: CardData;
  onSwipe: (dir: SwipeDirection) => void;
  externalSwipe: SwipeDirection | null;
}) {
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  const performSwipe = useCallback(
    (dir: SwipeDirection) => {
      translateX.value = withTiming(dir === 'right' ? SCREEN_WIDTH * 1.5 : -SCREEN_WIDTH * 1.5, { duration: 260 });
      translateY.value = withTiming(10, { duration: 260 });
      setTimeout(() => onSwipe(dir), 220);
    },
    [onSwipe, translateX, translateY]
  );

  useEffect(() => {
    if (!externalSwipe) return;
    performSwipe(externalSwipe);
  }, [externalSwipe, performSwipe]);

  const panResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderMove: (_, gestureState) => {
      translateX.value = gestureState.dx;
      translateY.value = gestureState.dy;
    },
    onPanResponderRelease: (_, gestureState) => {
      if (gestureState.dx > SWIPE_THRESHOLD || gestureState.vx > 0.5) {
        translateX.value = withTiming(SCREEN_WIDTH * 1.5, { duration: 240 });
        runOnJS(onSwipe)('right');
      } else if (gestureState.dx < -SWIPE_THRESHOLD || gestureState.vx < -0.5) {
        translateX.value = withTiming(-SCREEN_WIDTH * 1.5, { duration: 240 });
        runOnJS(onSwipe)('left');
      } else {
        translateX.value = withSpring(0);
        translateY.value = withSpring(0);
      }
    },
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
    <Animated.View
      style={[styles.card, cardStyle]}
      {...panResponder.panHandlers}
    >
      <Animated.View style={[styles.badgeLike, likeOpacity]}>
        <Text style={styles.badgeLikeText}>LIKE</Text>
      </Animated.View>
      <Animated.View style={[styles.badgeNope, nopeOpacity]}>
        <Text style={styles.badgeNopeText}>NOPE</Text>
      </Animated.View>

      <View style={styles.cardImage}>
        <SkeletonImage src={card.image} alt={card.title} />
        <View style={styles.cardBadges}>
          <View style={styles.badgePill}>
            <Text style={styles.badgePillText}>{card.badge}</Text>
          </View>
          <View style={styles.ratingBadge}>
            <Text style={styles.ratingText}>★ {card.rating}</Text>
          </View>
        </View>
      </View>
      <View style={styles.cardBody}>
        <View style={styles.cardTitleRow}>
          <Text style={styles.cardTitle}>{card.title}</Text>
          <Text style={styles.cardPrice}>{card.price}</Text>
        </View>
        <View style={styles.cardMeta}>
          <Text style={styles.cardMetaText}>📍 {card.restaurant} • {card.distance}</Text>
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
  );
}

export function Home() {
  const navigation = useNavigation<NavProp>();
  const { recommendationsLeft, consumeRecommendation, addToHistory, isFavorite, toggleFavorite } = useApp();
  const [cardIndex, setCardIndex] = useState(0);
  const [buttonSwipe, setButtonSwipe] = useState<SwipeDirection | null>(null);

  const handleSwipe = useCallback((dir: SwipeDirection) => {
    const current = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];
    void addToHistory({
      id: current.id,
      title: current.title,
      img: current.image,
      time: new Date().toISOString(),
      category: current.badge,
      status: dir === 'right' ? 'Liked' : 'Skipped',
    });
    if (dir === 'right' && !isFavorite(current.id)) {
      void toggleFavorite(current.id);
    }
    consumeRecommendation();
    setCardIndex((prev) => prev + 1);
    setButtonSwipe(null);
  }, [addToHistory, cardIndex, consumeRecommendation, isFavorite, toggleFavorite]);

  const currentCard = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <Text style={styles.logo}>🍽️ ChiShenMe</Text>
        <TouchableOpacity style={styles.bellBtn}>
          <Text style={styles.bellIcon}>🔔</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        <View style={styles.statusBar}>
          <View style={styles.statusLeft}>
            <Text style={styles.zapIcon}>⚡</Text>
            <Text style={styles.statusText}>
              <Text style={styles.statusBold}>{recommendationsLeft}</Text> recommendations left today
            </Text>
          </View>
          <TouchableOpacity
            style={styles.proBtn}
            onPress={() => navigation.navigate('Upgrade')}
          >
            <Text style={styles.proBtnText}>Go PRO</Text>
          </TouchableOpacity>
        </View>

        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.categoriesRow}
        >
          {CATEGORIES.map((cat) => (
            <TouchableOpacity
              key={cat.label}
              style={styles.categoryItem}
              onPress={() => navigation.navigate('Explore')}
            >
              <View style={styles.categoryIcon}>
                <Text style={styles.categoryEmoji}>{cat.icon}</Text>
              </View>
              <Text style={styles.categoryLabel}>{cat.label}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>What to Eat Today</Text>
          <Text style={styles.sectionSubtitle}>X 向左滑过，❤️ 向右滑过</Text>
        </View>

        <View style={styles.cardContainer}>
          {currentCard && (
            <SwipeCard
              key={`${currentCard.id}-${cardIndex}`}
              card={currentCard}
              onSwipe={handleSwipe}
              externalSwipe={buttonSwipe}
            />
          )}
        </View>

        <View style={styles.actionRow}>
          <TouchableOpacity
            style={[styles.actionBtn, styles.skipBtn]}
            onPress={() => setButtonSwipe('left')}
          >
            <Text style={styles.skipBtnIcon}>✕</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.infoBtn}
            onPress={() => navigation.navigate('Detail')}
          >
            <Text style={styles.infoBtnIcon}>ℹ️</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.actionBtn, styles.likeBtn]}
            onPress={() => setButtonSwipe('right')}
          >
            <Text style={styles.likeBtnIcon}>❤️</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.nearbySection}>
          <View style={styles.nearbyHeader}>
            <Text style={styles.nearbyTitle}>Nearby Hot</Text>
            <TouchableOpacity onPress={() => navigation.navigate('Explore')}>
              <Text style={styles.seeAllText}>See all →</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.nearbyList}>
            {NEARBY_ITEMS.map((item) => (
              <TouchableOpacity
                key={item.id}
                style={styles.nearbyItem}
                onPress={() => navigation.navigate('Detail')}
              >
                <View style={{ width: 60, height: 60, borderRadius: 10, overflow: 'hidden' }}>
                  <SkeletonImage src={item.image} alt={item.title} />
                </View>
                <View style={styles.nearbyItemContent}>
                  <Text style={styles.nearbyItemTitle}>{item.title}</Text>
                  <Text style={styles.nearbyItemSubtitle}>{item.subtitle}</Text>
                </View>
                <View style={styles.nearbyItemRight}>
                  <Text style={styles.nearbyRating}>★ {item.rating}</Text>
                  <Text style={styles.nearbyPrice}>{item.price}</Text>
                </View>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.surface },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  logo: { fontSize: 18, fontWeight: '700', color: theme.colors.foreground },
  bellBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  bellIcon: { fontSize: 20 },
  scrollView: { flex: 1 },
  statusBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    marginTop: 8,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  statusLeft: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  zapIcon: { fontSize: 14 },
  statusText: { fontSize: 12, color: '#6b7280' },
  statusBold: { fontWeight: '700', color: theme.colors.foreground },
  proBtn: {
    backgroundColor: theme.colors.brandLight,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 20,
  },
  proBtnText: { fontSize: 10, fontWeight: '700', color: theme.colors.brand },
  categoriesRow: { paddingHorizontal: 16, paddingVertical: 16, gap: 4 },
  categoryItem: { alignItems: 'center', gap: 4, marginRight: 12 },
  categoryIcon: {
    width: 48,
    height: 48,
    backgroundColor: '#ffffff',
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 2,
    elevation: 1,
  },
  categoryEmoji: { fontSize: 22 },
  categoryLabel: { fontSize: 10, color: '#6b7280', fontWeight: '500' },
  sectionHeader: { paddingHorizontal: 16, marginBottom: 12 },
  sectionTitle: { fontSize: 20, fontWeight: '700', color: theme.colors.foreground },
  sectionSubtitle: { fontSize: 12, color: '#6b7280', marginTop: 3 },
  cardContainer: {
    height: 420,
    paddingHorizontal: 16,
    marginBottom: 12,
  },
  card: {
    flex: 1,
    backgroundColor: '#ffffff',
    borderRadius: 20,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.08,
    shadowRadius: 8,
    elevation: 3,
  },
  badgeLike: {
    position: 'absolute',
    top: 20,
    left: 20,
    zIndex: 10,
    borderWidth: 2,
    borderColor: '#22c55e',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    transform: [{ rotate: '-15deg' }],
    backgroundColor: 'rgba(255,255,255,0.9)',
  },
  badgeLikeText: { color: '#22c55e', fontSize: 22, fontWeight: '700' },
  badgeNope: {
    position: 'absolute',
    top: 20,
    right: 20,
    zIndex: 10,
    borderWidth: 2,
    borderColor: '#ef4444',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    transform: [{ rotate: '15deg' }],
    backgroundColor: 'rgba(255,255,255,0.9)',
  },
  badgeNopeText: { color: '#ef4444', fontSize: 22, fontWeight: '700' },
  cardImage: { height: 250, position: 'relative' },
  cardBadges: {
    position: 'absolute',
    top: 12,
    left: 12,
    right: 12,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  badgePill: {
    backgroundColor: 'rgba(255,255,255,0.9)',
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  badgePillText: { fontSize: 10, fontWeight: '700', color: theme.colors.foreground },
  ratingBadge: {
    backgroundColor: 'rgba(0,0,0,0.6)',
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  ratingText: { color: '#ffffff', fontSize: 11, fontWeight: '600' },
  cardBody: { padding: 16, flex: 1 },
  cardTitleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 6,
  },
  cardTitle: { fontSize: 20, fontWeight: '700', color: theme.colors.foreground, flex: 1 },
  cardPrice: { fontSize: 18, fontWeight: '700', color: theme.colors.brand },
  cardMeta: { marginBottom: 10 },
  cardMetaText: { fontSize: 12, color: '#6b7280' },
  tagRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tag: {
    backgroundColor: '#f3f4f6',
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  tagText: { fontSize: 10, color: '#6b7280', fontWeight: '500' },
  actionRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 20,
    marginBottom: 20,
  },
  actionBtn: {
    width: 62,
    height: 62,
    borderRadius: 31,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 3,
    elevation: 2,
  },
  skipBtn: { backgroundColor: '#ffffff' },
  likeBtn: { backgroundColor: '#ECFDF3' },
  skipBtnIcon: { fontSize: 26, color: '#ef4444', fontWeight: '700' },
  likeBtnIcon: { fontSize: 25 },
  infoBtn: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 3,
    elevation: 2,
  },
  infoBtnIcon: { fontSize: 20 },
  nearbySection: { paddingHorizontal: 16 },
  nearbyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  nearbyTitle: { fontSize: 16, fontWeight: '700', color: theme.colors.foreground },
  seeAllText: { fontSize: 12, color: theme.colors.brand, fontWeight: '600' },
  nearbyList: { gap: 10 },
  nearbyItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 10,
    gap: 10,
  },
  nearbyItemContent: { flex: 1 },
  nearbyItemTitle: { fontSize: 14, fontWeight: '600', color: theme.colors.foreground },
  nearbyItemSubtitle: { fontSize: 11, color: '#9ca3af', marginTop: 2 },
  nearbyItemRight: { alignItems: 'flex-end', gap: 4 },
  nearbyRating: { fontSize: 12, color: '#111827', fontWeight: '600' },
  nearbyPrice: { fontSize: 12, color: theme.colors.brand, fontWeight: '700' },
  bottomPadding: { height: 20 },
});
