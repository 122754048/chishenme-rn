import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
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

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type CheckoutRouteProp = RouteProp<RootStackParamList, 'Checkout'>;

export function Checkout() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const route = useRoute<CheckoutRouteProp>();
  const { completeOnboarding, setMembershipPlan } = useApp();
  const [processing, setProcessing] = React.useState<'idle' | 'pay' | 'trial' | 'pending' | 'failed'>('idle');
  const [lastOrderNo, setLastOrderNo] = React.useState<string | null>(null);
  const eventSeq = React.useRef(0);

  const plan = route.params?.plan ?? 'pro';
  const planText = plan === 'family' ? '家庭版 ¥19.9/月' : 'Pro 版 ¥9.9/月';

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
    if (processing === 'pay' || processing === 'trial') return;
    try {
      await recordEvent('pay', 'processing');
      setProcessing('pay');

      if (backendApi.isEnabled()) {
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
          setProcessing('pending');
          return;
        }
        throw new Error(`order status is ${status}`);
      } else {
        await new Promise((resolve) => setTimeout(resolve, 600));
        await recordEvent('pay', 'success');
        await completeMembership();
        return;
      }
    } catch (error) {
      console.warn('Payment flow failed:', error);
      await recordEvent('pay', 'failed', 'mock_gateway_error');
      setProcessing('failed');
    }
  };

  const refreshOrderStatus = async () => {
    if (!lastOrderNo || !backendApi.isEnabled()) return;
    try {
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
        setProcessing('pending');
        return;
      }
      throw new Error(`order status is ${status}`);
    } catch (error) {
      console.warn('Refresh order status failed:', error);
      setProcessing('failed');
    }
  };

  const handleTrial = async () => {
    if (processing === 'pay' || processing === 'trial') return;
    try {
      await recordEvent('trial', 'processing');
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

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}>
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
            ? '正在开通试用...'
            : processing === 'pay'
              ? '正在处理支付...'
              : processing === 'pending'
                ? '订单处理中，请完成支付后点击“我已完成支付，刷新状态”。'
              : processing === 'failed'
                ? '支付失败，请重试或先试用。'
                : '支持随时取消，付款后立即生效。'}
        </Text>
      </View>

      <View style={styles.footer}>
        <Pressable
          style={({ pressed }) => [styles.payBtn, pressed && { opacity: 0.9 }, (processing === 'pay' || processing === 'trial') && styles.btnDisabled]}
          onPress={handlePay}
          disabled={processing === 'pay' || processing === 'trial'}
        >
          <Text style={styles.payText}>立即支付</Text>
        </Pressable>
        <Pressable
          style={({ pressed }) => [styles.trialBtn, pressed && { opacity: 0.8 }, (processing === 'pay' || processing === 'trial') && styles.btnDisabled]}
          onPress={handleTrial}
          disabled={processing === 'pay' || processing === 'trial'}
        >
          <Text style={styles.trialText}>先试用 7 天</Text>
        </Pressable>
        {processing === 'failed' && (
          <Pressable style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.8 }]} onPress={handlePay}>
            <Text style={styles.retryText}>重试支付</Text>
          </Pressable>
        )}
        {processing === 'pending' && (
          <Pressable style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.8 }]} onPress={refreshOrderStatus}>
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
  });
}
