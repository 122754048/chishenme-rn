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
import { theme } from '../theme';
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

function MenuRow({ icon, iconBg, label, value, onPress }: MenuRowProps) {
  return (
    <Pressable style={({ pressed }) => [styles.menuRow, pressed && { backgroundColor: theme.colors.borderLight }]} onPress={onPress} >
      <View style={[styles.menuIconWrap, { backgroundColor: iconBg }]}>
        {icon}
      </View>
      <Text style={styles.menuLabel}>{label}</Text>
      <View style={styles.menuRight}>
        {value && <Text style={styles.menuValue}>{value}</Text>}
        <ChevronRight size={16} color={theme.colors.subtle} strokeWidth={1.5} />
      </View>
    </Pressable>
  );
}

export function Profile() {
  const navigation = useNavigation<NavProp>();
  const { favorites } = useApp();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav — Brand mode */}
      <View style={styles.topNav}>
        <Text style={styles.logo}>🍽️ ChiShenMe</Text>
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    height: theme.topNavHeight,
    backgroundColor: theme.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderLight,
  },
  logo: { ...theme.typography.h1, color: theme.colors.foreground },
  bellBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  scrollView: { flex: 1 },
  profileHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.lg,
    paddingTop: theme.spacing.lg,
    paddingBottom: theme.spacing.md,
    gap: theme.spacing.md,
  },
  avatarWrap: { position: 'relative' },
  avatarImage: { width: 64, height: 64, borderRadius: theme.radius.full, overflow: 'hidden' },
  avatarBadge: {
    position: 'absolute',
    bottom: 0,
    right: -2,
    width: 20,
    height: 20,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    ...theme.shadows.sm,
  },
  profileInfo: { flex: 1 },
  profileName: { ...theme.typography.h1, color: theme.colors.foreground, marginBottom: 2 },
  profileJoined: { ...theme.typography.caption, color: theme.colors.subtle, marginBottom: 6 },
  levelBadge: {
    backgroundColor: '#FFDEBA',
    paddingHorizontal: theme.spacing.xs,
    paddingVertical: 3,
    borderRadius: theme.radius.full,
    alignSelf: 'flex-start',
  },
  levelBadgeText: {
    ...theme.typography.micro,
    fontWeight: '700',
    color: theme.colors.brandWarmDark,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  membershipCards: { paddingHorizontal: theme.spacing.md, gap: theme.spacing.sm, marginBottom: theme.spacing.md },
  membershipCard: {
    borderRadius: theme.radius.lg,
    padding: theme.spacing.md,
    overflow: 'hidden',
  },
  proCard: { backgroundColor: theme.colors.primary },
  familyCard: { backgroundColor: theme.colors.brandWarm },
  membershipLabel: {
    ...theme.typography.micro,
    color: 'rgba(255,255,255,0.7)',
    letterSpacing: 1,
    marginBottom: 2,
  },
  membershipTitle: { ...theme.typography.h1, color: theme.colors.surface, marginBottom: 4 },
  membershipDesc: {
    ...theme.typography.caption,
    color: 'rgba(255,255,255,0.8)',
    marginBottom: theme.spacing.sm,
    paddingRight: 40,
  },
  manageBtn: {
    backgroundColor: theme.colors.surface,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 6,
    borderRadius: theme.radius.full,
    alignSelf: 'flex-start',
  },
  manageBtnText: { ...theme.typography.caption, fontWeight: '700', color: theme.colors.primary },
  menuCard: {
    backgroundColor: theme.colors.surface,
    marginHorizontal: theme.spacing.md,
    borderRadius: theme.radius.lg,
    marginBottom: theme.spacing.sm,
    overflow: 'hidden',
    ...theme.shadows.sm,
  },
  menuRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderLight,
    gap: theme.spacing.sm,
  },
  menuIconWrap: {
    width: 32,
    height: 32,
    borderRadius: theme.radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuLabel: { ...theme.typography.body, fontWeight: '500', color: theme.colors.foreground, flex: 1 },
  menuRight: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  menuValue: { ...theme.typography.caption, color: theme.colors.subtle },
  signOutBtn: {
    backgroundColor: theme.colors.surface,
    marginHorizontal: theme.spacing.md,
    borderRadius: theme.radius.lg,
    paddingVertical: theme.spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: theme.spacing.xs,
    ...theme.shadows.sm,
  },
  signOutText: { ...theme.typography.body, fontWeight: '700', color: theme.colors.error },
  bottomPadding: { height: theme.spacing.lg },
});
