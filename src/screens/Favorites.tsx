import React, { useState, useMemo } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSequence,
  withSpring,
} from 'react-native-reanimated';
import { MoreHorizontal, Heart, Star, UtensilsCrossed } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors, theme } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { FAVORITES_DATA } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

const CATEGORIES = ['All', 'Sichuan', 'Japanese', 'Dessert', 'Western'];

const heartBtnStyle = {
  position: 'absolute' as const,
  top: 8,
  right: 8,
  width: 32,
  height: 32,
  borderRadius: 16,
  backgroundColor: 'rgba(255,255,255,0.92)',
  alignItems: 'center' as const,
  justifyContent: 'center' as const,
};

function AnimatedHeartButton({ isFavorite, onToggle }: { isFavorite: boolean; onToggle: () => void }) {
  const scale = useSharedValue(1);
  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  const handlePress = () => {
    scale.value = withSequence(
      withSpring(1.4, { damping: 4, stiffness: 300 }),
      withSpring(1, { damping: 8, stiffness: 200 })
    );
    onToggle();
  };

  return (
    <Pressable onPress={handlePress} style={heartBtnStyle}>
      <Animated.View style={animStyle}>
        <Heart
          size={14}
          color={isFavorite ? theme.colors.error : theme.colors.subtle}
          fill={isFavorite ? theme.colors.error : 'transparent'}
          strokeWidth={2}
        />
      </Animated.View>
    </Pressable>
  );
}

export function Favorites() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const [activeCategory, setActiveCategory] = useState('All');
  const { favorites, toggleFavorite } = useApp();

  const displayData = useMemo(() => {
    if (favorites.length === 0) return FAVORITES_DATA;
    return FAVORITES_DATA.filter((item) => favorites.includes(item.id));
  }, [favorites]);

  const filtered =
    activeCategory === 'All'
      ? displayData
      : displayData.filter((f) => f.category === activeCategory);

  const navigateToDetail = (item: { id: number; title: string; image: string }) => {
    navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.image });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav �?Page mode */}
      <View style={styles.topNav}>
        <View style={{ width: 40 }} />
        <Text style={styles.navTitle}>My Favorites</Text>
        <Pressable style={({ pressed }) => [styles.moreBtn, pressed && { opacity: 0.7 }]}>
          <MoreHorizontal size={20} color={theme.colors.muted} strokeWidth={1.8} />
        </Pressable>
      </View>

      {/* Category Tabs */}
      <View style={styles.tabBar}>
        <FlatList
          horizontal
          data={CATEGORIES}
          keyExtractor={(item) => item}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.tabList}
          renderItem={({ item }) => (
            <Pressable
              style={({ pressed }) => [
                styles.tabPill,
                activeCategory === item && styles.tabPillActive,
                pressed && { opacity: 0.85 },
              ]}
              onPress={() => setActiveCategory(item)}
            >
              <Text
                style={[
                  styles.tabPillText,
                  activeCategory === item && styles.tabPillTextActive,
                ]}
              >
                {item}
              </Text>
            </Pressable>
          )}
        />
      </View>

      {filtered.length === 0 ? (
        <View style={styles.emptyState}>
          <View style={styles.emptyIcon}>
            <UtensilsCrossed size={36} color={theme.colors.primary} strokeWidth={1.5} />
          </View>
          <Text style={styles.emptyTitle}>No favorites here yet</Text>
          <Text style={styles.emptyBody}>
            Start exploring and save your favorite dishes to see them here.
          </Text>
          <Pressable
            style={({ pressed }) => [styles.exploreBtn, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]}
            onPress={() => navigation.navigate('MainTabs')}
          >
            <Text style={styles.exploreBtnText}>Explore Dishes</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(item) => String(item.id)}
          numColumns={2}
          contentContainerStyle={styles.gridContent}
          columnWrapperStyle={styles.gridRow}
          renderItem={({ item }) => (
            <Pressable
              style={({ pressed }) => [styles.gridItem, pressed && { opacity: 0.85 }]}
              onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
            >
              <View style={styles.gridImageWrap}>
                <SkeletonImage src={item.image} alt={item.title} />
                <AnimatedHeartButton
                  isFavorite={favorites.includes(item.id)}
                  onToggle={() => toggleFavorite(item.id)}
                />
              </View>
              <Text style={styles.gridItemTitle} numberOfLines={2}>
                {item.title}
              </Text>
              <View style={styles.gridItemMeta}>
                <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
                <Text style={styles.gridItemRating}>{item.rating} ({item.reviews})</Text>
              </View>
            </Pressable>
          )}
        />
      )}
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
    height: theme.topNavHeight,
    backgroundColor: t.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
  },
  navTitle: { ...theme.typography.h2, color: t.colors.foreground },
  moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
  tabBar: {
    backgroundColor: t.colors.surface,
    paddingVertical: t.spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
  },
  tabList: { paddingHorizontal: t.spacing.md, gap: t.spacing.xs },
  tabPill: {
    paddingHorizontal: t.spacing.md,
    paddingVertical: 6,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.borderLight,
  },
  tabPillActive: { backgroundColor: t.colors.primary },
  tabPillText: { ...theme.typography.caption, fontWeight: '500', color: t.colors.muted },
  tabPillTextActive: { color: t.colors.surface },
  gridContent: { padding: t.spacing.md, gap: t.spacing.sm },
  gridRow: { justifyContent: 'space-between' },
  gridItem: { width: '48%', marginBottom: t.spacing.md },
  gridImageWrap: {
    height: 150,
    borderRadius: t.radius.md,
    overflow: 'hidden',
    marginBottom: t.spacing.xs,
    position: 'relative',
  },
  heartBtn: {
    position: 'absolute',
    top: t.spacing.xs,
    right: t.spacing.xs,
    width: 32,
    height: 32,
    borderRadius: t.radius.full,
    backgroundColor: 'rgba(255,255,255,0.92)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  gridItemTitle: {
    ...theme.typography.body,
    fontWeight: '600',
    color: t.colors.foreground,
    marginBottom: 4,
  },
  gridItemMeta: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  gridItemRating: { ...theme.typography.caption, color: t.colors.subtle },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: t.spacing.xl,
  },
  emptyIcon: {
    width: 80,
    height: 80,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: t.spacing.md,
  },
  emptyTitle: {
    ...theme.typography.h1,
    color: t.colors.foreground,
    marginBottom: t.spacing.xs,
    textAlign: 'center',
  },
  emptyBody: {
    ...theme.typography.body,
    color: t.colors.subtle,
    textAlign: 'center',
    marginBottom: t.spacing.lg,
  },
  exploreBtn: {
    backgroundColor: t.colors.primary,
    paddingHorizontal: t.spacing.lg,
    paddingVertical: t.spacing.sm,
    borderRadius: t.radius.full,
  },
  exploreBtnText: { ...theme.typography.body, fontWeight: '700', color: t.colors.surface },
});
}



