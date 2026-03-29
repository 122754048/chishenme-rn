import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, { useAnimatedStyle, withTiming } from 'react-native-reanimated';
import { theme } from '../theme';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<any>;

function PlanCard({
  title,
  subtitle,
  price,
  priceSuffix,
  features,
  highlighted,
  badge,
  onSelect,
}: {
  title: string;
  subtitle: string;
  price: string;
  priceSuffix?: string;
  features: Array<{ icon?: string; text: string; iconType?: 'zap' | 'shield' | 'check' }>;
  highlighted?: boolean;
  badge?: string;
  onSelect: () => void;
}) {
  return (
    <TouchableOpacity
      style={[styles.planCard, highlighted && styles.planCardHighlighted]}
      onPress={onSelect}
      activeOpacity={0.8}
    >
      {badge && (
        <View style={[styles.badge, highlighted ? styles.badgeHighlighted : styles.badgeNormal]}>
          <Text style={styles.badgeText}>{badge}</Text>
        </View>
      )}
      <View style={styles.planHeader}>
        <View>
          <Text style={styles.planSubtitle}>{subtitle}</Text>
          <Text style={[styles.planTitle, highlighted && styles.planTitleHighlighted]}>{title}</Text>
        </View>
        <View style={styles.priceBlock}>
          <Text style={[styles.price, highlighted && styles.priceHighlighted]}>{price}</Text>
          {priceSuffix && <Text style={styles.priceSuffix}>{priceSuffix}</Text>}
        </View>
      </View>
      <View style={styles.featuresList}>
        {features.map((f, i) => (
          <View key={i} style={styles.featureRow}>
            <Text style={styles.featureIcon}>
              {f.iconType === 'zap' ? '⚡' : f.iconType === 'shield' ? '🛡️' : '✓'}
            </Text>
            <Text style={[styles.featureText, highlighted && styles.featureTextHighlighted]}>{f.text}</Text>
          </View>
        ))}
      </View>
    </TouchableOpacity>
  );
}

export function Upgrade() {
  const navigation = useNavigation<NavProp>();
  const { completeOnboarding } = useApp();

  const handleStart = async () => {
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.skipText} onPress={handleStart}>Skip</Text>
      </View>

      <View style={styles.progressContainer}>
        <View style={styles.progressTrack}>
          <Animated.View style={[styles.progressBar, { width: '100%' }]} />
        </View>
        <Text style={styles.stepLabel}>3/3</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>
          Unlock Unlimited{'\n'}Exploration
        </Text>
        <Text style={styles.subtitle}>
          Unlock AI smart ordering, personalized recipes, and multi-device family sharing.
        </Text>

        <View style={styles.plans}>
          <PlanCard
            title="Free"
            subtitle="BASIC"
            price="¥0"
            priceSuffix="Free Forever"
            features={[
              { text: '3 AI order suggestions daily', iconType: 'check' },
              { text: 'Basic restaurant search', iconType: 'check' },
            ]}
            onSelect={() => {}}
          />
          <PlanCard
            title="Pro"
            subtitle="ADVANCED"
            price="¥9.9"
            priceSuffix="/mo"
            badge="MOST POPULAR"
            features={[
              { text: 'Unlimited AI deep order analysis', iconType: 'zap' },
              { text: 'Precise allergen & health filters', iconType: 'shield' },
              { text: 'Offline mode & Ad-free experience', iconType: 'check' },
            ]}
            highlighted
            onSelect={() => {}}
          />
          <PlanCard
            title="Family"
            subtitle="WIN-WIN"
            price="¥19.9"
            priceSuffix="/mo"
            features={[
              { text: 'Up to 6 family members shared', iconType: 'check' },
              { text: 'Auto-generated weekly family meal plans', iconType: 'check' },
            ]}
            onSelect={() => {}}
          />
        </View>

        <View style={styles.trustBadges}>
          <View style={styles.trustBadge}>
            <Text style={styles.trustIcon}>🔒</Text>
            <Text style={styles.trustLabel}>SECURE PAYMENT</Text>
          </View>
          <View style={styles.trustBadge}>
            <Text style={styles.trustIcon}>💳</Text>
            <Text style={styles.trustLabel}>CANCEL ANYTIME</Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <TouchableOpacity style={styles.upgradeButton} onPress={handleStart} activeOpacity={0.8}>
          <Text style={styles.upgradeButtonText}>Upgrade to Pro ¥9.9/mo</Text>
          <Text style={styles.arrowIcon}>→</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={handleStart} style={styles.skipButton}>
          <Text style={styles.skipButtonText}>Skip for now</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.surface },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  backIcon: { fontSize: 22, color: '#374151' },
  skipText: { fontSize: 13, color: '#9ca3af', fontWeight: '500' },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    marginBottom: 24,
    gap: 8,
  },
  progressTrack: { flex: 1, height: 4, backgroundColor: '#e5e7eb', borderRadius: 2, overflow: 'hidden' },
  progressBar: { height: '100%', backgroundColor: theme.colors.brand, borderRadius: 2 },
  stepLabel: { fontSize: 11, fontWeight: '700', color: theme.colors.brand },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: 16, paddingBottom: 24 },
  title: { fontSize: 26, fontWeight: '700', color: theme.colors.foreground, marginBottom: 8, lineHeight: 34 },
  subtitle: { fontSize: 14, color: '#6b7280', marginBottom: 24 },
  plans: { gap: 14, marginBottom: 20 },
  planCard: {
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1.5,
    borderColor: 'transparent',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  planCardHighlighted: {
    backgroundColor: theme.colors.brandLight,
    borderColor: theme.colors.brand,
  },
  badge: {
    position: 'absolute',
    top: 0,
    right: 0,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderTopRightRadius: 14,
    borderBottomLeftRadius: 8,
  },
  badgeHighlighted: { backgroundColor: theme.colors.brand },
  badgeNormal: { backgroundColor: '#ffffff' },
  badgeText: { fontSize: 10, fontWeight: '700', color: '#ffffff' },
  planHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 },
  planSubtitle: { fontSize: 10, fontWeight: '700', color: '#9ca3af', letterSpacing: 0.5, marginBottom: 2 },
  planTitle: { fontSize: 18, fontWeight: '700', color: theme.colors.foreground },
  planTitleHighlighted: { color: theme.colors.brand },
  priceBlock: { alignItems: 'flex-end' },
  price: { fontSize: 18, fontWeight: '700', color: theme.colors.foreground },
  priceHighlighted: { color: theme.colors.brand },
  priceSuffix: { fontSize: 11, color: '#9ca3af', marginTop: 1 },
  featuresList: { gap: 8 },
  featureRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  featureIcon: { fontSize: 13 },
  featureText: { fontSize: 12, color: '#4b5563' },
  featureTextHighlighted: { color: '#1f2937', fontWeight: '500' },
  trustBadges: { flexDirection: 'row', gap: 12 },
  trustBadge: {
    flex: 1,
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 12,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  trustIcon: { fontSize: 18, marginBottom: 4 },
  trustLabel: { fontSize: 8, fontWeight: '700', color: '#9ca3af', letterSpacing: 0.5 },
  footer: {
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
    gap: 8,
  },
  upgradeButton: {
    backgroundColor: theme.colors.brand,
    borderRadius: 30,
    paddingVertical: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  upgradeButtonText: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  arrowIcon: { color: '#ffffff', fontSize: 16, fontWeight: '700' },
  skipButton: { paddingVertical: 8, alignItems: 'center' },
  skipButtonText: { fontSize: 12, color: '#9ca3af', fontWeight: '500' },
});
