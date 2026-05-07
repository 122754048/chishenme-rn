/**
 * PrimaryButton
 *
 * Extracted from repeated inline Pressable button patterns found in:
 *   - src/screens/Detail.tsx   (primaryButton / secondaryButton)
 *   - src/screens/Upgrade.tsx  (upgradeButton)
 *   - src/screens/Checkout.tsx (payBtn / trialBtn)
 *   - src/screens/Home.tsx     (emptyButton / upgradePill)
 *
 * Usage:
 *   <PrimaryButton label="Choose" onPress={handleChoose} />
 *   <PrimaryButton label="Skip" variant="secondary" onPress={handleSkip} />
 *   <PrimaryButton label="Cancel" variant="ghost" size="sm" onPress={onClose} />
 */

import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';

export type ButtonSize = 'lg' | 'md' | 'sm';
export type ButtonVariant = 'primary' | 'secondary' | 'ghost';

export interface PrimaryButtonProps {
  /** Button label text */
  label: string;
  onPress: () => void;
  /** Visual variant – defaults to 'primary' */
  variant?: ButtonVariant;
  /** Size token – defaults to 'md' */
  size?: ButtonSize;
  disabled?: boolean;
  loading?: boolean;
  /** Optional icon rendered before the label */
  leftIcon?: React.ReactNode;
  /** Optional icon rendered after the label */
  rightIcon?: React.ReactNode;
  accessibilityLabel?: string;
  /** Fill the full width of its container */
  fullWidth?: boolean;
}

export function PrimaryButton({
  label,
  onPress,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  leftIcon,
  rightIcon,
  accessibilityLabel,
  fullWidth = false,
}: PrimaryButtonProps) {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);

  const containerStyle = [
    styles.base,
    styles[`size_${size}`],
    styles[`variant_${variant}`],
    disabled && styles.disabled,
    fullWidth && styles.fullWidth,
  ];

  const textStyle = [
    styles.label,
    styles[`labelSize_${size}`],
    styles[`labelVariant_${variant}`],
    disabled && styles.labelDisabled,
  ];

  return (
    <Pressable
      style={({ pressed }) => [
        ...containerStyle,
        pressed && !disabled && styles.pressed,
      ]}
      onPress={onPress}
      disabled={disabled || loading}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: disabled || loading }}
    >
      {loading ? (
        <ActivityIndicator
          size="small"
          color={variant === 'primary' ? '#FFFFFF' : theme.colors.primary}
        />
      ) : (
        <View style={styles.inner}>
          {leftIcon ? <View style={styles.iconLeft}>{leftIcon}</View> : null}
          <Text style={textStyle}>{label}</Text>
          {rightIcon ? <View style={styles.iconRight}>{rightIcon}</View> : null}
        </View>
      )}
    </Pressable>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    base: {
      borderRadius: t.radius.full,
      alignItems: 'center',
      justifyContent: 'center',
      flexDirection: 'row',
    },
    fullWidth: { alignSelf: 'stretch' },
    pressed: {
      opacity: t.interaction.pressedOpacity,
      transform: [{ scale: t.interaction.pressedScale }],
    },
    disabled: { opacity: 0.5 },

    // ── Sizes ────────────────────────────────────────────────────────────────
    size_lg: { height: 48, paddingHorizontal: 24 },
    size_md: { height: 44, paddingHorizontal: 20 },
    size_sm: { height: 36, paddingHorizontal: 14 },

    // ── Variants ─────────────────────────────────────────────────────────────
    variant_primary: {
      backgroundColor: t.colors.primary,
    },
    variant_secondary: {
      backgroundColor: t.colors.surface,
      borderWidth: 1,
      borderColor: t.colors.border,
    },
    variant_ghost: {
      backgroundColor: 'transparent',
    },

    // ── Labels ───────────────────────────────────────────────────────────────
    label: { fontWeight: '700' },
    labelSize_lg: { ...t.typography.body },
    labelSize_md: { ...t.typography.caption },
    labelSize_sm: { ...t.typography.micro },

    labelVariant_primary: { color: t.colors.surface },
    labelVariant_secondary: { color: t.colors.foreground },
    labelVariant_ghost: { color: t.colors.primary },
    labelDisabled: { opacity: 0.7 },

    // ── Inner layout ─────────────────────────────────────────────────────────
    inner: { flexDirection: 'row', alignItems: 'center' },
    iconLeft: { marginRight: 6 },
    iconRight: { marginLeft: 6 },
  });
}
