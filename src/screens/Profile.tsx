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
import { theme } from '../theme';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<any>;

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
  const { favorites, history, selectedCuisines, selectedRestrictions } = useApp();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <Text style={styles.logo}>我的</Text>
        <TouchableOpacity style={styles.bellBtn}>
          <Text style={styles.bellIcon}>🔔</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        <TouchableOpacity
          style={styles.profileHeader}
          onPress={() => navigation.navigate('AccountInfo')}
        >
          <View style={styles.avatarWrap}>
            <SkeletonImage
              src="https://images.unsplash.com/photo-1603086360919-8b8eacad64bc?w=200"
              alt="Alex Chen"
              className=""
            />
          </View>
          <View style={styles.profileInfo}>
            <Text style={styles.profileName}>Alex Chen</Text>
            <Text style={styles.profileJoined}>alex.chen@chishenme.app</Text>
            <Text style={styles.profileJoined}>手机号 +1 555 0199 · 已登录</Text>
          </View>
          <Text style={styles.menuChevron}>›</Text>
        </TouchableOpacity>

        <View style={styles.statsCard}>
          <View style={styles.statItem}>
            <Text style={styles.statValue}>{favorites.length}</Text>
            <Text style={styles.statLabel}>收藏</Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.statItem}>
            <Text style={styles.statValue}>{history.length}</Text>
            <Text style={styles.statLabel}>历史</Text>
          </View>
          <View style={styles.statDivider} />
          <View style={styles.statItem}>
            <Text style={styles.statValue}>{selectedCuisines.length}</Text>
            <Text style={styles.statLabel}>偏好菜系</Text>
          </View>
        </View>

        <TouchableOpacity
          style={[styles.membershipCard, { backgroundColor: theme.colors.brand }]}
          onPress={() => navigation.navigate('MembershipInfo')}
        >
          <Text style={styles.membershipLabel}>会员信息</Text>
          <Text style={styles.membershipTitle}>PRO 年度会员</Text>
          <Text style={styles.membershipDesc}>
            到期时间：2027-03-31 · 已开通无限推荐、优先客服与家庭共享
          </Text>
          <View style={styles.membershipMetaRow}>
            <Text style={styles.membershipMeta}>饮食限制：{selectedRestrictions.length || 0} 项</Text>
            <Text style={styles.membershipMeta}>查看详情 ›</Text>
          </View>
        </TouchableOpacity>

        <View style={styles.menuCard}>
          <MenuRow
            icon="👤"
            iconBg="#EEF2FF"
            iconColor="#4f46e5"
            label="登录信息"
            value="已绑定邮箱"
            onPress={() => navigation.navigate('AccountInfo')}
          />
          <MenuRow
            icon="💎"
            iconBg="#ECFDF3"
            iconColor={theme.colors.brand}
            label="会员信息"
            value="PRO"
            onPress={() => navigation.navigate('MembershipInfo')}
          />
          <MenuRow
            icon="❤️"
            iconBg="#FFF0F0"
            iconColor="#ef4444"
            label="收藏"
            value={`${favorites.length} 项`}
            onPress={() => navigation.navigate('Favorites')}
          />
          <MenuRow
            icon="🕘"
            iconBg="#F0F5FF"
            iconColor="#3b82f6"
            label="历史记录"
            value={`${history.length} 项`}
            onPress={() => navigation.navigate('History')}
          />
        </View>

        <View style={styles.menuCard}>
          <MenuRow
            icon="🔒"
            iconBg="#f3f4f6"
            iconColor="#4b5563"
            label="隐私政策"
            onPress={() => navigation.navigate('PrivacyPolicy')}
          />
          <MenuRow
            icon="ℹ️"
            iconBg="#FFF7ED"
            iconColor="#d97706"
            label="关于我们"
            onPress={() => navigation.navigate('About')}
          />
        </View>

        <TouchableOpacity style={styles.signOutBtn}>
          <Text style={styles.signOutText}>退出登录</Text>
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
  logo: { fontSize: 20, fontWeight: '700', color: theme.colors.foreground },
  bellBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  bellIcon: { fontSize: 20 },
  scrollView: { flex: 1 },
  profileHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: 16,
    marginTop: 16,
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 14,
    gap: 12,
  },
  avatarWrap: { borderRadius: 28, overflow: 'hidden' },
  profileInfo: { flex: 1 },
  profileName: { fontSize: 18, fontWeight: '700', color: theme.colors.foreground },
  profileJoined: { fontSize: 12, color: '#6b7280', marginTop: 2 },
  statsCard: {
    backgroundColor: '#fff',
    marginHorizontal: 16,
    marginTop: 12,
    borderRadius: 16,
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
  },
  statItem: { flex: 1, alignItems: 'center' },
  statValue: { fontSize: 20, fontWeight: '700', color: theme.colors.foreground },
  statLabel: { fontSize: 11, color: '#9ca3af', marginTop: 2 },
  statDivider: { width: 1, height: 26, backgroundColor: '#e5e7eb' },
  membershipCard: {
    marginHorizontal: 16,
    marginTop: 12,
    borderRadius: 16,
    padding: 16,
  },
  membershipLabel: { fontSize: 11, color: 'rgba(255,255,255,0.8)', fontWeight: '700' },
  membershipTitle: { fontSize: 22, color: '#fff', fontWeight: '700', marginTop: 4 },
  membershipDesc: { fontSize: 12, color: 'rgba(255,255,255,0.85)', lineHeight: 18, marginTop: 6 },
  membershipMetaRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 12 },
  membershipMeta: { fontSize: 11, color: '#fff', fontWeight: '600' },
  menuCard: {
    backgroundColor: '#ffffff',
    marginHorizontal: 16,
    borderRadius: 16,
    marginTop: 12,
    overflow: 'hidden',
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
    marginTop: 12,
  },
  signOutText: { fontSize: 14, fontWeight: '700', color: '#ef4444' },
  bottomPadding: { height: 24 },
});
