import React from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, { useAnimatedStyle, useSharedValue, useAnimatedScrollHandler } from 'react-native-reanimated';
import { ArrowLeft, Share2, Heart, Zap, Clock, UtensilsCrossed, Star, Plus } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
import { SkeletonImage } from '../components/SkeletonImage';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type DetailRouteProp = RouteProp<RootStackParamList, 'Detail'>;

const PAIRINGS = [
  {
    id: 1,
    title: 'Kale & Green Grape Juice',
    price: '¥28',
    badge: 'REFRESHING',
    image: 'https://images.unsplash.com/photo-1611497426695-412abe2f287b?w=400',
  },
  {
    id: 2,
    title: 'Japanese Miso Soup',
    price: '¥12',
    badge: 'WARMING',
    image: 'https://images.unsplash.com/photo-1763470260619-f971902b20db?w=400',
  },
];

export function Detail() {
  const navigation = useNavigation<NavProp>();
  const { width: screenWidth } = useWindowDimensions();
  const route = useRoute<DetailRouteProp>();
  const itemTitle = route.params?.title ?? 'Salmon Energy Bowl';
  const itemImage = route.params?.image ?? 'https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?w=1080';

  const scrollY = useSharedValue(0);

  const scrollHandler = useAnimatedScrollHandler({
    onScroll: (event) => {
      scrollY.value = event.contentOffset.y;
    },
  });

  const navBarStyle = useAnimatedStyle(() => {
    const opacity = Math.min(1, Math.max(0, (scrollY.value - 100) / 80));
    return {
      backgroundColor: `rgba(250,250,248,${opacity})`,
    };
  });

  const navBtnStyle = useAnimatedStyle(() => {
    const navOpaque = scrollY.value > 150;
    return {
      backgroundColor: navOpaque ? 'rgba(0,0,0,0.06)' : 'rgba(0,0,0,0.25)',
    };
  });

  const heroImageStyle = useAnimatedStyle(() => {
    return {
      transform: [
        { translateY: scrollY.value * 0.4 },
        { scale: 1 + scrollY.value * 0.0008 },
      ],
    };
  });

  return (
    <View style={styles.container}>
      {/* Overlay Nav Bar */}
      <SafeAreaView edges={['top']} style={styles.navBarOuter}>
        <Animated.View style={[styles.navBar, navBarStyle]}>
          <Pressable style={({ pressed }) => [pressed && { opacity: 0.7 }]} onPress={() => navigation.goBack()}>
            <Animated.View style={[styles.navCircle, navBtnStyle]}>
              <ArrowLeft size={18} color="#FFFFFF" strokeWidth={2} />
            </Animated.View>
          </Pressable>
          <View style={styles.navRight}>
            <Pressable style={({ pressed }) => [pressed && { opacity: 0.7 }]}>
              <Animated.View style={[styles.navCircle, navBtnStyle]}>
                <Share2 size={16} color="#FFFFFF" strokeWidth={2} />
              </Animated.View>
            </Pressable>
            <Pressable style={({ pressed }) => [pressed && { opacity: 0.7 }]}>
              <Animated.View style={[styles.navCircle, navBtnStyle]}>
                <Heart size={16} color="#FFFFFF" strokeWidth={2} />
              </Animated.View>
            </Pressable>
          </View>
        </Animated.View>
      </SafeAreaView>

      <Animated.ScrollView
        style={styles.scrollView}
        onScroll={scrollHandler}
        scrollEventThrottle={16}
        showsVerticalScrollIndicator={false}
      >
        {/* Hero Image with parallax */}
        <View style={styles.heroWrap}>
          <Animated.View style={[styles.heroImage, { width: screenWidth, height: 360 }, heroImageStyle]}>
            <SkeletonImage src={itemImage} alt={itemTitle} />
          </Animated.View>
        </View>

        {/* Content */}
        <View style={styles.content}>
          {/* Title Card */}
          <View style={styles.titleCard}>
            <View style={styles.titleRow}>
              <Text style={styles.dishTitle}>{itemTitle}</Text>
              <View style={styles.calorieBadge}>
                <Text style={styles.calorieNum}>485</Text>
                <Text style={styles.calorieUnit}>kcal</Text>
              </View>
            </View>
            <View style={styles.aiBadge}>
              <Zap size={12} color={theme.colors.primary} fill={theme.colors.primary} />
              <Text style={styles.aiBadgeText}>AI Nutrition Analysis</Text>
            </View>
            <Text style={styles.aiDescription}>
              ChiShenMe AI Recommendation: This meal is rich in high-quality protein and Omega-3. Its low-glycemic ingredients provide sustained energy for up to 4 hours, making it perfect for lunch to maintain productivity throughout the afternoon.
            </Text>
          </View>

          {/* Nutritional Facts */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Nutritional Facts</Text>
            <View style={styles.nutriGrid}>
              {[
                { label: 'Protein', value: '32g' },
                { label: 'Fat', value: '18g' },
                { label: 'Carbs', value: '45g' },
              ].map((n) => (
                <View key={n.label} style={styles.nutriCard}>
                  <Text style={styles.nutriLabel}>{n.label}</Text>
                  <Text style={styles.nutriValue}>{n.value}</Text>
                </View>
              ))}
            </View>
          </View>

          {/* Best Pairings */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Best Pairings</Text>
              <Pressable>
                <Text style={styles.viewMore}>View More</Text>
              </Pressable>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.pairingsScroll}>
              {PAIRINGS.map((p) => (
                <View key={p.id} style={styles.pairingCard}>
                  <View style={styles.pairingImageWrap}>
                    <SkeletonImage src={p.image} alt={p.title} />
                    <View style={styles.pairingBadge}>
                      <Text style={styles.pairingBadgeText}>{p.badge}</Text>
                    </View>
                  </View>
                  <Text style={styles.pairingTitle}>{p.title}</Text>
                  <Text style={styles.pairingPrice}>{p.price}</Text>
                </View>
              ))}
            </ScrollView>
          </View>

          {/* Meal Prep */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Meal Prep Details</Text>
            <View style={styles.mealPrepCard}>
              <View style={styles.mealPrepRow}>
                <View style={[styles.mealPrepIconWrap, { backgroundColor: theme.colors.warningLight }]}>
                  <Clock size={16} color={theme.colors.warning} strokeWidth={2} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.mealPrepRowTitle}>Preparation Time</Text>
                  <Text style={styles.mealPrepRowBody}>Estimated 15-20 mins.</Text>
                </View>
              </View>
              <View style={styles.mealPrepRow}>
                <View style={[styles.mealPrepIconWrap, { backgroundColor: theme.colors.primaryLight }]}>
                  <UtensilsCrossed size={16} color={theme.colors.primary} strokeWidth={2} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.mealPrepRowTitle}>Chef's Tip</Text>
                  <Text style={styles.mealPrepRowBody}>Raw salmon should be consumed within 30 minutes for best freshness.</Text>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.bottomPadding} />
        </View>
      </Animated.ScrollView>

      {/* Floating Action Bar */}
      <SafeAreaView edges={['bottom']} style={styles.actionBar}>
        <View>
          <Text style={styles.estimatedLabel}>ESTIMATED TOTAL</Text>
          <Text style={styles.estimatedPrice}>¥ 68.00</Text>
        </View>
        <Pressable style={({ pressed }) => [styles.addButton, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]}>
          <Plus size={18} color={theme.colors.surface} strokeWidth={2.5} />
          <Text style={styles.addButtonText}>Add to My Menu</Text>
        </Pressable>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  navBarOuter: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 100,
  },
  navBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    paddingBottom: theme.spacing.xs,
  },
  navCircle: {
    width: 36,
    height: 36,
    borderRadius: theme.radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  navRight: { flexDirection: 'row', gap: theme.spacing.xs },
  scrollView: { flex: 1 },
  heroWrap: { height: 360, overflow: 'hidden', position: 'relative' },
  heroImage: {},
  content: { paddingHorizontal: theme.spacing.md, marginTop: -theme.spacing.md },
  titleCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
    marginBottom: theme.spacing.md,
    ...theme.shadows.md,
  },
  titleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: theme.spacing.sm },
  dishTitle: { fontSize: 22, lineHeight: 30, fontWeight: '700', color: theme.colors.foreground, flex: 1 },
  calorieBadge: {
    backgroundColor: theme.colors.success,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 6,
    alignItems: 'center',
  },
  calorieNum: { ...theme.typography.h2, fontWeight: '700', color: theme.colors.surface },
  calorieUnit: { ...theme.typography.micro, color: theme.colors.surface },
  aiBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: theme.spacing.xs },
  aiBadgeText: { ...theme.typography.caption, color: theme.colors.primary, fontWeight: '600' },
  aiDescription: { ...theme.typography.body, color: theme.colors.muted, lineHeight: 20 },
  section: { marginBottom: theme.spacing.lg },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: theme.spacing.sm },
  sectionTitle: { ...theme.typography.h2, color: theme.colors.foreground, marginBottom: theme.spacing.sm },
  viewMore: { ...theme.typography.caption, color: theme.colors.primary, fontWeight: '500' },
  nutriGrid: { flexDirection: 'row', gap: theme.spacing.xs },
  nutriCard: {
    flex: 1,
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    padding: theme.spacing.md,
    alignItems: 'center',
    ...theme.shadows.sm,
  },
  nutriLabel: { ...theme.typography.caption, color: theme.colors.subtle, marginBottom: 4 },
  nutriValue: { fontSize: 17, lineHeight: 24, fontWeight: '700', color: theme.colors.foreground },
  pairingsScroll: { paddingRight: theme.spacing.md, gap: theme.spacing.sm },
  pairingCard: { width: 140 },
  pairingImageWrap: { height: 140, borderRadius: theme.radius.md, overflow: 'hidden', marginBottom: theme.spacing.xs, position: 'relative' },
  pairingBadge: {
    position: 'absolute',
    top: theme.spacing.xs,
    right: theme.spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.92)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: theme.radius.sm,
  },
  pairingBadgeText: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.foreground },
  pairingTitle: { ...theme.typography.body, fontWeight: '600', color: theme.colors.foreground, marginBottom: 2 },
  pairingPrice: { ...theme.typography.caption, color: theme.colors.subtle },
  mealPrepCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    padding: theme.spacing.md,
    gap: theme.spacing.md,
    ...theme.shadows.sm,
  },
  mealPrepRow: { flexDirection: 'row', gap: theme.spacing.sm, alignItems: 'flex-start' },
  mealPrepIconWrap: {
    width: 40,
    height: 40,
    borderRadius: theme.radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mealPrepRowTitle: { ...theme.typography.body, fontWeight: '700', color: theme.colors.foreground, marginBottom: 2 },
  mealPrepRowBody: { ...theme.typography.caption, color: theme.colors.subtle, lineHeight: 18 },
  bottomPadding: { height: 100 },
  actionBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: theme.colors.surface,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.lg,
    paddingTop: theme.spacing.sm,
    paddingBottom: 4,
    ...theme.shadows.lg,
  },
  estimatedLabel: { ...theme.typography.micro, color: theme.colors.subtle, letterSpacing: 0.5 },
  estimatedPrice: { ...theme.typography.h1, color: theme.colors.foreground, marginTop: 2 },
  addButton: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.full,
    paddingHorizontal: theme.spacing.lg,
    height: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    ...theme.shadows.md,
  },
  addButtonText: { ...theme.typography.body, fontWeight: '700', color: theme.colors.surface },
});
