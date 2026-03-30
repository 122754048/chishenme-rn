import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, { useAnimatedStyle, useSharedValue, useAnimatedScrollHandler } from 'react-native-reanimated';
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
  // Issue #7: Receive navigation params for the item.
  const route = useRoute<DetailRouteProp>();
  const { title: itemTitle, image: itemImage } = route.params ?? { title: 'Salmon Energy Bowl', image: 'https://images.unsplash.com/photo-1611599537845-1c7aca0091c0?w=1080' };

  // Issue #8: Use Reanimated shared value for scroll position instead of useState
  // to avoid re-rendering the entire component on every scroll event.
  const scrollY = useSharedValue(0);

  const scrollHandler = useAnimatedScrollHandler({
    onScroll: (event) => {
      scrollY.value = event.contentOffset.y;
    },
  });

  // Animated nav bar opacity (becomes opaque after scrolling past hero)
  const navBarStyle = useAnimatedStyle(() => {
    const opacity = Math.min(1, Math.max(0, (scrollY.value - 100) / 80));
    return {
      backgroundColor: `rgba(245,245,245,${opacity})`,
    };
  });

  const navBtnStyle = useAnimatedStyle(() => {
    const navOpaque = scrollY.value > 150;
    return {
      backgroundColor: navOpaque ? 'rgba(0,0,0,0.06)' : 'rgba(0,0,0,0.25)',
    };
  });

  // Issue #8: Parallax effect uses Animated.View + useAnimatedStyle (UI thread).
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
      {/* Custom Nav Bar */}
      <SafeAreaView edges={['top']} style={styles.navBarOuter}>
        <Animated.View style={[styles.navBar, navBarStyle]}>
          <TouchableOpacity style={styles.navBackBtn} onPress={() => navigation.goBack()}>
            <Animated.View style={[styles.backCircle, navBtnStyle]}>
              <Text style={{ fontSize: 18 }}>←</Text>
            </Animated.View>
          </TouchableOpacity>
          <View style={styles.navRight}>
            <TouchableOpacity>
              <Animated.View style={[styles.navIconBtn, navBtnStyle]}>
                <Text style={{ fontSize: 14 }}>↗</Text>
              </Animated.View>
            </TouchableOpacity>
            <TouchableOpacity>
              <Animated.View style={[styles.navIconBtn, navBtnStyle]}>
                <Text style={{ fontSize: 14 }}>❤️</Text>
              </Animated.View>
            </TouchableOpacity>
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
            <SkeletonImage
              src={itemImage}
              alt={itemTitle}
            />
          </Animated.View>
          <View style={styles.heroGradient} />
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
              <Text style={styles.aiBadgeIcon}>⚡</Text>
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
              <TouchableOpacity>
                <Text style={styles.viewMore}>View More</Text>
              </TouchableOpacity>
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
                <View style={styles.mealPrepIconWrap}>
                  <Text style={styles.mealPrepIcon}>⏱️</Text>
                </View>
                <View>
                  <Text style={styles.mealPrepRowTitle}>Preparation Time</Text>
                  <Text style={styles.mealPrepRowBody}>Estimated 15-20 mins.</Text>
                </View>
              </View>
              <View style={styles.mealPrepRow}>
                <View style={[styles.mealPrepIconWrap, { backgroundColor: theme.colors.brandLight }]}>
                  <Text style={styles.mealPrepIcon}>🍽️</Text>
                </View>
                <View>
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
          <Text style={styles.estimatedLabel}>Estimated Total</Text>
          <Text style={styles.estimatedPrice}>¥ 68.00</Text>
        </View>
        <TouchableOpacity style={styles.addButton}>
          <Text style={styles.addButtonIcon}>+</Text>
          <Text style={styles.addButtonText}>Add to My Menu</Text>
        </TouchableOpacity>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.surface },
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
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  navBackBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  backCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  navRight: { flexDirection: 'row', gap: 8 },
  navIconBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  scrollView: { flex: 1 },
  heroWrap: { height: 360, overflow: 'hidden', position: 'relative' },
  heroImage: {},
  heroGradient: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    height: 120,
    backgroundColor: 'transparent',
  },
  content: { paddingHorizontal: 16, marginTop: -16 },
  titleCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 3,
    elevation: 2,
  },
  titleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 },
  dishTitle: { fontSize: 22, fontWeight: '700', color: theme.colors.foreground, lineHeight: 30, flex: 1 },
  calorieBadge: {
    backgroundColor: '#81C784',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 6,
    alignItems: 'center',
  },
  calorieNum: { fontSize: 16, fontWeight: '700', color: '#ffffff' },
  calorieUnit: { fontSize: 9, color: '#ffffff', fontWeight: '600' },
  aiBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 10 },
  aiBadgeIcon: { fontSize: 12 },
  aiBadgeText: { fontSize: 12, color: theme.colors.brand, fontWeight: '600' },
  aiDescription: { fontSize: 13, color: '#6b7280', lineHeight: 20 },
  section: { marginBottom: 20 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: theme.colors.foreground, marginBottom: 12 },
  viewMore: { fontSize: 12, color: theme.colors.brand, fontWeight: '500' },
  nutriGrid: { flexDirection: 'row', gap: 10 },
  nutriCard: {
    flex: 1,
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 16,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  nutriLabel: { fontSize: 11, color: '#9ca3af', marginBottom: 4 },
  nutriValue: { fontSize: 17, fontWeight: '700', color: theme.colors.foreground },
  pairingsScroll: { paddingRight: 16, gap: 12 },
  pairingCard: { width: 140 },
  pairingImageWrap: { height: 140, borderRadius: 14, overflow: 'hidden', marginBottom: 8, position: 'relative' },
  pairingBadge: {
    position: 'absolute',
    top: 8,
    right: 8,
    backgroundColor: 'rgba(255,255,255,0.9)',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
  },
  pairingBadgeText: { fontSize: 9, fontWeight: '700', color: theme.colors.foreground },
  pairingTitle: { fontSize: 13, fontWeight: '600', color: theme.colors.foreground, marginBottom: 2 },
  pairingPrice: { fontSize: 12, color: '#9ca3af' },
  mealPrepCard: {
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 16,
    gap: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  mealPrepRow: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  mealPrepIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: theme.colors.brandAccentLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mealPrepIcon: { fontSize: 16 },
  mealPrepRowTitle: { fontSize: 13, fontWeight: '700', color: theme.colors.foreground, marginBottom: 2 },
  mealPrepRowBody: { fontSize: 11, color: '#9ca3af', lineHeight: 16 },
  bottomPadding: { height: 100 },
  actionBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: '#ffffff',
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.05,
    shadowRadius: 4,
    elevation: 3,
  },
  estimatedLabel: { fontSize: 10, color: '#9ca3af', fontWeight: '700', letterSpacing: 0.5, textTransform: 'uppercase' },
  estimatedPrice: { fontSize: 20, fontWeight: '700', color: theme.colors.foreground, marginTop: 2 },
  addButton: {
    backgroundColor: theme.colors.brandAccent,
    borderRadius: 30,
    paddingHorizontal: 24,
    height: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  addButtonIcon: { fontSize: 18, color: '#ffffff', fontWeight: '600' },
  addButtonText: { fontSize: 14, fontWeight: '700', color: '#ffffff' },
});
