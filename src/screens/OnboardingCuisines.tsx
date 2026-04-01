import React, { useState } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  ScrollView,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated from 'react-native-reanimated';
import { Check, Circle, ArrowRight } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors, theme } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { CUISINES } from '../data/mockData';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function OnboardingCuisines() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { setCuisines, completeOnboarding } = useApp();
  const [selected, setSelected] = useState<string[]>(['Sichuan', 'Western']);

  const toggleSelect = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleNext = async () => {
    await setCuisines(selected);
    navigation.navigate('OnboardingRestrictions');
  };

  const handleSkip = async () => {
    await completeOnboarding();
    navigation.reset({ index: 0, routes: [{ name: 'MainTabs' }] });
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <View style={{ width: 40 }} />
        <Pressable onPress={handleSkip}>
          <Text style={styles.skipText}>Skip</Text>
        </Pressable>
      </View>

      <View style={styles.progressContainer}>
        <View style={styles.progressTrack}>
          <Animated.View style={[styles.progressBar, { width: '33.3%' }]} />
        </View>
        <Text style={styles.stepLabel}>1/3</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>
          Which cuisines do you{'\n'}like?
        </Text>
        <Text style={styles.subtitle}>Select multiple to personalize your food journey.</Text>

        <View style={styles.cuisineGrid}>
          {CUISINES.map((item) => {
            const isSelected = selected.includes(item.id);
            return (
              <Pressable
                key={item.id}
                style={({ pressed }) => [
                  styles.cuisineCard,
                  isSelected && styles.cuisineCardSelected,
                  pressed && { opacity: 0.85 },
                ]}
                onPress={() => toggleSelect(item.id)}
              >
                <View style={styles.cuisineLeft}>
                  <Text style={styles.cuisineIcon}>{item.icon}</Text>
                  <Text
                    style={[
                      styles.cuisineLabel,
                      isSelected && styles.cuisineLabelSelected,
                    ]}
                  >
                    {item.label}
                  </Text>
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

        <View style={styles.banner}>
          <Image
            source={{ uri: 'https://images.unsplash.com/photo-1540420773420-3366772f4999?w=800' }}
            style={styles.bannerImage}
          />
          <View style={styles.bannerOverlay}>
            <Text style={styles.bannerText}>
              Customize your palate to get the best{'\n'}recommendations every day.
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

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
  container: { flex: 1, backgroundColor: t.colors.background },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.xs,
  },
  skipText: { ...theme.typography.caption, color: t.colors.subtle, fontWeight: '500' },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    marginBottom: t.spacing.lg,
    gap: t.spacing.xs,
  },
  progressTrack: { flex: 1, height: 4, backgroundColor: t.colors.border, borderRadius: 2, overflow: 'hidden' },
  progressBar: { height: '100%', backgroundColor: t.colors.primary, borderRadius: 2 },
  stepLabel: { ...theme.typography.micro, fontWeight: '700', color: t.colors.primary },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: t.spacing.md, paddingBottom: t.spacing.lg },
  title: { ...theme.typography.display, color: t.colors.foreground, marginBottom: t.spacing.xs },
  subtitle: { ...theme.typography.body, color: t.colors.muted, marginBottom: t.spacing.lg },
  cuisineGrid: { gap: t.spacing.xs, marginBottom: t.spacing.lg },
  cuisineCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.sm,
    borderWidth: 1.5,
    borderColor: 'transparent',
    ...theme.shadows.sm,
  },
  cuisineCardSelected: {
    backgroundColor: t.colors.primaryLight,
    borderColor: t.colors.primary,
  },
  cuisineLeft: { flexDirection: 'row', alignItems: 'center', gap: t.spacing.sm },
  cuisineIcon: { fontSize: 18 },
  cuisineLabel: { ...theme.typography.body, fontWeight: '500', color: t.colors.foreground },
  cuisineLabelSelected: { color: t.colors.primaryDark, fontWeight: '600' },
  checkmark: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  checkmarkFilled: {
    width: 22,
    height: 22,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  banner: { borderRadius: t.radius.lg, overflow: 'hidden', height: 128 },
  bannerImage: { width: '100%', height: '100%', position: 'absolute' },
  bannerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'flex-end',
    padding: t.spacing.md,
  },
  bannerText: { ...theme.typography.caption, color: t.colors.surface, fontWeight: '500', lineHeight: 18 },
  footer: {
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.md,
    backgroundColor: t.colors.surface,
    borderTopWidth: 1,
    borderTopColor: t.colors.borderLight,
  },
  nextButton: {
    backgroundColor: t.colors.primary,
    borderRadius: t.radius.full,
    paddingVertical: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  nextButtonText: { ...theme.typography.body, fontWeight: '700', color: t.colors.surface },
});
}



