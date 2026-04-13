import React, { useMemo } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Heart, MoreHorizontal, Star, UtensilsCrossed } from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';
import { FAVORITES_DATA } from '../data/mockData';
import type { RootStackParamList } from '../navigation/types';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function Favorites() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { favorites, toggleFavorite } = useApp();

  const displayData = useMemo(() => FAVORITES_DATA.filter((item) => favorites.includes(item.id)), [favorites]);
  const featuredPick = displayData[0] ?? null;

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <View style={styles.navSpacer} />
        <Text style={styles.navTitle}>Saved</Text>
        <Pressable style={({ pressed }) => [styles.moreBtn, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('History')} accessibilityRole="button" accessibilityLabel="Open decision history">
          <MoreHorizontal size={20} color={theme.colors.muted} strokeWidth={1.8} />
        </Pressable>
      </View>

      {displayData.length === 0 ? (
        <View style={styles.emptyState}>
          <View style={styles.emptyIcon}>
            <UtensilsCrossed size={36} color={theme.colors.primary} strokeWidth={1.5} />
          </View>
          <Text style={styles.emptyTitle}>Nothing saved yet</Text>
          <Text style={styles.emptyBody}>Save a few strong options for later.</Text>
          <Pressable style={({ pressed }) => [styles.exploreBtn, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('MainTabs', { screen: 'Home' })}>
            <Text style={styles.exploreBtnText}>Back to Home</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={displayData}
          keyExtractor={(item) => String(item.id)}
          numColumns={2}
          contentContainerStyle={styles.gridContent}
          columnWrapperStyle={styles.gridRow}
          ListHeaderComponent={
            featuredPick ? (
              <View style={styles.headerStack}>
                <View style={styles.summaryCard}>
                  <Text style={styles.summaryEyebrow}>Saved for later</Text>
                  <Text style={styles.summaryTitle}>{displayData.length} strong picks ready</Text>
                  <View style={styles.summaryActions}>
                    <Pressable style={({ pressed }) => [styles.summaryAction, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('Detail', { itemId: featuredPick.id, title: featuredPick.title, image: featuredPick.image })}>
                      <Text style={styles.summaryActionText}>Try tonight</Text>
                    </Pressable>
                    <Pressable style={({ pressed }) => [styles.summaryAction, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('History')}>
                      <Text style={styles.summaryActionText}>History</Text>
                    </Pressable>
                  </View>
                </View>

                <Pressable style={({ pressed }) => [styles.featuredCard, pressed && styles.pressedCard]} onPress={() => navigation.navigate('Detail', { itemId: featuredPick.id, title: featuredPick.title, image: featuredPick.image })}>
                  <View style={styles.featuredImage}>
                    <SkeletonImage src={featuredPick.image} alt={featuredPick.title} />
                  </View>
                  <View style={styles.featuredCopy}>
                    <Text style={styles.featuredEyebrow}>Tonight's easiest yes</Text>
                    <Text style={styles.featuredTitle}>{featuredPick.title}</Text>
                    <Text style={styles.featuredMeta}>{featuredPick.restaurantName} / {featuredPick.rating.toFixed(1)}</Text>
                  </View>
                </Pressable>
              </View>
            ) : null
          }
          renderItem={({ item }) => (
            <Pressable style={({ pressed }) => [styles.gridItem, pressed && styles.pressedCard]} onPress={() => navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.image })}>
              <View style={styles.gridImageWrap}>
                <SkeletonImage src={item.image} alt={item.title} />
                <Pressable style={({ pressed }) => [styles.heartBtn, pressed && styles.pressedChrome]} onPress={() => toggleFavorite(item.id)} accessibilityRole="button" accessibilityLabel="Remove from saved">
                  <Heart size={14} color={theme.colors.error} fill={theme.colors.error} strokeWidth={2} />
                </Pressable>
              </View>
              <Text style={styles.gridItemTitle} numberOfLines={2}>
                {item.title}
              </Text>
              <View style={styles.gridItemMeta}>
                <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
                <Text style={styles.gridItemRating}>{item.rating}</Text>
                <Text style={styles.gridItemDot}>/</Text>
                <Text style={styles.gridItemRating} numberOfLines={1}>{item.restaurantName}</Text>
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
    container: { flex: 1, backgroundColor: t.colors.surface },
    pressedCard: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
    topNav: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: t.spacing.md, height: t.topNavHeight, backgroundColor: t.colors.surface },
    navSpacer: { width: 40 },
    navTitle: { ...t.typography.h2, color: t.colors.foreground },
    moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
    gridContent: { padding: t.spacing.md, gap: t.spacing.sm },
    headerStack: { gap: t.spacing.md, marginBottom: t.spacing.sm },
    summaryCard: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.md,
      gap: t.spacing.sm,
    },
    summaryEyebrow: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    summaryTitle: { ...t.typography.h1, color: t.colors.foreground },
    summaryActions: { flexDirection: 'row', gap: t.spacing.sm },
    summaryAction: {
      minHeight: 36,
      borderRadius: t.radius.full,
      paddingHorizontal: 14,
      justifyContent: 'center',
      backgroundColor: 'rgba(255,255,255,0.78)',
    },
    summaryActionText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    featuredCard: {
      flexDirection: 'row',
      gap: t.spacing.sm,
      alignItems: 'center',
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
    },
    featuredImage: { width: 88, height: 88, borderRadius: t.radius.md, overflow: 'hidden' },
    featuredCopy: { flex: 1, gap: 3 },
    featuredEyebrow: { ...t.typography.micro, color: t.colors.primaryDark, fontWeight: '700' },
    featuredTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    featuredMeta: { ...t.typography.caption, color: t.colors.subtle },
    gridRow: { justifyContent: 'space-between' },
    gridItem: { width: '48%', marginBottom: t.spacing.md, backgroundColor: t.colors.surface, borderRadius: t.surface.cardRadius, padding: t.spacing.xs, minHeight: 232, ...t.shadows.sm },
    gridImageWrap: { height: 156, borderRadius: t.radius.md, overflow: 'hidden', marginBottom: t.spacing.sm, position: 'relative' },
    heartBtn: { position: 'absolute', top: t.spacing.xs, right: t.spacing.xs, width: 32, height: 32, borderRadius: t.radius.full, backgroundColor: 'rgba(255,255,255,0.92)', alignItems: 'center', justifyContent: 'center' },
    gridItemTitle: { ...t.typography.body, fontWeight: '700', color: t.colors.foreground, marginBottom: 6, minHeight: 42 },
    gridItemMeta: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingBottom: 2 },
    gridItemRating: { ...t.typography.caption, color: t.colors.subtle, flexShrink: 1 },
    gridItemDot: { ...t.typography.caption, color: t.colors.subtle },
    emptyState: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: t.spacing.xl },
    emptyIcon: { width: 80, height: 80, borderRadius: t.radius.full, backgroundColor: t.colors.primaryLight, alignItems: 'center', justifyContent: 'center', marginBottom: t.spacing.md },
    emptyTitle: { ...t.typography.h1, color: t.colors.foreground, marginBottom: t.spacing.xs, textAlign: 'center' },
    emptyBody: { ...t.typography.caption, color: t.colors.subtle, textAlign: 'center', marginBottom: t.spacing.lg },
    exploreBtn: { backgroundColor: t.colors.primary, paddingHorizontal: t.spacing.lg, paddingVertical: t.spacing.sm, borderRadius: t.radius.full },
    exploreBtnText: { ...t.typography.body, fontWeight: '700', color: t.colors.surface },
  });
}
