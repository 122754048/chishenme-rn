import React from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Bell, Heart, Clock, Settings, CreditCard, HelpCircle, LogOut, ChevronRight, Star } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors, theme } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

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
});

function MenuRow({ icon, iconBg, label, value, onPress }: MenuRowProps) {
  return (
    <Pressable style={({ pressed }) => [mrStyles.menuRow, pressed && { backgroundColor: '#F3F4F6' }]} onPress={onPress}>
      <View style={[mrStyles.menuIconWrap, { backgroundColor: iconBg }]}>
        {icon}
      </View>
      <Text style={mrStyles.menuLabel}>{label}</Text>
      <View style={mrStyles.menuRight}>
        {value && <Text style={mrStyles.menuValue}>{value}</Text>}
        <ChevronRight size={16} color="#9CA3AF" strokeWidth={1.5} />
      </View>
    </Pressable>
  );
}

export function Profile() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { favorites } = useApp();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav �?Brand mode */}
      <View style={styles.topNav}>
        <Text style={styles.logo}>🍽�?ChiShenMe</Text>
        <Pressable style={({ pressed }) => [styles.bellBtn, pressed && { opacity: 0.7 }]}>
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
            <Text style={styles.profileJoined}>Member since Sept 2023</Text>
            <View style={styles.levelBadge}>
              <Text style={styles.levelBadgeText}>Foodie Level 4</Text>
            </View>
          </View>
        </View>

        {/* Membership Cards */}
        <View style={styles.membershipCards}>
          <Pressable
            style={({ pressed }) => [styles.membershipCard, styles.proCard, pressed && { opacity: 0.9 }]}
            onPress={() => navigation.navigate('Upgrade')}
          >
            <View>
              <Text style={styles.membershipLabel}>MEMBERSHIP STATUS</Text>
              <Text style={styles.membershipTitle}>PRO PLAN</Text>
              <Text style={styles.membershipDesc}>
                Enjoy unlimited smart recommendations and priority booking.
              </Text>
              <View style={styles.manageBtn}>
                <Text style={styles.manageBtnText}>Manage Plan</Text>
              </View>
            </View>
          </Pressable>

          <Pressable style={({ pressed }) => [styles.membershipCard, styles.familyCard, pressed && { opacity: 0.9 }]}>
            <View>
              <Text style={[styles.membershipLabel, { color: 'rgba(0,0,0,0.4)' }]}>FAMILY SHARING</Text>
              <Text style={[styles.membershipTitle, { color: 'rgba(0,0,0,0.75)' }]}>4 SLOTS LEFT</Text>
              <Text style={[styles.membershipDesc, { color: 'rgba(0,0,0,0.6)' }]}>
                Invite your family members to share your dining history and tastes.
              </Text>
              <View style={[styles.manageBtn, { backgroundColor: theme.colors.brandWarmDark }]}>
                <Text style={[styles.manageBtnText, { color: theme.colors.surface }]}>Invite Now</Text>
              </View>
            </View>
          </Pressable>
        </View>

        {/* Menu Lists */}
        <View style={styles.menuCard}>
          <MenuRow
            icon={<Heart size={15} color={theme.colors.error} strokeWidth={2} />}
            iconBg={theme.colors.errorLight}
            label="Favorites"
            value={`${favorites.length} items`}
            onPress={() => navigation.navigate('MainTabs', { screen: 'Favorites' })}
          />
          <MenuRow
            icon={<Clock size={15} color={theme.colors.blue} strokeWidth={2} />}
            iconBg="#F0F5FF"
            label="History"
            onPress={() => navigation.navigate('History')}
          />
          <MenuRow
            icon={<Settings size={15} color={theme.colors.muted} strokeWidth={2} />}
            iconBg={theme.colors.borderLight}
            label="Preferences"
            value="Chinese, Spicy"
          />
        </View>

        <View style={styles.menuCard}>
          <MenuRow
            icon={<CreditCard size={15} color={theme.colors.primary} strokeWidth={2} />}
            iconBg={theme.colors.primaryLight}
            label="Payments"
          />
          <MenuRow
            icon={<HelpCircle size={15} color={theme.colors.warning} strokeWidth={2} />}
            iconBg={theme.colors.warningLight}
            label="Help & Support"
          />
        </View>

        <Pressable style={({ pressed }) => [styles.signOutBtn, pressed && { opacity: 0.85 }]}>
          <LogOut size={16} color={theme.colors.error} strokeWidth={2} />
          <Text style={styles.signOutText}>Sign Out</Text>
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
    height: theme.topNavHeight,
    backgroundColor: t.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
  },
  logo: { ...theme.typography.h1, color: t.colors.foreground },
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
    ...theme.shadows.sm,
  },
  profileInfo: { flex: 1 },
  profileName: { ...theme.typography.h1, color: t.colors.foreground, marginBottom: 2 },
  profileJoined: { ...theme.typography.caption, color: t.colors.subtle, marginBottom: 6 },
  levelBadge: {
    backgroundColor: '#FFDEBA',
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 3,
    borderRadius: t.radius.full,
    alignSelf: 'flex-start',
  },
  levelBadgeText: {
    ...theme.typography.micro,
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
    ...theme.typography.micro,
    color: 'rgba(255,255,255,0.7)',
    letterSpacing: 1,
    marginBottom: 2,
  },
  membershipTitle: { ...theme.typography.h1, color: t.colors.surface, marginBottom: 4 },
  membershipDesc: {
    ...theme.typography.caption,
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
  manageBtnText: { ...theme.typography.caption, fontWeight: '700', color: t.colors.primary },
  menuCard: {
    backgroundColor: t.colors.surface,
    marginHorizontal: t.spacing.md,
    borderRadius: t.radius.lg,
    marginBottom: t.spacing.sm,
    overflow: 'hidden',
    ...theme.shadows.sm,
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
  menuLabel: { ...theme.typography.body, fontWeight: '500', color: t.colors.foreground, flex: 1 },
  menuRight: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  menuValue: { ...theme.typography.caption, color: t.colors.subtle },
  signOutBtn: {
    backgroundColor: t.colors.surface,
    marginHorizontal: t.spacing.md,
    borderRadius: t.radius.lg,
    paddingVertical: t.spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: t.spacing.xs,
    ...theme.shadows.sm,
  },
  signOutText: { ...theme.typography.body, fontWeight: '700', color: t.colors.error },
  bottomPadding: { height: t.spacing.lg },
});
}



