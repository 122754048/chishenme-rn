/**
 * NavigationBar
 *
 * Extracted from repeated top-nav / header patterns found in:
 *   - src/screens/Detail.tsx   (navBar with back + share + favourite)
 *   - src/screens/Upgrade.tsx  (header with back + centred title)
 *   - src/screens/Checkout.tsx (header with back + centred title)
 *   - src/screens/Explore.tsx  (topNav with title + action buttons)
 *
 * Usage – transparent overlay (Detail-style):
 *   <NavigationBar
 *     onBack={() => navigation.goBack()}
 *     transparent
 *     rightActions={[
 *       { key: 'share', icon: <Share2 />, onPress: handleShare },
 *       { key: 'fav',   icon: <Heart />,  onPress: toggleFav },
 *     ]}
 *   />
 *
 * Usage – opaque (Upgrade/Checkout-style):
 *   <NavigationBar title="Upgrade" onBack={() => navigation.goBack()} />
 *
 * Usage – Explore-style (title + subtitle + right actions):
 *   <NavigationBar
 *     title="Explore"
 *     subtitle="Downtown SF"
 *     rightActions={[
 *       { key: 'search', icon: <Search />, onPress: () => setShowSearch(true) },
 *     ]}
 *   />
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';

export interface NavAction {
  key: string;
  icon: React.ReactNode;
  onPress: () => void;
  accessibilityLabel?: string;
}

export interface NavigationBarProps {
  title?: string;
  /** Small subtitle rendered below the title (e.g. location label) */
  subtitle?: string;
  onBack?: () => void;
  /** Action buttons on the right side */
  rightActions?: NavAction[];
  /**
   * When true the bar has a transparent background (suitable for overlay on
   * hero images, as in Detail.tsx).  The back & action buttons get a frosted
   * circle treatment to remain legible.
   */
  transparent?: boolean;
  /**
   * When true a bottom border is rendered (used in Upgrade / Checkout).
   */
  bordered?: boolean;
}

export function NavigationBar({
  title,
  subtitle,
  onBack,
  rightActions = [],
  transparent = false,
  bordered = false,
}: NavigationBarProps) {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);

  return (
    <View
      style={[
        styles.bar,
        transparent && styles.barTransparent,
        bordered && styles.barBordered,
      ]}
    >
      {/* Back button (or spacer) */}
      {onBack ? (
        <Pressable
          style={({ pressed }) => [
            styles.circleBtn,
            transparent && styles.circleBtnFrosted,
            pressed && styles.pressed,
          ]}
          onPress={onBack}
          accessibilityRole="button"
          accessibilityLabel="Go back"
          hitSlop={8}
        >
          {/* ArrowLeft – the caller passes the icon via children or we render
              a fallback chevron using border tricks so we have zero icon deps */}
          <BackChevron color={theme.colors.foreground} />
        </Pressable>
      ) : (
        <View style={styles.circleBtn} />
      )}

      {/* Title area */}
      {title ? (
        <View style={styles.titleWrap}>
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          {subtitle ? (
            <Text style={styles.subtitle} numberOfLines={1}>
              {subtitle}
            </Text>
          ) : null}
        </View>
      ) : (
        <View style={styles.titleWrap} />
      )}

      {/* Right actions */}
      <View style={styles.rightGroup}>
        {rightActions.map((action) => (
          <Pressable
            key={action.key}
            style={({ pressed }) => [
              styles.circleBtn,
              transparent && styles.circleBtnFrosted,
              pressed && styles.pressed,
            ]}
            onPress={action.onPress}
            accessibilityRole="button"
            accessibilityLabel={action.accessibilityLabel ?? action.key}
            hitSlop={8}
          >
            {action.icon}
          </Pressable>
        ))}
        {/* Spacer so title stays centred when no right actions */}
        {rightActions.length === 0 && <View style={styles.circleBtn} />}
      </View>
    </View>
  );
}

/** Minimal back-chevron rendered with border tricks — no icon dependency */
function BackChevron({ color }: { color: string }) {
  return (
    <View
      style={{
        width: 10,
        height: 10,
        borderLeftWidth: 2,
        borderBottomWidth: 2,
        borderColor: color,
        transform: [{ rotate: '45deg' }, { translateX: 2 }],
      }}
    />
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    bar: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: t.spacing.md,
      height: t.topNavHeight,
      backgroundColor: t.colors.surface,
    },
    barTransparent: { backgroundColor: 'transparent' },
    barBordered: { borderBottomWidth: 1, borderBottomColor: t.colors.borderLight },

    titleWrap: { flex: 1, alignItems: 'center' },
    title: { ...t.typography.h2, color: t.colors.foreground },
    subtitle: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600', marginTop: 2 },

    rightGroup: { flexDirection: 'row', gap: t.spacing.xs },

    circleBtn: {
      width: 36,
      height: 36,
      borderRadius: t.radius.full,
      alignItems: 'center',
      justifyContent: 'center',
    },
    circleBtnFrosted: {
      backgroundColor: 'rgba(255,255,255,0.92)',
    },
    pressed: {
      opacity: t.interaction.chipPressedOpacity,
    },
  });
}
