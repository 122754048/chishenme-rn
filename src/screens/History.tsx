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
import { ArrowLeft, MoreHorizontal, Heart, Ban, RefreshCw, ClipboardList } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
import { useApp } from '../context/AppContext';
import { SkeletonImage } from '../components/SkeletonImage';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function History() {
  const navigation = useNavigation<NavProp>();
  const { history } = useApp();

  const groupedHistory = React.useMemo(() => {
    const groups: Record<string, typeof history> = {};
    history.forEach((item) => {
      const groupKey = 'RECENT';
      if (!groups[groupKey]) groups[groupKey] = [];
      groups[groupKey].push(item);
    });
    return Object.entries(groups).map(([group, items]) => ({ group, items }));
  }, [history]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Top Nav — Page mode */}
      <View style={styles.topNav}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}>
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.navTitle}>History</Text>
        <Pressable style={({ pressed }) => [styles.moreBtn, pressed && { opacity: 0.7 }]}>
          <MoreHorizontal size={20} color={theme.colors.muted} strokeWidth={1.8} />
        </Pressable>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        {groupedHistory.length === 0 ? (
          <View style={styles.endState}>
            <View style={styles.endIcon}>
              <ClipboardList size={24} color={theme.colors.subtle} strokeWidth={1.5} />
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
                {group.items.map((item, index) => (
                  <View key={`${group.group}-${index}`} style={styles.historyItem}>
                    <View style={styles.historyImageWrap}>
                      <SkeletonImage src={item.img} alt={item.title} />
                    </View>
                    <View style={styles.historyItemContent}>
                      <Text style={styles.historyItemTitle}>{item.title}</Text>
                      <Text style={styles.historyItemMeta}>
                        {item.time} · {item.category}
                      </Text>
                    </View>
                    {item.status === 'Liked' ? (
                      <View style={styles.likedBadge}>
                        <Heart size={10} color={theme.colors.primary} fill={theme.colors.primary} />
                        <Text style={styles.likedText}>Liked</Text>
                      </View>
                    ) : (
                      <View style={styles.skippedBadge}>
                        <Ban size={10} color={theme.colors.subtle} strokeWidth={2} />
                        <Text style={styles.skippedText}>Skipped</Text>
                      </View>
                    )}
                  </View>
                ))}
              </View>
            </View>
          ))
        )}

        {groupedHistory.length > 0 && (
          <View style={styles.endState}>
            <View style={styles.endIcon}>
              <RefreshCw size={20} color={theme.colors.subtle} strokeWidth={1.5} />
            </View>
            <Text style={styles.endText}>No more history to show</Text>
          </View>
        )}
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
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  navTitle: { ...theme.typography.h2, color: theme.colors.foreground },
  moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: theme.spacing.md, paddingTop: theme.spacing.lg, paddingBottom: theme.spacing['2xl'] },
  group: { marginBottom: theme.spacing.xl },
  groupHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm, gap: theme.spacing.sm },
  groupLabel: {
    ...theme.typography.micro,
    fontWeight: '700',
    color: theme.colors.subtle,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  groupLine: { flex: 1, height: 1, backgroundColor: theme.colors.border },
  groupItems: { gap: theme.spacing.xs },
  historyItem: {
    flexDirection: 'row',
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    padding: theme.spacing.sm,
    gap: theme.spacing.sm,
    alignItems: 'center',
    ...theme.shadows.sm,
  },
  historyImageWrap: { width: 48, height: 48, borderRadius: theme.radius.sm, overflow: 'hidden' },
  historyItemContent: { flex: 1 },
  historyItemTitle: { ...theme.typography.body, fontWeight: '600', color: theme.colors.foreground },
  historyItemMeta: { ...theme.typography.micro, color: theme.colors.subtle, marginTop: 2 },
  likedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: theme.colors.primaryLight,
    borderRadius: theme.radius.full,
    paddingHorizontal: theme.spacing.xs,
    paddingVertical: 5,
  },
  likedText: { ...theme.typography.micro, fontWeight: '600', color: theme.colors.primary },
  skippedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: theme.colors.borderLight,
    borderRadius: theme.radius.full,
    paddingHorizontal: theme.spacing.xs,
    paddingVertical: 5,
  },
  skippedText: { ...theme.typography.micro, fontWeight: '600', color: theme.colors.subtle },
  endState: {
    alignItems: 'center',
    paddingTop: theme.spacing['2xl'],
    paddingBottom: theme.spacing.lg,
    gap: theme.spacing.xs,
  },
  endIcon: {
    width: 48,
    height: 48,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
    ...theme.shadows.sm,
  },
  endText: { ...theme.typography.caption, color: theme.colors.subtle },
});
