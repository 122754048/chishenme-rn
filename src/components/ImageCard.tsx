/**
 * ImageCard
 *
 * Extracted from repeated image-card / visual-card patterns found in:
 *   - src/screens/Explore.tsx  (restaurantVisualCard, fitVisualCard, featuredNearbyCard, topPickCard)
 *   - src/screens/Home.tsx     (card / previewCard in the swipe deck)
 *   - src/screens/Detail.tsx   (relatedCard)
 *
 * Usage — restaurant visual card:
 *   <ImageCard
 *     imageUrl={restaurant.image}
 *     title={restaurant.name}
 *     subtitle={restaurant.editorialSummary}
 *     tags={[{ label: '4.5', icon: <Star /> }, { label: '0.3 mi' }]}
 *     onPress={openRestaurant}
 *   />
 *
 * Usage — fit card (dish):
 *   <ImageCard
 *     imageUrl={dish.image}
 *     title={dish.name}
 *     subtitle={dish.restaurantName}
 *     supportText={dish.subtitle}
 *     size="md"
 *     onPress={() => navigation.navigate('Detail', { itemId: dish.id })}
 *   />
 *
 * Usage — featured (full-width):
 *   <ImageCard imageUrl={featured.image} title={featured.name} size="featured" onPress={open} />
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SkeletonImage } from '../components/SkeletonImage';
import { useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

export interface ImageCardTag {
  /** Short label rendered inside a frosted pill */
  label: string;
  /** Optional icon rendered before the label */
  icon?: React.ReactNode;
}

export type ImageCardSize =
  | 'sm'       // relatedCard  (w=170, h≈220)
  | 'md'       // fitVisualCard (w=210, h=236)
  | 'lg'       // restaurantVisualCard (w=220, h=192)
  | 'featured' // full-width featuredNearby (h=210)
  | 'pick';    // topPickCard (w=168, vertical layout)

export interface ImageCardProps {
  imageUrl: string;
  title: string;
  subtitle?: string;
  /** Smaller body text below subtitle (reason / editorial summary) */
  supportText?: string;
  tags?: ImageCardTag[];
  onPress?: () => void;
  size?: ImageCardSize;
  accessibilityLabel?: string;
}

export function ImageCard({
  imageUrl,
  title,
  subtitle,
  supportText,
  tags = [],
  onPress,
  size = 'md',
  accessibilityLabel,
}: ImageCardProps) {
  const styles = useThemedStyles(makeStyles);

  const isPickLayout = size === 'pick';

  const containerStyle = [
    styles.base,
    styles[`size_${size}`],
  ];

  if (isPickLayout) {
    // Top-pick card: image + text below (no overlay)
    return (
      <Pressable
        style={({ pressed }) => [
          ...containerStyle,
          pressed && styles.pressed,
        ]}
        onPress={onPress}
        disabled={!onPress}
        accessibilityRole={onPress ? 'button' : undefined}
        accessibilityLabel={accessibilityLabel ?? title}
      >
        <View style={styles.pickImageWrap}>
          <SkeletonImage src={imageUrl} alt={title} />
        </View>
        <Text style={styles.pickTitle} numberOfLines={2}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={styles.pickSubtitle} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
        {tags.length > 0 ? (
          <View style={styles.tagRow}>
            {tags.map((tag, i) => (
              <View key={i} style={styles.tag}>
                {tag.icon ?? null}
                <Text style={styles.tagText}>{tag.label}</Text>
              </View>
            ))}
          </View>
        ) : null}
        {supportText ? (
          <Text style={styles.pickSupportText} numberOfLines={2}>
            {supportText}
          </Text>
        ) : null}
      </Pressable>
    );
  }

  // Overlay layout: image fills the card, text + tags overlaid at the bottom
  return (
    <Pressable
      style={({ pressed }) => [
        ...containerStyle,
        pressed && styles.pressed,
      ]}
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={accessibilityLabel ?? title}
    >
      {/* Background image */}
      <View style={StyleSheet.absoluteFill}>
        <SkeletonImage src={imageUrl} alt={title} />
      </View>

      {/* Gradient overlay + text */}
      <View style={styles.overlay}>
        {/* Meta badges (rating, distance) at the top of the overlay */}
        {tags.length > 0 ? (
          <View style={styles.tagRow}>
            {tags.map((tag, i) => (
              <View key={i} style={styles.overlayTag}>
                {tag.icon ?? null}
                <Text style={styles.overlayTagText}>{tag.label}</Text>
              </View>
            ))}
          </View>
        ) : null}

        <Text style={styles.overlayTitle} numberOfLines={2}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={styles.overlaySubtitle} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
        {supportText ? (
          <Text style={styles.overlaySupportText} numberOfLines={2}>
            {supportText}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    base: {
      borderRadius: t.surface.cardRadius,
      overflow: 'hidden',
      backgroundColor: t.colors.surface,
      ...t.shadows.md,
    },
    pressed: {
      opacity: t.interaction.chipPressedOpacity,
      transform: [{ scale: t.interaction.pressedScale }],
    },

    // ── Sizes ─────────────────────────────────────────────────────────────────
    size_sm:       { width: 170, minHeight: 220 },          // relatedCard
    size_md:       { width: 210, height: 236 },             // fitVisualCard
    size_lg:       { width: 220, height: 192 },             // restaurantVisualCard
    size_featured: { height: 210 },                         // full-width featured card
    size_pick:     { width: 168, minHeight: 214, padding: 14 }, // topPickCard (no absolute fill)

    // ── Overlay layout ────────────────────────────────────────────────────────
    overlay: {
      flex: 1,
      justifyContent: 'flex-end',
      padding: t.spacing.md,
      backgroundColor: 'rgba(20, 15, 12, 0.28)',
      gap: 4,
    },
    overlayTitle: { ...t.typography.h2, color: '#FFFFFF', marginBottom: 2 },
    overlaySubtitle: { ...t.typography.caption, color: 'rgba(255,255,255,0.9)' },
    overlaySupportText: { ...t.typography.micro, color: 'rgba(255,255,255,0.88)' },

    tagRow: { flexDirection: 'row', gap: 8, marginBottom: 8, flexWrap: 'wrap' },
    overlayTag: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      minHeight: 28,
      borderRadius: t.radius.full,
      backgroundColor: 'rgba(255,255,255,0.9)',
      paddingHorizontal: 10,
      justifyContent: 'center',
    },
    overlayTagText: { ...t.typography.micro, color: t.colors.foreground, fontWeight: '700' },

    // ── Pick (top-pick) layout ────────────────────────────────────────────────
    pickImageWrap: { height: 104, borderRadius: t.radius.md, overflow: 'hidden', marginBottom: 10 },
    pickTitle: { ...t.typography.body, color: t.colors.foreground, fontWeight: '700' },
    pickSubtitle: { ...t.typography.caption, color: t.colors.subtle, fontWeight: '600' },
    pickSupportText: { ...t.typography.caption, color: t.colors.foreground, marginTop: 8, lineHeight: 18 },

    tag: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    tagText: { ...t.typography.caption, color: t.colors.subtle },
  });
}
