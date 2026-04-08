import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, ShieldCheck } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type CheckoutRouteProp = RouteProp<RootStackParamList, 'Checkout'>;

export function Checkout() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const route = useRoute<CheckoutRouteProp>();
  const { completeOnboarding, setMembershipPlan } = useApp();

  const plan = route.params?.plan ?? 'pro';
  const planText = plan === 'family' ? '家庭版 ¥19.9/月' : 'Pro 版 ¥9.9/月';

  const handlePay = async () => {
    await setMembershipPlan(plan);
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
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
        <Text style={styles.bodyText}>支持随时取消，付款后立即生效。</Text>
      </View>

      <View style={styles.footer}>
        <Pressable style={({ pressed }) => [styles.payBtn, pressed && { opacity: 0.9 }]} onPress={handlePay}>
          <Text style={styles.payText}>立即支付</Text>
        </Pressable>
        <Pressable style={({ pressed }) => [styles.trialBtn, pressed && { opacity: 0.8 }]} onPress={handlePay}>
          <Text style={styles.trialText}>先试用 7 天</Text>
        </Pressable>
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
  });
}
