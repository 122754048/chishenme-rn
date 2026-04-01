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
import { MoreHorizontal, Heart, Star, UtensilsCrossed } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
import { FAVORITES_DATA } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

const CATEGORIES = ['All', 'Sichuan', 'Japanese', 'Dessert', 'Western'];

export function Favorites() {
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
      {/* Top Nav — Page mode */}
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
                <Pressable
                  style={({ pressed }) => [styles.heartBtn, pressed && { transform: [{ scale: 1.2 }] }]}
                  onPress={() => toggleFavorite(item.id)}
                >
                  <Heart
                    size={14}
                    color={favorites.includes(item.id) ? theme.colors.error : theme.colors.subtle}
                    fill={favorites.includes(item.id) ? theme.colors.error : 'transparent'}
                    strokeWidth={2}
                  />
                </Pressable>
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    height: theme.topNavHeight,
    backgroundColor: theme.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderLight,
  },
  navTitle: { ...theme.typography.h2, color: theme.colors.foreground },
  moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
  tabBar: {
    backgroundColor: theme.colors.surface,
    paddingVertical: theme.spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderLight,
  },
  tabList: { paddingHorizontal: theme.spacing.md, gap: theme.spacing.xs },
  tabPill: {
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 6,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.borderLight,
  },
  tabPillActive: { backgroundColor: theme.colors.primary },
  tabPillText: { ...theme.typography.caption, fontWeight: '500', color: theme.colors.muted },
  tabPillTextActive: { color: theme.colors.surface },
  gridContent: { padding: theme.spacing.md, gap: theme.spacing.sm },
  gridRow: { justifyContent: 'space-between' },
  gridItem: { width: '48%', marginBottom: theme.spacing.md },
  gridImageWrap: {
    height: 150,
    borderRadius: theme.radius.md,
    overflow: 'hidden',
    marginBottom: theme.spacing.xs,
    position: 'relative',
  },
  heartBtn: {
    position: 'absolute',
    top: theme.spacing.xs,
    right: theme.spacing.xs,
    width: 32,
    height: 32,
    borderRadius: theme.radius.full,
    backgroundColor: 'rgba(255,255,255,0.92)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  gridItemTitle: {
    ...theme.typography.body,
    fontWeight: '600',
    color: theme.colors.foreground,
    marginBottom: 4,
  },
  gridItemMeta: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  gridItemRating: { ...theme.typography.caption, color: theme.colors.subtle },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: theme.spacing.xl,
  },
  emptyIcon: {
    width: 80,
    height: 80,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: theme.spacing.md,
  },
  emptyTitle: {
    ...theme.typography.h1,
    color: theme.colors.foreground,
    marginBottom: theme.spacing.xs,
    textAlign: 'center',
  },
  emptyBody: {
    ...theme.typography.body,
    color: theme.colors.subtle,
    textAlign: 'center',
    marginBottom: theme.spacing.lg,
  },
  exploreBtn: {
    backgroundColor: theme.colors.primary,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.sm,
    borderRadius: theme.radius.full,
  },
  exploreBtnText: { ...theme.typography.body, fontWeight: '700', color: theme.colors.surface },
});
