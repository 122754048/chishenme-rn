import React, { useState } from 'react';
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, ArrowRight, Check, Compass, ScanSearch, Shield, Users } from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import type { RootStackParamList } from '../navigation/types';
import { SWIPE_CARDS } from '../data/mockData';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

function PlanCard({
  icon,
  title,
  price,
  support,
  selected,
  features,
  onPress,
  badge,
  preview,
  styles,
  theme,
}: {
  icon: React.ReactNode;
  title: string;
  price: string;
  support: string;
  selected: boolean;
  features: string[];
  onPress: () => void;
  badge?: string;
  preview: string;
  styles: ReturnType<typeof makeStyles>;
  theme: AppTheme;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.planCard, selected && styles.planCardSelected, pressed && styles.pressedCard]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={`${title} ${price}`}
    >
      <View style={styles.planPreview}>
        <SkeletonImage src={preview} alt={title} />
      </View>
      {badge ? <Text style={styles.planBadge}>{badge}</Text> : null}
      <View style={styles.planHeader}>
        <View style={styles.planTitleWrap}>
          <View style={styles.planIcon}>{icon}</View>
          <View>
            <Text style={styles.planTitle}>{title}</Text>
            <Text style={styles.planSupport}>{support}</Text>
          </View>
        </View>
        <Text style={styles.planPrice}>{price}</Text>
      </View>
      <View style={styles.planFeatureList}>
        {features.map((feature) => (
          <View key={feature} style={styles.planFeatureRow}>
            <Check size={13} color={theme.colors.primary} strokeWidth={2.5} />
            <Text style={styles.planFeatureText}>{feature}</Text>
          </View>
        ))}
      </View>
    </Pressable>
  );
}

export function Upgrade() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const [selectedPlan, setSelectedPlan] = useState<'pro' | 'family'>('pro');

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.grabber} />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && styles.pressedChrome]} accessibilityRole="button" accessibilityLabel="Go back">
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.headerTitle}>Upgrade</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Upgrade your daily decision flow</Text>
          <View style={styles.heroImage}>
            <SkeletonImage src={SWIPE_CARDS[3].image} alt="Upgrade preview" />
          </View>
          <Text style={styles.heroTitle}>Spend less time second-guessing dinner.</Text>
          <View style={styles.heroPoints}>
            <View style={styles.heroPoint}>
              <Text style={styles.heroPointValue}>3x</Text>
              <Text style={styles.heroPointLabel}>faster saves</Text>
            </View>
            <View style={styles.heroPoint}>
              <Text style={styles.heroPointValue}>Full</Text>
              <Text style={styles.heroPointLabel}>menu help</Text>
            </View>
            <View style={styles.heroPoint}>
              <Text style={styles.heroPointValue}>Less</Text>
              <Text style={styles.heroPointLabel}>repeat noise</Text>
            </View>
          </View>
        </View>

        <View style={styles.freeBaseline}>
          <Text style={styles.freeBaselineLabel}>Free</Text>
          <Text style={styles.freeBaselineText}>Browse freely, then keep up to 3 good calls each day.</Text>
        </View>

        <View style={styles.benefitRow}>
          <View style={styles.benefitTile}>
            <Compass size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>Better picks</Text>
          </View>
          <View style={styles.benefitTile}>
            <ScanSearch size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>Menu help</Text>
          </View>
          <View style={styles.benefitTile}>
            <Shield size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>Fewer misses</Text>
          </View>
          <View style={styles.benefitTile}>
            <Users size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>Shared picks</Text>
          </View>
        </View>

        <View style={styles.planList}>
          <PlanCard
            icon={<Compass size={18} color={theme.colors.primary} strokeWidth={2} />}
            title="Pro"
            price="$9.99"
            support="Best for solo daily use"
            badge="Popular"
            selected={selectedPlan === 'pro'}
            features={['Sharper ranking for tonight', 'Full menu scan picks', 'Keep more good calls ready']}
            preview={SWIPE_CARDS[0].image}
            onPress={() => setSelectedPlan('pro')}
            styles={styles}
            theme={theme}
          />
          <PlanCard
            icon={<Users size={18} color={theme.colors.primary} strokeWidth={2} />}
            title="Family"
            price="$19.99"
            support="Best for shared decisions"
            selected={selectedPlan === 'family'}
            features={['Everything in Pro', 'Shared picks for two or more', 'Less friction when everyone votes differently']}
            preview={SWIPE_CARDS[4].image}
            onPress={() => setSelectedPlan('family')}
            styles={styles}
            theme={theme}
          />
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={({ pressed }) => [styles.upgradeButton, pressed && styles.pressedCard]} onPress={() => navigation.navigate('Checkout', { plan: selectedPlan })}>
          <Text style={styles.upgradeButtonText}>{selectedPlan === 'family' ? 'Continue with Family' : 'Continue with Pro'}</Text>
          <ArrowRight size={16} color={theme.colors.surface} strokeWidth={2.5} />
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    grabber: { alignSelf: 'center', width: 38, height: 5, borderRadius: 999, backgroundColor: t.colors.border, marginTop: 10, marginBottom: 8 },
    header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: t.spacing.md, height: t.topNavHeight, backgroundColor: t.colors.surface, borderBottomWidth: 1, borderBottomColor: t.colors.borderLight },
    backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
    headerTitle: { ...t.typography.h2, color: t.colors.foreground },
    scrollView: { flex: 1 },
    scrollContent: { padding: t.spacing.md, paddingBottom: 120, gap: t.spacing.md },
    heroCard: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.lg,
      gap: 10,
    },
    heroEyebrow: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    heroImage: { height: 150, borderRadius: t.radius.md, overflow: 'hidden', marginTop: 2 },
    heroTitle: { ...t.typography.h1, color: t.colors.foreground },
    heroPoints: { flexDirection: 'row', gap: t.spacing.xs },
    heroPoint: {
      flex: 1,
      minHeight: 64,
      borderRadius: t.radius.md,
      backgroundColor: t.colors.surfaceElevated,
      justifyContent: 'center',
      alignItems: 'center',
      gap: 2,
    },
    heroPointValue: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    heroPointLabel: { ...t.typography.micro, color: t.colors.subtle },
    freeBaseline: {
      backgroundColor: t.colors.surfaceMuted,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      gap: 4,
    },
    freeBaselineLabel: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '700' },
    freeBaselineText: { ...t.typography.body, color: t.colors.foreground },
    benefitRow: { flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.sm },
    benefitTile: {
      width: '48%',
      minHeight: 82,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surfaceElevated,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
    },
    benefitLabel: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    planList: { gap: t.spacing.sm },
    planCard: { backgroundColor: t.colors.surface, borderRadius: t.surface.cardRadius, padding: 16, gap: 12, ...t.shadows.sm },
    planCardSelected: { backgroundColor: t.colors.primaryLight },
    planPreview: { height: 112, borderRadius: t.radius.md, overflow: 'hidden' },
    planBadge: { ...t.typography.micro, color: t.colors.primaryDark, fontWeight: '700' },
    planHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
    planTitleWrap: { flexDirection: 'row', gap: 10, alignItems: 'center', flex: 1 },
    planIcon: {
      width: 36,
      height: 36,
      borderRadius: 18,
      backgroundColor: t.colors.surfaceElevated,
      alignItems: 'center',
      justifyContent: 'center',
    },
    planTitle: { ...t.typography.h2, color: t.colors.foreground },
    planSupport: { ...t.typography.micro, color: t.colors.subtle, marginTop: 2 },
    planPrice: { ...t.typography.h2, color: t.colors.foreground },
    planFeatureList: { gap: 8 },
    planFeatureRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
    planFeatureText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '600' },
    footer: { paddingHorizontal: t.spacing.md, paddingVertical: t.spacing.md, backgroundColor: 'rgba(255,253,252,0.98)', borderTopWidth: 1, borderTopColor: t.colors.borderLight },
    upgradeButton: { backgroundColor: t.colors.primary, borderRadius: t.radius.full, height: 48, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6 },
    upgradeButtonText: { ...t.typography.body, color: t.colors.surface, fontWeight: '700' },
    pressedCard: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
  });
}
