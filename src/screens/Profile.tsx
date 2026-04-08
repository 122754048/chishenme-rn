import React from 'react';
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
import { Bell, Heart, Clock, Settings, CreditCard, HelpCircle, LogOut, ChevronRight, Star } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { SkeletonImage } from '../components/SkeletonImage';
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

const mrStyles = StyleSheet.create({
  menuRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#F9FAFB',
    gap: 12,
  },
  menuIconWrap: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  menuLabel: { flex: 1, fontSize: 14, lineHeight: 22, fontWeight: '500', color: '#111827' },
  menuRight: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  menuValue: { fontSize: 12, lineHeight: 18, fontWeight: '500', color: '#9CA3AF' },
  menuRowDisabled: { opacity: 0.55 },
});

function MenuRow({ icon, iconBg, label, value, onPress }: MenuRowProps) {
  const disabled = !onPress;
  return (
    <Pressable
      style={({ pressed }) => [mrStyles.menuRow, disabled && mrStyles.menuRowDisabled, pressed && !disabled && { backgroundColor: '#F3F4F6' }]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={value ? `${label}，${value}` : label}
      accessibilityState={{ disabled }}
    >
      <View style={[mrStyles.menuIconWrap, { backgroundColor: iconBg }]}>
        {icon}
      </View>
      <Text style={mrStyles.menuLabel}>{label}</Text>
      <View style={mrStyles.menuRight}>
        {value && <Text style={mrStyles.menuValue}>{value}</Text>}
        {!disabled && <ChevronRight size={16} color="#9CA3AF" strokeWidth={1.5} />}
      </View>
    </Pressable>
  );
}

export function Profile() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { favorites, resetApp, membershipPlan, selectedCuisines, selectedRestrictions, setMembershipPlan } = useApp();
  const planTitle = membershipPlan === 'pro' ? 'PRO 计划' : membershipPlan === 'family' ? '家庭版计划' : '免费版';
  const planDescription = membershipPlan === 'pro'
    ? '享受无限智能推荐和优先预订服务。'
    : membershipPlan === 'family'
      ? '已启用家庭共享与多人口味协同推荐。'
    : '你正在使用免费功能，升级可解锁更多能力。';
  const familyTitle = membershipPlan === 'family' ? '还剩 4 个名额' : '家庭共享';
  const familyDesc = membershipPlan === 'family'
    ? '邀请家人一起分享你的美食记录和口味偏好。'
    : '升级家庭版后，可邀请家人共享口味偏好和推荐记录。';
  const familyAction = membershipPlan === 'family' ? '立即邀请' : '了解家庭版';
  const preferenceCount = selectedCuisines.length + selectedRestrictions.length;
  const preferenceValue = preferenceCount > 0 ? `已选 ${preferenceCount} 项` : '去完善';
  const showPaymentInfo = () => {
    Alert.alert('支付方式', 'iOS 会员订阅将通过 Apple ID 内购完成，支付成功后会员会自动生效。');
  };
  const showFeedbackInfo = () => {
    Alert.alert('帮助与反馈', '当前版本处于上线前体验优化阶段，如遇问题请记录截图和操作步骤。');
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
      Alert.alert('恢复购买', error instanceof Error ? error.message : '恢复购买失败，请稍后重试。');
    }
  };
  const handleDeleteAccount = () => {
    Alert.alert('删除账号', '删除后会清除本机资料、偏好、收藏、历史记录和会员缓存。此操作不会自动取消 Apple ID 订阅，如需停止续费，请在 Apple ID 的订阅设置中取消。此操作不可撤销。', [
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
    ]);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav — Brand mode */}
      <View style={styles.topNav}>
        <Text style={styles.logo}>🍽️ ChiShenMe</Text>
        <Pressable
          style={({ pressed }) => [styles.bellBtn, pressed && { opacity: 0.7 }]}
          onPress={() => navigation.navigate('History')}
          accessibilityRole="button"
          accessibilityLabel="查看浏览记录"
          hitSlop={8}
        >
          <Bell size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Profile Header */}
        <View style={styles.profileHeader}>
          <View style={styles.avatarWrap}>
            <View style={styles.avatarImage}>
              <SkeletonImage
                src="https://images.unsplash.com/photo-1603086360919-8b8eacad64bc?w=200"
                alt="Alex Chen"
              />
            </View>
            <View style={styles.avatarBadge}>
              <Star size={10} color={theme.colors.star} fill={theme.colors.star} />
            </View>
          </View>
          <View style={styles.profileInfo}>
            <Text style={styles.profileName}>Alex Chen</Text>
            <Text style={styles.profileJoined}>2023年9月加入</Text>
            <View style={styles.levelBadge}>
              <Text style={styles.levelBadgeText}>吃货等级 Lv.4</Text>
            </View>
          </View>
        </View>

        {/* Membership Cards */}
        <View style={styles.membershipCards}>
          <Pressable
            style={({ pressed }) => [styles.membershipCard, styles.proCard, pressed && { opacity: 0.9 }]}
            onPress={() => navigation.navigate('Upgrade')}
            accessibilityRole="button"
            accessibilityLabel={`会员状态，${planTitle}，管理套餐`}
          >
            <View>
              <Text style={styles.membershipLabel}>会员状态</Text>
              <Text style={styles.membershipTitle}>{planTitle}</Text>
              <Text style={styles.membershipDesc}>
                {planDescription}
              </Text>
              <View style={styles.manageBtn}>
                <Text style={styles.manageBtnText}>管理套餐</Text>
              </View>
            </View>
          </Pressable>

          <Pressable
            style={({ pressed }) => [styles.membershipCard, styles.familyCard, pressed && { opacity: 0.9 }]}
            onPress={() => navigation.navigate('Upgrade')}
            accessibilityRole="button"
            accessibilityLabel={`${familyTitle}，${familyAction}`}
          >
            <View>
              <Text style={[styles.membershipLabel, { color: 'rgba(0,0,0,0.4)' }]}>家庭共享</Text>
              <Text style={[styles.membershipTitle, { color: 'rgba(0,0,0,0.75)' }]}>{familyTitle}</Text>
              <Text style={[styles.membershipDesc, { color: 'rgba(0,0,0,0.6)' }]}>
                {familyDesc}
              </Text>
              <View style={[styles.manageBtn, { backgroundColor: theme.colors.brandWarmDark }]}>
                <Text style={[styles.manageBtnText, { color: theme.colors.surface }]}>{familyAction}</Text>
              </View>
            </View>
          </Pressable>
        </View>

        {/* Menu Lists */}
        <View style={styles.menuCard}>
          <MenuRow
            icon={<Heart size={15} color={theme.colors.error} strokeWidth={2} />}
            iconBg={theme.colors.errorLight}
            label="收藏"
            value={`${favorites.length} 道菜`}
            onPress={() => navigation.navigate('MainTabs', { screen: 'Favorites' })}
          />
          <MenuRow
            icon={<Clock size={15} color={theme.colors.blue} strokeWidth={2} />}
            iconBg="#F0F5FF"
            label="浏览记录"
            onPress={() => navigation.navigate('History')}
          />
          <MenuRow
            icon={<Settings size={15} color={theme.colors.muted} strokeWidth={2} />}
            iconBg={theme.colors.borderLight}
            label="偏好设置"
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
            icon={<CreditCard size={15} color={theme.colors.primary} strokeWidth={2} />}
            iconBg={theme.colors.primaryLight}
            label="恢复购买"
            value="Apple ID"
            onPress={handleRestorePurchase}
          />
          <MenuRow
            icon={<HelpCircle size={15} color={theme.colors.warning} strokeWidth={2} />}
            iconBg={theme.colors.warningLight}
            label="帮助与反馈"
            onPress={showFeedbackInfo}
          />
        </View>

        <Pressable
          style={({ pressed }) => [styles.deleteAccountBtn, pressed && { opacity: 0.85 }]}
          onPress={handleDeleteAccount}
          accessibilityRole="button"
          accessibilityLabel="删除账号"
        >
          <Text style={styles.deleteAccountText}>删除账号</Text>
        </Pressable>

        <Pressable
          style={({ pressed }) => [styles.signOutBtn, pressed && { opacity: 0.85 }]}
          onPress={async () => {
            await resetApp();
            navigation.reset({ index: 0, routes: [{ name: 'OnboardingCuisines' }] });
          }}
        >
          <LogOut size={16} color={theme.colors.error} strokeWidth={2} />
          <Text style={styles.signOutText}>退出登录（保留今日免费额度）</Text>
        </Pressable>

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
  bellBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  scrollView: { flex: 1 },
  profileHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: t.spacing.lg,
    paddingTop: t.spacing.lg,
    paddingBottom: t.spacing.md,
    gap: t.spacing.md,
  },
  avatarWrap: { position: 'relative' },
  avatarImage: { width: 64, height: 64, borderRadius: t.radius.full, overflow: 'hidden' },
  avatarBadge: {
    position: 'absolute',
    bottom: 0,
    right: -2,
    width: 20,
    height: 20,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    ...t.shadows.sm,
  },
  profileInfo: { flex: 1 },
  profileName: { ...t.typography.h1, color: t.colors.foreground, marginBottom: 2 },
  profileJoined: { ...t.typography.caption, color: t.colors.subtle, marginBottom: 6 },
  levelBadge: {
    backgroundColor: '#FFDEBA',
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 3,
    borderRadius: t.radius.full,
    alignSelf: 'flex-start',
  },
  levelBadgeText: {
    ...t.typography.micro,
    fontWeight: '700',
    color: t.colors.brandWarmDark,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  membershipCards: { paddingHorizontal: t.spacing.md, gap: t.spacing.sm, marginBottom: t.spacing.md },
  membershipCard: {
    borderRadius: t.radius.lg,
    padding: t.spacing.md,
    overflow: 'hidden',
  },
  proCard: { backgroundColor: t.colors.primary },
  familyCard: { backgroundColor: t.colors.brandWarm },
  membershipLabel: {
    ...t.typography.micro,
    color: 'rgba(255,255,255,0.7)',
    letterSpacing: 1,
    marginBottom: 2,
  },
  membershipTitle: { ...t.typography.h1, color: t.colors.surface, marginBottom: 4 },
  membershipDesc: {
    ...t.typography.caption,
    color: 'rgba(255,255,255,0.8)',
    marginBottom: t.spacing.sm,
    paddingRight: 40,
  },
  manageBtn: {
    backgroundColor: t.colors.surface,
    paddingHorizontal: t.spacing.md,
    paddingVertical: 6,
    borderRadius: t.radius.full,
    alignSelf: 'flex-start',
  },
  manageBtnText: { ...t.typography.caption, fontWeight: '700', color: t.colors.primary },
  menuCard: {
    backgroundColor: t.colors.surface,
    marginHorizontal: t.spacing.md,
    borderRadius: t.radius.lg,
    marginBottom: t.spacing.sm,
    overflow: 'hidden',
    ...t.shadows.sm,
  },
  menuRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
    gap: t.spacing.sm,
  },
  menuIconWrap: {
    width: 32,
    height: 32,
    borderRadius: t.radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuLabel: { ...t.typography.body, fontWeight: '500', color: t.colors.foreground, flex: 1 },
  menuRight: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  menuValue: { ...t.typography.caption, color: t.colors.subtle },
  signOutBtn: {
    backgroundColor: t.colors.surface,
    marginHorizontal: t.spacing.md,
    borderRadius: t.radius.lg,
    paddingVertical: t.spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: t.spacing.xs,
    ...t.shadows.sm,
  },
  signOutText: { ...t.typography.body, fontWeight: '700', color: t.colors.error },
  deleteAccountBtn: {
    backgroundColor: t.colors.surface,
    marginHorizontal: t.spacing.md,
    borderRadius: t.radius.lg,
    paddingVertical: t.spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: t.spacing.sm,
    borderWidth: 1,
    borderColor: t.colors.errorLight,
  },
  deleteAccountText: { ...t.typography.body, fontWeight: '700', color: t.colors.error },
  bottomPadding: { height: t.spacing.lg },
});
}
