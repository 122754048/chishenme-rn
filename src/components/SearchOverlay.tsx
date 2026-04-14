import React, { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Clock3, Search, TrendingUp, X } from 'lucide-react-native';
import { storage } from '../storage';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

interface SearchOverlayProps {
  visible: boolean;
  onClose: () => void;
  onSearch?: (query: string) => void;
}

const DEFAULT_RECENT_SEARCHES = ['ramen', 'healthy lunch', 'West Village', 'Thai'];
const TRENDING_TAGS = ['budget lunch', 'comfort dinner', 'late-night noodles', 'healthy bowls', 'dessert'];

function QuickGroup({
  icon,
  items,
  onSelect,
  styles,
}: {
  icon: React.ReactNode;
  items: string[];
  onSelect: (term: string) => void;
  styles: ReturnType<typeof makeStyles>;
}) {
  return (
    <View style={styles.quickGroup}>
      <View style={styles.quickGroupHeader}>
        <View style={styles.quickGroupIcon}>{icon}</View>
      </View>
      <View style={styles.chipGrid}>
        {items.map((term) => (
          <Pressable
            key={term}
            style={({ pressed }) => [styles.inlineChip, pressed && styles.pressedChip]}
            onPress={() => onSelect(term)}
            accessibilityRole="button"
            accessibilityLabel={`Search ${term}`}
          >
            <Text style={styles.inlineChipText}>{term}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

export function SearchOverlay({ visible, onClose, onSearch }: SearchOverlayProps) {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const [query, setQuery] = useState('');
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const userInteractedRef = useRef(false);

  useEffect(() => {
    async function loadRecentSearches() {
      try {
        const saved = await storage.getRecentSearches();
        if (!userInteractedRef.current) {
          setRecentSearches(saved);
        }
      } catch (error) {
        console.warn('[Teller]', 'Failed to read recent searches:', error);
      } finally {
        setHydrated(true);
      }
    }

    void loadRecentSearches();
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    void storage.setRecentSearches(recentSearches);
  }, [hydrated, recentSearches]);

  const handleSubmit = (term?: string) => {
    const trimmed = (term ?? query).trim();
    if (!trimmed) return;

    userInteractedRef.current = true;
    onSearch?.(trimmed);
    setRecentSearches((prev) => [trimmed, ...prev.filter((item) => item !== trimmed)].slice(0, 10));
    onClose();
  };

  const quickTerms = recentSearches.length > 0 ? recentSearches : DEFAULT_RECENT_SEARCHES;

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <SafeAreaView style={styles.safeArea} edges={['top', 'bottom']}>
        <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <View style={styles.grabber} />

          <View style={styles.header}>
            <View style={styles.searchBar}>
              <Search size={16} color={theme.colors.subtle} strokeWidth={1.8} />
              <TextInput
                style={styles.input}
                placeholder="dish, place, area"
                placeholderTextColor={theme.colors.subtle}
                value={query}
                onChangeText={setQuery}
                autoFocus
                returnKeyType="search"
                onSubmitEditing={() => handleSubmit()}
                accessibilityLabel="Search a dish, restaurant, or area"
              />
              {query.length > 0 ? (
                <Pressable onPress={() => setQuery('')} style={({ pressed }) => [styles.iconBtn, pressed && styles.pressedChrome]} accessibilityRole="button" accessibilityLabel="Clear search" hitSlop={8}>
                  <X size={14} color={theme.colors.subtle} strokeWidth={2} />
                </Pressable>
              ) : null}
            </View>
            <Pressable onPress={onClose} style={({ pressed }) => [styles.closeBtn, pressed && styles.pressedChrome]} accessibilityRole="button" accessibilityLabel="Close search" hitSlop={8}>
              <X size={18} color={theme.colors.foreground} strokeWidth={2} />
            </Pressable>
          </View>

          <View style={styles.content}>
            {query.trim().length > 0 ? (
              <Pressable style={({ pressed }) => [styles.submitCard, pressed && styles.pressedChip]} onPress={() => handleSubmit()}>
                <View>
                  <Text style={styles.submitLabel}>Search now</Text>
                  <Text style={styles.submitValue} numberOfLines={1}>
                    {query.trim()}
                  </Text>
                </View>
                <Search size={18} color={theme.colors.primary} strokeWidth={2} />
              </Pressable>
            ) : null}

            <View style={styles.groupHeader}>
              <Text style={styles.groupHeaderText}>Recent</Text>
            </View>
            <QuickGroup
              icon={<Clock3 size={14} color={theme.colors.subtle} strokeWidth={2} />}
              items={quickTerms}
              onSelect={handleSubmit}
              styles={styles}
            />
            <View style={styles.groupHeader}>
              <Text style={styles.groupHeaderText}>Trending</Text>
            </View>
            <QuickGroup
              icon={<TrendingUp size={14} color={theme.colors.primary} strokeWidth={2} />}
              items={TRENDING_TAGS}
              onSelect={handleSubmit}
              styles={styles}
            />
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    safeArea: { flex: 1, backgroundColor: t.colors.surface },
    container: { flex: 1, backgroundColor: t.colors.surface },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
    pressedChip: { opacity: t.interaction.chipPressedOpacity, backgroundColor: t.colors.border },
    grabber: {
      alignSelf: 'center',
      width: 40,
      height: 5,
      borderRadius: t.radius.full,
      backgroundColor: t.colors.border,
      marginTop: t.spacing.xs,
      marginBottom: t.spacing.sm,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: t.spacing.sm,
      paddingHorizontal: t.spacing.md,
      paddingBottom: t.spacing.sm,
    },
    searchBar: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      backgroundColor: t.colors.background,
      borderRadius: t.surface.cardRadius,
      paddingHorizontal: t.spacing.sm,
      height: t.surface.controlHeight,
      gap: t.spacing.xs,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    input: { flex: 1, ...t.typography.body, color: t.colors.foreground },
    iconBtn: { width: 28, height: 28, alignItems: 'center', justifyContent: 'center' },
    closeBtn: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: t.colors.background },
    content: { flex: 1, paddingHorizontal: t.spacing.md, gap: t.spacing.md },
    submitCard: {
      minHeight: 64,
      borderRadius: t.surface.cardRadius,
      backgroundColor: t.colors.primaryLight,
      paddingHorizontal: t.spacing.md,
      paddingVertical: t.spacing.sm,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    submitLabel: { ...t.typography.micro, color: t.colors.primaryDark, fontWeight: '700' },
    submitValue: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700', marginTop: 2 },
    groupHeader: { paddingTop: 6 },
    groupHeaderText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '700' },
    quickGroup: {
      backgroundColor: t.colors.surfaceElevated,
      borderRadius: t.surface.cardRadius,
      padding: t.surface.insetCardPadding,
      gap: t.spacing.sm,
    },
    quickGroupHeader: { flexDirection: 'row', alignItems: 'center' },
    quickGroupIcon: {
      width: 32,
      height: 32,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: t.colors.background,
    },
    chipGrid: { flex: 1, flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs },
    inlineChip: {
      backgroundColor: t.colors.background,
      minHeight: t.surface.compactChipHeight,
      paddingHorizontal: t.spacing.sm,
      paddingVertical: 6,
      borderRadius: t.radius.full,
      borderWidth: 1,
      borderColor: t.colors.borderLight,
      justifyContent: 'center',
    },
    inlineChipText: { ...t.typography.caption, color: t.colors.foreground, fontWeight: '600' },
  });
}
