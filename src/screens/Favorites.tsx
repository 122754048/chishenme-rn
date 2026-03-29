import React from 'react';
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
import { FAVORITES_DATA, SWIPE_CARDS } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<any>;

export function Favorites() {
  const navigation = useNavigation<NavProp>();
  const { favorites } = useApp();

  const dynamicFavorites = favorites
    .map((id) => SWIPE_CARDS.find((card) => card.id === id) || FAVORITES_DATA.find((item) => item.id === id))
    .filter(Boolean);
  const source = dynamicFavorites;

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.moreBtn}>
          <Text style={styles.moreIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.navTitle}>我的收藏</Text>
        <View style={styles.moreBtn} />
      </View>

      <FlatList
        data={source}
        keyExtractor={(item) => String(item?.id)}
        numColumns={2}
        contentContainerStyle={styles.gridContent}
        columnWrapperStyle={styles.gridRow}
        renderItem={({ item }) => {
          if (!item) return null;
          const subtitle = 'reviews' in item ? `${item.reviews} reviews` : item.restaurant;
          return (
            <TouchableOpacity
              style={styles.gridItem}
              onPress={() => navigation.navigate('Detail')}
            >
              <View style={styles.gridImageWrap}>
                <SkeletonImage src={item.image} alt={item.title} className="" />
                <View style={styles.heartBtn}>
                  <Text style={styles.heartIcon}>❤️</Text>
                </View>
              </View>
              <Text style={styles.gridItemTitle} numberOfLines={2}>
                {item.title}
              </Text>
              <View style={styles.gridItemMeta}>
                <Text style={styles.gridItemRating}>★ {item.rating} · {subtitle}</Text>
              </View>
            </TouchableOpacity>
          );
        }}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <View style={styles.emptyIcon}>
              <Text style={styles.emptyIconText}>🍽️</Text>
            </View>
            <Text style={styles.emptyTitle}>还没有收藏</Text>
            <Text style={styles.emptyBody}>去首页右滑爱心把喜欢的菜加入收藏吧。</Text>
            <TouchableOpacity
              style={styles.exploreBtn}
              onPress={() => navigation.navigate('Home')}
            >
              <Text style={styles.exploreBtnText}>去首页看看</Text>
            </TouchableOpacity>
          </View>
        }
      />
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
  moreBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  moreIcon: { fontSize: 18, color: '#6b7280' },
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
    paddingTop: 80,
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
