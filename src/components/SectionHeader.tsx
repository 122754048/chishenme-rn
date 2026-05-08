/**
 * SectionHeader
 *
 * Extracted from repeated section-header patterns found in:
 *   - src/screens/Explore.tsx  (sectionHeader: title + optional "Use deck" action)
 *   - src/screens/Detail.tsx   (sectionTitle, with margin/spacing)
 *   - src/screens/Upgrade.tsx  (implicit headings above feature lists)
 *
 * Usage:
 *   // With action button (Explore style)
 *   <SectionHeader
 *     title="Top 3"
 *     actionLabel="Use deck"
 *     onAction={() => navigation.navigate('Home')}
 *   />
 *
 *   // Title only (Detail style)
 *   <SectionHeader title="Why it fits" />
 *
 *   // With eyebrow label
 *   <SectionHeader eyebrow="Today's picks" title="Top 3" />
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

export interface SectionHeaderProps {
  /** Primary section title */
  title: string;
  /** Optional small eyebrow label above the title */
  eyebrow?: string;
  /** Label for the right-side action button */
  actionLabel?: string;
  onAction?: () => void;
  accessibilityLabel?: string;
  /**
   * Bottom spacing:
   * 'sm' (default) – standard section spacing (matches sectionHeader marginBottom: 10)
   * 'md'           – more breathing room
   * 'none'         – no bottom margin (caller handles spacing)
   */
  spacing?: 'sm' | 'md' | 'none';
}

export function SectionHeader({
  title,
  eyebrow,
  actionLabel,
  onAction,
  accessibilityLabel,
  spacing = 'sm',
}: SectionHeaderProps) {
  const styles = useThemedStyles(makeStyles);

  return (
    <View
      style={[
        styles.row,
        spacing === 'sm' && styles.spacingSm,
        spacing === 'md' && styles.spacingMd,
      ]}
    >
      <View style={styles.titleWrap}>
        {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
        <Text style={styles.title}>{title}</Text>
      </View>

      {actionLabel && onAction ? (
        <Pressable
          style={({ pressed }) => [styles.actionBtn, pressed && styles.pressed]}
          onPress={onAction}
          accessibilityRole="button"
          accessibilityLabel={accessibilityLabel ?? actionLabel}
        >
          <Text style={styles.actionText}>{actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    row: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
    },
    spacingSm: { marginBottom: 10 },
    spacingMd: { marginBottom: t.spacing.md },

    titleWrap: { flex: 1 },
    eyebrow: { ...t.typography.micro, color: t.colors.subtle, fontWeight: '700', marginBottom: 2 },
    title: { ...t.typography.h2, color: t.colors.foreground },

    actionBtn: {
      minHeight: 30,
      borderRadius: t.radius.full,
      paddingHorizontal: 10,
      justifyContent: 'center',
      backgroundColor: t.colors.surfaceElevated,
    },
    actionText: { ...t.typography.micro, color: t.colors.foreground, fontWeight: '700' },
    pressed: {
      opacity: t.interaction.chipPressedOpacity,
      transform: [{ scale: t.interaction.pressedScale }],
    },
  });
}
