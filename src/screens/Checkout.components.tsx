/**
 * Checkout.components.tsx
 * Subcomponents for the redesigned Checkout screen.
 *
 * Exports:
 *  - CheckoutHero          – 220pt full-width hero with LinearGradient overlay
 *  - PriceCompareCard      – individual pricing card (monthly / annual)
 *  - PricingComparison     – two-column price picker
 *  - BenefitList           – emotionally-driven benefit rows
 *  - TrustSignals          – testimonial + stats + guarantee badge
 *  - PendingOrderCard      – inline pending-order notice
 *  - FailedOrderCard       – inline failed-order notice
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
// Types
// ─────────────────────────────────────────────────────────────────

export type PricingPlan = 'monthly' | 'annual';

export interface PricingOption {
  id: PricingPlan;
  label: string;
  price: string;
  perDay: string;
  highlight: boolean;
  badgeLabel?: string;
  savingsLabel?: string;
}

export const PRICING_OPTIONS: PricingOption[] = [
  {
    id: 'monthly',
    label: 'Monthly',
    price: '$4.99',
    perDay: '$0.17 / day',
    highlight: false,
  },
  {
    id: 'annual',
    label: 'Annual',
    price: '$39.99',
    perDay: 'Only $0.11 / day',
    highlight: true,
    badgeLabel: 'BEST VALUE',
    savingsLabel: 'Save 33% vs monthly',
  },
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
  const isFamily = plan === 'family';

  const title = isFamily ? 'Better picks, together.' : 'Smarter every meal.';
  const tagline = isFamily
    ? 'Shared taste, fewer arguments.'
    : 'Less guessing, more good calls.';
  const badgeLabel = isFamily ? 'Family' : 'Pro';

  return (
    <View style={styles.heroZone}>
      {/* Food image – fills hero */}
      <View style={StyleSheet.absoluteFill}>
        <SkeletonImage src={heroImage} alt={badgeLabel} />
      </View>

      {/* Bottom gradient overlay */}
      <LinearGradient
        colors={['transparent', 'rgba(20,15,12,0.72)']}
        style={styles.heroGradient}
        pointerEvents="none"
      />

      {/* Plan badge – top-left */}
      <View style={styles.heroPlanBadge}>
        <Crown size={13} color="#FFFFFF" strokeWidth={2} />
        <Text style={styles.heroPlanBadgeText}>{badgeLabel}</Text>
      </View>

      {/* Text overlay – bottom */}
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
    heroGradient: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      height: 120,
    },
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
    heroPlanBadgeText: {
      fontSize: 13,
      fontWeight: '700',
      color: '#FFFFFF',
    },
    heroTextBlock: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      paddingHorizontal: 20,
      paddingBottom: 20,
    },
    heroTitle: {
      fontSize: 22,
      lineHeight: 28,
      fontWeight: '800',
      color: '#FFFFFF',
      marginBottom: 4,
    },
    heroTagline: {
      fontSize: 14,
      color: 'rgba(255,255,255,0.88)',
      fontWeight: '500',
    },
  });
}

// ─────────────────────────────────────────────────────────────────
// PriceCompareCard
// ─────────────────────────────────────────────────────────────────

interface PriceCompareCardProps {
  option: PricingOption;
  selected: boolean;
  onPress: () => void;
}

export function PriceCompareCard({
  option,
  selected,
  onPress,
}: PriceCompareCardProps) {
  const styles = useThemedStyles(makePricingStyles);

  return (
    <Pressable
      style={({ pressed }) => [
        styles.pricingCard,
        option.highlight && styles.pricingCardBestValue,
        selected && styles.pricingCardSelected,
        pressed && { opacity: 0.9 },
      ]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      accessibilityLabel={`${option.label} plan, ${option.price}`}
    >
      {/* Best Value badge – floats above the card */}
      {option.badgeLabel ? (
        <View style={styles.bestValueBadge}>
          <Text style={styles.bestValueText}>{option.badgeLabel}</Text>
        </View>
      ) : null}

      <Text
        style={[
          styles.pricingPeriod,
          option.highlight && styles.pricingPeriodHighlight,
        ]}
      >
        {option.label}
      </Text>

      <Text
        style={[
          styles.pricingAmount,
          option.highlight && styles.pricingAmountHighlight,
        ]}
      >
        {option.price}
      </Text>

      <Text
        style={[
          styles.pricingPerDay,
          option.highlight && styles.pricingPerDayHighlight,
        ]}
      >
        {option.perDay}
      </Text>

      {option.savingsLabel ? (
        <View style={styles.savingsRow}>
          <Text style={styles.savingsText}>{option.savingsLabel}</Text>
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
      // room for the floating badge
      marginTop: 12,
    },
    pricingCardBestValue: {
      backgroundColor: t.colors.primaryLight,
      borderColor: t.colors.primary,
    },
    pricingCardSelected: {
      borderColor: t.colors.primary,
    },
    bestValueBadge: {
      position: 'absolute',
      top: -13,
      alignSelf: 'center',
      backgroundColor: t.colors.primary,
      borderRadius: t.radius.full,
      paddingHorizontal: 12,
      paddingVertical: 4,
    },
    bestValueText: {
      fontSize: 11,
      fontWeight: '800',
      color: '#FFFFFF',
      letterSpacing: 0.5,
    },
    pricingPeriod: {
      fontSize: 13,
      fontWeight: '600',
      color: t.colors.subtle,
    },
    pricingPeriodHighlight: {
      color: t.colors.primaryDark,
    },
    pricingAmount: {
      fontSize: 26,
      lineHeight: 32,
      fontWeight: '800',
      color: t.colors.foreground,
    },
    pricingAmountHighlight: {
      color: t.colors.primary,
    },
    pricingPerDay: {
      fontSize: 12,
      color: t.colors.subtle,
    },
    pricingPerDayHighlight: {
      color: t.colors.primaryDark,
      fontWeight: '700',
    },
    savingsRow: {
      backgroundColor: 'rgba(201,103,60,0.12)',
      borderRadius: t.radius.full,
      paddingHorizontal: 10,
      paddingVertical: 4,
      marginTop: 4,
    },
    savingsText: {
      fontSize: 11,
      fontWeight: '700',
      color: t.colors.primaryDark,
    },
  });
}

// ─────────────────────────────────────────────────────────────────
// PricingComparison
// ─────────────────────────────────────────────────────────────────

interface PricingComparisonProps {
  selectedPlan: PricingPlan;
  onSelectPlan: (plan: PricingPlan) => void;
}

export function PricingComparison({
  selectedPlan,
  onSelectPlan,
}: PricingComparisonProps) {
  const styles = useThemedStyles(makeComparisonStyles);

  return (
    <View style={styles.pricingRow}>
      {PRICING_OPTIONS.map((option) => (
        <PriceCompareCard
          key={option.id}
          option={option}
          selected={selectedPlan === option.id}
          onPress={() => onSelectPlan(option.id)}
        />
      ))}
    </View>
  );
}

function makeComparisonStyles(t: AppTheme) {
  return StyleSheet.create({
    pricingRow: {
      flexDirection: 'row',
      gap: t.spacing.sm,
      marginBottom: t.spacing.md,
    },
  });
}

// ─────────────────────────────────────────────────────────────────
// BenefitList
// ─────────────────────────────────────────────────────────────────

interface BenefitItem {
  icon: React.ReactNode;
  title: string;
  body: string;
}

function buildProBenefits(primary: string): BenefitItem[] {
  return [
    {
      icon: <Sparkles size={16} color={primary} strokeWidth={2} />,
      title: 'Decide in under 30 seconds',
      body: 'Ranked picks based on your taste, location, and time of day.',
    },
    {
      icon: <ScanSearch size={16} color={primary} strokeWidth={2} />,
      title: 'Know what to order before you sit',
      body: 'Scan any menu. Get your best 3 options instantly.',
    },
    {
      icon: <CheckCircle2 size={16} color={primary} strokeWidth={2} />,
      title: 'No repeated disappointments',
      body: 'Smarter repeat-avoidance means every pick feels fresh.',
    },
  ];
}

function buildFamilyBenefits(primary: string): BenefitItem[] {
  return [
    {
      icon: <Sparkles size={16} color={primary} strokeWidth={2} />,
      title: 'One pick everyone actually likes',
      body: 'Shared taste profiles mean fewer arguments at the table.',
    },
    {
      icon: <ScanSearch size={16} color={primary} strokeWidth={2} />,
      title: 'Menu help for the whole group',
      body: 'Scan any menu and surface dishes your crew will love.',
    },
    {
      icon: <CheckCircle2 size={16} color={primary} strokeWidth={2} />,
      title: 'Keeps it fresh for everyone',
      body: 'Group repeat-avoidance so nobody hears "not that place again."',
    },
  ];
}

interface BenefitListProps {
  plan: 'pro' | 'family';
}

export function BenefitList({ plan }: BenefitListProps) {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeBenefitStyles);

  const benefits =
    plan === 'family'
      ? buildFamilyBenefits(theme.colors.primary)
      : buildProBenefits(theme.colors.primary);

  return (
    <View style={styles.benefitList}>
      <Text style={styles.benefitListTitle}>What changes today</Text>
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
    benefitListTitle: {
      fontSize: 16,
      fontWeight: '700',
      color: t.colors.foreground,
      marginBottom: 4,
    },
    benefitRow: {
      flexDirection: 'row',
      gap: 12,
      alignItems: 'flex-start',
    },
    benefitIcon: {
      width: 32,
      height: 32,
      borderRadius: 16,
      backgroundColor: 'rgba(255,255,255,0.72)',
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 2,
    },
    benefitCopy: {
      flex: 1,
      gap: 2,
    },
    benefitTitle: {
      fontSize: 15,
      fontWeight: '700',
      color: t.colors.foreground,
      lineHeight: 21,
    },
    benefitBody: {
      fontSize: 13,
      color: t.colors.primaryDark,
      lineHeight: 19,
    },
  });
}

// ─────────────────────────────────────────────────────────────────
// TrustSignals
// ─────────────────────────────────────────────────────────────────

export function TrustSignals() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeTrustStyles);

  return (
    <View style={styles.trustBlock}>
      {/* Testimonial card */}
      <View style={styles.testimonialCard}>
        <View style={styles.testimonialStars}>
          {[1, 2, 3, 4, 5].map((i) => (
            <Star key={i} size={12} color={theme.colors.star} fill={theme.colors.star} />
          ))}
          <Text style={styles.testimonialRatingText}>4.8 from 12K+ users</Text>
        </View>
        <Text style={styles.testimonialText}>
          {
            '"I used to spend 15 minutes deciding where to eat. Now it\'s under a minute. The menu scan is the feature I didn\'t know I needed."'
          }
        </Text>
        <Text style={styles.testimonialAuthor}>— Marcus T., Chicago</Text>
      </View>

      {/* Stats row */}
      <View style={styles.trustStats}>
        <View style={styles.trustStat}>
          <Text style={styles.trustStatValue}>50K+</Text>
          <Text style={styles.trustStatLabel}>decisions made</Text>
        </View>
        <View style={styles.trustStatDivider} />
        <View style={styles.trustStat}>
          <Text style={styles.trustStatValue}>4.8★</Text>
          <Text style={styles.trustStatLabel}>App Store</Text>
        </View>
        <View style={styles.trustStatDivider} />
        <View style={styles.trustStat}>
          <Text style={styles.trustStatValue}>Free</Text>
          <Text style={styles.trustStatLabel}>to cancel anytime</Text>
        </View>
      </View>

      {/* Guarantee badge */}
      <View style={styles.guaranteeRow}>
        <ShieldCheck size={16} color={theme.colors.success} strokeWidth={2} />
        <Text style={styles.guaranteeText}>
          7-day refund guarantee. No questions asked.
        </Text>
      </View>
    </View>
  );
}

function makeTrustStyles(t: AppTheme) {
  return StyleSheet.create({
    trustBlock: {
      gap: t.spacing.sm,
      marginBottom: t.spacing.md,
    },
    testimonialCard: {
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      gap: t.spacing.xs,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    testimonialStars: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 3,
    },
    testimonialRatingText: {
      fontSize: 12,
      fontWeight: '600',
      color: t.colors.subtle,
      marginLeft: 4,
    },
    testimonialText: {
      fontSize: 14,
      color: t.colors.foreground,
      lineHeight: 21,
      fontStyle: 'italic',
    },
    testimonialAuthor: {
      fontSize: 12,
      color: t.colors.subtle,
      fontWeight: '600',
    },
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
    trustStat: {
      alignItems: 'center',
      gap: 2,
    },
    trustStatValue: {
      fontSize: 18,
      fontWeight: '800',
      color: t.colors.foreground,
    },
    trustStatLabel: {
      fontSize: 11,
      color: t.colors.subtle,
      fontWeight: '600',
      textAlign: 'center',
    },
    trustStatDivider: {
      width: 1,
      height: 32,
      backgroundColor: t.colors.borderLight,
    },
    guaranteeRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      backgroundColor: t.colors.successLight,
      borderRadius: t.radius.md,
      paddingHorizontal: 14,
      paddingVertical: 10,
    },
    guaranteeText: {
      fontSize: 13,
      color: t.colors.success,
      fontWeight: '600',
      flex: 1,
    },
  });
}

// ─────────────────────────────────────────────────────────────────
// PendingOrderCard
// ─────────────────────────────────────────────────────────────────

interface PendingOrderCardProps {
  message: string;
  onRefresh: () => void;
  refreshing: boolean;
}

export function PendingOrderCard({
  message,
  onRefresh,
  refreshing,
}: PendingOrderCardProps) {
  const styles = useThemedStyles(makeNoticeStyles);

  return (
    <View style={[styles.noticeCard, styles.pendingCard]}>
      <Text style={styles.noticeTitlePending}>Payment pending</Text>
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
        accessibilityLabel="Refresh payment status"
      >
        {refreshing ? (
          <ActivityIndicator size="small" color="#FFFFFF" />
        ) : (
          <Text style={styles.noticeBtnText}>Refresh status</Text>
        )}
      </Pressable>
    </View>
  );
}

// ─────────────────────────────────────────────────────────────────
// FailedOrderCard
// ─────────────────────────────────────────────────────────────────

interface FailedOrderCardProps {
  message: string;
  onRetry: () => void;
}

export function FailedOrderCard({ message, onRetry }: FailedOrderCardProps) {
  const styles = useThemedStyles(makeNoticeStyles);

  return (
    <View style={[styles.noticeCard, styles.failedCard]}>
      <Text style={styles.noticeTitleFailed}>Something went wrong</Text>
      <Text style={styles.noticeBody}>{message}</Text>
      <Pressable
        style={({ pressed }) => [
          styles.noticeBtn,
          styles.noticeBtnFailed,
          pressed && { opacity: 0.85 },
        ]}
        onPress={onRetry}
        accessibilityRole="button"
        accessibilityLabel="Retry payment"
      >
        <Text style={styles.noticeBtnText}>Try again</Text>
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
    pendingCard: {
      backgroundColor: t.colors.warningLight,
      borderWidth: 1,
      borderColor: t.colors.warning,
    },
    failedCard: {
      backgroundColor: t.colors.errorLight,
      borderWidth: 1,
      borderColor: t.colors.error,
    },
    noticeTitlePending: {
      fontSize: 15,
      fontWeight: '700',
      color: t.colors.warning,
    },
    noticeTitleFailed: {
      fontSize: 15,
      fontWeight: '700',
      color: t.colors.error,
    },
    noticeBody: {
      fontSize: 13,
      color: t.colors.foreground,
      lineHeight: 19,
    },
    noticeBtn: {
      height: 40,
      borderRadius: t.radius.full,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 4,
    },
    noticeBtnPending: {
      backgroundColor: t.colors.warning,
    },
    noticeBtnFailed: {
      backgroundColor: t.colors.error,
    },
    noticeBtnText: {
      fontSize: 14,
      fontWeight: '700',
      color: '#FFFFFF',
    },
  });
}
