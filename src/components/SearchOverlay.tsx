import React, { useState } from 'react';
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
import { Search, X, Clock, TrendingUp } from 'lucide-react-native';
import { theme } from '../theme';

interface SearchOverlayProps {
  visible: boolean;
  onClose: () => void;
  onSearch?: (query: string) => void;
}

const DEFAULT_RECENT_SEARCHES = ['Salmon Bowl', 'Ramen', 'Pizza near me'];
const TRENDING_TAGS = ['Healthy Salad', 'Sichuan Hot Pot', 'Matcha Latte', 'Poke Bowl', 'Dim Sum', 'Korean BBQ'];

export function SearchOverlay({ visible, onClose, onSearch }: SearchOverlayProps) {
  const [query, setQuery] = useState('');
  const [recentSearches, setRecentSearches] = useState<string[]>(DEFAULT_RECENT_SEARCHES);

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
              placeholder="Search for food or restaurants"
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
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
        </View>

        <View style={styles.content}>
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Recent Searches</Text>
              <Pressable onPress={handleClearRecent}>
                <Text style={styles.clearAll}>Clear</Text>
              </Pressable>
            </View>
            {recentSearches.map((term) => (
              <Pressable
                key={term}
                style={({ pressed }) => [styles.recentItem, pressed && { backgroundColor: theme.colors.borderLight }]}
                onPress={() => setQuery(term)}
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
                <Text style={styles.sectionTitle}>Trending Now</Text>
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.surface },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    paddingTop: theme.spacing.sm,
    paddingBottom: theme.spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderLight,
    gap: theme.spacing.sm,
  },
  searchBar: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: theme.colors.borderLight,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.sm,
    height: 40,
    gap: theme.spacing.xs,
  },
  input: { flex: 1, ...theme.typography.body, color: theme.colors.foreground },
  cancelBtn: { paddingHorizontal: 4 },
  cancelText: { ...theme.typography.body, color: theme.colors.primary, fontWeight: '500' },
  content: { flex: 1, paddingHorizontal: theme.spacing.md, paddingTop: theme.spacing.md },
  section: { marginBottom: theme.spacing.lg },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: theme.spacing.xs,
  },
  sectionTitle: {
    ...theme.typography.micro,
    fontWeight: '700',
    color: theme.colors.subtle,
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  clearAll: { ...theme.typography.caption, color: theme.colors.primary, fontWeight: '500' },
  trendingHeader: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  recentItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: theme.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.borderLight,
    gap: theme.spacing.sm,
  },
  recentText: { ...theme.typography.body, color: theme.colors.foreground },
  tagContainer: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs, marginTop: 4 },
  tag: {
    backgroundColor: theme.colors.borderLight,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 6,
    borderRadius: theme.radius.full,
  },
  tagText: { ...theme.typography.body, color: '#4B5563', fontWeight: '500' },
});
