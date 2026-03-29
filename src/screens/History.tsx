import React, { useMemo } from 'react';
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
import { HISTORY_DATA } from '../data/mockData';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<any>;

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

export function History() {
  const navigation = useNavigation<NavProp>();
  const { history } = useApp();

  const groups = useMemo(() => {
    if (!history.length) return HISTORY_DATA;
    const today: typeof history = [];
    const earlier: typeof history = [];
    const now = new Date();

    history.forEach((item) => {
      const d = new Date(item.time);
      if (!Number.isNaN(d.getTime()) && d.toDateString() === now.toDateString()) {
        today.push(item);
      } else {
        earlier.push(item);
      }
    });

    return [
      { group: 'TODAY', items: today.map((item) => ({ ...item, time: formatTime(item.time) })) },
      { group: 'EARLIER', items: earlier.map((item) => ({ ...item, time: formatTime(item.time) })) },
    ].filter((section) => section.items.length > 0);
  }, [history]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.navTitle}>历史记录</Text>
        <View style={styles.moreBtn} />
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {groups.map((group) => (
          <View key={group.group} style={styles.group}>
            <View style={styles.groupHeader}>
              <Text style={styles.groupLabel}>{group.group}</Text>
              <View style={styles.groupLine} />
            </View>
            <View style={styles.groupItems}>
              {group.items.map((item) => (
                <View key={`${group.group}-${item.id}-${item.time}`} style={styles.historyItem}>
                  <SkeletonImage src={item.img} alt={item.title} className="" />
                  <View style={styles.historyItemContent}>
                    <Text style={styles.historyItemTitle}>{item.title}</Text>
                    <Text style={styles.historyItemMeta}>
                      {item.time} • {item.category}
                    </Text>
                  </View>
                  {item.status === 'Liked' ? (
                    <View style={styles.likedBadge}>
                      <Text style={styles.likedIcon}>❤️</Text>
                      <Text style={styles.likedText}>Liked</Text>
                    </View>
                  ) : (
                    <View style={styles.skippedBadge}>
                      <Text style={styles.skippedIcon}>🚫</Text>
                      <Text style={styles.skippedText}>Skipped</Text>
                    </View>
                  )}
                </View>
              ))}
            </View>
          </View>
        ))}

        <View style={styles.endState}>
          <View style={styles.endIcon}>
            <Text style={styles.endIconText}>🔄</Text>
          </View>
          <Text style={styles.endText}>以上是全部历史记录</Text>
        </View>
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
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  backIcon: { fontSize: 22, color: '#374151' },
  navTitle: { fontSize: 16, fontWeight: '600', color: theme.colors.foreground },
  moreBtn: { width: 40, height: 40 },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: 16, paddingTop: 20, paddingBottom: 40 },
  group: { marginBottom: 28 },
  groupHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: 12, gap: 12 },
  groupLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#9ca3af',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  groupLine: { flex: 1, height: 1, backgroundColor: '#e5e7eb' },
  groupItems: { gap: 10 },
  historyItem: {
    flexDirection: 'row',
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 12,
    gap: 12,
    alignItems: 'center',
  },
  historyItemContent: { flex: 1 },
  historyItemTitle: { fontSize: 14, fontWeight: '600', color: theme.colors.foreground },
  historyItemMeta: { fontSize: 10, color: '#9ca3af', marginTop: 2 },
  likedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: theme.colors.brandLight,
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  likedIcon: { fontSize: 11 },
  likedText: { fontSize: 10, fontWeight: '600', color: theme.colors.brand },
  skippedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#f3f4f6',
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  skippedIcon: { fontSize: 11 },
  skippedText: { fontSize: 10, fontWeight: '600', color: '#9ca3af' },
  endState: {
    alignItems: 'center',
    paddingTop: 40,
    paddingBottom: 20,
    gap: 8,
  },
  endIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
  },
  endIconText: { fontSize: 20 },
  endText: { fontSize: 12, color: '#9ca3af' },
});
