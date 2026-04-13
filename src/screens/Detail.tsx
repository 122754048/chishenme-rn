import React from 'react';
import { Alert, Linking, Pressable, ScrollView, Share, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, { useAnimatedScrollHandler, useAnimatedStyle, useSharedValue } from 'react-native-reanimated';
import { ArrowLeft, CheckCircle2, Heart, MapPin, Share2, ShieldCheck, Star } from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';
import { SWIPE_CARDS } from '../data/mockData';
import type { RootStackParamList } from '../navigation/types';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { formatDistanceMiles } from '../utils/location';
import { buildDecisionSnapshot, getRecommendationById, getRelatedRecommendations } from '../utils/recommendations';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type DetailRouteProp = RouteProp<RootStackParamList, 'Detail'>;

export function Detail() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const route = useRoute<DetailRouteProp>();
  const { width: screenWidth } = useWindowDimensions();
  const { addToHistory, isFavorite, selectedCuisines, selectedRestrictions, toggleFavorite } = useApp();

  const itemId = route.params?.itemId ?? SWIPE_CARDS[0].id;
  const fallbackDish = SWIPE_CARDS.find((item) => item.id === itemId) ?? SWIPE_CARDS[0];
  const recommendation = getRecommendationById(itemId, { selectedCuisines, selectedRestrictions });
  const dish = recommendation?.dish ?? fallbackDish;
  const reasons = recommendation?.reasons ?? [dish.recommendationBlurb];
  const decisionSnapshot = buildDecisionSnapshot(dish);
  const related = getRelatedRecommendations(dish.id, { selectedCuisines, selectedRestrictions });
  const liked = isFavorite(dish.id);
  const distanceLabel = formatDistanceMiles(dish.distanceMeters) ?? dish.distance;
  const scrollY = useSharedValue(0);
  const scrollHandler = useAnimatedScrollHandler({
    onScroll: (event) => {
      scrollY.value = event.contentOffset.y;
    },
  });

  const navBarStyle = useAnimatedStyle(() => {
    return { backgroundColor: 'transparent' };
  });

  const heroImageStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: scrollY.value * 0.35 }, { scale: 1 + scrollY.value * 0.0006 }],
  }));

  const compatibility =
    selectedRestrictions.length === 0
      ? 'No dietary restrictions are set yet, so this ranking leans on taste match, timing, and nearby quality signals.'
      : dish.restrictionConflicts.length === 0
        ? `This pick avoids your current restrictions: ${selectedRestrictions.join(', ')}.`
        : `Watch for ${dish.restrictionConflicts.join(', ')} in this dish before you order.`;

  const handleOpenMap = async () => {
    const query = encodeURIComponent(`${dish.restaurantName} ${dish.restaurantAddress}`);
    const url = `https://www.google.com/maps/search/?api=1&query=${query}`;

    try {
      await Linking.openURL(url);
    } catch (error) {
      Alert.alert('Map unavailable', error instanceof Error ? error.message : 'Please try again in a moment.');
    }
  };

  const handleShare = async () => {
    await Share.share({
      message: `A strong pick from ${dish.restaurantName}: ${dish.name}.`,
    });
  };

  const handleChoose = async () => {
    await addToHistory({
      id: dish.id,
      title: dish.name,
      img: dish.image,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      createdAt: Date.now(),
      category: dish.restaurantName,
      status: 'Liked',
    });
    Alert.alert('Saved for today', `${dish.name} is now in your decision history for a faster return later.`);
  };

  return (
    <View style={styles.container}>
      <SafeAreaView edges={['top']} style={styles.navBarOuter}>
        <Animated.View style={[styles.navBar, navBarStyle]}>
          <Pressable style={({ pressed }) => [styles.navCircle, pressed && styles.pressedChrome]} onPress={() => navigation.goBack()} accessibilityRole="button" accessibilityLabel="Go back">
            <ArrowLeft size={18} color={theme.colors.foreground} strokeWidth={2} />
          </Pressable>
          <View style={styles.navRight}>
            <Pressable style={({ pressed }) => [styles.navCircle, pressed && styles.pressedChrome]} onPress={handleShare} accessibilityRole="button" accessibilityLabel="Share this pick">
              <Share2 size={16} color={theme.colors.foreground} strokeWidth={2} />
            </Pressable>
            <Pressable style={({ pressed }) => [styles.navCircle, pressed && styles.pressedChrome]} onPress={() => toggleFavorite(dish.id)} accessibilityRole="button" accessibilityLabel={liked ? 'Remove from saved' : 'Save this pick'}>
              <Heart size={16} color={liked ? theme.colors.error : theme.colors.foreground} fill={liked ? theme.colors.error : 'transparent'} strokeWidth={2} />
            </Pressable>
          </View>
        </Animated.View>
      </SafeAreaView>

      <Animated.ScrollView style={styles.scrollView} onScroll={scrollHandler} scrollEventThrottle={16} showsVerticalScrollIndicator={false}>
        <View style={styles.heroWrap}>
          <Animated.View style={[styles.heroImage, { width: screenWidth, height: 380 }, heroImageStyle]}>
            <SkeletonImage src={dish.image} alt={dish.name} />
          </Animated.View>
          <View style={styles.heroOverlay}>
            <View style={styles.topline}>
              <View style={styles.categoryPill}>
                <Text style={styles.categoryPillText} numberOfLines={1}>
                  {dish.restaurantName}
                </Text>
              </View>
              <View style={styles.ratingBadge}>
                <Star size={12} color={theme.colors.star} fill={theme.colors.star} />
                <Text style={styles.ratingText}>{dish.restaurantRating.toFixed(1)}</Text>
              </View>
            </View>
            <Text style={styles.dishTitle}>{dish.name}</Text>
            {reasons[0] ? (
              <Text style={styles.heroSupportText} numberOfLines={1}>
                {reasons[0]}
              </Text>
            ) : null}
            <View style={styles.heroMetaRow}>
              <Text style={styles.heroMetaText}>{distanceLabel}</Text>
              <Text style={styles.heroMetaDot}>/</Text>
              <Text style={styles.heroMetaText}>{dish.prepTime}</Text>
              <Text style={styles.heroMetaDot}>/</Text>
              <Text style={styles.heroMetaText}>{dish.restaurantPriceLevel}</Text>
            </View>
          </View>
        </View>

        <View style={styles.content}>
          <Pressable style={({ pressed }) => [styles.restaurantRow, pressed && styles.pressedCard]} onPress={handleOpenMap}>
            <MapPin size={14} color={theme.colors.primary} strokeWidth={2} />
            <View style={styles.restaurantCopy}>
              <Text style={styles.restaurantText}>{dish.restaurantName}</Text>
              <Text style={styles.restaurantSubtext}>{dish.restaurantAddress}</Text>
              <Text style={styles.restaurantActionText}>Open in Maps</Text>
            </View>
          </Pressable>

          <View style={styles.quickActionRow}>
            <Pressable style={({ pressed }) => [styles.quickActionCard, pressed && styles.pressedCard]} onPress={handleOpenMap}>
              <MapPin size={18} color={theme.colors.primary} strokeWidth={2} />
              <Text style={styles.quickActionLabel}>Next step</Text>
              <Text style={styles.quickActionValue}>Route there</Text>
            </Pressable>
            <Pressable style={({ pressed }) => [styles.quickActionCard, pressed && styles.pressedCard]} onPress={handleShare}>
              <Share2 size={18} color={theme.colors.primary} strokeWidth={2} />
              <Text style={styles.quickActionLabel}>Share</Text>
              <Text style={styles.quickActionValue}>Ask someone</Text>
            </Pressable>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Why it fits</Text>
            {reasons.map((reason) => (
              <View key={reason} style={styles.reasonRow}>
                <CheckCircle2 size={14} color={theme.colors.primary} strokeWidth={2.3} />
                <Text style={styles.reasonText}>{reason}</Text>
              </View>
            ))}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>At a glance</Text>
            <View style={styles.snapshotGrid}>
              {decisionSnapshot.map((item) => (
                <View key={item.label} style={styles.snapshotCard}>
                  <Text style={styles.snapshotLabel}>{item.label}</Text>
                  <Text style={styles.snapshotValue}>{item.value}</Text>
                </View>
              ))}
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Dietary fit</Text>
            <View style={styles.compatibilityCard}>
              <View style={styles.compatibilityHeader}>
                <ShieldCheck size={16} color={theme.colors.primary} strokeWidth={2} />
                <Text style={styles.compatibilityTitle}>Restriction check</Text>
              </View>
              <Text style={styles.compatibilityBody}>{compatibility}</Text>
              <View style={styles.nutritionRow}>
                <View style={styles.nutritionCell}>
                  <Text style={styles.nutritionLabel}>Calories</Text>
                  <Text style={styles.nutritionValue}>{dish.nutrition.calories} kcal</Text>
                </View>
                <View style={styles.nutritionCell}>
                  <Text style={styles.nutritionLabel}>Protein</Text>
                  <Text style={styles.nutritionValue}>{dish.nutrition.protein}</Text>
                </View>
                <View style={styles.nutritionCell}>
                  <Text style={styles.nutritionLabel}>Fat</Text>
                  <Text style={styles.nutritionValue}>{dish.nutrition.fat}</Text>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>More from here</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.relatedScroll}>
              {related.map(({ dish: alternative }) => (
                <Pressable key={alternative.id} style={({ pressed }) => [styles.relatedCard, pressed && styles.pressedCard]} onPress={() => navigation.replace('Detail', { itemId: alternative.id, title: alternative.name, image: alternative.image })}>
                  <View style={styles.relatedImage}>
                    <SkeletonImage src={alternative.image} alt={alternative.name} />
                  </View>
                  <Text style={styles.relatedTitle}>{alternative.name}</Text>
                  <Text style={styles.relatedMeta}>{alternative.restaurantName}</Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>

          <View style={styles.bottomPadding} />
        </View>
      </Animated.ScrollView>

      <SafeAreaView edges={['bottom']} style={styles.actionBar}>
        <View>
          <Text style={styles.actionLabel}>Today</Text>
          <Text style={styles.actionSummary} numberOfLines={1}>{dish.name}</Text>
        </View>
        <View style={styles.actionButtons}>
          <Pressable style={({ pressed }) => [styles.secondaryButton, pressed && styles.pressedChrome]} onPress={handleOpenMap}>
            <Text style={styles.secondaryButtonText}>Map</Text>
          </Pressable>
          <Pressable style={({ pressed }) => [styles.secondaryButton, liked && styles.secondaryButtonActive, pressed && styles.pressedChrome]} onPress={() => toggleFavorite(dish.id)}>
            <Text style={[styles.secondaryButtonText, liked && styles.secondaryButtonTextActive]}>{liked ? 'Saved' : 'Save'}</Text>
          </Pressable>
          <Pressable style={({ pressed }) => [styles.primaryButton, pressed && styles.pressedChrome]} onPress={handleChoose}>
            <Text style={styles.primaryButtonText}>Choose</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    pressedCard: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
    navBarOuter: { position: 'absolute', top: 0, left: 0, right: 0, zIndex: 100 },
    navBar: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: t.spacing.md, paddingBottom: t.spacing.xs },
    navCircle: { width: 36, height: 36, borderRadius: t.radius.full, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.92)' },
    navRight: { flexDirection: 'row', gap: t.spacing.xs },
    scrollView: { flex: 1 },
    heroWrap: { height: 380, overflow: 'hidden' },
    heroImage: {},
    heroOverlay: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 20, paddingBottom: 24, paddingTop: 64, backgroundColor: 'rgba(16, 12, 10, 0.36)' },
    content: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.md },
    topline: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: t.spacing.sm },
    categoryPill: { backgroundColor: 'rgba(255,255,255,0.16)', borderRadius: t.radius.full, paddingHorizontal: 12, paddingVertical: 5, maxWidth: '76%' },
    categoryPillText: { ...t.typography.caption, color: '#FFFFFF', fontWeight: '700' },
    ratingBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: 'rgba(255,255,255,0.16)', borderRadius: t.radius.full, paddingHorizontal: 8, paddingVertical: 5 },
    ratingText: { ...t.typography.caption, color: '#FFFFFF', fontWeight: '700' },
    dishTitle: { fontSize: 28, lineHeight: 36, fontWeight: '800', color: '#FFFFFF', marginBottom: 4 },
    heroSupportText: { ...t.typography.caption, color: 'rgba(255,255,255,0.88)', marginBottom: 10 },
    heroMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
    heroMetaText: { ...t.typography.caption, color: 'rgba(255,255,255,0.9)', fontWeight: '600' },
    heroMetaDot: { fontSize: 13, color: 'rgba(255,255,255,0.42)' },
    restaurantRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      marginBottom: t.spacing.md,
      backgroundColor: t.colors.surfaceMuted,
      borderRadius: t.surface.cardRadius,
      paddingHorizontal: t.surface.insetCardPadding,
      paddingVertical: t.spacing.sm,
    },
    restaurantCopy: { flex: 1, gap: 2 },
    restaurantText: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700', flex: 1 },
    restaurantSubtext: { ...t.typography.caption, color: t.colors.subtle },
    restaurantActionText: { ...t.typography.micro, color: t.colors.primaryDark, fontWeight: '700' },
    quickActionRow: { flexDirection: 'row', gap: t.spacing.sm, marginBottom: t.spacing.lg },
    quickActionCard: {
      flex: 1,
      minHeight: 74,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surfaceMuted,
      padding: t.surface.insetCardPadding,
      justifyContent: 'space-between',
    },
    quickActionLabel: { ...t.typography.micro, color: t.colors.subtle },
    quickActionValue: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    section: { marginBottom: t.spacing.lg },
    sectionTitle: { ...t.typography.h2, color: t.colors.foreground, marginBottom: t.spacing.sm },
    reasonRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, paddingVertical: 4 },
    reasonText: { ...t.typography.body, color: t.colors.foreground, flex: 1, lineHeight: 22 },
    snapshotGrid: { flexDirection: 'row', gap: t.spacing.xs },
    snapshotCard: { flex: 1, backgroundColor: t.colors.surfaceMuted, borderRadius: t.surface.cardRadius, padding: t.surface.insetCardPadding },
    snapshotLabel: { ...t.typography.caption, color: t.colors.subtle, marginBottom: 4 },
    snapshotValue: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    compatibilityCard: { backgroundColor: t.colors.primaryLight, borderRadius: t.surface.cardRadius, padding: t.surface.insetCardPadding, gap: t.spacing.sm },
    compatibilityHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
    compatibilityTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    compatibilityBody: { ...t.typography.body, color: t.colors.muted, lineHeight: 22 },
    nutritionRow: { flexDirection: 'row', gap: t.spacing.xs },
    nutritionCell: { flex: 1, backgroundColor: t.colors.surfaceElevated, borderRadius: t.radius.md, padding: t.spacing.sm },
    nutritionLabel: { ...t.typography.micro, color: t.colors.subtle, marginBottom: 2 },
    nutritionValue: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    relatedScroll: { paddingRight: t.spacing.md, gap: t.spacing.sm },
    relatedCard: { width: 170, backgroundColor: t.colors.surface, borderRadius: t.surface.cardRadius, padding: t.spacing.sm, ...t.shadows.sm },
    relatedImage: { height: 110, borderRadius: t.radius.sm, overflow: 'hidden', marginBottom: t.spacing.xs },
    relatedTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700', marginBottom: 2 },
    relatedMeta: { ...t.typography.caption, color: t.colors.subtle },
    bottomPadding: { height: 120 },
    actionBar: { position: 'absolute', bottom: 0, left: 0, right: 0, backgroundColor: t.colors.surface, borderTopWidth: 1, borderTopColor: t.colors.borderLight, paddingHorizontal: t.spacing.md, paddingTop: t.spacing.sm, paddingBottom: 8, gap: t.spacing.sm },
    actionLabel: { ...t.typography.micro, color: t.colors.subtle },
    actionSummary: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    actionButtons: { flexDirection: 'row', gap: t.spacing.xs },
    secondaryButton: { flex: 1, borderWidth: 1, borderColor: t.colors.border, borderRadius: t.radius.full, height: 46, alignItems: 'center', justifyContent: 'center', backgroundColor: t.colors.surface },
    secondaryButtonActive: { borderColor: t.colors.primary, backgroundColor: t.colors.primaryLight },
    secondaryButtonText: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    secondaryButtonTextActive: { color: t.colors.primaryDark },
    primaryButton: { flex: 1.4, backgroundColor: t.colors.primary, borderRadius: t.radius.full, height: 46, alignItems: 'center', justifyContent: 'center' },
    primaryButtonText: { ...t.typography.body, color: t.colors.surface, fontWeight: '700' },
  });
}
