import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated from 'react-native-reanimated';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
import { MEATS, FLAVORS } from '../data/mockData';
import { useApp } from '../context/AppContext';

// Issue #17: Removed unused imports: useAnimatedStyle, withTiming.

type NavProp = NativeStackNavigationProp<RootStackParamList>;

function RestrictionButton({
  icon,
  label,
  isSelected,
  onPress,
}: {
  icon: string;
  label: string;
  isSelected: boolean;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      style={[styles.restrictionBtn, isSelected && styles.restrictionBtnSelected]}
      onPress={onPress}
      activeOpacity={0.7}
    >
      <Text style={styles.restrictionIcon}>{icon}</Text>
      <Text
        style={[
          styles.restrictionLabel,
          isSelected && styles.restrictionLabelSelected,
        ]}
      >
        {label}
      </Text>
    </TouchableOpacity>
  );
}

export function OnboardingRestrictions() {
  const navigation = useNavigation<NavProp>();
  const { setRestrictions, completeOnboarding } = useApp();
  const [selected, setSelected] = useState<string[]>(['spicy']);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleNext = async () => {
    await setRestrictions(selected);
    navigation.navigate('Upgrade');
  };

  // Issue #10: Skip now marks onboarding complete so user doesn't see it again.
  const handleSkip = async () => {
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backIcon}>←</Text>
        </TouchableOpacity>
        <Text style={styles.skipText} onPress={handleSkip}>
          Skip
        </Text>
      </View>

      <View style={styles.progressContainer}>
        <View style={styles.progressTrack}>
          <Animated.View style={[styles.progressBar, { width: '66.6%' }]} />
        </View>
        <Text style={styles.stepLabel}>2/3</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>
          Any dietary{'\n'}restrictions?
        </Text>
        <Text style={styles.subtitle}>
          Tell us about your dietary restrictions or ingredients you'd like to avoid.
        </Text>

        {/* Meats */}
        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>MEATS</Text>
          <View style={styles.grid}>
            {MEATS.map((item) => (
              <RestrictionButton
                key={item.id}
                icon={item.icon}
                label={item.label}
                isSelected={selected.includes(item.id)}
                onPress={() => toggle(item.id)}
              />
            ))}
          </View>
        </View>

        {/* Flavors & Restrictions */}
        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>FLAVORS & RESTRICTIONS</Text>
          <View style={styles.grid}>
            {FLAVORS.map((item) => (
              <RestrictionButton
                key={item.id}
                icon={item.icon}
                label={item.label}
                isSelected={selected.includes(item.id)}
                onPress={() => toggle(item.id)}
              />
            ))}
            <TouchableOpacity style={styles.customBtn} activeOpacity={0.7}>
              <Text style={styles.customBtnText}>+ Custom</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Info box */}
        <View style={styles.infoBox}>
          <View style={styles.infoIcon}>
            <Text style={styles.infoIconText}>ℹ️</Text>
          </View>
          <View style={styles.infoContent}>
            <Text style={styles.infoTitle}>Why ask this?</Text>
            <Text style={styles.infoBody}>
              We'll filter out dishes containing these items to ensure every recommendation is safe and delicious for you.
            </Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <TouchableOpacity style={styles.nextButton} onPress={handleNext} activeOpacity={0.8}>
          <Text style={styles.nextButtonText}>Next</Text>
          <Text style={styles.arrowIcon}>→</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.surface },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  backIcon: { fontSize: 22, color: '#374151' },
  skipText: { fontSize: 13, color: '#9ca3af', fontWeight: '500' },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    marginBottom: 24,
    gap: 8,
  },
  progressTrack: {
    flex: 1,
    height: 4,
    backgroundColor: '#e5e7eb',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressBar: {
    height: '100%',
    backgroundColor: theme.colors.brand,
    borderRadius: 2,
  },
  stepLabel: { fontSize: 11, fontWeight: '700', color: theme.colors.brand },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: 16, paddingBottom: 24 },
  title: {
    fontSize: 26,
    fontWeight: '700',
    color: theme.colors.foreground,
    marginBottom: 8,
    lineHeight: 34,
  },
  subtitle: { fontSize: 14, color: '#6b7280', marginBottom: 24 },
  sectionCard: {
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  sectionTitle: {
    fontSize: 11,
    fontWeight: '700',
    color: '#9ca3af',
    letterSpacing: 0.5,
    marginBottom: 12,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  restrictionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e5e7eb',
    backgroundColor: '#ffffff',
  },
  restrictionBtnSelected: {
    backgroundColor: '#2E7D32',
    borderColor: '#2E7D32',
  },
  restrictionIcon: { fontSize: 16 },
  restrictionLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#374151',
  },
  restrictionLabelSelected: { color: '#ffffff' },
  customBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#d1d5db',
    borderStyle: 'dashed',
    backgroundColor: '#ffffff',
  },
  customBtnText: { fontSize: 14, fontWeight: '500', color: '#9ca3af' },
  infoBox: {
    flexDirection: 'row',
    backgroundColor: '#f3f4f6',
    borderRadius: 14,
    padding: 14,
    gap: 12,
    alignItems: 'flex-start',
  },
  infoIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: theme.colors.brandLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoIconText: { fontSize: 14 },
  infoContent: { flex: 1 },
  infoTitle: { fontSize: 12, fontWeight: '700', color: theme.colors.foreground, marginBottom: 4 },
  infoBody: { fontSize: 11, color: '#6b7280', lineHeight: 16 },
  footer: {
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
  },
  nextButton: {
    backgroundColor: theme.colors.brandAccent,
    borderRadius: 30,
    paddingVertical: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  nextButtonText: { color: '#ffffff', fontSize: 15, fontWeight: '700' },
  arrowIcon: { color: '#ffffff', fontSize: 16, fontWeight: '700' },
});
