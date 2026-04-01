import React from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated from 'react-native-reanimated';
import { ArrowLeft, ArrowRight, Zap, Shield, Check, Lock, CreditCard } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

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
  features: Array<{ text: string; iconType?: 'zap' | 'shield' | 'check' }>;
  highlighted?: boolean;
  badge?: string;
  onSelect: () => void;
}) {
  const getIcon = (type?: string) => {
    switch (type) {
      case 'zap': return <Zap size={14} color={theme.colors.primary} fill={theme.colors.primary} />;
      case 'shield': return <Shield size={14} color={theme.colors.accent} strokeWidth={2} />;
      default: return <Check size={14} color={theme.colors.success} strokeWidth={2.5} />;
    }
  };

  return (
    <Pressable
      style={({ pressed }) => [
        styles.planCard,
        highlighted && styles.planCardHighlighted,
        pressed && { opacity: 0.9 },
      ]}
      onPress={onSelect}
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
            {getIcon(f.iconType)}
            <Text style={[styles.featureText, highlighted && styles.featureTextHighlighted]}>{f.text}</Text>
          </View>
        ))}
      </View>
    </Pressable>
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
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}>
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Pressable onPress={handleStart}>
          <Text style={styles.skipText}>Skip</Text>
        </Pressable>
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
            <Lock size={18} color={theme.colors.muted} strokeWidth={1.8} />
            <Text style={styles.trustLabel}>SECURE PAYMENT</Text>
          </View>
          <View style={styles.trustBadge}>
            <CreditCard size={18} color={theme.colors.muted} strokeWidth={1.8} />
            <Text style={styles.trustLabel}>CANCEL ANYTIME</Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          style={({ pressed }) => [styles.upgradeButton, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]}
          onPress={handleStart}
        >
          <Text style={styles.upgradeButtonText}>Upgrade to Pro ¥9.9/mo</Text>
          <ArrowRight size={16} color={theme.colors.surface} strokeWidth={2.5} />
        </Pressable>
        <Pressable onPress={handleStart} style={({ pressed }) => [styles.skipButton, pressed && { opacity: 0.7 }]}>
          <Text style={styles.skipButtonText}>Skip for now</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.xs,
  },
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  skipText: { ...theme.typography.caption, color: theme.colors.subtle, fontWeight: '500' },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.lg,
    gap: theme.spacing.xs,
  },
  progressTrack: { flex: 1, height: 4, backgroundColor: theme.colors.border, borderRadius: 2, overflow: 'hidden' },
  progressBar: { height: '100%', backgroundColor: theme.colors.primary, borderRadius: 2 },
  stepLabel: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.primary },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.lg },
  title: { ...theme.typography.display, color: theme.colors.foreground, marginBottom: theme.spacing.xs },
  subtitle: { ...theme.typography.body, color: theme.colors.muted, marginBottom: theme.spacing.lg },
  plans: { gap: theme.spacing.sm, marginBottom: theme.spacing.lg },
  planCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    padding: theme.spacing.md,
    borderWidth: 1.5,
    borderColor: 'transparent',
    ...theme.shadows.sm,
  },
  planCardHighlighted: {
    backgroundColor: theme.colors.primaryLight,
    borderColor: theme.colors.primary,
  },
  badge: {
    position: 'absolute',
    top: 0,
    right: 0,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 4,
    borderTopRightRadius: theme.radius.md,
    borderBottomLeftRadius: theme.radius.sm,
  },
  badgeHighlighted: { backgroundColor: theme.colors.primary },
  badgeNormal: { backgroundColor: theme.colors.surface },
  badgeText: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.surface },
  planHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: theme.spacing.sm },
  planSubtitle: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.subtle, letterSpacing: 0.5, marginBottom: 2 },
  planTitle: { ...theme.typography.h1, color: theme.colors.foreground },
  planTitleHighlighted: { color: theme.colors.primary },
  priceBlock: { alignItems: 'flex-end' },
  price: { ...theme.typography.h1, color: theme.colors.foreground },
  priceHighlighted: { color: theme.colors.primary },
  priceSuffix: { ...theme.typography.caption, color: theme.colors.subtle, marginTop: 1 },
  featuresList: { gap: theme.spacing.xs },
  featureRow: { flexDirection: 'row', alignItems: 'center', gap: theme.spacing.xs },
  featureText: { ...theme.typography.caption, color: '#4B5563' },
  featureTextHighlighted: { color: theme.colors.foreground, fontWeight: '500' },
  trustBadges: { flexDirection: 'row', gap: theme.spacing.sm },
  trustBadge: {
    flex: 1,
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    padding: theme.spacing.sm,
    alignItems: 'center',
    gap: 4,
    ...theme.shadows.sm,
  },
  trustLabel: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.subtle, letterSpacing: 0.5 },
  footer: {
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.md,
    backgroundColor: theme.colors.surface,
    borderTopWidth: 1,
    borderTopColor: theme.colors.borderLight,
    gap: theme.spacing.xs,
  },
  upgradeButton: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.full,
    paddingVertical: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: theme.spacing.xs,
  },
  upgradeButtonText: { ...theme.typography.body, fontWeight: '700', color: theme.colors.surface },
  skipButton: { paddingVertical: theme.spacing.xs, alignItems: 'center' },
  skipButtonText: { ...theme.typography.caption, color: theme.colors.subtle, fontWeight: '500' },
});
