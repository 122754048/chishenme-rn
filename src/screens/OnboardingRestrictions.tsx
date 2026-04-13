import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowLeft, ArrowRight, Plus } from 'lucide-react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import { useApp } from '../context/AppContext';
import { FLAVORS, MEATS, SWIPE_CARDS } from '../data/mockData';
import type { RootStackParamList } from '../navigation/types';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { buildManualAreaContext } from '../utils/location';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

function RestrictionButton({
  label,
  isSelected,
  onPress,
  theme,
}: {
  label: string;
  isSelected: boolean;
  onPress: () => void;
  theme: AppTheme;
}) {
  return (
    <Pressable
      style={({ pressed }) => [
        restrictionStyles.button,
        {
          width: '48%',
          minHeight: 64,
          borderRadius: theme.surface.cardRadius,
          borderColor: isSelected ? theme.colors.primary : theme.colors.borderLight,
          backgroundColor: isSelected ? theme.colors.primaryLight : theme.colors.surfaceElevated,
        },
        pressed && {
          opacity: theme.interaction.pressedOpacity,
          transform: [{ scale: theme.interaction.pressedScale }],
        },
      ]}
      onPress={onPress}
    >
      <Text style={[restrictionStyles.label, { color: isSelected ? theme.colors.primaryDark : theme.colors.foreground }]}>{label}</Text>
    </Pressable>
  );
}

const restrictionStyles = StyleSheet.create({
  button: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderWidth: 1,
  },
  label: {
    fontSize: 14,
    lineHeight: 22,
    fontWeight: '600',
  },
});

export function OnboardingRestrictions() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { completeOnboarding, saveAreaPreset, savedAreas, selectedRestrictions, setLocationSelection, setRestrictions } = useApp();
  const [selected, setSelected] = useState<string[]>(() => selectedRestrictions);
  const [customInput, setCustomInput] = useState('');
  const [homeArea, setHomeArea] = useState(savedAreas.home?.query ?? '');
  const [workArea, setWorkArea] = useState(savedAreas.work?.query ?? '');

  const toggle = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  };

  const addCustomRestriction = () => {
    const trimmed = customInput.trim();
    if (!trimmed) return;
    const key = `custom:${trimmed}`;
    if (!selected.includes(key)) {
      setSelected((prev) => [...prev, key]);
    }
    setCustomInput('');
  };

  const finish = async () => {
    await setRestrictions(selected);

    if (homeArea.trim()) {
      await saveAreaPreset('home', { label: 'Home', query: homeArea.trim() });
    }
    if (workArea.trim()) {
      await saveAreaPreset('work', { label: 'Work', query: workArea.trim() });
    }

    const nextArea = homeArea.trim() || workArea.trim();
    if (nextArea) {
      await setLocationSelection(buildManualAreaContext(nextArea));
    }

    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  const handleSkip = async () => {
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <Pressable
          onPress={() => navigation.goBack()}
          style={({ pressed }) => [styles.backBtn, pressed && styles.pressedChrome]}
          accessibilityRole="button"
          accessibilityLabel="Back to cuisine preferences"
          hitSlop={8}
        >
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Pressable onPress={handleSkip} style={({ pressed }) => [pressed && styles.pressedChrome]} accessibilityRole="button" accessibilityLabel="Skip for now" hitSlop={8}>
          <Text style={styles.skipText}>Skip for now</Text>
        </Pressable>
      </View>

      <View style={styles.progressContainer}>
        <View style={styles.progressTrack}>
          <View style={[styles.progressBar, { width: '100%' }]} />
        </View>
        <Text style={styles.stepLabel}>2/2</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Finish your defaults</Text>
          <View style={styles.heroStrip}>
            <View style={styles.heroThumb}>
              <SkeletonImage src={SWIPE_CARDS[0].image} alt="Preference preview" />
            </View>
            <View style={styles.heroThumb}>
              <SkeletonImage src={SWIPE_CARDS[3].image} alt="Preference preview" />
            </View>
          </View>
          <View style={styles.heroStats}>
            <View style={styles.heroStat}>
              <Text style={styles.heroStatValue}>{selected.length}</Text>
              <Text style={styles.heroStatLabel}>Filters</Text>
            </View>
            <View style={styles.heroStat}>
              <Text style={styles.heroStatValue}>{homeArea.trim() || workArea.trim() ? '1' : '0'}</Text>
              <Text style={styles.heroStatLabel}>Areas</Text>
            </View>
          </View>
        </View>

        <Text style={styles.title}>Anything you avoid?</Text>
        <Text style={styles.subtitle}>We will filter these out.</Text>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Common restrictions</Text>
          <View style={styles.grid}>
            {[...MEATS, ...FLAVORS].map((item) => (
              <RestrictionButton key={item.id} label={item.label} isSelected={selected.includes(item.id)} onPress={() => toggle(item.id)} theme={theme} />
            ))}
          </View>
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Add your own</Text>
          <View style={styles.customComposer}>
            <TextInput
              style={styles.customInput}
              placeholder="For example: shellfish or cilantro"
              placeholderTextColor={theme.colors.subtle}
              value={customInput}
              onChangeText={setCustomInput}
              onSubmitEditing={addCustomRestriction}
              returnKeyType="done"
              accessibilityLabel="Add a custom dietary restriction"
            />
            <Pressable
              style={({ pressed }) => [styles.customAddBtn, pressed && styles.pressedCard]}
              onPress={addCustomRestriction}
              accessibilityRole="button"
              accessibilityLabel="Add custom restriction"
            >
              <Plus size={14} color={theme.colors.surface} strokeWidth={2} />
            </Pressable>
          </View>
          <View style={styles.customTags}>
            {selected.filter((item) => item.startsWith('custom:')).map((tag) => (
              <Pressable
                key={tag}
                style={({ pressed }) => [styles.customTag, pressed && styles.pressedChrome]}
                onPress={() => toggle(tag)}
                accessibilityRole="button"
                accessibilityLabel={`Remove ${tag.replace('custom:', '')}`}
              >
                <Text style={styles.customTagText}>{tag.replace('custom:', '')} x</Text>
              </Pressable>
            ))}
          </View>
        </View>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>Saved areas</Text>
          <TextInput
            style={styles.areaInput}
            placeholder="Home area or neighborhood"
            placeholderTextColor={theme.colors.subtle}
            value={homeArea}
            onChangeText={setHomeArea}
            accessibilityLabel="Home area"
          />
          <TextInput
            style={styles.areaInput}
            placeholder="Work area or neighborhood"
            placeholderTextColor={theme.colors.subtle}
            value={workArea}
            onChangeText={setWorkArea}
            accessibilityLabel="Work area"
          />
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={({ pressed }) => [styles.nextButton, pressed && styles.pressedCard]} onPress={finish} accessibilityRole="button" accessibilityLabel="Finish setup and open the app">
          <Text style={styles.nextButtonText}>Start deciding</Text>
          <ArrowRight size={16} color={theme.colors.surface} strokeWidth={2.5} />
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    container: { flex: 1, backgroundColor: t.colors.background },
    header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: t.spacing.md, paddingVertical: t.spacing.xs },
    backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
    skipText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600' },
    progressContainer: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: t.spacing.md, marginBottom: t.spacing.lg, gap: t.spacing.xs },
    progressTrack: { flex: 1, height: 4, backgroundColor: t.colors.border, borderRadius: 2, overflow: 'hidden' },
    progressBar: { height: '100%', backgroundColor: t.colors.primary, borderRadius: 2 },
    stepLabel: { ...t.typography.micro, fontWeight: '700', color: t.colors.primary },
    scrollView: { flex: 1 },
    scrollContent: { paddingHorizontal: t.spacing.md, paddingBottom: 112 },
    heroCard: {
      backgroundColor: t.colors.primaryLight,
      borderRadius: t.surface.cardRadius,
      padding: t.spacing.md,
      marginBottom: t.spacing.lg,
      gap: t.spacing.sm,
    },
    heroEyebrow: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    heroStrip: { flexDirection: 'row', gap: t.spacing.xs },
    heroThumb: { flex: 1, height: 92, borderRadius: t.radius.md, overflow: 'hidden' },
    heroStats: { flexDirection: 'row', gap: t.spacing.sm },
    heroStat: {
      flex: 1,
      minHeight: 64,
      borderRadius: t.radius.md,
      backgroundColor: t.colors.surfaceElevated,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 2,
    },
    heroStatValue: { ...t.typography.h1, color: t.colors.foreground },
    heroStatLabel: { ...t.typography.micro, color: t.colors.subtle },
    title: { ...t.typography.display, color: t.colors.foreground, marginBottom: t.spacing.xs },
    subtitle: { ...t.typography.caption, color: t.colors.muted, marginBottom: t.spacing.lg },
    sectionCard: { backgroundColor: t.colors.surfaceElevated, borderRadius: t.surface.cardRadius, padding: t.surface.insetCardPadding, marginBottom: t.spacing.md },
    sectionTitle: { ...t.typography.caption, fontWeight: '700', color: t.colors.foreground, marginBottom: t.spacing.sm },
    grid: { flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs },
    customComposer: { flexDirection: 'row', gap: t.spacing.xs, marginBottom: t.spacing.sm },
    customInput: { flex: 1, borderWidth: 1, borderColor: t.colors.border, borderRadius: t.radius.md, paddingHorizontal: t.spacing.sm, paddingVertical: t.spacing.sm, color: t.colors.foreground, ...t.typography.body },
    customAddBtn: { width: 44, borderRadius: t.radius.md, backgroundColor: t.colors.primary, alignItems: 'center', justifyContent: 'center' },
    customTags: { flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs },
    customTag: { backgroundColor: t.colors.primaryLight, borderRadius: t.radius.full, paddingHorizontal: t.spacing.sm, paddingVertical: 6 },
    customTagText: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '600' },
    areaInput: { borderWidth: 1, borderColor: t.colors.border, borderRadius: t.radius.md, paddingHorizontal: t.spacing.sm, paddingVertical: t.spacing.sm, color: t.colors.foreground, ...t.typography.body, marginBottom: t.spacing.xs },
    footer: { paddingHorizontal: t.spacing.md, paddingVertical: t.spacing.md, backgroundColor: 'rgba(255,255,255,0.97)', borderTopWidth: 1, borderTopColor: t.colors.borderLight },
    nextButton: { backgroundColor: t.colors.primary, borderRadius: t.radius.full, paddingVertical: 15, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
    nextButtonText: { ...t.typography.body, fontWeight: '700', color: t.colors.surface },
    pressedCard: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
  });
}
