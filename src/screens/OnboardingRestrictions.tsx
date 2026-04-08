import React, { useState } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView, TextInput } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated from 'react-native-reanimated';
import { ArrowLeft, ArrowRight, Info, Plus } from 'lucide-react-native';
import type { RootStackParamList } from '../navigation/types';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
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
        rbStyles.restrictionBtn,
        isSelected && rbStyles.restrictionBtnSelected,
        pressed && { opacity: 0.85 },
      ]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${label}${isSelected ? '，已选择' : '，未选择'}`}
      accessibilityState={{ selected: isSelected }}
    >
      <Text style={rbStyles.restrictionIcon}>{icon}</Text>
      <Text style={[rbStyles.restrictionLabel, isSelected && rbStyles.restrictionLabelSelected]}>
        {label}
      </Text>
    </Pressable>
  );
}

// Static styles for RestrictionButton (color is constant across themes)
const rbStyles = StyleSheet.create({
  restrictionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#E5E7EB',
    backgroundColor: '#FFFFFF',
  },
  restrictionBtnSelected: { backgroundColor: '#E85D2C', borderColor: '#E85D2C' },
  restrictionIcon: { fontSize: 16 },
  restrictionLabel: { fontSize: 14, lineHeight: 22, fontWeight: '500', color: '#374151' },
  restrictionLabelSelected: { color: '#FFFFFF' },
});

export function OnboardingRestrictions() {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const navigation = useNavigation<NavProp>();
  const { setRestrictions, completeOnboarding, selectedRestrictions } = useApp();
  const [selected, setSelected] = useState<string[]>(() => selectedRestrictions);
  const [customInput, setCustomInput] = useState('');

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleNext = async () => {
    await setRestrictions(selected);
    navigation.navigate('Upgrade');
  };

  const addCustomRestriction = () => {
    const trimmed = customInput.trim();
    if (!trimmed) return;
    const key = `custom:${trimmed}`;
    if (!selected.includes(key)) setSelected((prev) => [...prev, key]);
    setCustomInput('');
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
          style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}
          accessibilityRole="button"
          accessibilityLabel="返回菜系选择"
          hitSlop={8}
        >
          <ArrowLeft size={20} color={theme.colors.foreground} strokeWidth={2} />
        </Pressable>
        <Pressable onPress={handleSkip} accessibilityRole="button" accessibilityLabel="稍后完善忌口" hitSlop={8}>
          <Text style={styles.skipText}>稍后完善</Text>
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
          有什么{'\n'}忌口吗？
        </Text>
        <Text style={styles.subtitle}>
          告诉我们你的饮食限制或想要避开的食材。
        </Text>

        <View style={styles.sectionCard}>
          <Text style={styles.sectionTitle}>肉类</Text>
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
          <Text style={styles.sectionTitle}>口味与忌口</Text>
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
            <Pressable
              style={({ pressed }) => [styles.customBtn, pressed && { opacity: 0.7 }]}
              onPress={() => toggle('custom')}
              accessibilityRole="button"
              accessibilityLabel={selected.includes('custom') ? '关闭自定义忌口输入' : '添加自定义忌口'}
            >
              <Plus size={14} color={theme.colors.subtle} strokeWidth={2} />
              <Text style={styles.customBtnText}>{selected.includes('custom') ? '已添加自定义' : '自定义'}</Text>
            </Pressable>
          </View>
          {selected.includes('custom') && (
            <View style={styles.customComposer}>
              <TextInput
                style={styles.customInput}
                placeholder="输入自定义忌口，如：香菜"
                placeholderTextColor={theme.colors.subtle}
                value={customInput}
                onChangeText={setCustomInput}
                onSubmitEditing={addCustomRestriction}
                returnKeyType="done"
                accessibilityLabel="自定义忌口"
              />
              <Pressable
                style={styles.customAddBtn}
                onPress={addCustomRestriction}
                accessibilityRole="button"
                accessibilityLabel="添加自定义忌口"
              >
                <Text style={styles.customAddBtnText}>添加</Text>
              </Pressable>
            </View>
          )}
          {selected.filter((s) => s.startsWith('custom:')).map((tag) => (
            <Pressable
              key={tag}
              style={styles.customTag}
              onPress={() => toggle(tag)}
              accessibilityRole="button"
              accessibilityLabel={`移除自定义忌口 ${tag.replace('custom:', '')}`}
            >
              <Text style={styles.customTagText}>{tag.replace('custom:', '')} ×</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.infoBox}>
          <View style={styles.infoIcon}>
            <Info size={14} color={theme.colors.primary} strokeWidth={2} />
          </View>
          <View style={styles.infoContent}>
            <Text style={styles.infoTitle}>为什么要问这些？</Text>
            <Text style={styles.infoBody}>
              我们会过滤掉含有这些食材的菜品，确保每一道推荐都安全又美味。
            </Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          style={({ pressed }) => [styles.nextButton, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]}
          onPress={handleNext}
          accessibilityRole="button"
          accessibilityLabel="进入下一步，选择升级方案"
        >
          <Text style={styles.nextButtonText}>下一步</Text>
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
  backBtn: { width: 40, height: 40, alignItems: 'flex-start', justifyContent: 'center' },
  skipText: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '500' },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: t.spacing.md,
    marginBottom: t.spacing.lg,
    gap: t.spacing.xs,
  },
  progressTrack: { flex: 1, height: 4, backgroundColor: t.colors.border, borderRadius: 2, overflow: 'hidden' },
  progressBar: { height: '100%', backgroundColor: t.colors.primary, borderRadius: 2 },
  stepLabel: { ...t.typography.micro, fontWeight: '700', color: t.colors.primary },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: t.spacing.md, paddingBottom: 112 },
  title: { ...t.typography.display, color: t.colors.foreground, marginBottom: t.spacing.xs },
  subtitle: { ...t.typography.body, color: t.colors.muted, marginBottom: t.spacing.lg },
  sectionCard: {
    backgroundColor: t.colors.surface,
    borderRadius: t.radius.md,
    padding: t.spacing.md,
    marginBottom: t.spacing.md,
    ...t.shadows.sm,
  },
  sectionTitle: { ...t.typography.micro, fontWeight: '700', color: t.colors.subtle, letterSpacing: 0.5, marginBottom: t.spacing.sm },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: t.spacing.xs },
  restrictionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.sm,
    borderRadius: t.radius.md,
    borderWidth: 1.5,
    borderColor: t.colors.border,
    backgroundColor: t.colors.surface,
  },
  restrictionBtnSelected: {
    backgroundColor: t.colors.primaryDark,
    borderColor: t.colors.primaryDark,
  },
  restrictionIcon: { fontSize: 16 },
  restrictionLabel: { ...t.typography.body, fontWeight: '500', color: t.colors.foreground },
  restrictionLabelSelected: { color: t.colors.surface },
  customBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: t.spacing.md,
    paddingVertical: t.spacing.sm,
    borderRadius: t.radius.md,
    borderWidth: 1.5,
    borderColor: t.colors.subtle,
    borderStyle: 'dashed',
    backgroundColor: t.colors.surface,
  },
  customBtnText: { ...t.typography.body, fontWeight: '500', color: t.colors.subtle },
  customComposer: { flexDirection: 'row', gap: t.spacing.xs, marginTop: t.spacing.sm },
  customInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: t.colors.border,
    borderRadius: t.radius.md,
    paddingHorizontal: t.spacing.sm,
    paddingVertical: t.spacing.xs,
    color: t.colors.foreground,
    ...t.typography.body,
  },
  customAddBtn: {
    backgroundColor: t.colors.primary,
    borderRadius: t.radius.md,
    paddingHorizontal: t.spacing.sm,
    justifyContent: 'center',
  },
  customAddBtnText: { ...t.typography.caption, color: t.colors.surface, fontWeight: '700' },
  customTag: {
    marginTop: t.spacing.xs,
    alignSelf: 'flex-start',
    backgroundColor: t.colors.primaryLight,
    borderRadius: t.radius.full,
    paddingHorizontal: t.spacing.sm,
    paddingVertical: 6,
  },
  customTagText: { ...t.typography.caption, color: t.colors.primaryDark, fontWeight: '600' },
  infoBox: {
    flexDirection: 'row',
    backgroundColor: t.colors.borderLight,
    borderRadius: t.radius.md,
    padding: t.spacing.sm,
    gap: t.spacing.sm,
    alignItems: 'flex-start',
  },
  infoIcon: {
    width: 32,
    height: 32,
    borderRadius: t.radius.full,
    backgroundColor: t.colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoContent: { flex: 1 },
  infoTitle: { ...t.typography.caption, fontWeight: '700', color: t.colors.foreground, marginBottom: 4 },
  infoBody: { ...t.typography.caption, color: t.colors.muted, lineHeight: 18 },
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
