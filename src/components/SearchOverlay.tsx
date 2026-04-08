import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  Modal,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Search, X, Clock, TrendingUp } from 'lucide-react-native';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';

interface SearchOverlayProps {
  visible: boolean;
  onClose: () => void;
  onSearch?: (query: string) => void;
}

const DEFAULT_RECENT_SEARCHES = ['三文鱼碗', '拉面', '附近的披萨'];
const TRENDING_TAGS = ['健康沙拉', '四川火锅', '抹茶拿铁', '夏威夷拌饭', '早茶点心', '韩式烤肉'];
const RECENT_SEARCHES_KEY = '@chishenme/recent_searches';

export function SearchOverlay({ visible, onClose, onSearch }: SearchOverlayProps) {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const [query, setQuery] = useState('');
  const [recentSearches, setRecentSearches] = useState<string[]>(DEFAULT_RECENT_SEARCHES);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    async function loadRecentSearches() {
      try {
        const saved = await AsyncStorage.getItem(RECENT_SEARCHES_KEY);
        if (saved) setRecentSearches(JSON.parse(saved));
      } catch (error) {
        console.warn('Failed to read recent searches:', error);
      } finally {
        setHydrated(true);
      }
    }
    loadRecentSearches();
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    void AsyncStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(recentSearches));
  }, [recentSearches, hydrated]);

  const handleSubmit = () => {
    const trimmed = query.trim();
    if (trimmed.length > 0) {
      onSearch?.(trimmed);
      setRecentSearches((prev) => [trimmed, ...prev.filter((s) => s !== trimmed)].slice(0, 10));
    }
  };

  const handleClearRecent = () => {
    setRecentSearches([]);
  };

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.header}>
          <View style={styles.searchBar}>
            <Search size={16} color={theme.colors.subtle} strokeWidth={1.8} />
            <TextInput
              style={styles.input}
              placeholder="搜索美食或餐厅"
              placeholderTextColor={theme.colors.subtle}
              value={query}
              onChangeText={setQuery}
              autoFocus
              returnKeyType="search"
              onSubmitEditing={handleSubmit}
            />
            {query.length > 0 && (
              <Pressable onPress={() => setQuery('')} style={({ pressed }) => [pressed && { opacity: 0.5 }]}>
                <X size={14} color={theme.colors.subtle} strokeWidth={2} />
              </Pressable>
            )}
          </View>
          <Pressable onPress={onClose} style={({ pressed }) => [styles.cancelBtn, pressed && { opacity: 0.7 }]}>
            <Text style={styles.cancelText}>取消</Text>
          </Pressable>
        </View>

        <View style={styles.content}>
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>最近搜索</Text>
              <Pressable onPress={handleClearRecent}>
                <Text style={styles.clearAll}>清除</Text>
              </Pressable>
            </View>
            {recentSearches.map((term) => (
              <Pressable
                key={term}
                style={({ pressed }) => [styles.recentItem, pressed && { backgroundColor: theme.colors.borderLight }]}
                onPress={() => {
                  setQuery(term);
                  setRecentSearches((prev) => [term, ...prev.filter((s) => s !== term)].slice(0, 10));
                  onSearch?.(term);
                  onClose();
                }}
              >
                <Clock size={14} color={theme.colors.subtle} strokeWidth={1.8} />
                <Text style={styles.recentText}>{term}</Text>
              </Pressable>
            ))}
          </View>

          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <View style={styles.trendingHeader}>
                <TrendingUp size={14} color={theme.colors.primary} strokeWidth={2} />
                <Text style={styles.sectionTitle}>热门搜索</Text>
              </View>
            </View>
            <View style={styles.tagContainer}>
              {TRENDING_TAGS.map((tag) => (
                <Pressable
                  key={tag}
                  style={({ pressed }) => [styles.tag, pressed && { backgroundColor: theme.colors.border }]}
                  onPress={() => setQuery(tag)}
                >
                  <Text style={styles.tagText}>{tag}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
  container: { flex: 1, backgroundColor: t.colors.surface },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    paddingTop: t.spacing.sm,
    paddingBottom: t.spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
    gap: t.spacing.sm,
  },
  searchBar: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: t.colors.borderLight,
    borderRadius: t.radius.md,
    paddingHorizontal: t.spacing.sm,
    height: 40,
    gap: t.spacing.xs,
  },
  input: { flex: 1, ...t.typography.body, color: t.colors.foreground },
  cancelBtn: { paddingHorizontal: 4 },
  cancelText: { ...t.typography.body, color: t.colors.primary, fontWeight: '500' },
  content: { flex: 1, paddingHorizontal: t.spacing.md, paddingTop: t.spacing.md },
  section: { marginBottom: t.spacing.lg },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: t.spacing.xs,
  },
  sectionTitle: {
    ...t.typography.micro,
    fontWeight: '700',
    color: t.colors.subtle,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  clearAll: { ...t.typography.caption, color: t.colors.primary, fontWeight: '500' },
  trendingHeader: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  recentItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: t.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: t.colors.borderLight,
    gap: t.spacing.sm,
  },
  recentText: { ...t.typography.body, color: t.colors.foreground },
  tagContainer: { flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs, marginTop: 4 },
  tag: {
    backgroundColor: t.colors.borderLight,
    paddingHorizontal: t.spacing.sm,
    paddingVertical: 6,
    borderRadius: t.radius.full,
  },
  tagText: { ...t.typography.body, color: t.colors.foreground, fontWeight: '500' },
});
}
