import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { theme } from '../theme';
import { FAVORITES_DATA } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';

type NavProp = NativeStackNavigationProp<any>;

const CATEGORIES = ['All', 'Sichuan', 'Japanese', 'Dessert', 'Western'];

export function Favorites() {
  const navigation = useNavigation<NavProp>();
  const [activeCategory, setActiveCategory] = useState('All');

  const filtered =
    activeCategory === 'All'
      ? FAVORITES_DATA
      : FAVORITES_DATA.filter((f) => f.category === activeCategory);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav */}
      <View style={styles.topNav}>
        <View style={{ width: 40 }} />
        <Text style={styles.navTitle}>My Favorites</Text>
        <TouchableOpacity style={styles.moreBtn}>
          <Text style={styles.moreIcon}>⋯</Text>
        </TouchableOpacity>
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
            <TouchableOpacity
              style={[
                styles.tabPill,
                activeCategory === item && styles.tabPillActive,
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
            </TouchableOpacity>
          )}
        />
      </View>

      {filtered.length === 0 ? (
        <View style={styles.emptyState}>
          <View style={styles.emptyIcon}>
            <Text style={styles.emptyIconText}>🍽️</Text>
          </View>
          <Text style={styles.emptyTitle}>No favorites here yet</Text>
          <Text style={styles.emptyBody}>
            Start exploring and save your favorite dishes to see them here.
          </Text>
          <TouchableOpacity
            style={styles.exploreBtn}
            onPress={() => navigation.navigate('Explore')}
          >
            <Text style={styles.exploreBtnText}>Explore Dishes</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(item) => String(item.id)}
          numColumns={2}
          contentContainerStyle={styles.gridContent}
          columnWrapperStyle={styles.gridRow}
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.gridItem}
              onPress={() => navigation.navigate('Detail')}
            >
              <View style={styles.gridImageWrap}>
                <SkeletonImage src={item.image} alt={item.title} className="" />
                <TouchableOpacity style={styles.heartBtn}>
                  <Text style={styles.heartIcon}>❤️</Text>
                </TouchableOpacity>
              </View>
              <Text style={styles.gridItemTitle} numberOfLines={2}>
                {item.title}
              </Text>
              <View style={styles.gridItemMeta}>
                <Text style={styles.gridItemRating}>★ {item.rating} ({item.reviews})</Text>
              </View>
            </TouchableOpacity>
          )}
        />
      )}
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
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  navTitle: { fontSize: 16, fontWeight: '600', color: theme.colors.foreground },
  moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
  moreIcon: { fontSize: 18, color: '#6b7280' },
  tabBar: {
    backgroundColor: '#ffffff',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  tabList: { paddingHorizontal: 16, gap: 8 },
  tabPill: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: '#f3f4f6',
    marginRight: 8,
  },
  tabPillActive: { backgroundColor: theme.colors.brand },
  tabPillText: { fontSize: 13, fontWeight: '500', color: '#6b7280' },
  tabPillTextActive: { color: '#ffffff' },
  gridContent: { padding: 16, gap: 12 },
  gridRow: { justifyContent: 'space-between' },
  gridItem: { width: '48%', marginBottom: 16 },
  gridImageWrap: {
    height: 150,
    borderRadius: 14,
    overflow: 'hidden',
    marginBottom: 8,
    position: 'relative',
  },
  heartBtn: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.9)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heartIcon: { fontSize: 14 },
  gridItemTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: theme.colors.foreground,
    lineHeight: 18,
    marginBottom: 4,
  },
  gridItemMeta: { flexDirection: 'row', alignItems: 'center' },
  gridItemRating: { fontSize: 11, color: '#9ca3af' },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  emptyIcon: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: theme.colors.brandLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  emptyIconText: { fontSize: 36 },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: theme.colors.foreground,
    marginBottom: 8,
    textAlign: 'center',
  },
  emptyBody: {
    fontSize: 14,
    color: '#9ca3af',
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 24,
  },
  exploreBtn: {
    backgroundColor: theme.colors.brand,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 30,
  },
  exploreBtnText: { fontSize: 14, fontWeight: '700', color: '#ffffff' },
});
