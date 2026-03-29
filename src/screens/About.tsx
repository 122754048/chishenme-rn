import React from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { theme } from '../theme';

type NavProp = NativeStackNavigationProp<any>;

export function About() {
  const navigation = useNavigation<NavProp>();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.navTitle}>关于 ChiShenMe</Text>
        <View style={styles.backBtn} />
      </View>

      <View style={styles.card}>
        <Text style={styles.title}>ChiShenMe</Text>
        <Text style={styles.meta}>Version 1.0.0</Text>
        <Text style={styles.body}>
          我们致力于用 AI 帮你更快找到“今天吃什么”。通过你的口味、历史与收藏，持续优化推荐结果。
        </Text>
        <Text style={styles.body}>官网: https://chishenme.app</Text>
        <Text style={styles.body}>联系: support@chishenme.app</Text>
      </View>
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
  card: { marginTop: 12, backgroundColor: '#fff', borderRadius: 14, padding: 16 },
  title: { fontSize: 24, fontWeight: '800', color: '#111827' },
  meta: { fontSize: 12, color: '#6b7280', marginTop: 4 },
  body: { fontSize: 13, color: '#4b5563', lineHeight: 20, marginTop: 12 },
});
