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
import { theme } from '../theme';
import { CUISINES } from '../data/mockData';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function OnboardingCuisines() {
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.xs,
  },
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
  cuisineGrid: { gap: theme.spacing.xs, marginBottom: theme.spacing.lg },
  cuisineCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
    borderWidth: 1.5,
    borderColor: 'transparent',
    ...theme.shadows.sm,
  },
  cuisineCardSelected: {
    backgroundColor: theme.colors.primaryLight,
    borderColor: theme.colors.primary,
  },
  cuisineLeft: { flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm },
  cuisineIcon: { fontSize: 18 },
  cuisineLabel: { ...theme.typography.body, fontWeight: '500', color: theme.colors.foreground },
  cuisineLabelSelected: { color: theme.colors.primaryDark, fontWeight: '600' },
  checkmark: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  checkmarkFilled: {
    width: 22,
    height: 22,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  banner: { borderRadius: theme.radius.lg, overflow: 'hidden', height: 128 },
  bannerImage: { width: '100%', height: '100%', position: 'absolute' },
  bannerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'flex-end',
    padding: theme.spacing.md,
  },
  bannerText: { ...theme.typography.caption, color: theme.colors.surface, fontWeight: '500', lineHeight: 18 },
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
