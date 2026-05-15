/**
 * Checkout.tsx (i18n)
 *
 * All user-facing copy now flows through react-i18next via the `checkout.*`
 * namespace. This file owns flow control + payment side effects only; copy
 * decisions live in src/i18n/locales/*.json.
 */

import React from 'react';
import {
  ActivityIndicator,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  useNavigation,
  useRoute,
  type RouteProp,
} from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  CheckCircle2,
  ScanSearch,
  Sparkles,
} from 'lucide-react-native';
import { backendApi } from '../api/backend';
import { useApp } from '../context/AppContext';
import { SWIPE_CARDS } from '../data/mockData';
import type { RootStackParamList } from '../navigation/types';
import { subscriptionService } from '../services/subscriptions';
import { storage } from '../storage';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { EventName, track } from '../monitoring';
import {
  BenefitList,
  CheckoutHero,
  FailedOrderCard,
  PendingOrderCard,
  PricingComparison,
  TrustSignals,
  type PricingPlan,
} from './Checkout.components';

const ENABLE_MOCK_PAYMENTS =
  process.env.EXPO_PUBLIC_ENABLE_MOCK_PAYMENTS === 'true';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type CheckoutRouteProp = RouteProp<RootStackParamList, 'Checkout'>;

type ProcessingState = 'idle' | 'pay' | 'trial' | 'pending' | 'failed';

export function Checkout() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const route = useRoute<CheckoutRouteProp>();
  const { t } = useTranslation();
  const { completeOnboarding, setMembershipPlan } = useApp();

  const [processing, setProcessing] = React.useState<ProcessingState>('idle');
  const [paymentNotice, setPaymentNotice] = React.useState<string | null>(null);
  const [lastOrderNo, setLastOrderNo] = React.useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = React.useState<PricingPlan>('annual');

  const eventSeq = React.useRef(0);

  const membershipPlan = route.params?.plan ?? 'pro';
  const heroImage =
    membershipPlan === 'family' ? SWIPE_CARDS[4].image : SWIPE_CARDS[0].image;
  const isBusy = processing === 'pay' || processing === 'trial';

  const ctaLabel = (plan: PricingPlan) =>
    t(plan === 'annual' ? 'checkout.ctaAnnual' : 'checkout.ctaMonthly');
  const ctaSubtext = (plan: PricingPlan) =>
    t(plan === 'annual' ? 'checkout.ctaAnnualSubtext' : 'checkout.ctaMonthlySubtext');
  const switchPlanLabel = (plan: PricingPlan) =>
    t(plan === 'annual' ? 'checkout.switchToMonthly' : 'checkout.switchToAnnual');

  const getSubscriptionUserId = async () => {
    const userId = await storage.ensureBackendUserId();
    if (backendApi.isEnabled()) {
      const token = await backendApi.ensureToken();
      if (!token) throw new Error('backend auth token not available');
    }
    return userId;
  };

  const recordEvent = async (
    flow: 'pay' | 'trial',
    status: 'processing' | 'success' | 'failed',
    reason?: string
  ) => {
    eventSeq.current += 1;
    await storage.appendPaymentEvent({
      id: `${Date.now()}-${flow}-${eventSeq.current}`,
      plan: membershipPlan,
      flow,
      status,
      createdAt: Date.now(),
      reason,
    });
  };

  const completeMembership = async () => {
    await setMembershipPlan(membershipPlan);
    await completeOnboarding();
    navigation.reset({
      index: 0,
      routes: [
        {
          name: 'MainTabs',
          params: { screen: 'Home', params: { justUnlocked: membershipPlan } },
        },
      ],
    });
  };

  const finishPaidMembership = async (
    token: string,
    fallbackPlan: 'pro' | 'family'
  ) => {
    const membership = await backendApi.getMembership(token).catch(() => null);
    const effectivePlan =
      membership?.plan === 'pro' || membership?.plan === 'family'
        ? membership.plan
        : fallbackPlan;
    await setMembershipPlan(effectivePlan);
    await completeOnboarding();
    navigation.reset({
      index: 0,
      routes: [
        {
          name: 'MainTabs',
          params: { screen: 'Home', params: { justUnlocked: effectivePlan } },
        },
      ],
    });
  };

  const pollOrderUntilSettled = async (
    token: string,
    orderNo: string
  ): Promise<'paid' | 'failed' | 'pending'> => {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const order = await backendApi.getOrder(token, orderNo);
      if (order.status === 'paid') return 'paid';
      if (order.status === 'failed') return 'failed';
    }
    return 'pending';
  };

  const handlePay = async () => {
    if (isBusy) return;
    try {
      await recordEvent('pay', 'processing');
      track(EventName.CheckoutStarted, {
        plan: membershipPlan,
        billingCycle: selectedPlan,
        source: 'checkout_screen',
      });
      setPaymentNotice(null);
      setProcessing('pay');

      if (Platform.OS === 'ios') {
        if (!subscriptionService.isIapAvailable()) {
          throw new Error('ios iap is not configured');
        }
        const revenueCatUserId = await getSubscriptionUserId();
        const result = await subscriptionService.purchase(
          membershipPlan,
          revenueCatUserId ?? undefined
        );
        await recordEvent('pay', 'success');
        track(EventName.CheckoutCompleted, {
          plan: membershipPlan,
          billingCycle: selectedPlan,
          provider: 'apple',
        });
        const resolvedPlan =
          result.plan === 'free' ? membershipPlan : result.plan;
        await setMembershipPlan(resolvedPlan);
        await completeOnboarding();
        navigation.reset({
          index: 0,
          routes: [
            {
              name: 'MainTabs',
              params: { screen: 'Home', params: { justUnlocked: resolvedPlan } },
            },
          ],
        });
        return;
      }

      if (backendApi.isEnabled()) {
        const token = await backendApi.ensureToken();
        if (!token) throw new Error('backend auth token not available');
        const created = await backendApi.createOrder(token, membershipPlan);
        setLastOrderNo(created.order_no);
        await Linking.openURL(created.pay_url).catch(() => {});
        const status = await pollOrderUntilSettled(token, created.order_no);
        if (status === 'paid') {
          await recordEvent('pay', 'success');
          track(EventName.CheckoutCompleted, {
            plan: membershipPlan,
            billingCycle: selectedPlan,
            provider: 'alipay',
          });
          await finishPaidMembership(token, membershipPlan);
          return;
        }
        if (status === 'pending') {
          setPaymentNotice(t('checkout.pendingBodyOpened'));
          setProcessing('pending');
          return;
        }
        throw new Error(`order status is ${status}`);
      }

      if (ENABLE_MOCK_PAYMENTS) {
        await new Promise((resolve) => setTimeout(resolve, 600));
        await recordEvent('pay', 'success');
        track(EventName.CheckoutCompleted, {
          plan: membershipPlan,
          billingCycle: selectedPlan,
          provider: 'mock',
        });
        await completeMembership();
        return;
      }

      throw new Error('payment backend is not configured');
    } catch (error) {
      console.warn('Payment flow failed:', error);
      const message = error instanceof Error ? error.message : '';
      const backendUnavailable =
        message.includes('not configured') ||
        message.includes('auth token');
      const iapUnavailable = message.includes('ios iap is not configured');
      const orderFailed = message.includes('order status is failed');
      const reason =
        backendUnavailable || iapUnavailable
          ? 'payment_backend_unavailable'
          : orderFailed
            ? 'order_failed'
            : 'payment_failed';

      setPaymentNotice(
        backendUnavailable || iapUnavailable
          ? t('checkout.failedBackendUnavailable')
          : orderFailed
            ? t('checkout.failedOrder')
            : t('checkout.failedGeneric')
      );
      await recordEvent('pay', 'failed', reason);
      track(EventName.CheckoutFailed, {
        plan: membershipPlan,
        billingCycle: selectedPlan,
        reason,
      });
      setProcessing('failed');
    }
  };

  const refreshOrderStatus = async () => {
    if (!lastOrderNo || !backendApi.isEnabled()) return;
    try {
      setPaymentNotice(null);
      setProcessing('pay');
      const token = await backendApi.ensureToken();
      if (!token) throw new Error('backend auth token not available');
      const status = await pollOrderUntilSettled(token, lastOrderNo);
      if (status === 'paid') {
        await recordEvent('pay', 'success');
        track(EventName.CheckoutCompleted, {
          plan: membershipPlan,
          billingCycle: selectedPlan,
          provider: 'alipay',
        });
        await finishPaidMembership(token, membershipPlan);
        return;
      }
      if (status === 'pending') {
        setPaymentNotice(t('checkout.pendingBodyRefresh'));
        setProcessing('pending');
        return;
      }
      throw new Error(`order status is ${status}`);
    } catch (error) {
      console.warn('Refresh order status failed:', error);
      setPaymentNotice(t('checkout.failedRefresh'));
      setProcessing('failed');
    }
  };

  const handleTrial = async () => {
    if (isBusy) return;
    if (!ENABLE_MOCK_PAYMENTS) {
      await recordEvent('trial', 'failed', 'trial_not_enabled');
      setPaymentNotice(t('checkout.trialNotEnabled'));
      setProcessing('failed');
      return;
    }
    try {
      await recordEvent('trial', 'processing');
      setPaymentNotice(null);
      setProcessing('trial');
      await new Promise((resolve) => setTimeout(resolve, 300));
      await recordEvent('trial', 'success');
      await completeMembership();
    } catch (error) {
      console.warn('Trial flow failed:', error);
      await recordEvent('trial', 'failed', 'mock_trial_error');
      setProcessing('failed');
    }
  };

  const handleRestore = async () => {
    if (isBusy) return;
    try {
      setProcessing('pay');
      setPaymentNotice(null);
      track(EventName.SubscriptionRestored, { source: 'checkout_screen' });
      const revenueCatUserId = await getSubscriptionUserId();
      const result = await subscriptionService.restore(
        revenueCatUserId ?? undefined
      );
      if (result.plan === 'free') {
        setPaymentNotice(result.message);
        setProcessing('failed');
        return;
      }
      await setMembershipPlan(result.plan);
      await completeOnboarding();
      navigation.reset({
        index: 0,
        routes: [
          {
            name: 'MainTabs',
            params: { screen: 'Home', params: { justUnlocked: result.plan } },
          },
        ],
      });
    } catch (error) {
      console.warn('Restore purchase failed:', error);
      setPaymentNotice(
        error instanceof Error ? error.message : t('checkout.failedRestoreFallback')
      );
      setProcessing('failed');
    }
  };

  const handleTogglePlan = () => {
    setSelectedPlan((prev) => {
      const next: PricingPlan = prev === 'annual' ? 'monthly' : 'annual';
      track(EventName.PaywallPlanSelected, {
        plan: membershipPlan,
        billingCycle: next,
        source: 'checkout_switch',
      });
      return next;
    });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.grabber} />

      <View style={styles.header}>
        <Pressable
          onPress={() => navigation.goBack()}
          style={({ pressed }) => [styles.backBtn, pressed && styles.pressedChrome]}
          accessibilityRole="button"
          accessibilityLabel={t('checkout.backA11y')}
          hitSlop={8}
        >
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.headerTitle}>{t('checkout.headerTitle')}</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <CheckoutHero plan={membershipPlan} heroImage={heroImage} />

        <PricingComparison
          selectedPlan={selectedPlan}
          onSelectPlan={(plan) => {
            setSelectedPlan(plan);
            track(EventName.PaywallPlanSelected, {
              plan: membershipPlan,
              billingCycle: plan,
              source: 'checkout_card',
            });
          }}
        />

        <BenefitList plan={membershipPlan} />

        <TrustSignals />

        <View style={styles.benefitGrid}>
          <View style={styles.benefitTile}>
            <Sparkles size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitText}>{t('checkout.featureFewerRepeats')}</Text>
          </View>
          <View style={styles.benefitTile}>
            <ScanSearch size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitText}>{t('checkout.featureMenuPicks')}</Text>
          </View>
          <View style={styles.benefitTile}>
            <CheckCircle2 size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitText}>{t('checkout.featureStrongerFilters')}</Text>
          </View>
        </View>

        {processing === 'pending' && paymentNotice ? (
          <PendingOrderCard
            message={paymentNotice}
            onRefresh={refreshOrderStatus}
            refreshing={isBusy}
          />
        ) : null}

        {processing === 'failed' && paymentNotice ? (
          <FailedOrderCard message={paymentNotice} onRetry={handlePay} />
        ) : null}

        {ENABLE_MOCK_PAYMENTS ? (
          <Pressable
            style={({ pressed }) => [
              styles.trialBtn,
              pressed && styles.pressedChrome,
              isBusy && styles.btnDisabled,
            ]}
            onPress={handleTrial}
            disabled={isBusy}
            accessibilityRole="button"
            accessibilityLabel={t('checkout.trialA11y')}
            accessibilityState={{ disabled: isBusy }}
          >
            <Text style={styles.trialText}>{t('checkout.trialButton')}</Text>
          </Pressable>
        ) : null}
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          style={({ pressed }) => [
            styles.payBtn,
            pressed && styles.payBtnPressed,
            isBusy && styles.btnDisabled,
          ]}
          onPress={handlePay}
          disabled={isBusy}
          accessibilityRole="button"
          accessibilityLabel={ctaLabel(selectedPlan)}
          accessibilityState={{ disabled: isBusy }}
        >
          {processing === 'pay' ? (
            <ActivityIndicator color="#FFFFFF" size="small" />
          ) : (
            <View style={styles.payBtnInner}>
              <Text style={styles.payText}>{ctaLabel(selectedPlan)}</Text>
              <Text style={styles.paySubtext}>{ctaSubtext(selectedPlan)}</Text>
            </View>
          )}
        </Pressable>

        <Pressable
          onPress={handleTogglePlan}
          style={styles.switchPlanBtn}
          accessibilityRole="button"
          accessibilityLabel={switchPlanLabel(selectedPlan)}
        >
          <Text style={styles.switchPlanText}>{switchPlanLabel(selectedPlan)}</Text>
        </Pressable>

        <View style={styles.legalRow}>
          <Pressable
            onPress={handleRestore}
            disabled={isBusy}
            accessibilityRole="button"
            accessibilityLabel={t('checkout.legalRestoreA11y')}
          >
            <Text style={styles.legalText}>{t('checkout.legalRestore')}</Text>
          </Pressable>
          <Text style={styles.legalDot}>·</Text>
          <Text style={styles.legalText}>{t('checkout.legalTerms')}</Text>
          <Text style={styles.legalDot}>·</Text>
          <Text style={styles.legalText}>{t('checkout.legalPrivacy')}</Text>
        </View>
      </View>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    grabber: {
      alignSelf: 'center',
      width: 40,
      height: 5,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.border,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.xs,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: t.spacing.md,
      paddingBottom: t.spacing.sm,
    },
    backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
    headerTitle: { ...t.typography.h2, color: t.colors.foreground },
    content: { paddingHorizontal: t.spacing.md, paddingBottom: t.spacing.lg },
    benefitGrid: { flexDirection: 'row', gap: t.spacing.sm, marginBottom: t.spacing.md },
    benefitTile: {
      flex: 1,
      minHeight: 84,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surfaceMuted,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
    },
    benefitText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    trialBtn: {
      backgroundColor: t.colors.surface,
      borderWidth: 1,
      borderColor: t.colors.border,
      height: 44,
      borderRadius: t.radius.full,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: t.spacing.md,
    },
    trialText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '600' },
    footer: {
      paddingHorizontal: t.spacing.md,
      paddingTop: t.spacing.md,
      paddingBottom: t.spacing.md,
      borderTopWidth: 1,
      borderTopColor: t.colors.borderLight,
      backgroundColor: t.colors.surface,
      gap: t.spacing.xs,
    },
    payBtn: {
      backgroundColor: t.colors.primary,
      height: 54,
      borderRadius: t.radius.full,
      alignItems: 'center',
      justifyContent: 'center',
    },
    payBtnInner: { alignItems: 'center', gap: 2 },
    payText: { fontSize: 17, color: '#FFFFFF', fontWeight: '700' },
    paySubtext: { fontSize: 12, color: 'rgba(255,255,255,0.82)', fontWeight: '500' },
    switchPlanBtn: { alignItems: 'center', justifyContent: 'center', minHeight: 36 },
    switchPlanText: { fontSize: 14, color: t.colors.primaryDark, fontWeight: '600' },
    legalRow: { flexDirection: 'row', justifyContent: 'center', gap: 8, alignItems: 'center' },
    legalText: { fontSize: 12, color: t.colors.subtle },
    legalDot: { fontSize: 12, color: t.colors.borderLight },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
    payBtnPressed: {
      opacity: t.interaction.pressedOpacity,
      transform: [{ scale: t.interaction.pressedScale }],
    },
    btnDisabled: { opacity: 0.42 },
  });
}
