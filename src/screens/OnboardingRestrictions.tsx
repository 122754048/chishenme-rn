import React, { useState } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated from 'react-native-reanimated';
import { ArrowLeft, ArrowRight, Info, Plus } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { theme } from '../theme';
import { MEATS, FLAVORS } from '../data/mockData';
import { useApp } from '../context/AppContext';

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
    <Pressable
      style={({ pressed }) => [
        styles.restrictionBtn,
        isSelected && styles.restrictionBtnSelected,
        pressed && { opacity: 0.85 },
      ]}
      onPress={onPress}
    >
      <Text style={styles.restrictionIcon}>{icon}</Text>
      <Text style={[styles.restrictionLabel, isSelected && styles.restrictionLabelSelected]}>
        {label}
      </Text>
    </Pressable>
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

  const handleSkip = async () => {
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}>
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Pressable onPress={handleSkip}>
          <Text style={styles.skipText}>Skip</Text>
        </Pressable>
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
            <Pressable style={({ pressed }) => [styles.customBtn, pressed && { opacity: 0.7 }]}>
              <Plus size={14} color={theme.colors.subtle} strokeWidth={2} />
              <Text style={styles.customBtnText}>Custom</Text>
            </Pressable>
          </View>
        </View>

        <View style={styles.infoBox}>
          <View style={styles.infoIcon}>
            <Info size={14} color={theme.colors.primary} strokeWidth={2} />
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
        <Pressable
          style={({ pressed }) => [styles.nextButton, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]}
          onPress={handleNext}
        >
          <Text style={styles.nextButtonText}>Next</Text>
          <ArrowRight size={16} color={theme.colors.surface} strokeWidth={2.5} />
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.xs,
  },
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  skipText: { ...theme.typography.caption, color: theme.colors.subtle, fontWeight: '500' },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.lg,
    gap: theme.spacing.xs,
  },
  progressTrack: { flex: 1, height: 4, backgroundColor: theme.colors.border, borderRadius: 2, overflow: 'hidden' },
  progressBar: { height: '100%', backgroundColor: theme.colors.primary, borderRadius: 2 },
  stepLabel: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.primary },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.lg },
  title: { ...theme.typography.display, color: theme.colors.foreground, marginBottom: theme.spacing.xs },
  subtitle: { ...theme.typography.body, color: theme.colors.muted, marginBottom: theme.spacing.lg },
  sectionCard: {
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    padding: theme.spacing.md,
    marginBottom: theme.spacing.md,
    ...theme.shadows.sm,
  },
  sectionTitle: { ...theme.typography.micro, fontWeight: '700', color: theme.colors.subtle, letterSpacing: 0.5, marginBottom: theme.spacing.sm },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs },
  restrictionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    borderRadius: theme.radius.md,
    borderWidth: 1.5,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.surface,
  },
  restrictionBtnSelected: {
    backgroundColor: theme.colors.primaryDark,
    borderColor: theme.colors.primaryDark,
  },
  restrictionIcon: { fontSize: 16 },
  restrictionLabel: { ...theme.typography.body, fontWeight: '500', color: theme.colors.foreground },
  restrictionLabelSelected: { color: theme.colors.surface },
  customBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    borderRadius: theme.radius.md,
    borderWidth: 1.5,
    borderColor: theme.colors.subtle,
    borderStyle: 'dashed',
    backgroundColor: theme.colors.surface,
  },
  customBtnText: { ...theme.typography.body, fontWeight: '500', color: theme.colors.subtle },
  infoBox: {
    flexDirection: 'row',
    backgroundColor: theme.colors.borderLight,
    borderRadius: theme.radius.md,
    padding: theme.spacing.sm,
    gap: theme.spacing.sm,
    alignItems: 'flex-start',
  },
  infoIcon: {
    width: 32,
    height: 32,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoContent: { flex: 1 },
  infoTitle: { ...theme.typography.caption, fontWeight: '700', color: theme.colors.foreground, marginBottom: 4 },
  infoBody: { ...theme.typography.caption, color: theme.colors.muted, lineHeight: 18 },
  footer: {
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.md,
    backgroundColor: theme.colors.surface,
    borderTopWidth: 1,
    borderTopColor: theme.colors.borderLight,
  },
  nextButton: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.full,
    paddingVertical: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  nextButtonText: { ...theme.typography.body, fontWeight: '700', color: theme.colors.surface },
});
