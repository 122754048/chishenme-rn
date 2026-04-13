import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { ArrowRight, Check, Circle } from 'lucide-react-native';
import { useApp } from '../context/AppContext';
import { SkeletonImage } from '../components/SkeletonImage';
import { CUISINES, SWIPE_CARDS } from '../data/mockData';
import type { RootStackParamList } from '../navigation/types';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function OnboardingCuisines() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { completeOnboarding, selectedCuisines, setCuisines } = useApp();
  const [selected, setSelected] = useState<string[]>(() => selectedCuisines);

  const toggleSelect = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  };

  const handleNext = async () => {
    await setCuisines(selected);
    navigation.navigate('OnboardingRestrictions');
  };

  const handleSkip = async () => {
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  const cuisineImages = CUISINES.map((item) => ({
    ...item,
    image: SWIPE_CARDS.find((card) => card.cuisineId === item.id)?.image ?? SWIPE_CARDS[0].image,
  }));

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <View style={styles.headerSpacer} />
        <Pressable
          onPress={handleSkip}
          accessibilityRole="button"
          accessibilityLabel="Skip for now"
          hitSlop={8}
          style={({ pressed }) => [pressed && styles.pressedChrome]}
        >
          <Text style={styles.skipText}>Skip for now</Text>
        </Pressable>
      </View>

      <View style={styles.progressContainer}>
        <View style={styles.progressTrack}>
          <View style={[styles.progressBar, { width: '50%' }]} />
        </View>
        <Text style={styles.stepLabel}>1/2</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Your deck starts here</Text>
          <Text style={styles.heroSummary}>{selected.length} picked so far</Text>
        </View>

        <Text style={styles.title}>Pick your favorites</Text>
        <Text style={styles.subtitle}>Build the first version of your deck.</Text>

        <View style={styles.cuisineGrid}>
          {cuisineImages.map((item) => {
            const isSelected = selected.includes(item.id);
            return (
              <Pressable
                key={item.id}
                style={({ pressed }) => [styles.cuisineCard, isSelected && styles.cuisineCardSelected, pressed && styles.pressedCard]}
                onPress={() => toggleSelect(item.id)}
                accessibilityRole="button"
                accessibilityLabel={`${item.label}${isSelected ? ', selected' : ', not selected'}`}
                accessibilityState={{ selected: isSelected }}
              >
                <View style={styles.cuisineImage}>
                  <SkeletonImage src={item.image} alt={item.label} />
                </View>
                <View style={styles.cuisineOverlay} />
                <View style={styles.cuisineCopy}>
                  <Text style={[styles.cuisineLabel, isSelected && styles.cuisineLabelSelected]}>{item.label}</Text>
                </View>
                <View style={styles.checkmark}>
                  {isSelected ? (
                    <View style={styles.checkmarkFilled}>
                      <Check size={14} color={theme.colors.surface} strokeWidth={3} />
                    </View>
                  ) : (
                    <Circle size={20} color={theme.colors.subtle} strokeWidth={1.5} />
                  )}
                </View>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable style={({ pressed }) => [styles.nextButton, pressed && styles.pressedCard]} onPress={handleNext} accessibilityRole="button" accessibilityLabel="Continue to dietary settings">
          <Text style={styles.nextButtonText}>Continue</Text>
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
    headerSpacer: { width: 40 },
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
    },
    heroEyebrow: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '700' },
    heroSummary: { ...t.typography.h2, color: t.colors.foreground, marginTop: 4 },
    title: { ...t.typography.display, color: t.colors.foreground, marginBottom: t.spacing.xs },
    subtitle: { ...t.typography.caption, color: t.colors.muted, marginBottom: t.spacing.lg },
    cuisineGrid: { gap: t.spacing.sm, marginBottom: t.spacing.lg },
    cuisineCard: {
      height: 116,
      borderRadius: t.surface.cardRadius,
      overflow: 'hidden',
      justifyContent: 'space-between',
      paddingHorizontal: t.surface.insetCardPadding,
      paddingVertical: t.surface.insetCardPadding,
      ...t.shadows.md,
    },
    cuisineCardSelected: {},
    cuisineImage: { ...StyleSheet.absoluteFillObject },
    cuisineOverlay: {
      ...StyleSheet.absoluteFillObject,
      backgroundColor: 'rgba(18, 14, 12, 0.34)',
    },
    cuisineCopy: { flex: 1, justifyContent: 'flex-end', zIndex: 1, paddingRight: t.spacing.sm },
    cuisineLabel: { ...t.typography.h2, fontWeight: '700', color: '#FFFFFF' },
    cuisineLabelSelected: { color: '#FFFFFF' },
    checkmark: { width: 28, height: 28, alignItems: 'center', justifyContent: 'center', zIndex: 1, alignSelf: 'flex-end' },
    checkmarkFilled: { width: 22, height: 22, borderRadius: t.radius.full, backgroundColor: t.colors.primary, alignItems: 'center', justifyContent: 'center' },
    footer: { paddingHorizontal: t.spacing.md, paddingVertical: t.spacing.md, backgroundColor: 'rgba(255,255,255,0.97)', borderTopWidth: 1, borderTopColor: t.colors.borderLight },
    nextButton: { backgroundColor: t.colors.primary, borderRadius: t.radius.full, paddingVertical: 15, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
    nextButtonText: { ...t.typography.body, fontWeight: '700', color: t.colors.surface },
    pressedCard: { opacity: t.interaction.pressedOpacity, transform: [{ scale: t.interaction.pressedScale }] },
    pressedChrome: { opacity: t.interaction.chipPressedOpacity },
  });
}
