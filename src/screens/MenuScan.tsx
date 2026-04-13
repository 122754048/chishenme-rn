import React from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, Camera, ImageUp, ShieldAlert, Sparkles } from 'lucide-react-native';
import { useApp } from '../context/AppContext';
import type { RootStackParamList } from '../navigation/types';
import { menuScanService } from '../services/menuScan';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;
type MenuScanRouteProp = RouteProp<RootStackParamList, 'MenuScan'>;

export function MenuScan() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const route = useRoute<MenuScanRouteProp>();
  const { backendToken, selectedCuisines, selectedRestrictions } = useApp();
  const [loading, setLoading] = React.useState<'camera' | 'library' | null>(null);
  const [note, setNote] = React.useState<string | null>(null);
  const [items, setItems] = React.useState<Array<{
    name: string;
    description?: string | null;
    price?: string | null;
    recommendation: 'best' | 'safe' | 'avoid';
    reason: string;
    caution?: string | null;
  }>>([]);

  const restaurantName = route.params?.restaurantName ?? 'this restaurant';
  const profileChips = [...selectedCuisines.slice(0, 2), ...selectedRestrictions.slice(0, 2)].slice(0, 4);

  const runScan = async (source: 'camera' | 'library') => {
    if (!backendToken) {
      Alert.alert('Menu scan unavailable', 'Menu scan needs the app service configuration before it can process images.');
      return;
    }

    try {
      setLoading(source);
      setNote(null);
      const result = await menuScanService.scanFromSource(backendToken, source, {
        cuisines: selectedCuisines,
        restrictions: selectedRestrictions,
        restaurantName,
      });
      setItems(result.items);
      setNote(result.note ?? (result.source === 'fallback' ? 'Using a fallback recommendation set.' : null));
    } catch (error) {
      Alert.alert('Scan interrupted', error instanceof Error ? error.message : 'Please try again with a clearer image.');
    } finally {
      setLoading(null);
    }
  };

  const best = items.filter((item) => item.recommendation === 'best');
  const safe = items.filter((item) => item.recommendation === 'safe');
  const avoid = items.filter((item) => item.recommendation === 'avoid');

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.grabber} />
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && styles.pressedChrome]} accessibilityRole="button" accessibilityLabel="Go back">
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Text style={styles.headerTitle}>Scan a menu</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.content}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>For {restaurantName}</Text>
          <Text style={styles.heroTitle}>Scan a menu</Text>
          <Text style={styles.heroBody}>Photo or screenshot. We&apos;ll sort the safest picks first.</Text>
          {profileChips.length > 0 ? (
            <View style={styles.profileChipRow}>
              {profileChips.map((chip) => (
                <View key={chip} style={styles.profileChip}>
                  <Text style={styles.profileChipText}>{chip}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </View>

        <View style={styles.actionRow}>
          <Pressable
            style={({ pressed }) => [styles.actionCard, pressed && styles.actionCardPressed]}
            onPress={() => runScan('camera')}
            accessibilityRole="button"
            accessibilityLabel="Take a photo of a menu"
          >
            <View style={styles.actionIcon}>
              <Camera size={18} color={theme.colors.primary} strokeWidth={2} />
            </View>
            <Text style={styles.actionTitle}>{loading === 'camera' ? 'Opening camera...' : 'Take photo'}</Text>
            <Text style={styles.actionBody}>Printed menus</Text>
          </Pressable>

          <Pressable
            style={({ pressed }) => [styles.actionCard, pressed && styles.actionCardPressed]}
            onPress={() => runScan('library')}
            accessibilityRole="button"
            accessibilityLabel="Upload a screenshot of a menu"
          >
            <View style={styles.actionIcon}>
              <ImageUp size={18} color={theme.colors.primary} strokeWidth={2} />
            </View>
            <Text style={styles.actionTitle}>{loading === 'library' ? 'Opening photos...' : 'Upload screenshot'}</Text>
            <Text style={styles.actionBody}>Apps and websites</Text>
          </Pressable>
        </View>

        {note ? (
          <View style={styles.noteCard}>
            <ShieldAlert size={15} color={theme.colors.warning} strokeWidth={2} />
            <Text style={styles.noteText}>{note}</Text>
          </View>
        ) : null}

        {items.length > 0 ? (
          <View style={styles.summaryRow}>
            <View style={styles.summaryChip}>
              <Text style={styles.summaryChipValue}>{best.length}</Text>
              <Text style={styles.summaryChipLabel}>Best</Text>
            </View>
            <View style={styles.summaryChip}>
              <Text style={styles.summaryChipValue}>{safe.length}</Text>
              <Text style={styles.summaryChipLabel}>Safe</Text>
            </View>
            <View style={styles.summaryChip}>
              <Text style={styles.summaryChipValue}>{avoid.length}</Text>
              <Text style={styles.summaryChipLabel}>Avoid</Text>
            </View>
          </View>
        ) : null}

        {items.length === 0 ? (
          <View style={styles.emptyCard}>
            <Sparkles size={18} color={theme.colors.primary} strokeWidth={2} />
            <Text style={styles.emptyTitle}>No menu items yet</Text>
            <Text style={styles.emptyBody}>Your picks will show up here.</Text>
          </View>
        ) : (
          <>
            <Section title="Best for you" tone="best" items={best} styles={styles} />
            <Section title="Safe picks" tone="safe" items={safe} styles={styles} />
            <Section title="Avoid" tone="avoid" items={avoid} styles={styles} />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({
  title,
  tone,
  items,
  styles,
}: {
  title: string;
  tone: 'best' | 'safe' | 'avoid';
  items: Array<{
    name: string;
    description?: string | null;
    price?: string | null;
    reason: string;
    caution?: string | null;
  }>;
  styles: ReturnType<typeof makeStyles>;
}) {
  if (items.length === 0) return null;

  const toneWrapStyle =
    tone === 'best'
      ? styles.sectionToneBest
      : tone === 'safe'
        ? styles.sectionToneSafe
        : styles.sectionToneAvoid;
  const toneDotStyle =
    tone === 'best'
      ? styles.sectionToneDotBest
      : tone === 'safe'
        ? styles.sectionToneDotSafe
        : styles.sectionToneDotAvoid;
  const itemToneStyle =
    tone === 'best'
      ? styles.itemCardBest
      : tone === 'safe'
        ? styles.itemCardSafe
        : styles.itemCardAvoid;

  return (
    <View style={styles.section}>
      <View style={[styles.sectionToneWrap, toneWrapStyle]}>
        <View style={[styles.sectionToneDot, toneDotStyle]} />
        <Text style={styles.sectionTitle}>{title}</Text>
        <Text style={styles.sectionCount}>{items.length}</Text>
      </View>
      <View style={styles.sectionStack}>
        {items.map((item) => (
          <View key={`${title}-${item.name}`} style={[styles.itemCard, itemToneStyle]}>
            <View style={styles.itemHeader}>
              <Text style={styles.itemTitle}>{item.name}</Text>
              {item.price ? <Text style={styles.itemPrice}>{item.price}</Text> : null}
            </View>
            {item.description ? <Text style={styles.itemDescription}>{item.description}</Text> : null}
            <Text style={styles.itemReason}>{item.reason}</Text>
            {item.caution ? <Text style={styles.itemCaution}>{item.caution}</Text> : null}
          </View>
        ))}
      </View>
    </View>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
    grabber: {
      alignSelf: 'center',
      width: 40,
      height: 5,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.border,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.xs,
    },
    header: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      paddingBottom: t.spacing.sm,
    },
    backBtn: {
      width: 40,
      height: 40,
      alignItems: 'flex-start',
      justifyContent: 'center',
    },
    headerTitle: { ...t.typography.h2, color: t.colors.foreground },
    scrollView: { flex: 1 },
    content: { padding: t.spacing.md, gap: t.spacing.md, paddingBottom: t.spacing['2xl'] },
    heroCard: {
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.lg,
    },
    heroEyebrow: {
      ...t.typography.caption,
      color: t.colors.primary,
      fontWeight: '700',
      marginBottom: 6,
    },
    heroTitle: {
      ...t.typography.display,
      color: t.colors.foreground,
      marginBottom: 4,
    },
    heroBody: {
      ...t.typography.caption,
      color: t.colors.muted,
    },
    profileChipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
    profileChip: {
      minHeight: 28,
      borderRadius: t.radius.full,
      paddingHorizontal: 10,
      justifyContent: 'center',
      backgroundColor: t.colors.primaryLight,
    },
    profileChipText: { ...t.typography.micro, color: t.colors.primaryDark, fontWeight: '700' },
    actionRow: { flexDirection: 'row', gap: t.spacing.sm },
    actionCard: {
      flex: 1,
      backgroundColor: t.colors.surface,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      ...t.shadows.sm,
    },
    actionCardPressed: {
      opacity: t.interaction.pressedOpacity,
      transform: [{ scale: t.interaction.pressedScale }],
    },
    actionIcon: {
      width: 40,
      height: 40,
      borderRadius: 20,
      backgroundColor: t.colors.primaryLight,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: t.spacing.sm,
    },
    actionTitle: {
      ...t.typography.body,
      color: t.colors.foreground,
      fontWeight: '700',
      marginBottom: 4,
    },
    actionBody: {
      ...t.typography.micro,
      color: t.colors.muted,
    },
    noteCard: {
      flexDirection: 'row',
      gap: 10,
      alignItems: 'flex-start',
      backgroundColor: t.colors.warningLight,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
    },
    noteText: {
      ...t.typography.caption,
      color: t.colors.foreground,
      flex: 1,
      lineHeight: 18,
    },
    summaryRow: { flexDirection: 'row', gap: t.spacing.sm },
    summaryChip: {
      flex: 1,
      minHeight: 64,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.surfaceElevated,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 2,
    },
    summaryChipValue: { ...t.typography.h1, color: t.colors.foreground },
    summaryChipLabel: { ...t.typography.micro, color: t.colors.subtle },
    emptyCard: {
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.lg,
      alignItems: 'center',
      gap: 8,
    },
    emptyTitle: {
      ...t.typography.h2,
      color: t.colors.foreground,
    },
    emptyBody: {
      ...t.typography.caption,
      color: t.colors.muted,
      textAlign: 'center',
    },
    section: { gap: t.spacing.sm },
    sectionToneWrap: {
      minHeight: 36,
      borderRadius: t.radius.full,
      paddingHorizontal: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      alignSelf: 'flex-start',
    },
    sectionToneBest: { backgroundColor: t.colors.primaryLight },
    sectionToneSafe: { backgroundColor: t.colors.successLight },
    sectionToneAvoid: { backgroundColor: t.colors.warningLight },
    sectionToneDot: { width: 8, height: 8, borderRadius: 4 },
    sectionToneDotBest: { backgroundColor: t.colors.primary },
    sectionToneDotSafe: { backgroundColor: t.colors.success },
    sectionToneDotAvoid: { backgroundColor: t.colors.warning },
    sectionTitle: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '700' },
    sectionCount: { ...t.typography.micro, color: t.colors.subtle, fontWeight: '700' },
    sectionStack: { gap: t.spacing.sm },
    itemCard: {
      backgroundColor: t.colors.surface,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      ...t.shadows.sm,
    },
    itemCardBest: { backgroundColor: t.colors.surface },
    itemCardSafe: { backgroundColor: t.colors.surfaceMuted },
    itemCardAvoid: { backgroundColor: t.colors.surfaceMuted },
    itemHeader: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: t.spacing.sm,
      marginBottom: 4,
    },
    itemTitle: {
      ...t.typography.body,
      color: t.colors.foreground,
      fontWeight: '700',
      flex: 1,
    },
    itemPrice: {
      ...t.typography.caption,
      color: t.colors.subtle,
      fontWeight: '700',
    },
    itemDescription: {
      ...t.typography.caption,
      color: t.colors.muted,
      marginBottom: 6,
    },
    itemReason: {
      ...t.typography.caption,
      color: t.colors.foreground,
      lineHeight: 18,
      marginBottom: 4,
    },
    itemCaution: {
      ...t.typography.micro,
      color: t.colors.error,
      fontWeight: '700',
    },
  });
}
