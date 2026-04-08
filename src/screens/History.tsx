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
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { useApp } from '../context/AppContext';
import { SkeletonImage } from '../components/SkeletonImage';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function History() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
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

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
  container: { flex: 1, backgroundColor: t.colors.background },
  topNav: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    height: t.topNavHeight,
    backgroundColor: t.colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
  },
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  navTitle: { ...t.typography.h2, color: t.colors.foreground },
  moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.lg, paddingBottom: t.spacing['2xl'] },
  group: { marginBottom: t.spacing.xl },
  groupHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: t.spacing.sm, gap: t.spacing.sm },
  groupLabel: {
    ...t.typography.micro,
    fontWeight: '700',
    color: t.colors.subtle,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  groupLine: { flex: 1, height: 1, backgroundColor: t.colors.border },
  groupItems: { gap: t.spacing.xs },
  historyItem: {
    flexDirection: 'row',
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.sm,
    gap: t.spacing.sm,
    alignItems: 'center',
    ...t.shadows.sm,
  },
  historyImageWrap: { width: 48, height: 48, borderRadius: t.radius.sm, overflow: 'hidden' },
  historyItemContent: { flex: 1 },
  historyItemTitle: { ...t.typography.body, fontWeight: '600', color: t.colors.foreground },
  historyItemMeta: { ...t.typography.micro, color: t.colors.subtle, marginTop: 2 },
  likedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: t.colors.primaryLight,
    borderRadius: t.radius.full,
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 5,
  },
  likedText: { ...t.typography.micro, fontWeight: '600', color: t.colors.primary },
  skippedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: t.colors.borderLight,
    borderRadius: t.radius.full,
    paddingHorizontal: t.spacing.xs,
    paddingVertical: 5,
  },
  skippedText: { ...t.typography.micro, fontWeight: '600', color: t.colors.subtle },
  endState: {
    alignItems: 'center',
    paddingTop: t.spacing['2xl'],
    paddingBottom: t.spacing.lg,
    gap: t.spacing.xs,
  },
  endIcon: {
    width: 48,
    height: 48,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
    ...t.shadows.sm,
  },
  endText: { ...t.typography.caption, color: t.colors.subtle },
});
}
