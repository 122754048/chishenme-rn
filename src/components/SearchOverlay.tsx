import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Modal,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
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
      // Add to recent searches (avoid duplicates, keep at top)
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
            <Text style={styles.searchIcon}>🔍</Text>
            <TextInput
              style={styles.input}
              placeholder="Search for food or restaurants"
              placeholderTextColor="#9ca3af"
              value={query}
              onChangeText={setQuery}
              autoFocus
              returnKeyType="search"
              onSubmitEditing={handleSubmit}
            />
            {query.length > 0 && (
              <TouchableOpacity onPress={() => setQuery('')}>
                <Text style={styles.clearBtn}>✕</Text>
              </TouchableOpacity>
            )}
          </View>
          <TouchableOpacity onPress={onClose} style={styles.cancelBtn}>
            <Text style={styles.cancelText}>Cancel</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.content}>
          {/* Recent Searches */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Recent Searches</Text>
              <TouchableOpacity onPress={handleClearRecent}>
                <Text style={styles.clearAll}>Clear</Text>
              </TouchableOpacity>
            </View>
            {recentSearches.map((term) => (
              <TouchableOpacity
                key={term}
                style={styles.recentItem}
                onPress={() => setQuery(term)}
              >
                <Text style={styles.clockIcon}>🕐</Text>
                <Text style={styles.recentText}>{term}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Trending */}
          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.trendingIcon}>📈</Text>
              <Text style={styles.sectionTitle}>Trending Now</Text>
            </View>
            <View style={styles.tagContainer}>
              {TRENDING_TAGS.map((tag) => (
                <TouchableOpacity
                  key={tag}
                  style={styles.tag}
                  onPress={() => setQuery(tag)}
                >
                  <Text style={styles.tagText}>{tag}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
    gap: 12,
  },
  searchBar: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f3f4f6',
    borderRadius: 10,
    paddingHorizontal: 12,
    height: 40,
    gap: 8,
  },
  searchIcon: {
    fontSize: 14,
  },
  input: {
    flex: 1,
    fontSize: 15,
    color: '#374151',
  },
  clearBtn: {
    fontSize: 12,
    color: '#9ca3af',
  },
  cancelBtn: {
    paddingHorizontal: 4,
  },
  cancelText: {
    fontSize: 15,
    color: theme.colors.brand,
    fontWeight: '500',
  },
  content: {
    flex: 1,
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  section: {
    marginBottom: 24,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: '700',
    color: '#9ca3af',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  clearAll: {
    fontSize: 12,
    color: theme.colors.brand,
    fontWeight: '500',
  },
  trendingIcon: {
    fontSize: 14,
    marginRight: 4,
  },
  recentItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#fafafa',
    gap: 12,
  },
  clockIcon: {
    fontSize: 14,
  },
  recentText: {
    fontSize: 15,
    color: '#374151',
  },
  tagContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 4,
  },
  tag: {
    backgroundColor: '#f3f4f6',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  tagText: {
    fontSize: 14,
    color: '#4b5563',
    fontWeight: '500',
  },
});
