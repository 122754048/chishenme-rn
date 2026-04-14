import React from 'react';
import { Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, CheckCircle2, ScanSearch, ShieldCheck, Sparkles } from 'lucide-react-native';
import { backendApi } from '../api/backend';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';
import { SWIPE_CARDS } from '../data/mockData';
import type { RootStackParamList } from '../navigation/types';
import { subscriptionService } from '../services/subscriptions';
import { storage } from '../storage';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type CheckoutRouteProp = RouteProp<RootStackParamList, 'Checkout'>;

const ENABLE_MOCK_PAYMENTS = process.env.EXPO_PUBLIC_ENABLE_MOCK_PAYMENTS === 'true';

export function Checkout() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const route = useRoute<CheckoutRouteProp>();
  const { completeOnboarding, setMembershipPlan } = useApp();
  const [processing, setProcessing] = React.useState<'idle' | 'pay' | 'trial' | 'pending' | 'failed'>('idle');
  const [paymentNotice, setPaymentNotice] = React.useState<string | null>(null);
  const [lastOrderNo, setLastOrderNo] = React.useState<string | null>(null);
  const eventSeq = React.useRef(0);

  const plan = route.params?.plan ?? 'pro';
  const planText = plan === 'family' ? 'Family / $19.99 month' : 'Pro / $9.99 month';
  const planBenefits =
    plan === 'family'
      ? ['Shared picks stay in sync', 'Full menu scan recommendations', 'Better tie-breakers for groups']
      : ['Sharper ranking for tonight', 'Full menu scan recommendations', 'More room to save the good calls'];
  const heroImage = plan === 'family' ? SWIPE_CARDS[4].image : SWIPE_CARDS[0].image;
  const isBusy = processing === 'pay' || processing === 'trial';

  const getSubscriptionUserId = async () => {
    const userId = await storage.ensureBackendUserId();
    if (backendApi.isEnabled()) {
      const token = await backendApi.ensureToken();
      if (!token) {
        throw new Error('backend auth token not available');
      }
    }
    return userId;
  };

  const recordEvent = async (flow: 'pay' | 'trial', status: 'processing' | 'success' | 'failed', reason?: string) => {
    eventSeq.current += 1;
    await storage.appendPaymentEvent({
      id: `${Date.now()}-${flow}-${eventSeq.current}`,
      plan,
      flow,
      status,
      createdAt: Date.now(),
      reason,
    });
  };

  const completeMembership = async () => {
    await setMembershipPlan(plan);
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs', params: { screen: 'Home', params: { justUnlocked: plan } } }] });
  };

  const finishPaidMembership = async (token: string, fallbackPlan: 'pro' | 'family') => {
    const membership = await backendApi.getMembership(token).catch(() => null);
    const effectivePlan = membership?.plan === 'pro' || membership?.plan === 'family' ? membership.plan : fallbackPlan;
    await setMembershipPlan(effectivePlan);
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs', params: { screen: 'Home', params: { justUnlocked: effectivePlan } } }] });
  };

  const pollOrderUntilSettled = async (token: string, orderNo: string) => {
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
      setPaymentNotice(null);
      setProcessing('pay');

      if (Platform.OS === 'ios') {
        if (!subscriptionService.isIapAvailable()) {
          throw new Error('ios iap is not configured');
        }
        const revenueCatUserId = await getSubscriptionUserId();
        const result = await subscriptionService.purchase(plan, revenueCatUserId ?? undefined);
        await recordEvent('pay', 'success');
        const resolvedPlan = result.plan === 'free' ? plan : result.plan;
        await setMembershipPlan(resolvedPlan);
        await completeOnboarding();
        navigation.reset({ index: 0, routes: [{ name: 'MainTabs', params: { screen: 'Home', params: { justUnlocked: resolvedPlan } } }] });
        return;
      } else if (backendApi.isEnabled()) {
        const token = await backendApi.ensureToken();
        if (!token) {
          throw new Error('backend auth token not available');
        }
        const created = await backendApi.createOrder(token, plan);
        setLastOrderNo(created.order_no);
        await Linking.openURL(created.pay_url).catch(() => {
          // Simulators and preview devices can fail to open the external payment URL.
        });
        const status = await pollOrderUntilSettled(token, created.order_no);
        if (status === 'paid') {
          await recordEvent('pay', 'success');
          await finishPaidMembership(token, plan);
          return;
        }
        if (status === 'pending') {
          setPaymentNotice('Your order is created. Finish payment, then come back here and refresh the status.');
          setProcessing('pending');
          return;
        }
        throw new Error(`order status is ${status}`);
      } else if (ENABLE_MOCK_PAYMENTS) {
        await new Promise((resolve) => setTimeout(resolve, 600));
        await recordEvent('pay', 'success');
        await completeMembership();
        return;
      }
      throw new Error('payment backend is not configured');
    } catch (error) {
      console.warn('[Teller]', 'Payment flow failed:', error);
      const message = error instanceof Error ? error.message : '';
      const backendUnavailable = message.includes('not configured') || message.includes('auth token');
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
          ? 'Apple subscription services are not configured for this build yet. You can keep using Free and finish setup later.'
          : orderFailed
            ? 'The order could not be completed. Please try again.'
            : 'Payment did not finish. Try again or stay on the free plan for now.'
      );
      await recordEvent('pay', 'failed', reason);
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
        await finishPaidMembership(token, plan);
        return;
      }
      if (status === 'pending') {
        setPaymentNotice('We still have not received a completed payment notification yet. Please refresh again in a moment.');
        setProcessing('pending');
        return;
      }
      throw new Error(`order status is ${status}`);
    } catch (error) {
      console.warn('[Teller]', 'Refresh order status failed:', error);
      setPaymentNotice('We could not refresh the order status right now. Please try again in a moment.');
      setProcessing('failed');
    }
  };

  const handleTrial = async () => {
    if (isBusy) return;
    if (!ENABLE_MOCK_PAYMENTS) {
      await recordEvent('trial', 'failed', 'trial_not_enabled');
      setPaymentNotice('Trial mode is not enabled for this build. Keep using Free or use the real subscription flow.');
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
      console.warn('[Teller]', 'Trial flow failed:', error);
      await recordEvent('trial', 'failed', 'mock_trial_error');
      setProcessing('failed');
    }
  };

  const handleRestore = async () => {
    if (isBusy) return;
    try {
      setProcessing('pay');
      setPaymentNotice(null);
      const revenueCatUserId = await getSubscriptionUserId();
      const result = await subscriptionService.restore(revenueCatUserId ?? undefined);
      if (result.plan === 'free') {
        setPaymentNotice(result.message);
        setProcessing('failed');
        return;
      }
      await setMembershipPlan(result.plan);
      await completeOnboarding();
      navigation.reset({ index: 0, routes: [{ name: 'MainTabs', params: { screen: 'Home', params: { justUnlocked: result.plan } } }] });
    } catch (error) {
      console.warn('[Teller]', 'Restore purchase failed:', error);
      setPaymentNotice(error instanceof Error ? error.message : 'Restore failed. Please try again in a moment.');
      setProcessing('failed');
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.grabber} />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && styles.pressedChrome]} accessibilityRole="button" accessibilityLabel="Go back" hitSlop={8}>
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.headerTitle}>Confirm subscription</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.planBlock}>
          <View style={styles.planHeroImage}>
            <SkeletonImage src={heroImage} alt={planText} />
          </View>
          <View style={styles.planBadge}>
            <ShieldCheck size={16} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.cardTitle}>Plan</Text>
          </View>
          <Text style={styles.planText}>{planText}</Text>
          <View style={styles.statusPill}>
            <Text style={styles.statusText}>
              {processing === 'trial'
                ? 'Starting preview'
                : processing === 'pay'
                  ? 'Processing'
                  : processing === 'pending'
                    ? 'Pending'
                    : processing === 'failed'
                      ? 'Try again'
                      : 'Apple billing'}
            </Text>
          </View>
          {paymentNotice ? <Text style={styles.noticeText}>{paymentNotice}</Text> : null}
        </View>

        <View style={styles.resultBlock}>
          <Text style={styles.resultTitle}>What changes today</Text>
          <View style={styles.resultList}>
            {planBenefits.map((benefit) => (
              <View key={benefit} style={styles.resultRow}>
                <CheckCircle2 size={15} color={theme.colors.primary} strokeWidth={2.4} />
                <Text style={styles.resultText}>{benefit}</Text>
              </View>
            ))}
          </View>
        </View>

        <View style={styles.benefitGrid}>
          <View style={styles.benefitTile}>
            <Sparkles size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitText}>Fewer repeats</Text>
          </View>
          <View style={styles.benefitTile}>
            <ScanSearch size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitText}>Menu picks</Text>
          </View>
          <View style={styles.benefitTile}>
            <CheckCircle2 size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.benefitText}>Stronger filters</Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={({ pressed }) => [styles.payBtn, pressed && styles.payBtnPressed, isBusy && styles.btnDisabled]} onPress={handlePay} disabled={isBusy} accessibilityRole="button" accessibilityLabel={`Pay for ${planText}`} accessibilityState={{ disabled: isBusy }}>
          <Text style={styles.payText}>{processing === 'pay' ? 'Processing...' : 'Subscribe'}</Text>
        </Pressable>
        {ENABLE_MOCK_PAYMENTS ? (
          <Pressable style={({ pressed }) => [styles.trialBtn, pressed && styles.pressedChrome, isBusy && styles.btnDisabled]} onPress={handleTrial} disabled={isBusy} accessibilityRole="button" accessibilityLabel="Start a trial" accessibilityState={{ disabled: isBusy }}>
            <Text style={styles.trialText}>Start trial</Text>
          </Pressable>
        ) : null}
        {processing === 'failed' ? (
          <Pressable style={({ pressed }) => [styles.retryBtn, pressed && styles.pressedChrome]} onPress={handlePay} accessibilityRole="button" accessibilityLabel="Retry payment">
            <Text style={styles.retryText}>Retry payment</Text>
          </Pressable>
        ) : null}
        <Pressable style={({ pressed }) => [styles.restoreBtn, pressed && styles.pressedChrome, isBusy && styles.btnDisabled]} onPress={handleRestore} disabled={isBusy} accessibilityRole="button" accessibilityLabel="Restore purchases" accessibilityState={{ disabled: isBusy }}>
          <Text style={styles.restoreText}>Restore</Text>
        </Pressable>
        {processing === 'pending' ? (
          <Pressable style={({ pressed }) => [styles.retryBtn, pressed && styles.pressedChrome]} onPress={refreshOrderStatus} accessibilityRole="button" accessibilityLabel="Refresh payment status">
            <Text style={styles.retryText}>Refresh status</Text>
          </Pressable>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
    payBtnPressed: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    grabber: {
      alignSelf: 'center',
      width: 40,
      height: 5,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.border,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.xs,
    },
    header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: t.spacing.md, paddingBottom: t.spacing.sm },
    backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
    headerTitle: { ...t.typography.h2, color: t.colors.foreground },
    content: { paddingHorizontal: t.spacing.md, paddingBottom: t.spacing.lg, gap: t.spacing.lg },
    planBlock: {
      paddingTop: t.spacing.sm,
      gap: t.spacing.sm,
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      paddingHorizontal: t.surface.insetCardPadding,
      paddingBottom: t.surface.insetCardPadding,
    },
    planHeroImage: { height: 132, borderRadius: t.radius.md, overflow: 'hidden', marginBottom: 4 },
    planBadge: { flexDirection: 'row', alignItems: 'center', gap: 8 },
    cardTitle: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '700' },
    planText: { ...t.typography.h1, color: t.colors.foreground, marginBottom: 6 },
    statusPill: { alignSelf: 'flex-start', minHeight: 34, borderRadius: 17, backgroundColor: t.colors.surface, paddingHorizontal: 12, justifyContent: 'center' },
    statusText: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    noticeText: { ...t.typography.caption, color: t.colors.subtle, lineHeight: 18 },
    resultBlock: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      gap: t.spacing.sm,
    },
    resultTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    resultList: { gap: 8 },
    resultRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
    resultText: { ...t.typography.caption, color: t.colors.foreground, flex: 1 },
    benefitGrid: { flexDirection: 'row', gap: t.spacing.sm },
    benefitTile: { flex: 1, minHeight: 84, borderRadius: t.surface.cardRadius, backgroundColor: t.colors.surfaceMuted, alignItems: 'center', justifyContent: 'center', gap: 8 },
    benefitText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    footer: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.sm, paddingBottom: t.spacing.md, borderTopWidth: 1, borderTopColor: t.colors.borderLight, backgroundColor: t.colors.surface, gap: t.spacing.xs },
    payBtn: { backgroundColor: t.colors.primary, height: 48, borderRadius: t.radius.full, alignItems: 'center', justifyContent: 'center' },
    payText: { ...t.typography.body, color: t.colors.surface, fontWeight: '700' },
    trialBtn: { backgroundColor: t.colors.surface, borderWidth: 1, borderColor: t.colors.border, height: 44, borderRadius: t.radius.full, alignItems: 'center', justifyContent: 'center' },
    trialText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '600' },
    retryBtn: { alignItems: 'center', justifyContent: 'center', height: 40 },
    btnDisabled: { opacity: 0.6 },
    retryText: { ...t.typography.caption, color: t.colors.error, fontWeight: '700' },
    restoreBtn: { alignItems: 'center', justifyContent: 'center', height: 40 },
    restoreText: { ...t.typography.caption, color: t.colors.primary, fontWeight: '700' },
  });
}
