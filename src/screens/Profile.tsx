import React, { useMemo } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import {
  Bell,
  ChevronRight,
  ClipboardList,
  CreditCard,
  Heart,
  HelpCircle,
  LogOut,
  Settings,
  ShieldAlert,
  Sparkles,
  Users,
} from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { useApp } from '../context/AppContext';
import { backendApi } from '../api/backend';
import { storage } from '../storage';
import { subscriptionService } from '../services/subscriptions';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

interface MenuRowProps {
  icon: React.ReactNode;
  iconBg: string;
  label: string;
  value?: string;
  onPress?: () => void;
}

interface SummaryCardProps {
  eyebrow: string;
  value: string;
  description: string;
}

const rowStyles = StyleSheet.create({
  menuRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
    gap: 12,
  },
  menuIconWrap: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuLabel: {
    flex: 1,
    fontSize: 14,
    lineHeight: 22,
    fontWeight: '600',
    color: '#111827',
  },
  menuRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  menuValue: {
    fontSize: 12,
    lineHeight: 18,
    fontWeight: '500',
    color: '#6B7280',
  },
  menuRowDisabled: { opacity: 0.55 },
});

function MenuRow({ icon, iconBg, label, value, onPress }: MenuRowProps) {
  const disabled = !onPress;

  return (
    <Pressable
      style={({ pressed }) => [
        rowStyles.menuRow,
        disabled && rowStyles.menuRowDisabled,
        pressed && !disabled && { backgroundColor: '#F9FAFB' },
      ]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={value ? `${label}，${value}` : label}
      accessibilityState={{ disabled }}
    >
      <View style={[rowStyles.menuIconWrap, { backgroundColor: iconBg }]}>{icon}</View>
      <Text style={rowStyles.menuLabel}>{label}</Text>
      <View style={rowStyles.menuRight}>
        {value ? <Text style={rowStyles.menuValue}>{value}</Text> : null}
        {!disabled ? <ChevronRight size={16} color="#9CA3AF" strokeWidth={1.5} /> : null}
      </View>
    </Pressable>
  );
}

const summaryStyles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    borderRadius: 14,
    padding: 14,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 6,
    elevation: 2,
  },
  eyebrow: {
    fontSize: 11,
    lineHeight: 16,
    fontWeight: '700',
    color: '#9CA3AF',
    marginBottom: 4,
    textTransform: 'uppercase',
  },
  value: {
    fontSize: 20,
    lineHeight: 28,
    fontWeight: '800',
    color: '#111827',
    marginBottom: 4,
  },
  description: {
    fontSize: 12,
    lineHeight: 18,
    color: '#6B7280',
  },
});

function SummaryCard({ eyebrow, value, description }: SummaryCardProps) {
  return (
    <View style={summaryStyles.card}>
      <Text style={summaryStyles.eyebrow}>{eyebrow}</Text>
      <Text style={summaryStyles.value}>{value}</Text>
      <Text style={summaryStyles.description}>{description}</Text>
    </View>
  );
}

function getPlanTitle(plan: 'free' | 'pro' | 'family') {
  if (plan === 'pro') return 'Pro 会员';
  if (plan === 'family') return 'Family 会员';
  return '基础版';
}

function getPlanDescription(plan: 'free' | 'pro' | 'family') {
  if (plan === 'pro') {
    return '更深的推荐解释、更多备选方案，以及更细的筛选维度。';
  }
  if (plan === 'family') {
    return '更适合情侣和家庭一起做决定，减少多人晚餐讨论成本。';
  }
  return '先用基础版验证口味命中，再决定是否升级更强的决策能力。';
}

export function Profile() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const {
    favorites,
    history,
    membershipPlan,
    recommendationsLeft,
    resetApp,
    selectedCuisines,
    selectedRestrictions,
    setMembershipPlan,
  } = useApp();

  const planTitle = getPlanTitle(membershipPlan);
  const planDescription = getPlanDescription(membershipPlan);
  const tasteCount = selectedCuisines.length + selectedRestrictions.length;
  const latestDecision = history[0];
  const decisionSummary = useMemo(() => {
    if (!latestDecision) {
      return '还没有留下决策记录，今天先做一次不纠结的选择。';
    }
    return `${latestDecision.title} · ${latestDecision.time}`;
  }, [latestDecision]);

  const remainingDecisionText =
    recommendationsLeft < 0 ? '不限次数' : `今日还剩 ${recommendationsLeft} 次`;
  const preferenceValue = tasteCount > 0 ? `已配置 ${tasteCount} 项` : '去完善';
  const familyValue = membershipPlan === 'family' ? '已开启' : '更适合多人一起吃饭';

  const showPaymentInfo = () => {
    Alert.alert(
      '支付方式',
      'iOS 会员订阅通过 Apple ID 内购完成。购买、续订和取消都以 Apple 订阅设置为准，App 内会同步权益状态。'
    );
  };

  const showFeedbackInfo = () => {
    Alert.alert(
      '帮助与反馈',
      '当前仓库已经预留商业上线所需的支持入口和账号删除能力。正式上架前，还需要在 App Store Connect 配置支持 URL 和隐私政策 URL。'
    );
  };

  const handleRestorePurchase = async () => {
    try {
      const revenueCatUserId = await storage.ensureBackendUserId();
      const result = await subscriptionService.restore(revenueCatUserId ?? undefined);
      if (result.plan !== 'free') {
        await setMembershipPlan(result.plan);
      }
      Alert.alert('恢复购买', result.message);
    } catch (error) {
      Alert.alert(
        '恢复购买',
        error instanceof Error ? error.message : '恢复购买失败，请稍后再试。'
      );
    }
  };

  const handleDeleteAccount = () => {
    Alert.alert(
      '删除账号',
      '删除后会清空本机资料、偏好、收藏、历史记录和会员缓存。此操作不会自动取消 Apple ID 订阅，如需停止续费，请前往 Apple ID 订阅设置取消。',
      [
        { text: '取消', style: 'cancel' },
        {
          text: '确认删除',
          style: 'destructive',
          onPress: async () => {
            try {
              const token = backendApi.isEnabled() ? await backendApi.ensureToken() : null;
              if (token) {
                await backendApi.deleteAccount(token);
              }
            } catch (error) {
              console.warn('Backend account deletion failed:', error);
            } finally {
              await resetApp();
              navigation.reset({ index: 0, routes: [{ name: 'OnboardingCuisines' }] });
            }
          },
        },
      ]
    );
  };

  const handleResetExperience = async () => {
    await resetApp();
    navigation.reset({ index: 0, routes: [{ name: 'OnboardingCuisines' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <Text style={styles.logo}>ChiShenMe</Text>
        <Pressable
          style={({ pressed }) => [styles.bellBtn, pressed && { opacity: 0.7 }]}
          onPress={() => navigation.navigate('History')}
          accessibilityRole="button"
          accessibilityLabel="查看决策记录"
          hitSlop={8}
        >
          <Bell size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        <View style={styles.heroCard}>
          <View style={styles.heroHeader}>
            <View style={styles.heroAvatar}>
              <Text style={styles.heroAvatarText}>CS</Text>
            </View>
            <View style={styles.heroCopy}>
              <Text style={styles.heroTitle}>我的决策档案</Text>
              <Text style={styles.heroSubtitle}>{decisionSummary}</Text>
            </View>
          </View>

          <View style={styles.planBadge}>
            <Sparkles size={14} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.planBadgeText}>{planTitle}</Text>
          </View>

          <Text style={styles.heroBody}>{planDescription}</Text>
        </View>

        <View style={styles.summaryRow}>
          <SummaryCard
            eyebrow="今日状态"
            value={remainingDecisionText}
            description="帮助你判断今天还需不需要升级到更强的决策能力。"
          />
          <SummaryCard
            eyebrow="偏好完整度"
            value={tasteCount > 0 ? `${tasteCount} 项` : '待完善'}
            description="口味和忌口越完整，首页推荐越像真正懂你的选择。"
          />
        </View>

        <View style={styles.summaryRow}>
          <SummaryCard
            eyebrow="已收藏"
            value={`${favorites.length} 道`}
            description="把犹豫过但还没决定的菜先存起来，留给更合适的时机。"
          />
          <SummaryCard
            eyebrow="已做决定"
            value={`${history.length} 次`}
            description="记录真实选择，逐步训练出更符合你习惯的推荐。"
          />
        </View>

        <View style={styles.membershipCards}>
          <Pressable
            style={({ pressed }) => [
              styles.membershipCard,
              styles.membershipPrimary,
              pressed && { opacity: 0.92 },
            ]}
            onPress={() => navigation.navigate('Upgrade')}
            accessibilityRole="button"
            accessibilityLabel={`当前方案，${planTitle}，管理订阅权益`}
          >
            <Text style={styles.membershipEyebrow}>会员权益</Text>
            <Text style={styles.membershipTitle}>{planTitle}</Text>
            <Text style={styles.membershipBody}>{planDescription}</Text>
            <View style={styles.membershipAction}>
              <Text style={styles.membershipActionText}>管理订阅</Text>
            </View>
          </Pressable>

          <Pressable
            style={({ pressed }) => [
              styles.membershipCard,
              styles.membershipSecondary,
              pressed && { opacity: 0.92 },
            ]}
            onPress={() => navigation.navigate('Upgrade')}
            accessibilityRole="button"
            accessibilityLabel={`多人决策，${familyValue}`}
          >
            <View style={styles.familyHeader}>
              <Users size={16} color={theme.colors.brandWarmDark} strokeWidth={2} />
              <Text style={styles.familyTitle}>多人一起吃，也能更快定下来</Text>
            </View>
            <Text style={styles.familyBody}>
              Family 更适合情侣、室友和家庭，把多人口味融合成更容易达成一致的结果。
            </Text>
            <Text style={styles.familyFoot}>{familyValue}</Text>
          </Pressable>
        </View>

        <View style={styles.menuCard}>
          <MenuRow
            icon={<Heart size={15} color={theme.colors.error} strokeWidth={2} />}
            iconBg={theme.colors.errorLight}
            label="收藏夹"
            value={`${favorites.length} 道`}
            onPress={() => navigation.navigate('MainTabs', { screen: 'Favorites' })}
          />
          <MenuRow
            icon={<ClipboardList size={15} color={theme.colors.blue} strokeWidth={2} />}
            iconBg="#F0F5FF"
            label="决策记录"
            value={history.length > 0 ? `${history.length} 条` : '去积累'}
            onPress={() => navigation.navigate('History')}
          />
          <MenuRow
            icon={<Settings size={15} color={theme.colors.muted} strokeWidth={2} />}
            iconBg={theme.colors.borderLight}
            label="口味档案"
            value={preferenceValue}
            onPress={() => navigation.navigate('OnboardingCuisines')}
          />
        </View>

        <View style={styles.menuCard}>
          <MenuRow
            icon={<CreditCard size={15} color={theme.colors.primary} strokeWidth={2} />}
            iconBg={theme.colors.primaryLight}
            label="支付方式"
            value="Apple IAP"
            onPress={showPaymentInfo}
          />
          <MenuRow
            icon={<Sparkles size={15} color={theme.colors.primary} strokeWidth={2} />}
            iconBg={theme.colors.primaryLight}
            label="恢复购买"
            value="Apple ID"
            onPress={handleRestorePurchase}
          />
          <MenuRow
            icon={<HelpCircle size={15} color={theme.colors.warning} strokeWidth={2} />}
            iconBg={theme.colors.warningLight}
            label="帮助与反馈"
            value="上线前支持项"
            onPress={showFeedbackInfo}
          />
        </View>

        <View style={styles.menuCard}>
          <MenuRow
            icon={<ShieldAlert size={15} color={theme.colors.error} strokeWidth={2} />}
            iconBg={theme.colors.errorLight}
            label="删除账号"
            value="不可撤销"
            onPress={handleDeleteAccount}
          />
          <MenuRow
            icon={<LogOut size={15} color={theme.colors.subtle} strokeWidth={2} />}
            iconBg={theme.colors.borderLight}
            label="重新开始体验"
            value="清空本地记录"
            onPress={handleResetExperience}
          />
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    topNav: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      height: t.topNavHeight,
      backgroundColor: t.colors.surface,
      borderBottomWidth: 1,
      borderBottomColor: t.colors.borderLight,
    },
    logo: { ...t.typography.h1, color: t.colors.foreground },
    bellBtn: {
      width: 40,
      height: 40,
      alignItems: 'center',
      justifyContent: 'center',
    },
    scrollView: { flex: 1 },
    heroCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.lg,
      marginHorizontal: t.spacing.md,
      marginTop: t.spacing.md,
      padding: t.spacing.lg,
      ...t.shadows.md,
    },
    heroHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: t.spacing.sm,
      marginBottom: t.spacing.sm,
    },
    heroAvatar: {
      width: 52,
      height: 52,
      borderRadius: 26,
      backgroundColor: t.colors.primaryLight,
      alignItems: 'center',
      justifyContent: 'center',
    },
    heroAvatarText: {
      ...t.typography.h2,
      color: t.colors.primaryDark,
      fontWeight: '800',
    },
    heroCopy: { flex: 1 },
    heroTitle: {
      ...t.typography.h1,
      color: t.colors.foreground,
      marginBottom: 2,
    },
    heroSubtitle: {
      ...t.typography.caption,
      color: t.colors.subtle,
    },
    planBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      alignSelf: 'flex-start',
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.radius.full,
      paddingHorizontal: 10,
      paddingVertical: 6,
      marginBottom: t.spacing.sm,
    },
    planBadgeText: {
      ...t.typography.caption,
      color: t.colors.primaryDark,
      fontWeight: '700',
    },
    heroBody: {
      ...t.typography.body,
      color: t.colors.muted,
      lineHeight: 22,
    },
    summaryRow: {
      flexDirection: 'row',
      gap: t.spacing.sm,
      marginHorizontal: t.spacing.md,
      marginTop: t.spacing.sm,
    },
    membershipCards: {
      paddingHorizontal: t.spacing.md,
      gap: t.spacing.sm,
      marginTop: t.spacing.md,
      marginBottom: t.spacing.sm,
    },
    membershipCard: {
      borderRadius: t.radius.lg,
      padding: t.spacing.md,
      overflow: 'hidden',
    },
    membershipPrimary: { backgroundColor: t.colors.primary },
    membershipSecondary: { backgroundColor: t.colors.brandWarm },
    membershipEyebrow: {
      ...t.typography.micro,
      color: 'rgba(255,255,255,0.72)',
      marginBottom: 4,
      fontWeight: '700',
      letterSpacing: 0.3,
    },
    membershipTitle: {
      ...t.typography.h1,
      color: t.colors.surface,
      marginBottom: 6,
    },
    membershipBody: {
      ...t.typography.caption,
      color: 'rgba(255,255,255,0.88)',
      lineHeight: 18,
      marginBottom: t.spacing.sm,
      paddingRight: 36,
    },
    membershipAction: {
      backgroundColor: t.colors.surface,
      paddingHorizontal: t.spacing.md,
      paddingVertical: 6,
      borderRadius: t.radius.full,
      alignSelf: 'flex-start',
    },
    membershipActionText: {
      ...t.typography.caption,
      color: t.colors.primary,
      fontWeight: '700',
    },
    familyHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      marginBottom: 8,
    },
    familyTitle: {
      ...t.typography.body,
      color: t.colors.brandWarmDark,
      fontWeight: '700',
      flex: 1,
    },
    familyBody: {
      ...t.typography.caption,
      color: 'rgba(0,0,0,0.68)',
      lineHeight: 18,
      marginBottom: t.spacing.sm,
    },
    familyFoot: {
      ...t.typography.caption,
      color: t.colors.brandWarmDark,
      fontWeight: '700',
    },
    menuCard: {
      backgroundColor: t.colors.surface,
      marginHorizontal: t.spacing.md,
      borderRadius: t.radius.lg,
      marginBottom: t.spacing.sm,
      overflow: 'hidden',
      ...t.shadows.sm,
    },
    bottomPadding: { height: t.spacing.lg },
  });
}
