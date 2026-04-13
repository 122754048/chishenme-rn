import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Compass, MapPin, RefreshCw, Search, Sparkles, User, Users } from 'lucide-react-native';
import { SearchOverlay } from '../components/SearchOverlay';
import { brand, type HomeFilter } from '../config/brand';
import { useApp } from '../context/AppContext';
import { SkeletonImage } from '../components/SkeletonImage';
import { SWIPE_CARDS, type MealType } from '../data/mockData';
import type { MainTabParamList, RootStackParamList } from '../navigation/types';
import { fetchNearbyRestaurants } from '../services/places';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { buildManualAreaContext, formatDistanceMiles } from '../utils/location';
import { getRecommendedDishes, getTodaysTopPicks } from '../utils/recommendations';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type ExploreRouteProp = RouteProp<MainTabParamList, 'Explore'>;
type ExploreTabNavProp = BottomTabNavigationProp<MainTabParamList, 'Explore'>;

const FILTER_ICONS: Record<'All' | HomeFilter, typeof Sparkles> = {
  All: Sparkles,
  Quick: Compass,
  Comfort: Sparkles,
  Healthy: MapPin,
  Budget: Search,
  Treat: Users,
};

const SCENARIOS: Array<'All' | HomeFilter> = ['All', ...brand.homeFilters];

function getRestaurantPreview(restaurantName: string) {
  return (
    SWIPE_CARDS.find((item) => item.restaurantName.trim().toLowerCase() === restaurantName.trim().toLowerCase()) ?? null
  );
}

function inferMealTypeByHour(): MealType {
  const hour = new Date().getHours();
  if (hour < 10) return 'Breakfast';
  if (hour < 15) return 'Lunch';
  if (hour < 18) return 'Snack';
  if (hour < 22) return 'Dinner';
  return 'Late Night';
}

function IconToggle({
  icon,
  label,
  active,
  onPress,
  styles,
  theme,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onPress: () => void;
  styles: ReturnType<typeof makeStyles>;
  theme: AppTheme;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.iconToggle, active && styles.iconToggleActive, pressed && styles.pressedChrome]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      accessibilityLabel={label}
    >
      <View style={[styles.iconToggleGlyph, active && styles.iconToggleGlyphActive]}>{icon}</View>
      <Text style={[styles.iconToggleLabel, active && styles.iconToggleLabelActive]}>{label}</Text>
    </Pressable>
  );
}

export function Explore() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const route = useRoute<ExploreRouteProp>();
  const navigation = useNavigation<NavProp>();
  const tabNavigation = useNavigation<ExploreTabNavProp>();
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]>('All');
  const [showSearch, setShowSearch] = useState(false);
  const [nearbyRestaurants, setNearbyRestaurants] = useState<Awaited<ReturnType<typeof fetchNearbyRestaurants>>['restaurants']>([]);
  const [loadingNearby, setLoadingNearby] = useState(false);
  const initialQuery = route.params?.initialQuery ?? '';
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const {
    backendToken,
    decisionSettings,
    history,
    locationContext,
    saveAreaPreset,
    savedAreas,
    selectedCuisines,
    selectedRestrictions,
    setLocationSelection,
    updateDecisionSettings,
  } = useApp();

  useEffect(() => {
    const nextQuery = route.params?.initialQuery;
    if (typeof nextQuery === 'string') {
      setSearchQuery(nextQuery);
      tabNavigation.setParams({ initialQuery: undefined });
    }
  }, [route.params?.initialQuery, tabNavigation]);

  useEffect(() => {
    if (!backendToken) {
      setNearbyRestaurants([]);
      return;
    }

    const trimmedQuery = searchQuery.trim();
    const input =
      trimmedQuery.length > 0
        ? { query: trimmedQuery }
        : locationContext?.mode === 'live'
          ? { latitude: locationContext.latitude, longitude: locationContext.longitude, radiusMeters: 2500 }
          : locationContext?.mode === 'manual'
            ? { query: locationContext.query }
            : null;

    if (!input) {
      setNearbyRestaurants([]);
      return;
    }

    let active = true;
    setLoadingNearby(true);

    void fetchNearbyRestaurants(backendToken, input)
      .then((result) => {
        if (!active) return;
        setNearbyRestaurants(result.restaurants);
      })
      .catch((error) => {
        if (!active) return;
        console.warn('Failed to fetch nearby restaurants for Explore:', error);
        setNearbyRestaurants([]);
      })
      .finally(() => {
        if (active) setLoadingNearby(false);
      });

    return () => {
      active = false;
    };
  }, [backendToken, locationContext, searchQuery]);

  const recommendationInput = useMemo(
    () => ({
      selectedCuisines,
      selectedRestrictions,
      nearbyRestaurants,
      preferredMealType: inferMealTypeByHour(),
      activeFilter: scenario === 'All' ? null : scenario,
      history,
      keepItFresh: decisionSettings.keepItFresh,
      forTwo: decisionSettings.forTwo,
    }),
    [decisionSettings.forTwo, decisionSettings.keepItFresh, history, nearbyRestaurants, scenario, selectedCuisines, selectedRestrictions]
  );

  const recommendations = useMemo(() => getRecommendedDishes(recommendationInput), [recommendationInput]);
  const topPicks = useMemo(() => getTodaysTopPicks(recommendationInput), [recommendationInput]);
  const locationLabel = searchQuery.trim() || locationContext?.label || 'Current area';
  const featuredNearby = nearbyRestaurants[0] ?? null;
  const activeSignals = useMemo(() => {
    const signals: string[] = [];
    if (scenario !== 'All') signals.push(scenario);
    if (decisionSettings.keepItFresh) signals.push('Fresh');
    if (decisionSettings.forTwo) signals.push('For two');
    if (nearbyRestaurants.length > 0) signals.push(`${nearbyRestaurants.length} nearby`);
    return signals.slice(0, 4);
  }, [decisionSettings.forTwo, decisionSettings.keepItFresh, nearbyRestaurants.length, scenario]);

  const visibleCards = useMemo(() => {
    const keyword = searchQuery.trim().toLowerCase();
    return recommendations.filter(({ dish }) => {
      if (keyword.length === 0) return true;
      return [dish.name, dish.subtitle, dish.cuisineLabel, dish.restaurantName, ...dish.decisionTags, ...dish.healthTags]
        .join(' ')
        .toLowerCase()
        .includes(keyword);
    });
  }, [recommendations, searchQuery]);

  const useManualArea = async () => {
    const trimmed = searchQuery.trim();
    if (!trimmed) return;
    await setLocationSelection(buildManualAreaContext(trimmed));
    navigation.navigate('MainTabs', { screen: 'Home' });
  };

  const saveCurrentSearch = async (key: 'home' | 'work') => {
    const trimmed = searchQuery.trim();
    if (!trimmed) return;
    await saveAreaPreset(key, { label: key === 'home' ? 'Home' : 'Work', query: trimmed });
  };

  const openRestaurantPreview = (restaurantName: string) => {
    const preview = getRestaurantPreview(restaurantName);
    if (preview) {
      navigation.navigate('Detail', { itemId: preview.id, title: preview.name, image: preview.image });
      return;
    }
    setSearchQuery(restaurantName);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <View style={styles.topNavLead}>
          <Text style={styles.navTitle}>Explore</Text>
          {locationContext?.label ? (
            <View style={styles.inlineArea}>
              <MapPin size={12} color={theme.colors.primary} strokeWidth={2} />
              <Text style={styles.inlineAreaText} numberOfLines={1}>
                {locationContext.label}
              </Text>
            </View>
          ) : null}
        </View>
        <View style={styles.navActions}>
          <Pressable style={({ pressed }) => [styles.navBtn, pressed && styles.pressedChrome]} onPress={() => setShowSearch(true)} accessibilityRole="button" accessibilityLabel="Search">
            <Search size={18} color={theme.colors.foreground} strokeWidth={1.8} />
          </Pressable>
          <Pressable style={({ pressed }) => [styles.navBtn, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('MainTabs', { screen: 'Profile' })} accessibilityRole="button" accessibilityLabel="Open profile">
            <User size={18} color={theme.colors.foreground} strokeWidth={1.8} />
          </Pressable>
        </View>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.summaryCard}>
          <Text style={styles.summaryEyebrow}>Built around {locationLabel}</Text>
          <Text style={styles.summaryTitle}>Find a better answer faster.</Text>
          <View style={styles.summaryStats}>
            <View style={styles.summaryStat}>
              <Text style={styles.summaryStatValue}>{topPicks.length}</Text>
              <Text style={styles.summaryStatLabel}>Top picks</Text>
            </View>
            <View style={styles.summaryStat}>
              <Text style={styles.summaryStatValue}>{nearbyRestaurants.length}</Text>
              <Text style={styles.summaryStatLabel}>Nearby</Text>
            </View>
            <View style={styles.summaryStat}>
              <Text style={styles.summaryStatValue}>{visibleCards.length}</Text>
              <Text style={styles.summaryStatLabel}>Fits</Text>
            </View>
          </View>
          {activeSignals.length > 0 ? (
            <View style={styles.summarySignalRow}>
              {activeSignals.map((signal) => (
                <View key={signal} style={styles.summarySignal}>
                  <Text style={styles.summarySignalText}>{signal}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </View>

        <View style={styles.savedAreaRow}>
          <Pressable style={({ pressed }) => [styles.savedAreaChip, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('MainTabs', { screen: 'Home' })}>
            <Compass size={14} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.savedAreaText}>Deck</Text>
          </Pressable>
          <Pressable style={({ pressed }) => [styles.savedAreaChip, pressed && styles.pressedChrome]} onPress={() => savedAreas.home && setLocationSelection(buildManualAreaContext(savedAreas.home.query))}>
            <MapPin size={14} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.savedAreaText}>{savedAreas.home?.query ?? 'Home'}</Text>
          </Pressable>
          <Pressable style={({ pressed }) => [styles.savedAreaChip, pressed && styles.pressedChrome]} onPress={() => savedAreas.work && setLocationSelection(buildManualAreaContext(savedAreas.work.query))}>
            <MapPin size={14} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.savedAreaText}>{savedAreas.work?.query ?? 'Work'}</Text>
          </Pressable>
        </View>

        <View style={styles.toggleRow}>
          <IconToggle
            icon={<RefreshCw size={16} color={decisionSettings.keepItFresh ? '#FFFFFF' : theme.colors.muted} strokeWidth={2} />}
            label="Fresh"
            active={decisionSettings.keepItFresh}
            onPress={() => void updateDecisionSettings({ keepItFresh: !decisionSettings.keepItFresh })}
            styles={styles}
            theme={theme}
          />
          <IconToggle
            icon={<Users size={16} color={decisionSettings.forTwo ? '#FFFFFF' : theme.colors.muted} strokeWidth={2} />}
            label="For two"
            active={decisionSettings.forTwo}
            onPress={() => void updateDecisionSettings({ forTwo: !decisionSettings.forTwo })}
            styles={styles}
            theme={theme}
          />
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
          {SCENARIOS.map((item) => {
            const active = scenario === item;
            const Icon = FILTER_ICONS[item];
            return (
              <Pressable
                key={item}
                style={({ pressed }) => [styles.filterChip, active && styles.filterChipActive, pressed && styles.pressedChrome]}
                onPress={() => setScenario(item)}
                accessibilityRole="button"
                accessibilityLabel={`Filter ${item}`}
                accessibilityState={{ selected: active }}
              >
                <Icon size={14} color={active ? '#FFFFFF' : theme.colors.muted} strokeWidth={2} />
                <Text style={[styles.filterChipText, active && styles.filterChipTextActive]}>{item}</Text>
              </Pressable>
            );
          })}
        </ScrollView>

        {searchQuery.trim().length > 0 ? (
          <View style={styles.microRow}>
            <Pressable style={({ pressed }) => [styles.microAction, pressed && styles.pressedChrome]} onPress={useManualArea}>
              <MapPin size={14} color={theme.colors.primary} strokeWidth={2} />
              <Text style={styles.microActionText} numberOfLines={1}>
                {searchQuery.trim()}
              </Text>
            </Pressable>
            <Pressable style={({ pressed }) => [styles.microAction, pressed && styles.pressedChrome]} onPress={() => void saveCurrentSearch('home')}>
              <Text style={styles.microActionText}>Save Home</Text>
            </Pressable>
            <Pressable style={({ pressed }) => [styles.microAction, pressed && styles.pressedChrome]} onPress={() => void saveCurrentSearch('work')}>
              <Text style={styles.microActionText}>Save Work</Text>
            </Pressable>
          </View>
        ) : null}

        {topPicks.length > 0 ? (
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Top 3</Text>
              <Pressable style={({ pressed }) => [styles.sectionAction, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('MainTabs', { screen: 'Home' })}>
                <Text style={styles.sectionActionText}>Use deck</Text>
              </Pressable>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.topPicksRow}>
              {topPicks.map((item) => {
                const nearbyDistance = formatDistanceMiles(item.nearbyRestaurant?.distanceMeters ?? item.dish.distanceMeters) ?? item.dish.distance;
                return (
                  <Pressable
                    key={item.dish.id}
                    style={({ pressed }) => [styles.topPickCard, pressed && styles.pressedChrome]}
                    onPress={() => navigation.navigate('Detail', { itemId: item.dish.id, title: item.dish.name, image: item.dish.image })}
                  >
                    <View style={styles.topPickImageWrap}>
                      <SkeletonImage src={item.dish.image} alt={item.dish.name} />
                    </View>
                    <Text style={styles.topPickDish} numberOfLines={2}>
                      {item.dish.name}
                    </Text>
                    <Text style={styles.topPickRestaurant} numberOfLines={1}>
                      {item.dish.restaurantName}
                    </Text>
                  <View style={styles.topPickMetaRow}>
                      <StarDot />
                      <Text style={styles.topPickMeta} numberOfLines={1}>
                        {nearbyDistance}
                      </Text>
                    </View>
                    <Text style={styles.topPickReason} numberOfLines={2}>
                      {item.reasons[0] ?? item.dish.subtitle}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        ) : null}

        {featuredNearby ? (
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Spotlight nearby</Text>
            </View>
            <Pressable
              style={({ pressed }) => [styles.featuredNearbyCard, pressed && styles.pressedChrome]}
              onPress={() => openRestaurantPreview(featuredNearby.name)}
            >
              <View style={styles.featuredNearbyImage}>
                <SkeletonImage
                  src={
                    getRestaurantPreview(featuredNearby.name)?.restaurantImage ??
                    getRestaurantPreview(featuredNearby.name)?.image ??
                    ''
                  }
                  alt={featuredNearby.name}
                />
              </View>
              <View style={styles.featuredNearbyOverlay}>
                <View style={styles.featuredNearbyMetaRow}>
                  {featuredNearby.rating ? (
                    <View style={styles.featuredNearbyBadge}>
                      <Text style={styles.featuredNearbyBadgeText}>{featuredNearby.rating.toFixed(1)}</Text>
                    </View>
                  ) : null}
                  {featuredNearby.distanceMeters ? (
                    <View style={styles.featuredNearbyBadge}>
                      <Text style={styles.featuredNearbyBadgeText}>{formatDistanceMiles(featuredNearby.distanceMeters)}</Text>
                    </View>
                  ) : null}
                </View>
                <Text style={styles.featuredNearbyTitle}>{featuredNearby.name}</Text>
                <Text style={styles.featuredNearbyBody} numberOfLines={2}>
                  {featuredNearby.editorialSummary ?? featuredNearby.address}
                </Text>
              </View>
            </Pressable>
          </View>
        ) : null}

        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Nearby</Text>
          </View>
          {nearbyRestaurants.length === 0 ? (
            <View style={styles.emptyBlock}>
              <MapPin size={16} color={theme.colors.subtle} strokeWidth={2} />
            </View>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.visualCardRow}>
              {nearbyRestaurants.slice(featuredNearby ? 1 : 0, 5).map((restaurant) => (
                <Pressable
                  key={restaurant.id}
                  style={({ pressed }) => [styles.restaurantVisualCard, pressed && styles.pressedChrome]}
                  onPress={() => openRestaurantPreview(restaurant.name)}
                >
                  <View style={styles.restaurantVisualImage}>
                    <SkeletonImage
                      src={getRestaurantPreview(restaurant.name)?.restaurantImage ?? getRestaurantPreview(restaurant.name)?.image ?? ''}
                      alt={restaurant.name}
                    />
                  </View>
                  <View style={styles.restaurantVisualOverlay}>
                    <View style={styles.visualMetaRow}>
                      {restaurant.rating ? (
                        <View style={styles.visualMetaBadge}>
                          <Text style={styles.visualMetaBadgeText}>{restaurant.rating.toFixed(1)}</Text>
                        </View>
                      ) : null}
                      {restaurant.distanceMeters ? (
                        <View style={styles.visualMetaBadge}>
                          <Text style={styles.visualMetaBadgeText}>{formatDistanceMiles(restaurant.distanceMeters)}</Text>
                        </View>
                      ) : null}
                    </View>
                    <Text style={styles.restaurantVisualTitle} numberOfLines={1}>
                      {restaurant.name}
                    </Text>
                    <Text style={styles.restaurantVisualBody} numberOfLines={2}>
                      {restaurant.openNow === false ? 'Closed right now' : restaurant.editorialSummary ?? restaurant.address}
                    </Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          )}
        </View>

        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Fits</Text>
          </View>
          {visibleCards.length === 0 ? (
            <View style={styles.emptyBlock}>
              <Sparkles size={16} color={theme.colors.subtle} strokeWidth={2} />
            </View>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.visualCardRow}>
              {visibleCards.slice(0, 8).map(({ dish, reasons, nearbyRestaurant }) => (
                <Pressable
                  key={dish.id}
                  style={({ pressed }) => [styles.fitVisualCard, pressed && styles.pressedChrome]}
                  onPress={() => navigation.navigate('Detail', { itemId: dish.id, title: dish.name, image: dish.image })}
                >
                  <View style={styles.fitVisualImage}>
                    <SkeletonImage src={dish.image} alt={dish.name} />
                  </View>
                  <View style={styles.fitVisualOverlay}>
                    <View style={styles.visualMetaRow}>
                      <View style={styles.visualMetaBadge}>
                        <Text style={styles.visualMetaBadgeText}>{nearbyRestaurant?.rating?.toFixed(1) ?? dish.restaurantRating.toFixed(1)}</Text>
                      </View>
                    </View>
                    <Text style={styles.fitVisualTitle} numberOfLines={2}>
                      {dish.name}
                    </Text>
                    <Text style={styles.fitVisualBody} numberOfLines={1}>
                      {dish.restaurantName}
                    </Text>
                    <Text style={styles.fitVisualReason} numberOfLines={2}>
                      {reasons[0] ?? dish.subtitle}
                    </Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          )}
        </View>
      </ScrollView>

      <SearchOverlay
        visible={showSearch}
        onClose={() => setShowSearch(false)}
        onSearch={(query) => {
          setSearchQuery(query);
          setShowSearch(false);
        }}
      />
    </SafeAreaView>
  );
}

function StarDot() {
  return <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: '#F5B74F' }} />;
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.surface },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    topNav: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      height: t.topNavHeight,
      backgroundColor: t.colors.surface,
    },
    topNavLead: { flex: 1 },
    navTitle: { ...t.typography.h1, color: t.colors.foreground },
    inlineArea: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 },
    inlineAreaText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600' },
    navActions: { flexDirection: 'row', gap: 4 },
    navBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: t.radius.md },
    scrollView: { flex: 1, backgroundColor: t.colors.background },
    scrollContent: { paddingBottom: 112 },
    summaryCard: {
      marginHorizontal: t.spacing.md,
      marginTop: t.spacing.sm,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.primaryLight,
      padding: t.spacing.md,
      gap: t.spacing.md,
    },
    summaryEyebrow: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    summaryTitle: { ...t.typography.h1, color: t.colors.foreground },
    summaryStats: { flexDirection: 'row', gap: t.spacing.xs },
    summaryStat: {
      flex: 1,
      minHeight: 64,
      borderRadius: t.radius.md,
      backgroundColor: t.colors.surfaceElevated,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 2,
    },
    summaryStatValue: { ...t.typography.h1, color: t.colors.foreground },
    summaryStatLabel: { ...t.typography.micro, color: t.colors.subtle },
    summarySignalRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
    summarySignal: {
      minHeight: 28,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.surfaceElevated,
      paddingHorizontal: 10,
      justifyContent: 'center',
    },
    summarySignalText: { ...t.typography.micro, color: t.colors.primaryDark, fontWeight: '700' },
    savedAreaRow: { flexDirection: 'row', gap: 8, paddingHorizontal: t.spacing.md, paddingTop: t.spacing.sm },
    savedAreaChip: {
      minHeight: 38,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.surfaceElevated,
      paddingHorizontal: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    savedAreaText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    toggleRow: { flexDirection: 'row', gap: 10, paddingHorizontal: t.spacing.md, paddingTop: t.spacing.md },
    iconToggle: {
      flex: 1,
      minHeight: 52,
      borderRadius: 26,
      backgroundColor: t.colors.surfaceElevated,
      paddingHorizontal: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    iconToggleActive: { backgroundColor: t.colors.primary, borderColor: t.colors.primary },
    iconToggleGlyph: { width: 28, height: 28, borderRadius: 14, backgroundColor: t.colors.background, alignItems: 'center', justifyContent: 'center' },
    iconToggleGlyphActive: { backgroundColor: 'rgba(255,255,255,0.16)' },
    iconToggleLabel: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    iconToggleLabelActive: { color: '#FFFFFF' },
    filterRow: { gap: 8, paddingHorizontal: t.spacing.md, paddingTop: t.spacing.md },
    filterChip: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      minHeight: 36,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.surfaceElevated,
      paddingHorizontal: 14,
      justifyContent: 'center',
    },
    filterChipActive: { backgroundColor: t.colors.primary, borderColor: t.colors.primary },
    filterChipText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    filterChipTextActive: { color: '#FFFFFF' },
    microRow: { flexDirection: 'row', gap: 8, paddingHorizontal: t.spacing.md, paddingTop: t.spacing.md },
    microAction: {
      minHeight: 36,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.surfaceElevated,
      paddingHorizontal: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      justifyContent: 'center',
    },
    microActionText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    section: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.lg },
    sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
    sectionTitle: { ...t.typography.h2, color: t.colors.foreground },
    sectionAction: {
      minHeight: 30,
      borderRadius: t.radius.full,
      paddingHorizontal: 10,
      justifyContent: 'center',
      backgroundColor: t.colors.surfaceElevated,
    },
    sectionActionText: { ...t.typography.micro, color: t.colors.foreground, fontWeight: '700' },
    topPicksRow: { gap: 10, paddingRight: t.spacing.md },
    topPickCard: {
      width: 168,
      minHeight: 214,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surface,
      padding: 14,
      ...t.shadows.sm,
    },
    topPickImageWrap: { height: 104, borderRadius: t.radius.md, overflow: 'hidden', marginBottom: 10 },
    topPickDish: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    topPickRestaurant: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600' },
    topPickMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
    topPickMeta: { ...t.typography.caption, color: t.colors.subtle },
    topPickReason: { ...t.typography.caption, color: t.colors.foreground, marginTop: 8, lineHeight: 18 },
    featuredNearbyCard: {
      height: 210,
      borderRadius: t.surface.cardRadius,
      overflow: 'hidden',
      backgroundColor: t.colors.surface,
      ...t.shadows.md,
    },
    featuredNearbyImage: {
      ...StyleSheet.absoluteFillObject,
    },
    featuredNearbyOverlay: {
      flex: 1,
      justifyContent: 'flex-end',
      padding: t.spacing.md,
      backgroundColor: 'rgba(20, 15, 12, 0.24)',
    },
    featuredNearbyMetaRow: { flexDirection: 'row', gap: 8, marginBottom: 10 },
    featuredNearbyBadge: {
      minHeight: 28,
      borderRadius: t.radius.full,
      backgroundColor: 'rgba(255,255,255,0.9)',
      paddingHorizontal: 10,
      justifyContent: 'center',
    },
    featuredNearbyBadgeText: { ...t.typography.micro, color: t.colors.foreground, fontWeight: '700' },
    featuredNearbyTitle: { ...t.typography.h1, color: '#FFFFFF', marginBottom: 4 },
    featuredNearbyBody: { ...t.typography.caption, color: 'rgba(255,255,255,0.9)' },
    emptyBlock: {
      minHeight: 82,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surfaceElevated,
      justifyContent: 'center',
      alignItems: 'center',
    },
    visualCardRow: { gap: 10, paddingRight: t.spacing.md },
    restaurantVisualCard: {
      width: 220,
      height: 192,
      borderRadius: t.surface.cardRadius,
      overflow: 'hidden',
      backgroundColor: t.colors.surface,
      ...t.shadows.md,
    },
    restaurantVisualImage: { ...StyleSheet.absoluteFillObject },
    restaurantVisualOverlay: {
      flex: 1,
      justifyContent: 'flex-end',
      padding: t.spacing.md,
      backgroundColor: 'rgba(20, 15, 12, 0.26)',
    },
    visualMetaRow: { flexDirection: 'row', gap: 8, marginBottom: 10 },
    visualMetaBadge: {
      minHeight: 28,
      borderRadius: t.radius.full,
      backgroundColor: 'rgba(255,255,255,0.9)',
      paddingHorizontal: 10,
      justifyContent: 'center',
    },
    visualMetaBadgeText: { ...t.typography.micro, color: t.colors.foreground, fontWeight: '700' },
    restaurantVisualTitle: { ...t.typography.h2, color: '#FFFFFF', marginBottom: 4 },
    restaurantVisualBody: { ...t.typography.caption, color: 'rgba(255,255,255,0.9)' },
    fitVisualCard: {
      width: 210,
      height: 236,
      borderRadius: t.surface.cardRadius,
      overflow: 'hidden',
      backgroundColor: t.colors.surface,
      ...t.shadows.md,
    },
    fitVisualImage: { ...StyleSheet.absoluteFillObject },
    fitVisualOverlay: {
      flex: 1,
      justifyContent: 'flex-end',
      padding: t.spacing.md,
      backgroundColor: 'rgba(20, 15, 12, 0.3)',
    },
    fitVisualTitle: { ...t.typography.h2, color: '#FFFFFF', marginBottom: 2 },
    fitVisualBody: { ...t.typography.caption, color: 'rgba(255,255,255,0.88)', marginBottom: 6 },
    fitVisualReason: { ...t.typography.micro, color: 'rgba(255,255,255,0.88)' },
  });
}
