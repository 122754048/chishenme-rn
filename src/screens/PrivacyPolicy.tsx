import React from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { theme } from '../theme';

type NavProp = NativeStackNavigationProp<any>;

export function PrivacyPolicy() {
  const navigation = useNavigation<NavProp>();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.navTitle}>隐私政策</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView style={styles.scrollView}>
        <Text style={styles.p}>我们仅收集提供推荐服务所需的最小数据：账号信息、偏好设置、收藏与历史记录。</Text>
        <Text style={styles.h}>1. 数据用途</Text>
        <Text style={styles.p}>用于生成个性化推荐、同步你的收藏与历史、改进产品体验。</Text>
        <Text style={styles.h}>2. 数据共享</Text>
        <Text style={styles.p}>不会出售你的个人数据；仅在法律要求或提供核心服务时与受约束合作方共享。</Text>
        <Text style={styles.h}>3. 数据控制</Text>
        <Text style={styles.p}>你可以在“我的”页面随时查看、导出或申请删除账号相关数据。</Text>
        <Text style={styles.h}>4. 联系我们</Text>
        <Text style={styles.p}>privacy@chishenme.app</Text>
      </ScrollView>
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
  scrollView: { marginTop: 10, backgroundColor: '#fff', borderRadius: 14, padding: 16 },
  h: { fontSize: 14, fontWeight: '700', color: '#111827', marginTop: 10 },
  p: { fontSize: 13, lineHeight: 20, color: '#4b5563', marginTop: 8 },
});
