import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, ClipboardList, Heart, MoreHorizontal, RefreshCw } from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';
import type { RootStackParamList } from '../navigation/types';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function History() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { decisionSettings, history } = useApp();

  const groupedHistory = React.useMemo(() => {
    const groups: Record<string, typeof history> = {};
    const now = Date.now();
    const oneDay = 24 * 60 * 60 * 1000;

    history.forEach((item) => {
      const age = item.createdAt ? now - item.createdAt : oneDay * 7 + 1;
      const groupKey = age < oneDay ? 'Today' : age < oneDay * 2 ? 'Yesterday' : 'Earlier';
      if (!groups[groupKey]) groups[groupKey] = [];
      groups[groupKey].push(item);
    });

    const order: Array<'Today' | 'Yesterday' | 'Earlier'> = ['Today', 'Yesterday', 'Earlier'];
    return order.filter((group) => groups[group]?.length).map((group) => ({ group, items: groups[group] }));
  }, [history]);

  const revisitPicks = React.useMemo(() => {
    const seen = new Set<number>();
    return history
      .filter((item) => item.status === 'Liked')
      .filter((item) => {
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      })
      .slice(0, 3);
  }, [history]);

  const likedCount = history.filter((item) => item.status === 'Liked').length;
  const skippedCount = history.filter((item) => item.status === 'Skipped').length;
  const latestLiked = revisitPicks[0] ?? null;

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.topNav}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && styles.pressedChrome]} accessibilityRole="button" accessibilityLabel="Go back">
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.navTitle}>History</Text>
        <Pressable style={({ pressed }) => [styles.moreBtn, pressed && styles.pressedChrome]} onPress={() => navigation.navigate('MainTabs', { screen: 'Home' })} accessibilityRole="button" accessibilityLabel="Back to home">
          <MoreHorizontal size={20} color={theme.colors.muted} strokeWidth={1.8} />
        </Pressable>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.summaryCard}>
          <Text style={styles.summaryEyebrow}>Decision memory</Text>
          <Text style={styles.summaryTitle}>Keep the good calls easy to reuse.</Text>
          <View style={styles.summaryStats}>
            <View style={styles.summaryStat}>
              <Text style={styles.summaryStatValue}>{likedCount}</Text>
              <Text style={styles.summaryStatLabel}>Picked</Text>
            </View>
            <View style={styles.summaryStat}>
              <Text style={styles.summaryStatValue}>{skippedCount}</Text>
              <Text style={styles.summaryStatLabel}>Passed</Text>
            </View>
            <View style={styles.summaryStat}>
              <Text style={styles.summaryStatValue}>{history.length}</Text>
              <Text style={styles.summaryStatLabel}>Total</Text>
            </View>
          </View>
        </View>

        {latestLiked ? (
          <Pressable style={({ pressed }) => [styles.tonightCard, pressed && styles.pressedCard]} onPress={() => navigation.navigate('Detail', { itemId: latestLiked.id, title: latestLiked.title, image: latestLiked.img })}>
            <View style={styles.tonightImage}>
              <SkeletonImage src={latestLiked.img} alt={latestLiked.title} />
            </View>
            <View style={styles.tonightCopy}>
              <Text style={styles.tonightEyebrow}>Tonight from your history</Text>
              <Text style={styles.tonightTitle}>{latestLiked.title}</Text>
              <Text style={styles.tonightMeta}>{latestLiked.category} / {latestLiked.time}</Text>
            </View>
          </Pressable>
        ) : null}

        {revisitPicks.length > 0 ? (
          <View style={styles.revisitSection}>
            <View style={styles.revisitHeader}>
              <Text style={styles.revisitTitle}>Worth revisiting</Text>
              {decisionSettings.keepItFresh ? <Text style={styles.revisitHint}>Fresh mode on</Text> : null}
            </View>
            <View style={styles.revisitList}>
              {revisitPicks.map((item) => (
                <Pressable
                  key={`revisit-${item.id}`}
                  style={({ pressed }) => [styles.revisitCard, pressed && styles.pressedCard]}
                  onPress={() => navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.img })}
                >
                  <View style={styles.revisitThumb}>
                    <SkeletonImage src={item.img} alt={item.title} />
                  </View>
                  <Text style={styles.revisitCardTitle} numberOfLines={1}>
                    {item.title}
                  </Text>
                  <Text style={styles.revisitCardMeta} numberOfLines={1}>
                    {item.category}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}

        {groupedHistory.length === 0 ? (
          <View style={styles.endState}>
            <View style={styles.endIcon}>
              <ClipboardList size={24} color={theme.colors.subtle} strokeWidth={1.5} />
            </View>
            <Text style={styles.endText}>Your recent decisions will show up here.</Text>
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
                  <Pressable key={`${group.group}-${index}`} style={({ pressed }) => [styles.historyItem, pressed && styles.pressedCard]} onPress={() => navigation.navigate('Detail', { itemId: item.id, title: item.title, image: item.img })}>
                    <View style={styles.historyImageWrap}>
                      <SkeletonImage src={item.img} alt={item.title} />
                    </View>
                    <View style={styles.historyItemContent}>
                      <Text style={styles.historyItemTitle}>{item.title}</Text>
                      <Text style={styles.historyItemMeta}>
                        {item.time} / {item.category}
                      </Text>
                    </View>
                    <View style={[styles.statusBadge, item.status === 'Liked' ? styles.likedBadge : styles.skippedBadge]}>
                      <Heart size={10} color={item.status === 'Liked' ? theme.colors.primary : theme.colors.subtle} fill={item.status === 'Liked' ? theme.colors.primary : 'transparent'} strokeWidth={2} />
                      <Text style={[styles.statusText, item.status === 'Liked' ? styles.likedText : styles.skippedText]}>{item.status === 'Liked' ? 'Picked' : 'Passed'}</Text>
                    </View>
                  </Pressable>
                ))}
              </View>
            </View>
          ))
        )}

        {groupedHistory.length > 0 ? (
          <View style={styles.endState}>
            <View style={styles.endIcon}>
              <RefreshCw size={20} color={theme.colors.subtle} strokeWidth={1.5} />
            </View>
            <Text style={styles.endText}>All caught up.</Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    pressedCard: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
    topNav: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: t.spacing.md, height: t.topNavHeight, backgroundColor: t.colors.surface },
    backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
    navTitle: { ...t.typography.h2, color: t.colors.foreground },
    moreBtn: { width: 40, height: 40, alignItems: 'flex-end', justifyContent: 'center' },
    scrollView: { flex: 1 },
    scrollContent: { paddingHorizontal: t.spacing.md, paddingTop: t.spacing.lg, paddingBottom: t.spacing['2xl'] },
    summaryCard: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.md,
      gap: t.spacing.sm,
      marginBottom: t.spacing.md,
    },
    summaryEyebrow: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    summaryTitle: { ...t.typography.h1, color: t.colors.foreground },
    summaryStats: { flexDirection: 'row', gap: t.spacing.xs },
    summaryStat: {
      flex: 1,
      minHeight: 68,
      borderRadius: t.radius.md,
      backgroundColor: 'rgba(255,255,255,0.72)',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 2,
    },
    summaryStatValue: { ...t.typography.h1, color: t.colors.foreground },
    summaryStatLabel: { ...t.typography.micro, color: t.colors.subtle },
    tonightCard: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: t.spacing.sm,
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      marginBottom: t.spacing.lg,
    },
    tonightImage: { width: 84, height: 84, borderRadius: t.radius.md, overflow: 'hidden' },
    tonightCopy: { flex: 1, gap: 4 },
    tonightEyebrow: { ...t.typography.micro, color: t.colors.primaryDark, fontWeight: '700' },
    tonightTitle: { ...t.typography.h2, color: t.colors.foreground },
    tonightMeta: { ...t.typography.caption, color: t.colors.subtle },
    group: { marginBottom: t.spacing.xl },
    groupHeader: { flexDirection: 'row', alignItems: 'center', marginBottom: t.spacing.sm, gap: t.spacing.sm },
    groupLabel: { ...t.typography.caption, fontWeight: '700', color: t.colors.subtle },
    groupLine: { flex: 1, height: 1, backgroundColor: t.colors.border },
    groupItems: { gap: t.spacing.xs },
    revisitSection: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.radius.lg,
      padding: t.spacing.md,
      marginBottom: t.spacing.xl,
      gap: t.spacing.sm,
    },
    revisitHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
    revisitTitle: { ...t.typography.h2, color: t.colors.foreground },
    revisitHint: { ...t.typography.micro, color: t.colors.primary, fontWeight: '700' },
    revisitList: { flexDirection: 'row', gap: t.spacing.xs },
    revisitCard: { flex: 1, backgroundColor: t.colors.surfaceElevated, borderRadius: t.radius.md, padding: t.spacing.xs, gap: 8 },
    revisitThumb: { height: 72, borderRadius: t.radius.sm, overflow: 'hidden' },
    revisitCardTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    revisitCardMeta: { ...t.typography.micro, color: t.colors.subtle },
    historyItem: { minHeight: t.surface.listCardMinHeight, flexDirection: 'row', backgroundColor: t.colors.surfaceElevated, borderRadius: t.surface.cardRadius, padding: t.surface.insetCardPadding, gap: t.spacing.sm, alignItems: 'center' },
    historyImageWrap: { width: 52, height: 52, borderRadius: t.radius.sm, overflow: 'hidden' },
    historyItemContent: { flex: 1 },
    historyItemTitle: { ...t.typography.body, fontWeight: '700', color: t.colors.foreground },
    historyItemMeta: { ...t.typography.micro, color: t.colors.subtle, marginTop: 2 },
    statusBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: t.radius.full, paddingHorizontal: t.spacing.xs, paddingVertical: 5 },
    likedBadge: { backgroundColor: t.colors.primaryLight },
    skippedBadge: { backgroundColor: t.colors.borderLight },
    statusText: { ...t.typography.micro, fontWeight: '600' },
    likedText: { color: t.colors.primary },
    skippedText: { color: t.colors.subtle },
    endState: { alignItems: 'center', paddingTop: t.spacing['2xl'], paddingBottom: t.spacing.lg, gap: t.spacing.xs },
    endIcon: { width: 48, height: 48, borderRadius: t.radius.full, backgroundColor: t.colors.surface, alignItems: 'center', justifyContent: 'center', marginBottom: 4, ...t.shadows.sm },
    endText: { ...t.typography.caption, color: t.colors.subtle, textAlign: 'center' },
  });
}
