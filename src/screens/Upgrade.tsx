import React, { useState } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated from 'react-native-reanimated';
import { ArrowLeft, ArrowRight, Zap, Shield, Check, Lock, CreditCard } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

const pcStyles = StyleSheet.create({
  planCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1.5,
    borderColor: 'transparent',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 3,
    elevation: 2,
  },
  planCardHighlighted: { backgroundColor: '#FFF0E8', borderColor: '#FF6B35' },
  badge: { position: 'absolute', top: 0, right: 0, paddingHorizontal: 12, paddingVertical: 4, borderTopRightRadius: 12, borderBottomLeftRadius: 8 },
  badgeHighlighted: { backgroundColor: '#FF6B35' },
  badgeNormal: { backgroundColor: '#FFFFFF' },
  badgeText: { fontSize: 10, lineHeight: 14, fontWeight: '600', color: '#FFFFFF' },
  planHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 },
  planSubtitle: { fontSize: 10, lineHeight: 14, fontWeight: '600', color: '#9CA3AF', letterSpacing: 0.5, marginBottom: 2 },
  planTitle: { fontSize: 20, lineHeight: 28, fontWeight: '700', color: '#111827' },
  planTitleHighlighted: { color: '#FF6B35' },
  priceBlock: { alignItems: 'flex-end' },
  price: { fontSize: 20, lineHeight: 28, fontWeight: '700', color: '#111827' },
  priceHighlighted: { color: '#FF6B35' },
  priceSuffix: { fontSize: 12, lineHeight: 18, fontWeight: '500', color: '#9CA3AF', marginTop: 1 },
  featuresList: { gap: 8 },
  featureRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  featureText: { fontSize: 12, lineHeight: 18, fontWeight: '500', color: '#4B5563' },
  featureTextHighlighted: { color: '#1F2937', fontWeight: '600' },
});

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
      case 'zap': return <Zap size={14} color="#FF6B35" fill="#FF6B35" />;
      case 'shield': return <Shield size={14} color="#2EC4B6" strokeWidth={2} />;
      default: return <Check size={14} color="#4CAF50" strokeWidth={2.5} />;
    }
  };

  return (
    <Pressable
      style={({ pressed }) => [
        pcStyles.planCard,
        highlighted && pcStyles.planCardHighlighted,
        pressed && { opacity: 0.9 },
      ]}
      onPress={onSelect}
    >
      {badge && (
        <View style={[pcStyles.badge, highlighted ? pcStyles.badgeHighlighted : pcStyles.badgeNormal]}>
          <Text style={pcStyles.badgeText}>{badge}</Text>
        </View>
      )}
      <View style={pcStyles.planHeader}>
        <View>
          <Text style={pcStyles.planSubtitle}>{subtitle}</Text>
          <Text style={[pcStyles.planTitle, highlighted && pcStyles.planTitleHighlighted]}>{title}</Text>
        </View>
        <View style={pcStyles.priceBlock}>
          <Text style={[pcStyles.price, highlighted && pcStyles.priceHighlighted]}>{price}</Text>
          {priceSuffix && <Text style={pcStyles.priceSuffix}>{priceSuffix}</Text>}
        </View>
      </View>
      <View style={pcStyles.featuresList}>
        {features.map((f, i) => (
          <View key={i} style={pcStyles.featureRow}>
            {getIcon(f.iconType)}
            <Text style={[pcStyles.featureText, highlighted && pcStyles.featureTextHighlighted]}>{f.text}</Text>
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
  const { completeOnboarding, setMembershipPlan } = useApp();
  const [selectedPlan, setSelectedPlan] = useState<'free' | 'pro' | 'family'>('pro');

  const handleStart = async () => {
    if (selectedPlan === 'free') {
      await setMembershipPlan('free');
      await completeOnboarding();
      navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
      return;
    }
    navigation.navigate('Checkout', { plan: selectedPlan });
  };

  const handleSkip = async () => {
    await setMembershipPlan('free');
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}>
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Pressable onPress={handleSkip}>
          <Text style={styles.skipText}>稍后完善</Text>
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
          解锁无限{'\n'}美食探索
        </Text>
        <Text style={styles.subtitle}>
          解锁 AI 智能点餐、个性化食谱和多设备家庭共享。
        </Text>

        <View style={styles.plans}>
          <PlanCard
            title="免费版"
            subtitle="基础"
            price="¥0"
            priceSuffix="永久免费"
            features={[
              { text: '每日 3 次 AI 点餐建议', iconType: 'check' },
              { text: '基础餐厅搜索', iconType: 'check' },
            ]}
            highlighted={selectedPlan === 'free'}
            onSelect={() => setSelectedPlan('free')}
          />
          <PlanCard
            title="Pro 版"
            subtitle="进阶"
            price="¥9.9"
            priceSuffix="/月"
            badge="最受欢迎"
            features={[
              { text: '无限次 AI 深度点餐分析', iconType: 'zap' },
              { text: '精准过敏原与健康筛选', iconType: 'shield' },
              { text: '离线模式 & 无广告体验', iconType: 'check' },
            ]}
            highlighted={selectedPlan === 'pro'}
            onSelect={() => setSelectedPlan('pro')}
          />
          <PlanCard
            title="家庭版"
            subtitle="共赢"
            price="¥19.9"
            priceSuffix="/月"
            features={[
              { text: '最多 6 位家庭成员共享', iconType: 'check' },
              { text: '自动生成每周家庭菜谱', iconType: 'check' },
            ]}
            highlighted={selectedPlan === 'family'}
            onSelect={() => setSelectedPlan('family')}
          />
        </View>

        <View style={styles.trustBadges}>
          <View style={styles.trustBadge}>
            <Lock size={18} color={theme.colors.muted} strokeWidth={1.8} />
            <Text style={styles.trustLabel}>安全支付</Text>
          </View>
          <View style={styles.trustBadge}>
            <CreditCard size={18} color={theme.colors.muted} strokeWidth={1.8} />
            <Text style={styles.trustLabel}>随时取消</Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          style={({ pressed }) => [styles.upgradeButton, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]}
          onPress={handleStart}
        >
          <Text style={styles.upgradeButtonText}>
            {selectedPlan === 'free'
              ? '继续使用免费版'
              : selectedPlan === 'family'
                ? '升级家庭版 ¥19.9/月'
                : '升级 Pro ¥9.9/月'}
          </Text>
          <ArrowRight size={16} color={theme.colors.surface} strokeWidth={2.5} />
        </Pressable>
        <Pressable onPress={handleSkip} style={({ pressed }) => [styles.skipButton, pressed && { opacity: 0.7 }]}>
          <Text style={styles.skipButtonText}>暂时跳过</Text>
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
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.xs,
  },
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  skipText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '500' },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    marginBottom: t.spacing.lg,
    gap: t.spacing.xs,
  },
  progressTrack: { flex: 1, height: 4, backgroundColor: t.colors.border, borderRadius: 2, overflow: 'hidden' },
  progressBar: { height: '100%', backgroundColor: t.colors.primary, borderRadius: 2 },
  stepLabel: { ...t.typography.micro, fontWeight: '700', color: t.colors.primary },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: t.spacing.md, paddingBottom: t.spacing.lg },
  title: { ...t.typography.display, color: t.colors.foreground, marginBottom: t.spacing.xs },
  subtitle: { ...t.typography.body, color: t.colors.muted, marginBottom: t.spacing.lg },
  plans: { gap: t.spacing.sm, marginBottom: t.spacing.lg },
  planCard: {
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.md,
    borderWidth: 1.5,
    borderColor: 'transparent',
    ...t.shadows.sm,
  },
  planCardHighlighted: {
    backgroundColor: t.colors.primaryLight,
    borderColor: t.colors.primary,
  },
  badge: {
    position: 'absolute',
    top: 0,
    right: 0,
    paddingHorizontal: t.spacing.sm,
    paddingVertical: 4,
    borderTopRightRadius: t.radius.md,
    borderBottomLeftRadius: t.radius.sm,
  },
  badgeHighlighted: { backgroundColor: t.colors.primary },
  badgeNormal: { backgroundColor: t.colors.surface },
  badgeText: { ...t.typography.micro, fontWeight: '700', color: t.colors.surface },
  planHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: t.spacing.sm },
  planSubtitle: { ...t.typography.micro, fontWeight: '700', color: t.colors.subtle, letterSpacing: 0.5, marginBottom: 2 },
  planTitle: { ...t.typography.h1, color: t.colors.foreground },
  planTitleHighlighted: { color: t.colors.primary },
  priceBlock: { alignItems: 'flex-end' },
  price: { ...t.typography.h1, color: t.colors.foreground },
  priceHighlighted: { color: t.colors.primary },
  priceSuffix: { ...t.typography.caption, color: t.colors.subtle, marginTop: 1 },
  featuresList: { gap: t.spacing.xs },
  featureRow: { flexDirection: 'row', alignItems: 'center', gap: t.spacing.xs },
  featureText: { ...t.typography.caption, color: '#4B5563' },
  featureTextHighlighted: { color: t.colors.foreground, fontWeight: '500' },
  trustBadges: { flexDirection: 'row', gap: t.spacing.sm },
  trustBadge: {
    flex: 1,
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.sm,
    alignItems: 'center',
    gap: 4,
    ...t.shadows.sm,
  },
  trustLabel: { ...t.typography.micro, fontWeight: '700', color: t.colors.subtle, letterSpacing: 0.5 },
  footer: {
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.md,
    backgroundColor: t.colors.surface,
    borderTopWidth: 1,
    borderTopColor: t.colors.borderLight,
    gap: t.spacing.xs,
  },
  upgradeButton: {
    backgroundColor: t.colors.primary,
    borderRadius: t.radius.full,
    paddingVertical: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: t.spacing.xs,
  },
  upgradeButtonText: { ...t.typography.body, fontWeight: '700', color: t.colors.surface },
  skipButton: { paddingVertical: t.spacing.xs, alignItems: 'center' },
  skipButtonText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '500' },
});
}
