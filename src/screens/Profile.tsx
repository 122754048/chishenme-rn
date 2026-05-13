import React from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useTranslation } from 'react-i18next';
import { Bell, Compass, CreditCard, Heart, HelpCircle, History as HistoryIcon, LogOut, MapPin, ShieldAlert, Sparkles } from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import { backendApi } from '../api/backend';
import { brand } from '../config/brand';
import { useApp } from '../context/AppContext';
import { SWIPE_CARDS } from '../data/mockData';
import type { RootStackParamList } from '../navigation/types';
import { subscriptionService } from '../services/subscriptions';
import { storage } from '../storage';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { EventName, track } from '../monitoring';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

function ActionTile({
  icon,
  label,
  value,
  onPress,
  styles,
}: {
  icon: React.ReactNode;
  label: string;
  value?: string;
  onPress?: () => void;
  styles: ReturnType<typeof makeStyles>;
}) {
  const disabled = !onPress;
  return (
    <Pressable
      style={({ pressed }) => [styles.tile, disabled && styles.tileDisabled, pressed && !disabled && styles.pressedChrome]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={value ? `${label}, ${value}` : label}
      accessibilityState={{ disabled }}
    >
      <View style={styles.tileIcon}>{icon}</View>
      <Text style={styles.tileLabel}>{label}</Text>
      {value ? (
        <Text style={styles.tileValue} numberOfLines={1}>
          {value}
        </Text>
      ) : null}
    </Pressable>
  );
}

export function Profile() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { t } = useTranslation();
  const {
    favorites,
    history,
    membershipPlan,
    recommendationsLeft,
    resetApp,
    savedAreas,
    selectedCuisines,
    selectedRestrictions,
    setMembershipPlan,
  } = useApp();

  const planTitle =
    membershipPlan === 'family'
      ? t('profile.planTitleFamily')
      : membershipPlan === 'pro'
        ? t('profile.planTitlePro')
        : t('profile.planTitleFree');
  const preferenceValue = String(selectedCuisines.length + selectedRestrictions.length);
  const areaValue =
    savedAreas.home?.query || savedAreas.work?.query
      ? [savedAreas.home?.query, savedAreas.work?.query].filter(Boolean).join(' / ')
      : t('profile.tileAreasFallback');
  const previewImages = SWIPE_CARDS.filter((card) => favorites.includes(card.id)).slice(0, 3);
  const planSummary =
    membershipPlan === 'family'
      ? t('profile.planSummaryFamily')
      : membershipPlan === 'pro'
        ? t('profile.planSummaryPro')
        : t('profile.planSummaryFree');

  const showPaymentInfo = () => {
    Alert.alert(t('profile.alertBillingTitle'), t('profile.alertBillingBody'));
  };

  const showFeedbackInfo = () => {
    Alert.alert(t('profile.alertFeedbackTitle'), t('profile.alertFeedbackBody'));
  };

  const handleRestorePurchase = async () => {
    track(EventName.SubscriptionRestored, { source: 'profile' });
    try {
      const revenueCatUserId = await storage.ensureBackendUserId();
      const result = await subscriptionService.restore(revenueCatUserId);
      if (result.plan !== 'free') {
        await setMembershipPlan(result.plan);
      }
      Alert.alert(t('profile.alertRestoreTitle'), result.message);
    } catch (error) {
      Alert.alert(
        t('profile.alertRestoreTitle'),
        error instanceof Error ? error.message : t('profile.alertRestoreFallback'),
      );
    }
  };

  const handleDeleteAccount = () => {
    Alert.alert(t('profile.alertDeleteTitle'), t('profile.alertDeleteBody'), [
      { text: t('profile.alertDeleteKeep'), style: 'cancel' },
      {
        text: t('profile.alertDeleteConfirm'),
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

  const handleResetExperience = async () => {
    await resetApp();
    navigation.reset({ index: 0, routes: [{ name: 'OnboardingCuisines' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <Text style={styles.logo}>{brand.appName}</Text>
        <Pressable
          style={({ pressed }) => [styles.iconBtn, pressed && styles.pressedChrome]}
          onPress={() => navigation.navigate('History')}
          accessibilityRole="button"
          accessibilityLabel={t('profile.openHistoryA11y')}
          hitSlop={8}
        >
          <Bell size={20} color={theme.colors.foreground} strokeWidth={1.8} />
        </Pressable>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.heroCard}>
          <Text style={styles.heroPlan}>{planTitle}</Text>
          <Text style={styles.heroBody}>{planSummary}</Text>
          <View style={styles.heroStats}>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>
                {recommendationsLeft < 0 ? t('profile.statsPicksOpen') : String(recommendationsLeft)}
              </Text>
              <Text style={styles.statLabel}>{t('profile.statsPicks')}</Text>
            </View>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>{favorites.length}</Text>
              <Text style={styles.statLabel}>{t('profile.statsSaved')}</Text>
            </View>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>{history.length}</Text>
              <Text style={styles.statLabel}>{t('profile.statsHistory')}</Text>
            </View>
          </View>
          {previewImages.length > 0 ? (
            <View style={styles.previewStrip}>
              {previewImages.map((item) => (
                <View key={item.id} style={styles.previewThumb}>
                  <SkeletonImage src={item.image} alt={item.name} />
                </View>
              ))}
            </View>
          ) : null}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('profile.sectionSetup')}</Text>
          <View style={styles.grid}>
            <ActionTile
              icon={<Sparkles size={18} color={theme.colors.primary} strokeWidth={2} />}
              label={t('profile.tileTaste')}
              value={preferenceValue}
              onPress={() => navigation.navigate('OnboardingCuisines')}
              styles={styles}
            />
            <ActionTile
              icon={<MapPin size={18} color={theme.colors.primary} strokeWidth={2} />}
              label={t('profile.tileAreas')}
              value={areaValue}
              onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
              styles={styles}
            />
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('profile.sectionLibrary')}</Text>
          <View style={styles.grid}>
            <ActionTile
              icon={<Heart size={18} color={theme.colors.primary} strokeWidth={2} />}
              label={t('profile.tileSaved')}
              value={`${favorites.length}`}
              onPress={() => navigation.navigate('MainTabs', { screen: 'Favorites' })}
              styles={styles}
            />
            <ActionTile
              icon={<HistoryIcon size={18} color={theme.colors.primary} strokeWidth={2} />}
              label={t('profile.tileHistory')}
              value={`${history.length}`}
              onPress={() => navigation.navigate('History')}
              styles={styles}
            />
            <ActionTile
              icon={<Compass size={18} color={theme.colors.primary} strokeWidth={2} />}
              label={t('profile.tileExplore')}
              onPress={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
              styles={styles}
            />
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('profile.sectionMembership')}</Text>
          <View style={styles.grid}>
            <ActionTile
              icon={<CreditCard size={18} color={theme.colors.primary} strokeWidth={2} />}
              label={t('profile.tilePlan')}
              value={planTitle}
              onPress={() => navigation.navigate('Upgrade')}
              styles={styles}
            />
            <ActionTile
              icon={<Sparkles size={18} color={theme.colors.primary} strokeWidth={2} />}
              label={t('profile.tileRestore')}
              value={t('profile.tileRestoreValue')}
              onPress={handleRestorePurchase}
              styles={styles}
            />
            <ActionTile
              icon={<HelpCircle size={18} color={theme.colors.subtle} strokeWidth={2} />}
              label={t('profile.tileBilling')}
              value={t('profile.tileBillingValue')}
              onPress={showPaymentInfo}
              styles={styles}
            />
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>{t('profile.sectionSupport')}</Text>
          <View style={styles.grid}>
            <ActionTile
              icon={<HelpCircle size={18} color={theme.colors.subtle} strokeWidth={2} />}
              label={t('profile.tileNotes')}
              onPress={showFeedbackInfo}
              styles={styles}
            />
            <ActionTile
              icon={<ShieldAlert size={18} color={theme.colors.error} strokeWidth={2} />}
              label={t('profile.tileDelete')}
              value={t('profile.tileDeleteValue')}
              onPress={handleDeleteAccount}
              styles={styles}
            />
            <ActionTile
              icon={<LogOut size={18} color={theme.colors.subtle} strokeWidth={2} />}
              label={t('profile.tileReset')}
              onPress={handleResetExperience}
              styles={styles}
            />
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.surface },
    topNav: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      height: t.topNavHeight,
      backgroundColor: t.colors.surface,
    },
    logo: { ...t.typography.h1, color: t.colors.foreground },
    iconBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
    scrollView: { flex: 1, backgroundColor: t.colors.background },
    scrollContent: { padding: t.spacing.md, paddingBottom: 112, gap: t.spacing.md },
    heroCard: { backgroundColor: t.colors.primaryLight, borderRadius: t.surface.cardRadius, padding: t.spacing.lg },
    heroPlan: { ...t.typography.display, color: t.colors.foreground },
    heroBody: { ...t.typography.caption, color: t.colors.primaryDark, marginTop: 4 },
    heroStats: { flexDirection: 'row', gap: t.spacing.sm, marginTop: t.spacing.md },
    statCard: {
      flex: 1,
      minHeight: 76,
      borderRadius: t.radius.md,
      backgroundColor: t.colors.surfaceElevated,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 4,
    },
    statValue: { ...t.typography.h1, color: t.colors.foreground },
    statLabel: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600' },
    previewStrip: { flexDirection: 'row', gap: t.spacing.xs, marginTop: t.spacing.md },
    previewThumb: { flex: 1, height: 74, borderRadius: t.radius.md, overflow: 'hidden' },
    section: { gap: t.spacing.sm },
    sectionTitle: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '700' },
    grid: { flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.sm },
    tile: {
      width: '48%',
      minHeight: 108,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surfaceElevated,
      padding: 14,
      gap: 10,
    },
    tileDisabled: { opacity: 0.5 },
    tileIcon: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.primaryLight,
    },
    tileLabel: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    tileValue: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600' },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
  });
}
