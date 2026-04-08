import React, { useState } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Menu, User, Search, Star, Plus } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { EXPLORE_CARDS } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { SearchOverlay } from '../components/SearchOverlay';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

const CATEGORIES = ['Recommended', 'Chinese', 'Japanese'];

const SEASONAL_ITEMS = [
  {
    id: 1,
    title: 'Cinnamon Apple Tart',
    subtitle: 'Warm, flaky, and sweet.',
    price: '¥9.00',
    image: 'https://images.unsplash.com/photo-1620991565081-82743a5a499c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxibHVlYmVycnklMjBwYW5jYWtlc3xlbnwxfHx8fDE3NzQ2ODQxOTh8MA&ixlib=rb-4.1.0&q=80&w=1080',
  },
];

export function Explore() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const [activeCategory, setActiveCategory] = useState(0);
  const [showSearch, setShowSearch] = useState(false);

  const navigateToDetail = (item: { id: number; title: string; image: string }) => {
    navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.image });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav — Page mode */}
      <View style={styles.topNav}>
        <Pressable style={({ pressed }) => [styles.navBtn, pressed && styles.pressed]}>
          <Menu size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
        <Text style={styles.navTitle}>Discover</Text>
        <Pressable style={({ pressed }) => [styles.navBtn, pressed && styles.pressed]}>
          <User size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      {/* Sticky Search + Categories */}
      <View style={styles.stickyBar}>
        <Pressable
          style={({ pressed }) => [styles.searchBar, pressed && { opacity: 0.85 }]}
          onPress={() => setShowSearch(true)}
        >
          <Search size={16} color={theme.colors.subtle} strokeWidth={1.8} />
          <Text style={styles.searchPlaceholder}>Search for food or restaurants</Text>
        </Pressable>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.categoryScroll}
        >
          {CATEGORIES.map((cat, idx) => (
            <Pressable
              key={cat}
              style={({ pressed }) => [
                styles.categoryPill,
                idx === activeCategory && styles.categoryPillActive,
                pressed && { opacity: 0.85 },
              ]}
              onPress={() => setActiveCategory(idx)}
            >
              <Text
                style={[
                  styles.categoryPillText,
                  idx === activeCategory && styles.categoryPillTextActive,
                ]}
              >
                {cat}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Today's Picks */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Today's Picks</Text>
            <Pressable>
              <Text style={styles.seeAllText}>See all</Text>
            </Pressable>
          </View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.picksScroll}
          >
            {EXPLORE_CARDS.map((item) => (
              <Pressable
                key={item.id}
                style={({ pressed }) => [styles.pickCard, pressed && { opacity: 0.85 }]}
                onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
              >
                <View style={styles.pickImageWrap}>
                  <SkeletonImage src={item.image} alt={item.title} />
                  {item.badge && (
                    <View style={styles.pickBadge}>
                      <Text style={styles.pickBadgeText}>{item.badge}</Text>
                    </View>
                  )}
                </View>
                <Text style={styles.pickTitle}>{item.title}</Text>
                <View style={styles.pickMetaRow}>
                  <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
                  <Text style={styles.pickMeta}>{item.rating} ({item.reviews}) · {item.subtitle}</Text>
                </View>
              </Pressable>
            ))}
            <Pressable
              style={({ pressed }) => [styles.pickCard, pressed && { opacity: 0.85 }]}
              onPress={() => navigateToDetail({ id: 99, title: 'Butter Croissant', image: 'https://images.unsplash.com/photo-1555126634-323283e090fa?w=400' })}
            >
              <View style={styles.pickImageWrap}>
                <SkeletonImage
                  src="https://images.unsplash.com/photo-1555126634-323283e090fa?w=400"
                  alt="Croissant"
                />
              </View>
              <Text style={styles.pickTitle}>Butter Croissant</Text>
              <View style={styles.pickMetaRow}>
                <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
                <Text style={styles.pickMeta}>4.6 (42+) · Bakery · 5 min</Text>
              </View>
            </Pressable>
          </ScrollView>
        </View>

        {/* Seasonal */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Seasonal Recommendations</Text>

          <Pressable
            style={({ pressed }) => [styles.seasonalHero, pressed && { opacity: 0.9 }]}
            onPress={() => navigateToDetail({ id: 100, title: 'Maple Glazed Roasted Squash', image: 'https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?w=1080' })}
          >
            <SkeletonImage
              src="https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?w=1080"
              alt="Autumn Special"
            />
            <View style={styles.seasonalHeroOverlay}>
              <View style={styles.autumnBadge}>
                <Text style={styles.autumnBadgeText}>AUTUMN SPECIAL</Text>
              </View>
              <Text style={styles.seasonalHeroTitle}>Maple Glazed Roasted Squash</Text>
              <Text style={styles.seasonalHeroSubtitle}>Experience the warmth of the season in every bite.</Text>
            </View>
          </Pressable>

          {SEASONAL_ITEMS.map((item) => (
            <Pressable
              key={item.id}
              style={({ pressed }) => [styles.listItem, pressed && { opacity: 0.85 }]}
              onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
            >
              <View style={styles.listItemImage}>
                <SkeletonImage src={item.image} alt={item.title} />
              </View>
              <View style={styles.listItemContent}>
                <Text style={styles.listItemTitle}>{item.title}</Text>
                <Text style={styles.listItemSubtitle}>{item.subtitle}</Text>
              </View>
              <View style={styles.listItemRight}>
                <Text style={styles.listItemPrice}>{item.price}</Text>
                <Pressable style={({ pressed }) => [styles.addBtn, pressed && { backgroundColor: theme.colors.primaryLight }]}>
                  <Plus size={16} color={theme.colors.primary} strokeWidth={2.5} />
                </Pressable>
              </View>
            </Pressable>
          ))}
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>

      <SearchOverlay visible={showSearch} onClose={() => setShowSearch(false)} />
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
  container: { flex: 1, backgroundColor: t.colors.background },
  pressed: { opacity: 0.85, transform: [{ scale: 0.97 }] },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    height: t.topNavHeight,
    backgroundColor: t.colors.surface,
  },
  navBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: t.radius.md },
  navTitle: { ...t.typography.h2, color: t.colors.foreground },
  stickyBar: {
    backgroundColor: t.colors.surface,
    paddingHorizontal: t.spacing.md,
    paddingTop: t.spacing.xs,
    paddingBottom: t.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
    gap: t.spacing.xs,
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: t.colors.borderLight,
    borderRadius: t.radius.md,
    paddingHorizontal: t.spacing.sm,
    height: 40,
    gap: t.spacing.xs,
  },
  searchPlaceholder: { ...t.typography.body, color: t.colors.subtle },
  categoryScroll: { flexDirection: 'row', gap: t.spacing.xs },
  categoryPill: {
    paddingHorizontal: t.spacing.md,
    paddingVertical: 6,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.borderLight,
  },
  categoryPillActive: { backgroundColor: t.colors.primary },
  categoryPillText: { ...t.typography.caption, fontWeight: '500', color: t.colors.muted },
  categoryPillTextActive: { color: t.colors.surface },
  scrollView: { flex: 1 },
  section: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.lg },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: t.spacing.sm },
  sectionTitle: { ...t.typography.h2, color: t.colors.foreground, marginBottom: t.spacing.sm },
  seeAllText: { ...t.typography.caption, color: t.colors.primary, fontWeight: '500' },
  picksScroll: { paddingRight: t.spacing.md, gap: t.spacing.sm },
  pickCard: { width: 200 },
  pickImageWrap: { height: 140, borderRadius: t.radius.md, overflow: 'hidden', marginBottom: t.spacing.xs, position: 'relative' },
  pickBadge: {
    position: 'absolute',
    top: t.spacing.xs,
    right: t.spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 3,
    borderRadius: t.radius.sm,
  },
  pickBadgeText: { ...t.typography.micro, fontWeight: '700', color: t.colors.foreground },
  pickTitle: { ...t.typography.body, fontWeight: '600', color: t.colors.foreground, marginBottom: 2 },
  pickMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  pickMeta: { ...t.typography.micro, color: t.colors.subtle },
  seasonalHero: {
    height: 180,
    borderRadius: t.radius.lg,
    overflow: 'hidden',
    marginBottom: t.spacing.sm,
    position: 'relative',
  },
  seasonalHeroOverlay: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    padding: t.spacing.md,
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  autumnBadge: {
    backgroundColor: t.colors.warning,
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 3,
    borderRadius: t.radius.sm,
    alignSelf: 'flex-start',
    marginBottom: 6,
  },
  autumnBadgeText: { ...t.typography.micro, fontWeight: '700', color: t.colors.surface },
  seasonalHeroTitle: { ...t.typography.h2, fontWeight: '700', color: t.colors.surface },
  seasonalHeroSubtitle: { ...t.typography.caption, color: 'rgba(255,255,255,0.8)', marginTop: 2 },
  listItem: {
    flexDirection: 'row',
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.sm,
    gap: t.spacing.sm,
    marginBottom: t.spacing.xs,
    alignItems: 'center',
    ...t.shadows.sm,
  },
  listItemImage: { width: 56, height: 56, borderRadius: t.radius.sm, overflow: 'hidden' },
  listItemContent: { flex: 1 },
  listItemTitle: { ...t.typography.body, fontWeight: '700', color: t.colors.foreground },
  listItemSubtitle: { ...t.typography.caption, color: t.colors.subtle, marginTop: 2 },
  listItemRight: { alignItems: 'flex-end', justifyContent: 'space-between', height: 56 },
  listItemPrice: { ...t.typography.body, fontWeight: '700', color: t.colors.primary },
  addBtn: {
    width: 28,
    height: 28,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.borderLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bottomPadding: { height: t.spacing['2xl'] },
});
}
