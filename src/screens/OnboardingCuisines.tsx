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
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import { CUISINES } from '../data/mockData';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<RootStackParamList>;

export function OnboardingCuisines() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { setCuisines, completeOnboarding, selectedCuisines } = useApp();
  const [selected, setSelected] = useState<string[]>(() => selectedCuisines);

  const toggleSelect = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
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
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <View style={{ width: 40 }} />
        <Pressable
          onPress={handleSkip}
          accessibilityRole="button"
          accessibilityLabel="稍后完善口味偏好"
          hitSlop={8}
        >
          <Text style={styles.skipText}>稍后完善</Text>
        </Pressable>
      </View>

      <View style={styles.progressContainer}>
        <View style={styles.progressTrack}>
          <Animated.View style={[styles.progressBar, { width: '50%' }]} />
        </View>
        <Text style={styles.stepLabel}>1/2</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>
          你喜欢什么{'\n'}菜系？
        </Text>
        <Text style={styles.subtitle}>可以多选，系统会先帮你缩短最不可能喜欢的范围。</Text>

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
                accessibilityRole="button"
                accessibilityLabel={`${item.label}${isSelected ? '，已选择' : '，未选择'}`}
                accessibilityState={{ selected: isSelected }}
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
              先把你的口味说清楚，{'\n'}首页推荐才会像真正懂你的决策助手。
            </Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          style={({ pressed }) => [
            styles.nextButton,
            pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] },
          ]}
          onPress={handleNext}
          accessibilityRole="button"
          accessibilityLabel="进入下一步，设置忌口"
        >
          <Text style={styles.nextButtonText}>继续</Text>
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
    skipText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '500' },
    progressContainer: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: t.spacing.md,
      marginBottom: t.spacing.lg,
      gap: t.spacing.xs,
    },
    progressTrack: {
      flex: 1,
      height: 4,
      backgroundColor: t.colors.border,
      borderRadius: 2,
      overflow: 'hidden',
    },
    progressBar: { height: '100%', backgroundColor: t.colors.primary, borderRadius: 2 },
    stepLabel: { ...t.typography.micro, fontWeight: '700', color: t.colors.primary },
    scrollView: { flex: 1 },
    scrollContent: { paddingHorizontal: t.spacing.md, paddingBottom: 112 },
    title: { ...t.typography.display, color: t.colors.foreground, marginBottom: t.spacing.xs },
    subtitle: { ...t.typography.body, color: t.colors.muted, marginBottom: t.spacing.lg },
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
      ...t.shadows.sm,
    },
    cuisineCardSelected: {
      backgroundColor: t.colors.primaryLight,
      borderColor: t.colors.primary,
    },
    cuisineLeft: { flexDirection: 'row', alignItems: 'center', gap: t.spacing.sm },
    cuisineIcon: { fontSize: 18 },
    cuisineLabel: { ...t.typography.body, fontWeight: '500', color: t.colors.foreground },
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
    bannerText: {
      ...t.typography.caption,
      color: t.colors.surface,
      fontWeight: '500',
      lineHeight: 18,
    },
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
    nextButtonText: { ...t.typography.body, fontWeight: '700', color: t.colors.surface },
  });
}
