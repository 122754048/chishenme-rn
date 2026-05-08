/**
 * Chip
 *
 * Extracted from repeated filter-chip / tag-chip patterns found in:
 *   - src/screens/Explore.tsx  (filterChip / savedAreaChip / summarySignal)
 *   - src/screens/Home.tsx     (areaPill / scanAction / statusPill)
 *
 * Usage:
 *   <Chip label="Quick" onPress={() => setScenario('Quick')} selected={scenario === 'Quick'} />
 *   <Chip label="For two" icon={<Users size={14} />} selected={forTwo} onPress={toggle} />
 *   <Chip label="Static tag" />
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

export interface ChipProps {
  label: string;
  /** Whether the chip is in selected / active state */
  selected?: boolean;
  onPress?: () => void;
  /** Optional icon rendered before the label */
  icon?: React.ReactNode;
  disabled?: boolean;
  accessibilityLabel?: string;
  /**
   * Visual size variant.
   * 'md' (default) – standard filter chip
   * 'sm'           – compact tag / signal pill
   */
  size?: 'md' | 'sm';
}

export function Chip({
  label,
  selected = false,
  onPress,
  icon,
  disabled = false,
  accessibilityLabel,
  size = 'md',
}: ChipProps) {
  const styles = useThemedStyles(makeStyles);

  const containerStyles = [
    styles.base,
    size === 'sm' ? styles.sizeSm : styles.sizeMd,
    selected && styles.selected,
    disabled && styles.disabled,
  ];

  const textStyles = [
    styles.label,
    size === 'sm' ? styles.labelSm : styles.labelMd,
    selected && styles.labelSelected,
  ];

  if (!onPress) {
    // Non-interactive tag/signal pill
    return (
      <View style={containerStyles}>
        {icon ? <View style={styles.iconWrap}>{icon}</View> : null}
        <Text style={textStyles}>{label}</Text>
      </View>
    );
  }

  return (
    <Pressable
      style={({ pressed }) => [
        ...containerStyles,
        pressed && !disabled && styles.pressed,
      ]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ selected, disabled }}
    >
      {icon ? <View style={styles.iconWrap}>{icon}</View> : null}
      <Text style={textStyles}>{label}</Text>
    </Pressable>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    base: {
      flexDirection: 'row',
      alignItems: 'center',
      borderRadius: t.radius.full,
      backgroundColor: t.colors.surfaceElevated,
    },
    sizeMd: {
      minHeight: 36,
      paddingHorizontal: 14,
      gap: 6,
    },
    sizeSm: {
      minHeight: 28,
      paddingHorizontal: 10,
      gap: 4,
      justifyContent: 'center',
    },
    selected: {
      backgroundColor: t.colors.primary,
    },
    disabled: { opacity: 0.5 },
    pressed: {
      opacity: t.interaction.chipPressedOpacity,
      transform: [{ scale: t.interaction.pressedScale }],
    },
    label: { fontWeight: '700' },
    labelMd: { ...t.typography.caption, color: t.colors.foreground },
    labelSm: { ...t.typography.micro, color: t.colors.primaryDark },
    labelSelected: { color: '#FFFFFF' },
    iconWrap: { alignItems: 'center', justifyContent: 'center' },
  });
}
