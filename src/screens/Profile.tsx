import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
import { SkeletonImage } from '../components/SkeletonImage';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

interface MenuRowProps {
  icon: string;
  iconBg: string;
  iconColor: string;
  label: string;
  value?: string;
  onPress?: () => void;
}

function MenuRow({ icon, iconBg, iconColor, label, value, onPress }: MenuRowProps) {
  return (
    <TouchableOpacity style={styles.menuRow} onPress={onPress} activeOpacity={0.7}>
      <View style={[styles.menuIconWrap, { backgroundColor: iconBg }]}>
        <Text style={[styles.menuIcon, { color: iconColor }]}>{icon}</Text>
      </View>
      <Text style={styles.menuLabel}>{label}</Text>
      <View style={styles.menuRight}>
        {value && <Text style={styles.menuValue}>{value}</Text>}
        <Text style={styles.menuChevron}>›</Text>
      </View>
    </TouchableOpacity>
  );
}

export function Profile() {
  const navigation = useNavigation<NavProp>();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav */}
      <View style={styles.topNav}>
        <Text style={styles.logo}>🍽️ ChiShenMe</Text>
        <TouchableOpacity style={styles.bellBtn}>
          <Text style={styles.bellIcon}>🔔</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Profile Header */}
        <View style={styles.profileHeader}>
          {/* Issue #16: Avatar now has explicit dimensions */}
          <View style={styles.avatarWrap}>
            <View style={{ width: 64, height: 64, borderRadius: 32, overflow: 'hidden' }}>
              <SkeletonImage
                src="https://images.unsplash.com/photo-1603086360919-8b8eacad64bc?w=200"
                alt="Alex Chen"
              />
            </View>
            <View style={styles.avatarBadge}>
              <Text style={styles.avatarBadgeIcon}>⭐</Text>
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
          {/* Pro Plan */}
          <TouchableOpacity
            style={[styles.membershipCard, { backgroundColor: theme.colors.brand }]}
            onPress={() => navigation.navigate('Upgrade')}
          >
            <Text style={styles.membershipStarIcon}>⭐</Text>
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
          </TouchableOpacity>

          {/* Family Plan */}
          <TouchableOpacity style={[styles.membershipCard, styles.familyCard]}>
            <View style={styles.familyDecor}>
              <View style={[styles.familyStripe, styles.familyStripe1]} />
              <View style={[styles.familyStripe, styles.familyStripe2]} />
              <View style={[styles.familyStripe, styles.familyStripe3]} />
            </View>
            <View>
              <Text style={[styles.membershipLabel, { color: 'rgba(0,0,0,0.4)' }]}>FAMILY SHARING</Text>
              <Text style={[styles.membershipTitle, { color: 'rgba(0,0,0,0.75)' }]}>4 SLOTS LEFT</Text>
              <Text style={[styles.membershipDesc, { color: 'rgba(0,0,0,0.6)' }]}>
                Invite your family members to share your dining history and tastes.
              </Text>
              <View style={[styles.manageBtn, { backgroundColor: theme.colors.brandWarmDark }]}>
                <Text style={styles.manageBtnText}>Invite Now</Text>
              </View>
            </View>
          </TouchableOpacity>
        </View>

        {/* Menu Lists */}
        <View style={styles.menuCard}>
          <MenuRow
            icon="❤️"
            iconBg="#FFF0F0"
            iconColor="#ef4444"
            label="Favorites"
            value="24 items"
            onPress={() => navigation.navigate('MainTabs')}
          />
          <MenuRow
            icon="🕐"
            iconBg="#F0F5FF"
            iconColor="#3b82f6"
            label="History"
            onPress={() => navigation.navigate('History')}
          />
          <MenuRow
            icon="⚙️"
            iconBg="#f3f4f6"
            iconColor="#6b7280"
            label="Preferences"
            value="Chinese, Spicy"
            onPress={() => {}}
          />
        </View>

        <View style={styles.menuCard}>
          <MenuRow
            icon="💳"
            iconBg={theme.colors.brandLight}
            iconColor={theme.colors.brand}
            label="Payments"
            onPress={() => {}}
          />
          <MenuRow
            icon="❓"
            iconBg={theme.colors.brandAccentLight}
            iconColor={theme.colors.brandAccent}
            label="Help & Support"
            onPress={() => {}}
          />
        </View>

        <TouchableOpacity style={styles.signOutBtn}>
          <Text style={styles.signOutText}>Sign Out</Text>
        </TouchableOpacity>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.surface },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  logo: { fontSize: 18, fontWeight: '700', color: theme.colors.foreground },
  bellBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  bellIcon: { fontSize: 20 },
  scrollView: { flex: 1 },
  profileHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 16,
    gap: 16,
  },
  avatarWrap: { position: 'relative' },
  avatarBadge: {
    position: 'absolute',
    bottom: 0,
    right: -2,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
    elevation: 2,
  },
  avatarBadgeIcon: { fontSize: 10 },
  profileInfo: { flex: 1 },
  profileName: { fontSize: 20, fontWeight: '700', color: theme.colors.foreground, marginBottom: 2 },
  profileJoined: { fontSize: 11, color: '#9ca3af', marginBottom: 6 },
  levelBadge: {
    backgroundColor: '#FFDEBA',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 20,
    alignSelf: 'flex-start',
  },
  levelBadgeText: {
    fontSize: 10,
    fontWeight: '700',
    color: theme.colors.brandWarmDark,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  membershipCards: { paddingHorizontal: 16, gap: 12, marginBottom: 16 },
  membershipCard: {
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    gap: 12,
    overflow: 'hidden',
  },
  familyCard: { backgroundColor: theme.colors.brandWarm },
  membershipStarIcon: { fontSize: 48, opacity: 0.2, position: 'absolute', right: -12, top: -12 },
  membershipLabel: {
    fontSize: 9,
    fontWeight: '700',
    color: 'rgba(255,255,255,0.7)',
    letterSpacing: 1,
    marginBottom: 2,
  },
  membershipTitle: { fontSize: 20, fontWeight: '700', color: '#ffffff', marginBottom: 4 },
  membershipDesc: {
    fontSize: 11,
    color: 'rgba(255,255,255,0.8)',
    lineHeight: 16,
    marginBottom: 12,
    paddingRight: 40,
  },
  manageBtn: {
    backgroundColor: '#ffffff',
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 20,
    alignSelf: 'flex-start',
  },
  manageBtnText: { fontSize: 11, fontWeight: '700', color: theme.colors.brand },
  familyDecor: {
    position: 'absolute',
    right: 12,
    top: '50%',
    transform: [{ translateY: -30 }],
    gap: 4,
    opacity: 0.15,
  },
  familyStripe: { width: 20, backgroundColor: '#ffffff', borderRadius: 10 },
  familyStripe1: { height: 60 },
  familyStripe2: { height: 40, marginTop: 8 },
  familyStripe3: { height: 24, marginTop: 8 },
  menuCard: {
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    borderRadius: 16,
    marginBottom: 12,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  menuRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#fafafa',
    gap: 12,
  },
  menuIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuIcon: { fontSize: 15 },
  menuLabel: { flex: 1, fontSize: 14, fontWeight: '500', color: theme.colors.foreground },
  menuRight: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  menuValue: { fontSize: 12, color: '#9ca3af' },
  menuChevron: { fontSize: 18, color: '#d1d5db', fontWeight: '300' },
  signOutBtn: {
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    borderRadius: 16,
    paddingVertical: 16,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  signOutText: { fontSize: 14, fontWeight: '700', color: '#ef4444' },
  bottomPadding: { height: 20 },
});
