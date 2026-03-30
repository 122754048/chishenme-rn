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
import { useApp } from '../context/AppContext';
import { SkeletonImage } from '../components/SkeletonImage';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function History() {
  const navigation = useNavigation<NavProp>();
  // Issue #13: Use history from AppContext instead of hardcoded HISTORY_DATA.
  const { history } = useApp();

  // Group history items by date for display
  const groupedHistory = React.useMemo(() => {
    const today = new Date().toDateString();
    const yesterday = new Date(Date.now() - 86400000).toDateString();
    const groups: Record<string, typeof history> = {};

    history.forEach((item) => {
      // Simple grouping by "TODAY" / "YESTERDAY" / "EARLIER"
      // Since our items don't have full date info, we'll just show them all under "RECENT"
      const groupKey = 'RECENT';
      if (!groups[groupKey]) groups[groupKey] = [];
      groups[groupKey].push(item);
    });

    return Object.entries(groups).map(([group, items]) => ({ group, items }));
  }, [history]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav */}
      <View style={styles.topNav}>
        {/* Issue #4: Fixed back button — was empty `() => {}`, now calls `navigation.goBack()`. */}
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.navTitle}>History</Text>
        <TouchableOpacity style={styles.moreBtn}>
          <Text style={styles.moreIcon}>⋯</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {groupedHistory.length === 0 ? (
          <View style={styles.endState}>
            <View style={styles.endIcon}>
              <Text style={styles.endIconText}>📋</Text>
            </View>
            <Text style={styles.endText}>No history yet. Start swiping!</Text>
          </View>
        ) : (
          groupedHistory.map((group) => (
            <View key={group.group} style={styles.group}>
              <View style={styles.groupHeader}>
                <Text style={styles.groupLabel}>{group.group}</Text>
                <View style={styles.groupLine} />
              </View>
              <View style={styles.groupItems}>
                {group.items.map((item) => (
                  <View key={`${item.id}-${item.time}`} style={styles.historyItem}>
                    <View style={{ width: 48, height: 48, borderRadius: 10, overflow: 'hidden' }}>
                      <SkeletonImage src={item.img} alt={item.title} />
                    </View>
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
          ))
        )}

        {/* Empty end state */}
        {groupedHistory.length > 0 && (
          <View style={styles.endState}>
            <View style={styles.endIcon}>
              <Text style={styles.endIconText}>🔄</Text>
            </View>
            <Text style={styles.endText}>No more history to show</Text>
          </View>
        )}
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
  moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
  moreIcon: { fontSize: 18, color: '#6b7280' },
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
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
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
  endText: { fontSize: 12, color: '#d1d5db' },
});
