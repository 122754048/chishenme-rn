import React from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { theme } from '../theme';

type NavProp = NativeStackNavigationProp<any>;

export function MembershipInfo() {
  const navigation = useNavigation<NavProp>();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.navTitle}>会员信息</Text>
        <View style={styles.backBtn} />
      </View>

      <View style={styles.hero}>
        <Text style={styles.plan}>PRO Annual</Text>
        <Text style={styles.expire}>到期时间 2027-03-31</Text>
        <Text style={styles.desc}>当前权益：无限推荐 / 高级分析 / 家庭共享 4 人</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>权益清单</Text>
        <Text style={styles.item}>• 每日推荐不限次数</Text>
        <Text style={styles.item}>• 收藏与历史跨设备同步</Text>
        <Text style={styles.item}>• 优先客服响应</Text>
        <Text style={styles.item}>• 饮食偏好智能学习加速</Text>
      </View>

      <TouchableOpacity style={styles.actionBtn} onPress={() => navigation.navigate('Upgrade')}>
        <Text style={styles.actionText}>管理/升级会员</Text>
      </TouchableOpacity>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.surface, paddingHorizontal: 16 },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
  },
  backBtn: { width: 36, height: 36, justifyContent: 'center', alignItems: 'center' },
  backIcon: { fontSize: 20, color: '#111827' },
  navTitle: { fontSize: 17, fontWeight: '700', color: theme.colors.foreground },
  hero: { marginTop: 10, backgroundColor: theme.colors.brand, borderRadius: 14, padding: 16 },
  plan: { fontSize: 22, fontWeight: '700', color: '#fff' },
  expire: { fontSize: 12, color: 'rgba(255,255,255,0.9)', marginTop: 4 },
  desc: { fontSize: 12, color: '#fff', lineHeight: 18, marginTop: 10 },
  card: { marginTop: 12, backgroundColor: '#fff', borderRadius: 14, padding: 16 },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#111827', marginBottom: 8 },
  item: { fontSize: 13, color: '#4b5563', marginTop: 6 },
  actionBtn: {
    marginTop: 16,
    backgroundColor: '#111827',
    borderRadius: 24,
    alignItems: 'center',
    paddingVertical: 12,
  },
  actionText: { color: '#fff', fontWeight: '700' },
});
