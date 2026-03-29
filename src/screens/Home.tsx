import React, { useState, useCallback } from 'react';
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

function SwipeCard({ card, onSwipe }: { card: CardData; onSwipe: (dir: 'left' | 'right') => void }) {
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  const panResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderMove: (_, gestureState) => {
      translateX.value = gestureState.dx;
      translateY.value = gestureState.dy;
    },
    onPanResponderRelease: (_, gestureState) => {
      if (gestureState.dx > SWIPE_THRESHOLD || gestureState.vx > 0.5) {
        translateX.value = withTiming(SCREEN_WIDTH * 1.5, { duration: 300 });
        runOnJS(onSwipe)('right');
      } else if (gestureState.dx < -SWIPE_THRESHOLD || gestureState.vx < -0.5) {
        translateX.value = withTiming(-SCREEN_WIDTH * 1.5, { duration: 300 });
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
  const { recommendationsLeft, consumeRecommendation, addToHistory } = useApp();
  const [cardIndex, setCardIndex] = useState(0);

  const handleSwipe = useCallback((dir: 'left' | 'right') => {
    const current = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];
    void addToHistory({
      id: current.id,
      title: current.title,
      img: current.image,
      time: new Date().toISOString(),
      category: current.badge,
      status: dir === 'right' ? 'Liked' : 'Skipped',
    });
    consumeRecommendation();
    setCardIndex((prev) => prev + 1);
  }, [addToHistory, cardIndex, consumeRecommendation]);

  const currentCard = SWIPE_CARDS[cardIndex % SWIPE_CARDS.length];

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav */}
      <View style={styles.topNav}>
        <Text style={styles.logo}>🍽️ ChiShenMe</Text>
        <TouchableOpacity style={styles.bellBtn}>
          <Text style={styles.bellIcon}>🔔</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Status Bar */}
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

        {/* Quick Categories */}
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

        {/* Title */}
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>What to Eat Today</Text>
          <Text style={styles.sectionSubtitle}>Swipe right to like, left to skip</Text>
        </View>

        {/* Swipe Card */}
        <View style={styles.cardContainer}>
          {currentCard && (
            <SwipeCard key={`${currentCard.id}-${cardIndex}`} card={currentCard} onSwipe={handleSwipe} />
          )}
        </View>

        {/* Action Buttons */}
        <View style={styles.actionRow}>
          <TouchableOpacity
            style={[styles.actionBtn, styles.skipBtn]}
            onPress={() => handleSwipe('left')}
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
            onPress={() => handleSwipe('right')}
          >
            <Text style={styles.likeBtnIcon}>❤️</Text>
          </TouchableOpacity>
        </View>

        {/* Nearby Hot */}
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
  sectionSubtitle: { fontSize: 12, color: '#9ca3af', marginTop: 2 },
  cardContainer: { height: 390, alignItems: 'center', paddingHorizontal: 16 },
  card: {
    position: 'absolute',
    width: SCREEN_WIDTH - 32,
    backgroundColor: '#ffffff',
    borderRadius: 18,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 3,
  },
  badgeLike: {
    position: 'absolute',
    top: 16,
    left: 16,
    zIndex: 10,
    borderWidth: 2,
    borderColor: theme.colors.brand,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    transform: [{ rotate: '-12deg' }],
  },
  badgeLikeText: { fontSize: 13, fontWeight: '700', color: theme.colors.brand },
  badgeNope: {
    position: 'absolute',
    top: 16,
    right: 16,
    zIndex: 10,
    borderWidth: 2,
    borderColor: '#ef4444',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    transform: [{ rotate: '12deg' }],
  },
  badgeNopeText: { fontSize: 13, fontWeight: '700', color: '#ef4444' },
  cardImage: { height: 240, position: 'relative', borderRadius: 18, overflow: 'hidden' },
  cardBadges: { position: 'absolute', top: 12, left: 12, flexDirection: 'row', gap: 6 },
  badgePill: {
    backgroundColor: 'rgba(255,255,255,0.9)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 20,
  },
  badgePillText: { fontSize: 10, fontWeight: '700', color: theme.colors.brand, textTransform: 'uppercase', letterSpacing: 0.5 },
  ratingBadge: {
    backgroundColor: 'rgba(255,255,255,0.9)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 20,
  },
  ratingText: { fontSize: 10, fontWeight: '600', color: theme.colors.foreground },
  cardBody: { padding: 16 },
  cardTitleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 },
  cardTitle: { fontSize: 18, fontWeight: '700', color: theme.colors.foreground, flex: 1 },
  cardPrice: { fontSize: 18, fontWeight: '700', color: theme.colors.foreground },
  cardMeta: { marginBottom: 10 },
  cardMetaText: { fontSize: 12, color: '#6b7280' },
  tagRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: { backgroundColor: '#f3f4f6', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  tagText: { fontSize: 11, color: '#4b5563', fontWeight: '500' },
  actionRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 24, paddingVertical: 12 },
  actionBtn: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 2,
  },
  skipBtn: { backgroundColor: '#ffffff' },
  skipBtnIcon: { fontSize: 22, color: '#ef4444' },
  infoBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 2,
    elevation: 1,
  },
  infoBtnIcon: { fontSize: 18 },
  likeBtn: { backgroundColor: '#ffffff' },
  likeBtnIcon: { fontSize: 22 },
  nearbySection: { paddingHorizontal: 16, marginTop: 8 },
  nearbyHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  nearbyTitle: { fontSize: 16, fontWeight: '700', color: theme.colors.foreground },
  seeAllText: { fontSize: 12, color: theme.colors.brand, fontWeight: '500' },
  nearbyList: { gap: 10 },
  nearbyItem: {
    flexDirection: 'row',
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 10,
    gap: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
    alignItems: 'center',
  },
  nearbyItemContent: { flex: 1 },
  nearbyItemTitle: { fontSize: 14, fontWeight: '700', color: theme.colors.foreground },
  nearbyItemSubtitle: { fontSize: 11, color: '#9ca3af', marginTop: 2 },
  nearbyItemRight: { alignItems: 'flex-end' },
  nearbyRating: { fontSize: 11, color: theme.colors.star, fontWeight: '700' },
  nearbyPrice: { fontSize: 14, fontWeight: '700', color: theme.colors.brand, marginTop: 2 },
  bottomPadding: { height: 20 },
});
