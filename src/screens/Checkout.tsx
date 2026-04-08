import React from 'react';
import { View, Text, Pressable, StyleSheet, Platform } from 'react-native';
import { Linking } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, ShieldCheck } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { useApp } from '../context/AppContext';
import { storage } from '../storage';
import { backendApi } from '../api/backend';
import { subscriptionService } from '../services/subscriptions';

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
  const planText = plan === 'family' ? '家庭版 ¥19.9/月' : 'Pro 版 ¥9.9/月';
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
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  const finishPaidMembership = async (token: string, fallbackPlan: 'pro' | 'family') => {
    const membership = await backendApi.getMembership(token).catch(() => null);
    const effectivePlan = membership?.plan === 'pro' || membership?.plan === 'family' ? membership.plan : fallbackPlan;
    await setMembershipPlan(effectivePlan);
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
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
        await setMembershipPlan(result.plan === 'free' ? plan : result.plan);
        await completeOnboarding();
        navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
        return;
      } else if (backendApi.isEnabled()) {
        const token = await backendApi.ensureToken();
        if (!token) {
          throw new Error('backend auth token not available');
        }
        const created = await backendApi.createOrder(token, plan);
        setLastOrderNo(created.order_no);
        await Linking.openURL(created.pay_url).catch(() => {
          // Some simulators/devices cannot open external URLs; keep checkout flow alive.
        });
        const status = await pollOrderUntilSettled(token, created.order_no);
        if (status === 'paid') {
          await recordEvent('pay', 'success');
          await finishPaidMembership(token, plan);
          return;
        }
        if (status === 'pending') {
          setPaymentNotice('订单已创建，请在支付宝完成付款后回到本页刷新状态。');
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
      console.warn('Payment flow failed:', error);
      const message = error instanceof Error ? error.message : '';
      const backendUnavailable = message.includes('not configured') || message.includes('auth token');
      const iapUnavailable = message.includes('ios iap is not configured');
      const orderFailed = message.includes('order status is failed');
      const reason = backendUnavailable || iapUnavailable
        ? 'payment_backend_unavailable'
        : orderFailed
          ? 'order_failed'
          : 'payment_failed';
      setPaymentNotice(
        backendUnavailable || iapUnavailable
          ? 'iOS 内购暂未配置完成，请稍后再试，或先返回选择免费版继续使用。'
          : orderFailed
            ? '订单未能完成，请重新发起支付。'
            : '支付暂未完成，请重试或返回选择免费版继续使用。'
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
        setPaymentNotice('还没有收到支付成功通知，请确认支付宝付款完成后再刷新。');
        setProcessing('pending');
        return;
      }
      throw new Error(`order status is ${status}`);
    } catch (error) {
      console.warn('Refresh order status failed:', error);
      setPaymentNotice('暂时无法刷新订单状态，请稍后重试。');
      setProcessing('failed');
    }
  };

  const handleTrial = async () => {
    if (isBusy) return;
    if (!ENABLE_MOCK_PAYMENTS) {
      await recordEvent('trial', 'failed', 'trial_not_enabled');
      setPaymentNotice('当前版本未开启试用，请返回选择免费版或使用正式支付。');
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
      const revenueCatUserId = await getSubscriptionUserId();
      const result = await subscriptionService.restore(revenueCatUserId ?? undefined);
      if (result.plan === 'free') {
        setPaymentNotice(result.message);
        setProcessing('failed');
        return;
      }
      await setMembershipPlan(result.plan);
      await completeOnboarding();
      navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
    } catch (error) {
      console.warn('Restore purchase failed:', error);
      setPaymentNotice(error instanceof Error ? error.message : '恢复购买失败，请稍后重试。');
      setProcessing('failed');
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <Pressable
          onPress={() => navigation.goBack()}
          style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}
          accessibilityRole="button"
          accessibilityLabel="返回方案选择"
          hitSlop={8}
        >
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.headerTitle}>确认支付</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={styles.card}>
        <View style={styles.cardTitleRow}>
          <ShieldCheck size={18} color={theme.colors.success} strokeWidth={2} />
          <Text style={styles.cardTitle}>已选择方案</Text>
        </View>
        <Text style={styles.planText}>{planText}</Text>
        <Text style={styles.bodyText}>
          {processing === 'trial'
            ? '正在开通试用…'
            : processing === 'pay'
              ? '正在处理支付…'
              : processing === 'pending'
                ? paymentNotice ?? '订单处理中，请完成支付后点击“我已完成支付，刷新状态”。'
              : processing === 'failed'
                ? paymentNotice ?? '支付暂未完成，请重试或返回选择免费版继续使用。'
                : '支持随时取消，付款后立即生效。'}
        </Text>
      </View>

      <View style={styles.footer}>
        <Pressable
          style={({ pressed }) => [styles.payBtn, pressed && { opacity: 0.9 }, isBusy && styles.btnDisabled]}
          onPress={handlePay}
          disabled={isBusy}
          accessibilityRole="button"
          accessibilityLabel={`立即支付 ${planText}`}
          accessibilityState={{ disabled: isBusy }}
        >
          <Text style={styles.payText}>{processing === 'pay' ? '处理中…' : '立即支付'}</Text>
        </Pressable>
        {ENABLE_MOCK_PAYMENTS && (
          <Pressable
            style={({ pressed }) => [styles.trialBtn, pressed && { opacity: 0.8 }, isBusy && styles.btnDisabled]}
            onPress={handleTrial}
            disabled={isBusy}
            accessibilityRole="button"
            accessibilityLabel="先试用 7 天"
            accessibilityState={{ disabled: isBusy }}
          >
            <Text style={styles.trialText}>先试用 7 天</Text>
          </Pressable>
        )}
        {processing === 'failed' && (
          <Pressable
            style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.8 }]}
            onPress={handlePay}
            accessibilityRole="button"
            accessibilityLabel="重试支付"
          >
            <Text style={styles.retryText}>重试支付</Text>
          </Pressable>
        )}
        <Pressable
          style={({ pressed }) => [styles.restoreBtn, pressed && { opacity: 0.8 }, isBusy && styles.btnDisabled]}
          onPress={handleRestore}
          disabled={isBusy}
          accessibilityRole="button"
          accessibilityLabel="恢复购买"
          accessibilityState={{ disabled: isBusy }}
        >
          <Text style={styles.restoreText}>恢复购买</Text>
        </Pressable>
        {processing === 'pending' && (
          <Pressable
            style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.8 }]}
            onPress={refreshOrderStatus}
            accessibilityRole="button"
            accessibilityLabel="我已完成支付，刷新状态"
          >
            <Text style={styles.retryText}>我已完成支付，刷新状态</Text>
          </Pressable>
        )}
      </View>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: t.spacing.md,
      height: t.topNavHeight,
      backgroundColor: t.colors.surface,
      borderBottomWidth: 1,
      borderBottomColor: t.colors.borderLight,
    },
    backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
    headerTitle: { ...t.typography.h2, color: t.colors.foreground },
    card: {
      margin: t.spacing.md,
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.md,
      ...t.shadows.md,
    },
    cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: t.spacing.xs },
    cardTitle: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '700' },
    planText: { ...t.typography.h1, color: t.colors.foreground, marginBottom: 6 },
    bodyText: { ...t.typography.body, color: t.colors.muted },
    footer: { marginTop: 'auto', padding: t.spacing.md, gap: t.spacing.xs },
    payBtn: {
      backgroundColor: t.colors.primary,
      height: 48,
      borderRadius: t.radius.full,
      alignItems: 'center',
      justifyContent: 'center',
    },
    payText: { ...t.typography.body, color: t.colors.surface, fontWeight: '700' },
    trialBtn: {
      backgroundColor: t.colors.surface,
      borderWidth: 1,
      borderColor: t.colors.border,
      height: 44,
      borderRadius: t.radius.full,
      alignItems: 'center',
      justifyContent: 'center',
    },
    trialText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '600' },
    retryBtn: {
      alignItems: 'center',
      justifyContent: 'center',
      height: 40,
    },
    btnDisabled: {
      opacity: 0.6,
    },
    retryText: { ...t.typography.caption, color: t.colors.error, fontWeight: '700' },
    restoreBtn: {
      alignItems: 'center',
      justifyContent: 'center',
      height: 40,
    },
    restoreText: { ...t.typography.caption, color: t.colors.primary, fontWeight: '700' },
  });
}
