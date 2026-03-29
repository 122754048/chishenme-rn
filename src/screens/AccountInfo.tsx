import React from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { theme } from '../theme';

type NavProp = NativeStackNavigationProp<any>;

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

export function AccountInfo() {
  const navigation = useNavigation<NavProp>();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.navTitle}>登录信息</Text>
        <View style={styles.backBtn} />
      </View>

      <View style={styles.card}>
        <Row label="账号昵称" value="Alex Chen" />
        <Row label="邮箱" value="alex.chen@chishenme.app" />
        <Row label="手机号" value="+1 555 0199" />
        <Row label="登录方式" value="Apple / 邮箱验证码" />
        <Row label="最近登录" value="2026-03-29 08:30 UTC" />
      </View>

      <TouchableOpacity style={styles.actionBtn}>
        <Text style={styles.actionText}>修改登录方式</Text>
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
  card: {
    marginTop: 12,
    backgroundColor: '#fff',
    borderRadius: 14,
    overflow: 'hidden',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  rowLabel: { fontSize: 13, color: '#6b7280' },
  rowValue: { fontSize: 13, color: '#111827', fontWeight: '600' },
  actionBtn: {
    marginTop: 16,
    backgroundColor: theme.colors.brand,
    borderRadius: 24,
    alignItems: 'center',
    paddingVertical: 12,
  },
  actionText: { color: '#fff', fontWeight: '700' },
});
