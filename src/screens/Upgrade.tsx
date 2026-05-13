import React, { useEffect, useState } from 'react';
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ArrowRight, Check, Compass, ScanSearch, Shield, Users } from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import type { RootStackParamList } from '../navigation/types';
import { SWIPE_CARDS } from '../data/mockData';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { EventName, track } from '../monitoring';

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
  a11yLabel,
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
  a11yLabel: string;
}) {
  return (
    <Pressable
      style={({ pressed }) => [styles.planCard, selected && styles.planCardSelected, pressed && styles.pressedCard]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={a11yLabel}
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
  const { t } = useTranslation();
  const [selectedPlan, setSelectedPlan] = useState<'pro' | 'family'>('pro');

  // Fire paywall_viewed once per mount. Real paywall A/B tests will read
  // properties to slice by variant; we ship a simple baseline event for now.
  useEffect(() => {
    track(EventName.PaywallViewed, { source: 'upgrade_screen', initial_plan: 'pro' });
  }, []);

  const handleSelectPlan = (plan: 'pro' | 'family') => {
    setSelectedPlan(plan);
    track(EventName.PaywallPlanSelected, { plan });
  };

  const handleContinue = () => {
    track(EventName.CheckoutStarted, { plan: selectedPlan, source: 'upgrade_screen' });
    navigation.navigate('Checkout', { plan: selectedPlan });
  };

  const proFeatures = [
    t('upgrade.planProFeature1'),
    t('upgrade.planProFeature2'),
    t('upgrade.planProFeature3'),
  ];
  const familyFeatures = [
    t('upgrade.planFamilyFeature1'),
    t('upgrade.planFamilyFeature2'),
    t('upgrade.planFamilyFeature3'),
  ];

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.grabber} />
      <View style={styles.header}>
        <Pressable
          onPress={() => navigation.goBack()}
          style={({ pressed }) => [styles.backBtn, pressed && styles.pressedChrome]}
          accessibilityRole="button"
          accessibilityLabel={t('upgrade.backA11y')}
        >
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.headerTitle}>{t('upgrade.headerTitle')}</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>{t('upgrade.heroEyebrow')}</Text>
          <View style={styles.heroImage}>
            <SkeletonImage src={SWIPE_CARDS[3].image} alt={t('upgrade.heroImageAlt')} />
          </View>
          <Text style={styles.heroTitle}>{t('upgrade.heroTitle')}</Text>
          <View style={styles.heroPoints}>
            <View style={styles.heroPoint}>
              <Text style={styles.heroPointValue}>{t('upgrade.heroPoint1Value')}</Text>
              <Text style={styles.heroPointLabel}>{t('upgrade.heroPoint1Label')}</Text>
            </View>
            <View style={styles.heroPoint}>
              <Text style={styles.heroPointValue}>{t('upgrade.heroPoint2Value')}</Text>
              <Text style={styles.heroPointLabel}>{t('upgrade.heroPoint2Label')}</Text>
            </View>
            <View style={styles.heroPoint}>
              <Text style={styles.heroPointValue}>{t('upgrade.heroPoint3Value')}</Text>
              <Text style={styles.heroPointLabel}>{t('upgrade.heroPoint3Label')}</Text>
            </View>
          </View>
        </View>

        <View style={styles.freeBaseline}>
          <Text style={styles.freeBaselineLabel}>{t('upgrade.freeLabel')}</Text>
          <Text style={styles.freeBaselineText}>{t('upgrade.freeText')}</Text>
        </View>

        <View style={styles.benefitRow}>
          <View style={styles.benefitTile}>
            <Compass size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>{t('upgrade.benefitBetterPicks')}</Text>
          </View>
          <View style={styles.benefitTile}>
            <ScanSearch size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>{t('upgrade.benefitMenuHelp')}</Text>
          </View>
          <View style={styles.benefitTile}>
            <Shield size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>{t('upgrade.benefitFewerMisses')}</Text>
          </View>
          <View style={styles.benefitTile}>
            <Users size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitLabel}>{t('upgrade.benefitSharedPicks')}</Text>
          </View>
        </View>

        <View style={styles.planList}>
          <PlanCard
            icon={<Compass size={18} color={theme.colors.primary} strokeWidth={2} />}
            title={t('upgrade.planProTitle')}
            price={t('upgrade.planProPrice')}
            support={t('upgrade.planProSupport')}
            badge={t('upgrade.planProBadge')}
            selected={selectedPlan === 'pro'}
            features={proFeatures}
            preview={SWIPE_CARDS[0].image}
            onPress={() => handleSelectPlan('pro')}
            styles={styles}
            theme={theme}
            a11yLabel={t('upgrade.planLabelA11y', { title: t('upgrade.planProTitle'), price: t('upgrade.planProPrice') })}
          />
          <PlanCard
            icon={<Users size={18} color={theme.colors.primary} strokeWidth={2} />}
            title={t('upgrade.planFamilyTitle')}
            price={t('upgrade.planFamilyPrice')}
            support={t('upgrade.planFamilySupport')}
            selected={selectedPlan === 'family'}
            features={familyFeatures}
            preview={SWIPE_CARDS[4].image}
            onPress={() => handleSelectPlan('family')}
            styles={styles}
            theme={theme}
            a11yLabel={t('upgrade.planLabelA11y', { title: t('upgrade.planFamilyTitle'), price: t('upgrade.planFamilyPrice') })}
          />
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={({ pressed }) => [styles.upgradeButton, pressed && styles.pressedCard]} onPress={handleContinue}>
          <Text style={styles.upgradeButtonText}>
            {selectedPlan === 'family' ? t('upgrade.ctaFamily') : t('upgrade.ctaPro')}
          </Text>
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
    footer: { paddingHorizontal: t.spacing.md, paddingVertical: t.spacing.md, backgroundColor: t.colors.surface, borderTopWidth: 1, borderTopColor: t.colors.borderLight },
    upgradeButton: { backgroundColor: t.colors.primary, borderRadius: t.radius.full, height: 48, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6 },
    upgradeButtonText: { ...t.typography.body, color: t.colors.surface, fontWeight: '700' },
    pressedCard: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
  });
}
