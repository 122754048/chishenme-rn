/**
 * Checkout.components.tsx
 * Subcomponents for the redesigned Checkout screen. All copy is now driven
 * by react-i18next via the `checkout.*` namespace; non-text props (icons,
 * highlight flag) stay as plain config.
 */

import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle2,
  Crown,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Star,
} from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

// ─────────────────────────────────────────────────────────────────
// Types & static option config
// ─────────────────────────────────────────────────────────────────

export type PricingPlan = 'monthly' | 'annual';

interface PricingOptionConfig {
  id: PricingPlan;
  highlight: boolean;
  hasBadge: boolean;
  hasSavings: boolean;
}

const PRICING_OPTION_CONFIG: PricingOptionConfig[] = [
  { id: 'monthly', highlight: false, hasBadge: false, hasSavings: false },
  { id: 'annual', highlight: true, hasBadge: true, hasSavings: true },
];

// ─────────────────────────────────────────────────────────────────
// CheckoutHero
// ─────────────────────────────────────────────────────────────────

interface CheckoutHeroProps {
  plan: 'pro' | 'family';
  heroImage: string;
}

export function CheckoutHero({ plan, heroImage }: CheckoutHeroProps) {
  const styles = useThemedStyles(makeHeroStyles);
  const { t } = useTranslation();
  const isFamily = plan === 'family';

  const title = isFamily ? t('checkout.heroTitleFamily') : t('checkout.heroTitlePro');
  const tagline = isFamily ? t('checkout.heroTaglineFamily') : t('checkout.heroTaglinePro');
  const badgeLabel = isFamily ? t('checkout.heroBadgeFamily') : t('checkout.heroBadgePro');

  return (
    <View style={styles.heroZone}>
      <View style={StyleSheet.absoluteFill}>
        <SkeletonImage src={heroImage} alt={badgeLabel} priority="high" />
      </View>

      <LinearGradient
        colors={['transparent', 'rgba(20,15,12,0.72)']}
        style={styles.heroGradient}
        pointerEvents="none"
      />

      <View style={styles.heroPlanBadge}>
        <Crown size={13} color="#FFFFFF" strokeWidth={2} />
        <Text style={styles.heroPlanBadgeText}>{badgeLabel}</Text>
      </View>

      <View style={styles.heroTextBlock} pointerEvents="none">
        <Text style={styles.heroTitle}>{title}</Text>
        <Text style={styles.heroTagline}>{tagline}</Text>
      </View>
    </View>
  );
}

function makeHeroStyles(t: AppTheme) {
  return StyleSheet.create({
    heroZone: {
      height: 220,
      borderRadius: t.surface.cardRadius,
      overflow: 'hidden',
      marginBottom: t.spacing.md,
    },
    heroGradient: { position: 'absolute', bottom: 0, left: 0, right: 0, height: 120 },
    heroPlanBadge: {
      position: 'absolute',
      top: 16,
      left: 16,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      backgroundColor: 'rgba(255,255,255,0.18)',
      borderRadius: t.radius.full,
      paddingHorizontal: 12,
      paddingVertical: 6,
    },
    heroPlanBadgeText: { fontSize: 13, fontWeight: '700', color: '#FFFFFF' },
    heroTextBlock: { position: 'absolute', bottom: 0, left: 0, right: 0, paddingHorizontal: 20, paddingBottom: 20 },
    heroTitle: { fontSize: 22, lineHeight: 28, fontWeight: '800', color: '#FFFFFF', marginBottom: 4 },
    heroTagline: { fontSize: 14, color: 'rgba(255,255,255,0.88)', fontWeight: '500' },
  });
}

// ─────────────────────────────────────────────────────────────────
// PriceCompareCard
// ─────────────────────────────────────────────────────────────────

interface PriceCompareCardProps {
  config: PricingOptionConfig;
  selected: boolean;
  onPress: () => void;
}

function PriceCompareCard({ config, selected, onPress }: PriceCompareCardProps) {
  const styles = useThemedStyles(makePricingStyles);
  const { t } = useTranslation();

  const label = t(config.id === 'annual' ? 'checkout.pricingAnnual' : 'checkout.pricingMonthly');
  const price = t(config.id === 'annual' ? 'checkout.pricingAnnualAmount' : 'checkout.pricingMonthlyAmount');
  const perDay = t(config.id === 'annual' ? 'checkout.pricingAnnualPerDay' : 'checkout.pricingMonthlyPerDay');

  return (
    <Pressable
      style={({ pressed }) => [
        styles.pricingCard,
        config.highlight && styles.pricingCardBestValue,
        selected && styles.pricingCardSelected,
        pressed && { opacity: 0.9 },
      ]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={t('checkout.pricingCardA11y', { label, price })}
    >
      {config.hasBadge ? (
        <View style={styles.bestValueBadge}>
          <Text style={styles.bestValueText}>{t('checkout.pricingBestValue')}</Text>
        </View>
      ) : null}

      <Text style={[styles.pricingPeriod, config.highlight && styles.pricingPeriodHighlight]}>{label}</Text>
      <Text style={[styles.pricingAmount, config.highlight && styles.pricingAmountHighlight]}>{price}</Text>
      <Text style={[styles.pricingPerDay, config.highlight && styles.pricingPerDayHighlight]}>{perDay}</Text>

      {config.hasSavings ? (
        <View style={styles.savingsRow}>
          <Text style={styles.savingsText}>{t('checkout.pricingSavings')}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

function makePricingStyles(t: AppTheme) {
  return StyleSheet.create({
    pricingCard: {
      flex: 1,
      borderRadius: t.surface.cardRadius,
      padding: 16,
      paddingTop: 20,
      backgroundColor: t.colors.surfaceElevated,
      borderWidth: 2,
      borderColor: t.colors.borderLight,
      alignItems: 'center',
      gap: 4,
      marginTop: 12,
    },
    pricingCardBestValue: { backgroundColor: t.colors.primaryLight, borderColor: t.colors.primary },
    pricingCardSelected: { borderColor: t.colors.primary },
    bestValueBadge: {
      position: 'absolute',
      top: -13,
      alignSelf: 'center',
      backgroundColor: t.colors.primary,
      borderRadius: t.radius.full,
      paddingHorizontal: 12,
      paddingVertical: 4,
    },
    bestValueText: { fontSize: 11, fontWeight: '800', color: '#FFFFFF', letterSpacing: 0.5 },
    pricingPeriod: { fontSize: 13, fontWeight: '600', color: t.colors.subtle },
    pricingPeriodHighlight: { color: t.colors.primaryDark },
    pricingAmount: { fontSize: 26, lineHeight: 32, fontWeight: '800', color: t.colors.foreground },
    pricingAmountHighlight: { color: t.colors.primary },
    pricingPerDay: { fontSize: 12, color: t.colors.subtle },
    pricingPerDayHighlight: { color: t.colors.primaryDark, fontWeight: '700' },
    savingsRow: {
      backgroundColor: 'rgba(201,103,60,0.12)',
      borderRadius: t.radius.full,
      paddingHorizontal: 10,
      paddingVertical: 4,
      marginTop: 4,
    },
    savingsText: { fontSize: 11, fontWeight: '700', color: t.colors.primaryDark },
  });
}

// ─────────────────────────────────────────────────────────────────
// PricingComparison
// ─────────────────────────────────────────────────────────────────

interface PricingComparisonProps {
  selectedPlan: PricingPlan;
  onSelectPlan: (plan: PricingPlan) => void;
}

export function PricingComparison({ selectedPlan, onSelectPlan }: PricingComparisonProps) {
  const styles = useThemedStyles(makeComparisonStyles);

  return (
    <View style={styles.pricingRow}>
      {PRICING_OPTION_CONFIG.map((config) => (
        <PriceCompareCard
          key={config.id}
          config={config}
          selected={selectedPlan === config.id}
          onPress={() => onSelectPlan(config.id)}
        />
      ))}
    </View>
  );
}

function makeComparisonStyles(t: AppTheme) {
  return StyleSheet.create({
    pricingRow: { flexDirection: 'row', gap: t.spacing.sm, marginBottom: t.spacing.md },
  });
}

// ─────────────────────────────────────────────────────────────────
// BenefitList
// ─────────────────────────────────────────────────────────────────

interface BenefitListProps {
  plan: 'pro' | 'family';
}

export function BenefitList({ plan }: BenefitListProps) {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeBenefitStyles);
  const { t } = useTranslation();

  const isFamily = plan === 'family';
  const prefix = isFamily ? 'checkout.benefitFamily' : 'checkout.benefitPro';
  const benefits: Array<{ icon: React.ReactNode; title: string; body: string }> = [
    {
      icon: <Sparkles size={16} color={theme.colors.primary} strokeWidth={2} />,
      title: t(`${prefix}Title1`),
      body: t(`${prefix}Body1`),
    },
    {
      icon: <ScanSearch size={16} color={theme.colors.primary} strokeWidth={2} />,
      title: t(`${prefix}Title2`),
      body: t(`${prefix}Body2`),
    },
    {
      icon: <CheckCircle2 size={16} color={theme.colors.primary} strokeWidth={2} />,
      title: t(`${prefix}Title3`),
      body: t(`${prefix}Body3`),
    },
  ];

  return (
    <View style={styles.benefitList}>
      <Text style={styles.benefitListTitle}>{t('checkout.benefitsTitle')}</Text>
      {benefits.map((item) => (
        <View key={item.title} style={styles.benefitRow}>
          <View style={styles.benefitIcon}>{item.icon}</View>
          <View style={styles.benefitCopy}>
            <Text style={styles.benefitTitle}>{item.title}</Text>
            <Text style={styles.benefitBody}>{item.body}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

function makeBenefitStyles(t: AppTheme) {
  return StyleSheet.create({
    benefitList: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      gap: t.spacing.sm,
      marginBottom: t.spacing.md,
    },
    benefitListTitle: { fontSize: 16, fontWeight: '700', color: t.colors.foreground, marginBottom: 4 },
    benefitRow: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
    benefitIcon: {
      width: 32,
      height: 32,
      borderRadius: 16,
      backgroundColor: 'rgba(255,255,255,0.72)',
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 2,
    },
    benefitCopy: { flex: 1, gap: 2 },
    benefitTitle: { fontSize: 15, fontWeight: '700', color: t.colors.foreground, lineHeight: 21 },
    benefitBody: { fontSize: 13, color: t.colors.primaryDark, lineHeight: 19 },
  });
}

// ─────────────────────────────────────────────────────────────────
// TrustSignals
// ─────────────────────────────────────────────────────────────────

export function TrustSignals() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeTrustStyles);
  const { t } = useTranslation();

  return (
    <View style={styles.trustBlock}>
      <View style={styles.testimonialCard}>
        <View style={styles.testimonialStars}>
          {[1, 2, 3, 4, 5].map((i) => (
            <Star key={i} size={12} color={theme.colors.star} fill={theme.colors.star} />
          ))}
          <Text style={styles.testimonialRatingText}>{t('checkout.trustRating')}</Text>
        </View>
        <Text style={styles.testimonialText}>{t('checkout.trustTestimonial')}</Text>
        <Text style={styles.testimonialAuthor}>{t('checkout.trustAuthor')}</Text>
      </View>

      <View style={styles.trustStats}>
        <View style={styles.trustStat}>
          <Text style={styles.trustStatValue}>{t('checkout.trustStat1Value')}</Text>
          <Text style={styles.trustStatLabel}>{t('checkout.trustStat1Label')}</Text>
        </View>
        <View style={styles.trustStatDivider} />
        <View style={styles.trustStat}>
          <Text style={styles.trustStatValue}>{t('checkout.trustStat2Value')}</Text>
          <Text style={styles.trustStatLabel}>{t('checkout.trustStat2Label')}</Text>
        </View>
        <View style={styles.trustStatDivider} />
        <View style={styles.trustStat}>
          <Text style={styles.trustStatValue}>{t('checkout.trustStat3Value')}</Text>
          <Text style={styles.trustStatLabel}>{t('checkout.trustStat3Label')}</Text>
        </View>
      </View>

      <View style={styles.guaranteeRow}>
        <ShieldCheck size={16} color={theme.colors.success} strokeWidth={2} />
        <Text style={styles.guaranteeText}>{t('checkout.trustGuarantee')}</Text>
      </View>
    </View>
  );
}

function makeTrustStyles(t: AppTheme) {
  return StyleSheet.create({
    trustBlock: { gap: t.spacing.sm, marginBottom: t.spacing.md },
    testimonialCard: {
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      gap: t.spacing.xs,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    testimonialStars: { flexDirection: 'row', alignItems: 'center', gap: 3 },
    testimonialRatingText: { fontSize: 12, fontWeight: '600', color: t.colors.subtle, marginLeft: 4 },
    testimonialText: { fontSize: 14, color: t.colors.foreground, lineHeight: 21, fontStyle: 'italic' },
    testimonialAuthor: { fontSize: 12, color: t.colors.subtle, fontWeight: '600' },
    trustStats: {
      flexDirection: 'row',
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.md,
      alignItems: 'center',
      justifyContent: 'space-around',
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    trustStat: { alignItems: 'center', gap: 2 },
    trustStatValue: { fontSize: 18, fontWeight: '800', color: t.colors.foreground },
    trustStatLabel: { fontSize: 11, color: t.colors.subtle, fontWeight: '600', textAlign: 'center' },
    trustStatDivider: { width: 1, height: 32, backgroundColor: t.colors.borderLight },
    guaranteeRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      backgroundColor: t.colors.successLight,
      borderRadius: t.radius.md,
      paddingHorizontal: 14,
      paddingVertical: 10,
    },
    guaranteeText: { fontSize: 13, color: t.colors.success, fontWeight: '600', flex: 1 },
  });
}

// ─────────────────────────────────────────────────────────────────
// PendingOrderCard / FailedOrderCard
// ─────────────────────────────────────────────────────────────────

interface PendingOrderCardProps {
  message: string;
  onRefresh: () => void;
  refreshing: boolean;
}

export function PendingOrderCard({ message, onRefresh, refreshing }: PendingOrderCardProps) {
  const styles = useThemedStyles(makeNoticeStyles);
  const { t } = useTranslation();

  return (
    <View style={[styles.noticeCard, styles.pendingCard]}>
      <Text style={styles.noticeTitlePending}>{t('checkout.pendingTitle')}</Text>
      <Text style={styles.noticeBody}>{message}</Text>
      <Pressable
        style={({ pressed }) => [
          styles.noticeBtn,
          styles.noticeBtnPending,
          pressed && { opacity: 0.85 },
          refreshing && { opacity: 0.5 },
        ]}
        onPress={onRefresh}
        disabled={refreshing}
        accessibilityRole="button"
        accessibilityLabel={t('checkout.pendingRefreshA11y')}
      >
        {refreshing ? (
          <ActivityIndicator size="small" color="#FFFFFF" />
        ) : (
          <Text style={styles.noticeBtnText}>{t('checkout.pendingRefresh')}</Text>
        )}
      </Pressable>
    </View>
  );
}

interface FailedOrderCardProps {
  message: string;
  onRetry: () => void;
}

export function FailedOrderCard({ message, onRetry }: FailedOrderCardProps) {
  const styles = useThemedStyles(makeNoticeStyles);
  const { t } = useTranslation();

  return (
    <View style={[styles.noticeCard, styles.failedCard]}>
      <Text style={styles.noticeTitleFailed}>{t('checkout.failedTitle')}</Text>
      <Text style={styles.noticeBody}>{message}</Text>
      <Pressable
        style={({ pressed }) => [styles.noticeBtn, styles.noticeBtnFailed, pressed && { opacity: 0.85 }]}
        onPress={onRetry}
        accessibilityRole="button"
        accessibilityLabel={t('checkout.failedRetryA11y')}
      >
        <Text style={styles.noticeBtnText}>{t('checkout.failedRetry')}</Text>
      </Pressable>
    </View>
  );
}

function makeNoticeStyles(t: AppTheme) {
  return StyleSheet.create({
    noticeCard: {
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      gap: t.spacing.xs,
      marginBottom: t.spacing.md,
    },
    pendingCard: { backgroundColor: t.colors.warningLight, borderWidth: 1, borderColor: t.colors.warning },
    failedCard: { backgroundColor: t.colors.errorLight, borderWidth: 1, borderColor: t.colors.error },
    noticeTitlePending: { fontSize: 15, fontWeight: '700', color: t.colors.warning },
    noticeTitleFailed: { fontSize: 15, fontWeight: '700', color: t.colors.error },
    noticeBody: { fontSize: 13, color: t.colors.foreground, lineHeight: 19 },
    noticeBtn: { height: 40, borderRadius: t.radius.full, alignItems: 'center', justifyContent: 'center', marginTop: 4 },
    noticeBtnPending: { backgroundColor: t.colors.warning },
    noticeBtnFailed: { backgroundColor: t.colors.error },
    noticeBtnText: { fontSize: 14, fontWeight: '700', color: '#FFFFFF' },
  });
}
