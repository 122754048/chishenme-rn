import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
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
    price: '$9.00',
    image: 'https://images.unsplash.com/photo-1620991565081-82743a5a499c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxibHVlYmVycnklMjBwYW5jYWtlc3xlbnwxfHx8fDE3NzQ2ODQxOTh8MA&ixlib=rb-4.1.0&q=80&w=1080',
  },
];

export function Explore() {
  const navigation = useNavigation<NavProp>();
  const [activeCategory, setActiveCategory] = useState(0);
  const [showSearch, setShowSearch] = useState(false);

  const navigateToDetail = (item: { id: number; title: string; image: string }) => {
    navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.image });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav */}
      <View style={styles.topNav}>
        <Text style={styles.menuIcon}>☰</Text>
        <Text style={styles.navTitle}>Discover</Text>
        <TouchableOpacity>
          <Text style={styles.profileIcon}>👤</Text>
        </TouchableOpacity>
      </View>

      {/* Sticky Search + Categories */}
      <View style={styles.stickyBar}>
        <TouchableOpacity
          style={styles.searchBar}
          onPress={() => setShowSearch(true)}
        >
          <Text style={styles.searchIcon}>🔍</Text>
          <Text style={styles.searchPlaceholder}>Search for food or restaurants</Text>
        </TouchableOpacity>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.categoryScroll}
        >
          {CATEGORIES.map((cat, idx) => (
            <TouchableOpacity
              key={cat}
              style={[
                styles.categoryPill,
                idx === activeCategory && styles.categoryPillActive,
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
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Today's Picks */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Today's Picks</Text>
            <TouchableOpacity>
              <Text style={styles.seeAllText}>See all</Text>
            </TouchableOpacity>
          </View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.picksScroll}
          >
            {EXPLORE_CARDS.map((item) => (
              <TouchableOpacity
                key={item.id}
                style={styles.pickCard}
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
                <Text style={styles.pickMeta}>★ {item.rating} ({item.reviews}) • {item.subtitle}</Text>
              </TouchableOpacity>
            ))}
            {/* Extra placeholder cards for horizontal scroll feel */}
            <TouchableOpacity
              style={styles.pickCard}
              onPress={() => navigateToDetail({ id: 99, title: 'Butter Croissant', image: 'https://images.unsplash.com/photo-1555126634-323283e090fa?w=400' })}
            >
              <View style={styles.pickImageWrap}>
                <SkeletonImage
                  src="https://images.unsplash.com/photo-1555126634-323283e090fa?w=400"
                  alt="Croissant"
                />
              </View>
              <Text style={styles.pickTitle}>Butter Croissant</Text>
              <Text style={styles.pickMeta}>★ 4.6 (42+) • Bakery • 5 min</Text>
            </TouchableOpacity>
          </ScrollView>
        </View>

        {/* Seasonal */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Seasonal Recommendations</Text>

          {/* Hero seasonal card */}
          <TouchableOpacity
            style={styles.seasonalHero}
            onPress={() => navigateToDetail({ id: 100, title: 'Maple Glazed Roasted Squash', image: 'https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxzYWxtb24lMjBib3dsfGVufDF8fHx8MTc3NDY4NDE4N3ww&ixlib=rb-4.1.0&q=80&w=1080' })}
          >
            <SkeletonImage
              src="https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxzYWxtb24lMjBib3dsfGVufDF8fHx8MTc3NDY4NDE4N3ww&ixlib=rb-4.1.0&q=80&w=1080"
              alt="Autumn Special"
            />
            <View style={styles.seasonalHeroOverlay}>
              <View style={styles.autumnBadge}>
                <Text style={styles.autumnBadgeText}>AUTUMN SPECIAL</Text>
              </View>
              <Text style={styles.seasonalHeroTitle}>Maple Glazed Roasted Squash</Text>
              <Text style={styles.seasonalHeroSubtitle}>Experience the warmth of the season in every bite.</Text>
            </View>
          </TouchableOpacity>

          {/* Issue #15: Fixed — listItem SkeletonImage now has explicit dimensions via wrapper View */}
          {SEASONAL_ITEMS.map((item) => (
            <TouchableOpacity
              key={item.id}
              style={styles.listItem}
              onPress={() => navigateToDetail({ id: item.id, title: item.title, image: item.image })}
            >
              <View style={{ width: 56, height: 56, borderRadius: 10, overflow: 'hidden' }}>
                <SkeletonImage src={item.image} alt={item.title} />
              </View>
              <View style={styles.listItemContent}>
                <Text style={styles.listItemTitle}>{item.title}</Text>
                <Text style={styles.listItemSubtitle}>{item.subtitle}</Text>
              </View>
              <View style={styles.listItemRight}>
                <Text style={styles.listItemPrice}>{item.price}</Text>
                <TouchableOpacity style={styles.addBtn}>
                  <Text style={styles.addBtnText}>+</Text>
                </TouchableOpacity>
              </View>
            </TouchableOpacity>
          ))}
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>

      <SearchOverlay visible={showSearch} onClose={() => setShowSearch(false)} />
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
    backgroundColor: '#ffffff',
  },
  menuIcon: { fontSize: 20 },
  navTitle: { fontSize: 16, fontWeight: '600', color: theme.colors.foreground },
  profileIcon: { fontSize: 22 },
  stickyBar: {
    backgroundColor: '#ffffff',
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
    gap: 10,
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f3f4f6',
    borderRadius: 10,
    paddingHorizontal: 12,
    height: 40,
    gap: 8,
  },
  searchIcon: { fontSize: 14 },
  searchPlaceholder: { fontSize: 14, color: '#9ca3af' },
  categoryScroll: { flexDirection: 'row', gap: 8 },
  categoryPill: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: '#f3f4f6',
  },
  categoryPillActive: { backgroundColor: theme.colors.brand },
  categoryPillText: { fontSize: 13, fontWeight: '500', color: '#6b7280' },
  categoryPillTextActive: { color: '#ffffff' },
  scrollView: { flex: 1 },
  section: { paddingHorizontal: 16, paddingTop: 20 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sectionTitle: { fontSize: 16, fontWeight: '700', color: theme.colors.foreground, marginBottom: 12 },
  seeAllText: { fontSize: 12, color: theme.colors.brand, fontWeight: '500' },
  picksScroll: { paddingRight: 16, gap: 12 },
  pickCard: { width: 200 },
  pickImageWrap: { height: 140, borderRadius: 14, overflow: 'hidden', marginBottom: 8, position: 'relative' },
  pickBadge: {
    position: 'absolute',
    top: 8,
    right: 8,
    backgroundColor: 'rgba(255,255,255,0.9)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
  },
  pickBadgeText: { fontSize: 9, fontWeight: '700', color: theme.colors.foreground },
  pickTitle: { fontSize: 13, fontWeight: '600', color: theme.colors.foreground, marginBottom: 2 },
  pickMeta: { fontSize: 10, color: '#9ca3af' },
  seasonalHero: {
    height: 180,
    borderRadius: 14,
    overflow: 'hidden',
    marginBottom: 12,
    position: 'relative',
  },
  seasonalHeroOverlay: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    padding: 16,
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  autumnBadge: {
    backgroundColor: theme.colors.brandAccent,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    alignSelf: 'flex-start',
    marginBottom: 6,
  },
  autumnBadgeText: { fontSize: 9, fontWeight: '700', color: '#ffffff' },
  seasonalHeroTitle: { fontSize: 16, fontWeight: '700', color: '#ffffff', lineHeight: 22 },
  seasonalHeroSubtitle: { fontSize: 11, color: 'rgba(255,255,255,0.75)', marginTop: 2 },
  listItem: {
    flexDirection: 'row',
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 10,
    gap: 12,
    marginBottom: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
    alignItems: 'center',
  },
  listItemContent: { flex: 1 },
  listItemTitle: { fontSize: 14, fontWeight: '700', color: theme.colors.foreground },
  listItemSubtitle: { fontSize: 11, color: '#9ca3af', marginTop: 2 },
  listItemRight: { alignItems: 'flex-end', justifyContent: 'space-between', height: 60 },
  listItemPrice: { fontSize: 14, fontWeight: '700', color: theme.colors.brand },
  addBtn: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: '#f3f4f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  addBtnText: { fontSize: 16, color: theme.colors.brand, fontWeight: '600' },
  bottomPadding: { height: 20 },
});
