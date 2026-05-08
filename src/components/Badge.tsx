/**
 * Badge
 *
 * Extracted from repeated badge / pill patterns found in:
 *   - src/screens/Home.tsx     (ratingBadge / statusPill)
 *   - src/screens/Explore.tsx  (visualMetaBadge / featuredNearbyBadge / summarySignal)
 *   - src/screens/Detail.tsx   (ratingBadge)
 *   - src/screens/Checkout.tsx (statusPill / planBadge)
 *
 * Usage:
 *   <Badge rating={4.8} />               // star + numeric rating
 *   <Badge label="Popular" />            // text label only
 *   <Badge label="0.3 mi" variant="meta" />  // distance / meta info
 *   <Badge label="Pro active" variant="premium" icon={<Crown size={12} />} />
 */

import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Star } from 'lucide-react-native';
import { useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

export type BadgeVariant =
  | 'rating'   // star icon + numeric value, white bg on overlay
  | 'meta'     // distance / prep time, white bg on overlay
  | 'status'   // standard on-surface pill (e.g. "Apple billing")
  | 'premium'  // tinted primary-light background
  | 'tag';     // simple tag, surface-elevated background

export interface BadgeProps {
  /** Numeric rating value – renders a star icon when provided */
  rating?: number;
  /** Text label – used when rating is not provided */
  label?: string;
  variant?: BadgeVariant;
  /** Optional icon rendered before the label */
  icon?: React.ReactNode;
}

export function Badge({
  rating,
  label,
  variant = 'tag',
  icon,
}: BadgeProps) {
  const styles = useThemedStyles(makeStyles);

  const containerStyles = [
    styles.base,
    styles[`variant_${variant}`],
  ];

  const textStyles = [
    styles.label,
    styles[`labelVariant_${variant}`],
  ];

  const displayLabel =
    rating !== undefined ? rating.toFixed(1) : (label ?? '');

  return (
    <View style={containerStyles}>
      {/* Star icon for rating variant */}
      {variant === 'rating' && (
        <Star size={11} color="#F5B74F" fill="#F5B74F" />
      )}
      {/* Custom icon (non-rating) */}
      {variant !== 'rating' && icon ? (
        <View style={styles.iconWrap}>{icon}</View>
      ) : null}
      <Text style={textStyles}>{displayLabel}</Text>
    </View>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    base: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      borderRadius: t.radius.full,
      alignSelf: 'flex-start',
    },

    // ── Variants ─────────────────────────────────────────────────────────────
    // Overlay badges (white translucent bg — used on top of dark images)
    variant_rating: {
      backgroundColor: 'rgba(255,255,255,0.16)',
      paddingHorizontal: 8,
      paddingVertical: 5,
    },
    variant_meta: {
      backgroundColor: 'rgba(255,255,255,0.9)',
      paddingHorizontal: 10,
      minHeight: 28,
      justifyContent: 'center',
    },

    // On-surface badges
    variant_status: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.full,
      minHeight: 34,
      paddingHorizontal: 12,
      justifyContent: 'center',
    },
    variant_premium: {
      backgroundColor: t.colors.primaryLight,
      borderWidth: 1,
      borderColor: 'rgba(201,103,60,0.18)',
      paddingHorizontal: 12,
      minHeight: 34,
      justifyContent: 'center',
    },
    variant_tag: {
      backgroundColor: t.colors.surfaceElevated,
      paddingHorizontal: 10,
      minHeight: 28,
      justifyContent: 'center',
    },

    // ── Labels ───────────────────────────────────────────────────────────────
    label: { fontWeight: '700' },
    labelVariant_rating: { ...t.typography.caption, color: '#FFFFFF' },
    labelVariant_meta: { ...t.typography.micro, color: t.colors.foreground },
    labelVariant_status: { ...t.typography.caption, color: t.colors.primaryDark },
    labelVariant_premium: { ...t.typography.caption, color: t.colors.primaryDark },
    labelVariant_tag: { ...t.typography.micro, color: t.colors.primaryDark },

    iconWrap: { alignItems: 'center', justifyContent: 'center' },
  });
}
