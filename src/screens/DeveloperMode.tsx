import React, { useMemo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { CheckCircle2, Clock3, Crown, Shield, Sparkles, X } from 'lucide-react-native';
import { useApp } from '../context/AppContext';
import type { RootStackParamList } from '../navigation/types';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

function formatRemaining(expiresAt: number | null) {
  if (!expiresAt) return null;
  const remainingMs = expiresAt - Date.now();
  if (remainingMs <= 0) return 'Expires now';
  const minutes = Math.floor(remainingMs / 60000);
  const seconds = Math.floor((remainingMs % 60000) / 1000);
  if (minutes <= 0) return `${seconds}s left`;
  return `${minutes}m ${seconds}s left`;
}

function QuickAction({
  icon,
  title,
  subtitle,
  onPress,
  styles,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  onPress: () => void;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <Pressable style={({ pressed }) => [styles.actionCard, pressed && styles.pressed]} onPress={onPress}>
      <View style={styles.actionIcon}>{icon}</View>
      <View style={styles.actionCopy}>
        <Text style={styles.actionTitle}>{title}</Text>
        <Text style={styles.actionSubtitle}>{subtitle}</Text>
      </View>
    </Pressable>
  );
}

export function DeveloperMode() {
  const navigation = useNavigation<NavProp>();
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const { membershipPlan, activateDeveloperMembership, clearDeveloperMembershipOverride, developerOverrideExpiresAt } = useApp();

  const remainingLabel = useMemo(() => formatRemaining(developerOverrideExpiresAt), [developerOverrideExpiresAt]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topBar}>
        <View>
          <Text style={styles.title}>Developer Mode</Text>
          <Text style={styles.subtitle}>Local tools only</Text>
        </View>
        <Pressable style={({ pressed }) => [styles.closeBtn, pressed && styles.pressed]} onPress={() => navigation.goBack()}>
          <X size={18} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.hero}>
          <View style={styles.heroBadge}>
            <Shield size={16} color={theme.colors.primaryDark} strokeWidth={2} />
            <Text style={styles.heroBadgeText}>Hidden debug panel</Text>
          </View>
          <Text style={styles.heroTitle}>{membershipPlan === 'family' ? 'Family active' : membershipPlan === 'pro' ? 'Pro active' : 'Free active'}</Text>
          <Text style={styles.heroBody}>Use this panel to unlock a temporary local membership without touching real billing.</Text>
        </View>

        <View style={styles.statusCard}>
          <View style={styles.statusRow}>
            <View style={styles.statusIcon}>
              <Clock3 size={16} color={theme.colors.primary} strokeWidth={2} />
            </View>
            <View style={styles.statusCopy}>
              <Text style={styles.statusTitle}>Temporary unlock</Text>
              <Text style={styles.statusBody}>{remainingLabel ?? 'No active override'}</Text>
            </View>
          </View>
        </View>

        <View style={styles.section}>
          <QuickAction
            icon={<Sparkles size={18} color={theme.colors.primary} strokeWidth={2} />}
            title="Unlock Pro"
            subtitle="10 minutes"
            onPress={() => void activateDeveloperMembership('pro', 10)}
            styles={styles}
          />
          <QuickAction
            icon={<Crown size={18} color={theme.colors.primary} strokeWidth={2} />}
            title="Unlock Family"
            subtitle="10 minutes"
            onPress={() => void activateDeveloperMembership('family', 10)}
            styles={styles}
          />
          <QuickAction
            icon={<CheckCircle2 size={18} color={theme.colors.subtle} strokeWidth={2} />}
            title="Back to live billing"
            subtitle="Clear local override"
            onPress={() => void clearDeveloperMembershipOverride()}
            styles={styles}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.surface },
    topBar: {
      height: t.topNavHeight,
      paddingHorizontal: t.spacing.md,
      backgroundColor: t.colors.surface,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    title: { ...t.typography.h1, color: t.colors.foreground },
    subtitle: { ...t.typography.caption, color: t.colors.subtle },
    closeBtn: {
      width: 36,
      height: 36,
      borderRadius: 18,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.background,
    },
    pressed: { opacity: t.interaction.chipPressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    scrollView: { flex: 1, backgroundColor: t.colors.background },
    scrollContent: { padding: t.spacing.md, paddingBottom: 120, gap: t.spacing.md },
    hero: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.lg,
      gap: 10,
    },
    heroBadge: {
      alignSelf: 'flex-start',
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      backgroundColor: 'rgba(255,255,255,0.64)',
      borderRadius: t.radius.full,
      paddingHorizontal: 10,
      paddingVertical: 6,
    },
    heroBadgeText: { ...t.typography.micro, color: t.colors.primaryDark },
    heroTitle: { ...t.typography.display, color: t.colors.foreground },
    heroBody: { ...t.typography.body, color: t.colors.muted },
    statusCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.md,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    statusRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
    statusIcon: {
      width: 36,
      height: 36,
      borderRadius: 18,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.primaryLight,
    },
    statusCopy: { gap: 2, flex: 1 },
    statusTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    statusBody: { ...t.typography.caption, color: t.colors.subtle },
    section: { gap: t.spacing.sm },
    actionCard: {
      minHeight: 84,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surface,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
      paddingHorizontal: t.spacing.md,
      paddingVertical: t.spacing.md,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    actionIcon: {
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.primaryLight,
    },
    actionCopy: { flex: 1, gap: 2 },
    actionTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    actionSubtitle: { ...t.typography.caption, color: t.colors.subtle },
  });
}
