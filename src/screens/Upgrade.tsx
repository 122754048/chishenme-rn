import React, { useState } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, ArrowRight, Check, Shield, Sparkles, Users } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

function ValuePlanCard({
  title,
  subtitle,
  price,
  badge,
  selected,
  features,
  icon,
  onPress,
}: {
  title: string;
  subtitle: string;
  price: string;
  badge?: string;
  selected: boolean;
  features: string[];
  icon: React.ReactNode;
  onPress: () => void;
}) {
  return (
    <Pressable style={({ pressed }) => [valueStyles.card, selected && valueStyles.cardSelected, pressed && { opacity: 0.92 }]} onPress={onPress}>
      {badge ? (
        <View style={valueStyles.badge}>
          <Text style={valueStyles.badgeText}>{badge}</Text>
        </View>
      ) : null}
      <View style={valueStyles.header}>
        <View style={valueStyles.iconWrap}>{icon}</View>
        <View style={valueStyles.titleWrap}>
          <Text style={valueStyles.title}>{title}</Text>
          <Text style={valueStyles.subtitle}>{subtitle}</Text>
        </View>
        <Text style={valueStyles.price}>{price}</Text>
      </View>
      <View style={valueStyles.features}>
        {features.map((feature) => (
          <View key={feature} style={valueStyles.featureRow}>
            <Check size={14} color="#FF6B35" strokeWidth={2.5} />
            <Text style={valueStyles.featureText}>{feature}</Text>
          </View>
        ))}
      </View>
    </Pressable>
  );
}

const valueStyles = StyleSheet.create({
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1.5,
    borderColor: '#F3F4F6',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 4,
    elevation: 2,
  },
  cardSelected: {
    borderColor: '#FF6B35',
    backgroundColor: '#FFF4EE',
  },
  badge: {
    position: 'absolute',
    top: 0,
    right: 0,
    backgroundColor: '#FF6B35',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderTopRightRadius: 16,
    borderBottomLeftRadius: 10,
  },
  badgeText: {
    fontSize: 10,
    lineHeight: 14,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 12,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#FFF0E8',
  },
  titleWrap: { flex: 1 },
  title: { fontSize: 18, lineHeight: 26, fontWeight: '700', color: '#111827' },
  subtitle: { fontSize: 12, lineHeight: 18, color: '#6B7280', marginTop: 2 },
  price: { fontSize: 18, lineHeight: 26, fontWeight: '700', color: '#111827' },
  features: { gap: 8 },
  featureRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  featureText: { fontSize: 13, lineHeight: 18, color: '#374151', flex: 1 },
});

export function Upgrade() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const [selectedPlan, setSelectedPlan] = useState<'pro' | 'family'>('pro');

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} style={styles.backBtn}>
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.headerTitle}>升级你的决策能力</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>不是买次数，而是买更好的结果</Text>
          <Text style={styles.heroTitle}>少纠结，少试错，更快决定今天吃什么</Text>
          <Text style={styles.heroBody}>
            升级后你会得到更强的推荐解释、更多备选方案、更细的筛选维度，以及适合多人用餐的协同决策能力。
          </Text>
        </View>

        <View style={styles.valueStrip}>
          <View style={styles.valueItem}>
            <Sparkles size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.valueText}>为什么推荐你一眼能懂</Text>
          </View>
          <View style={styles.valueItem}>
            <Shield size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.valueText}>忌口和健康风险看得更清楚</Text>
          </View>
          <View style={styles.valueItem}>
            <Users size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.valueText}>多人吃饭也能更快达成一致</Text>
          </View>
        </View>

        <View style={styles.planList}>
          <ValuePlanCard
            title="Pro"
            subtitle="给自己一个更快、更准的决策助手"
            price="¥9.9/月"
            badge="最适合日常使用"
            selected={selectedPlan === 'pro'}
            icon={<Sparkles size={18} color="#FF6B35" strokeWidth={2.2} />}
            features={[
              '不限次查看更精准的推荐解释',
              '解锁更多备选方案与对比理由',
              '按场景、预算、口味更细地筛选',
            ]}
            onPress={() => setSelectedPlan('pro')}
          />

          <ValuePlanCard
            title="Family"
            subtitle="把晚餐分歧，变成可以协商的结果"
            price="¥19.9/月"
            selected={selectedPlan === 'family'}
            icon={<Users size={18} color="#FF6B35" strokeWidth={2.2} />}
            features={[
              '融合多人偏好，减少家庭晚餐分歧',
              '共享收藏和已做过的决策',
              '更适合情侣、室友和家庭共用',
            ]}
            onPress={() => setSelectedPlan('family')}
          />
        </View>

        <Text style={styles.subscriptionNote}>
          订阅通过 Apple ID 自动续订，可随时在 Apple ID 的订阅设置中取消。已购买用户可在下一步恢复购买。
        </Text>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={styles.upgradeButton} onPress={() => navigation.navigate('Checkout', { plan: selectedPlan })}>
          <Text style={styles.upgradeButtonText}>{selectedPlan === 'family' ? '继续升级 Family' : '继续升级 Pro'}</Text>
          <ArrowRight size={16} color={theme.colors.surface} strokeWidth={2.5} />
        </Pressable>
        <Pressable style={styles.secondaryButton} onPress={() => navigation.goBack()}>
          <Text style={styles.secondaryButtonText}>继续使用基础版</Text>
        </Pressable>
        <Pressable style={styles.restoreButton} onPress={() => navigation.navigate('Checkout', { plan: selectedPlan })}>
          <Text style={styles.restoreButtonText}>已订阅？恢复购买</Text>
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
      height: t.topNavHeight,
      backgroundColor: t.colors.surface,
      borderBottomWidth: 1,
      borderBottomColor: t.colors.borderLight,
    },
    backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
    headerTitle: { ...t.typography.h2, color: t.colors.foreground },
    scrollView: { flex: 1 },
    scrollContent: { padding: t.spacing.md, paddingBottom: 120, gap: t.spacing.md },
    heroCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.lg,
      padding: t.spacing.lg,
      ...t.shadows.md,
    },
    heroEyebrow: { ...t.typography.caption, color: t.colors.primary, fontWeight: '700', marginBottom: 6 },
    heroTitle: { ...t.typography.display, color: t.colors.foreground, marginBottom: 8 },
    heroBody: { ...t.typography.body, color: t.colors.muted, lineHeight: 22 },
    valueStrip: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      padding: t.spacing.md,
      gap: t.spacing.sm,
      ...t.shadows.sm,
    },
    valueItem: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    valueText: { ...t.typography.body, color: t.colors.foreground, flex: 1 },
    planList: { gap: t.spacing.sm },
    subscriptionNote: { ...t.typography.caption, color: t.colors.subtle, lineHeight: 18 },
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
      height: 48,
      alignItems: 'center',
      justifyContent: 'center',
      flexDirection: 'row',
      gap: 6,
    },
    upgradeButtonText: { ...t.typography.body, color: t.colors.surface, fontWeight: '700' },
    secondaryButton: { height: 40, alignItems: 'center', justifyContent: 'center' },
    secondaryButtonText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600' },
    restoreButton: { height: 40, alignItems: 'center', justifyContent: 'center' },
    restoreButtonText: { ...t.typography.caption, color: t.colors.primary, fontWeight: '700' },
  });
}
