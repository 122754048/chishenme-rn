/**
 * EmptyState.tsx — 统一 Empty State 组件，覆盖 8 个场景
 *
 * 用法示例：
 *
 *   // 场景1：刷完卡片
 *   <EmptyState
 *     scenario="home-empty"
 *     language="zh"
 *     onCta={() => navigation.navigate('MainTabs', { screen: 'Explore' })}
 *     onSecondary={() => navigation.navigate('MainTabs', { screen: 'Profile' })}
 *   />
 *
 *   // 场景7：网络错误（带 retry 回调）
 *   <EmptyState
 *     scenario="network-error"
 *     language="en"
 *     onCta={refetch}
 *   />
 *
 * 所有 UI 使用 theme token，深色模式自动适配
 */

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import {
  ClipboardList,
  Crown,
  Heart,
  MapPin,
  MapPinOff,
  RefreshCw,
  Search,
  WifiOff,
} from 'lucide-react-native';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

export type EmptyScenario =
  | 'home-empty'       // 场景1：刷完卡片
  | 'home-quota'       // 场景2：配额用完
  | 'explore-search'   // 场景3：搜索无结果
  | 'explore-nearby'   // 场景4：附近无餐厅
  | 'favorites-empty'  // 场景5：收藏为空
  | 'history-empty'    // 场景6：历史为空
  | 'network-error'    // 场景7：网络错误
  | 'location-error';  // 场景8：定位失败

export type EmptyVariant = 'default' | 'quota' | 'error' | 'neutral';

export interface EmptyStateProps {
  scenario: EmptyScenario;
  /** 双语支持，默认 'en' */
  language?: 'zh' | 'en';
  /** 主 CTA 回调 */
  onCta?: () => void;
  /** 次级链接回调 */
  onSecondary?: () => void;
  /** 搜索无结果时注入当前 query */
  searchQuery?: string;
  /** 紧凑行内模式（不占全屏，用于 explore-nearby 行内） */
  compact?: boolean;
}

// ─────────────────────────────────────────────
// Scene configuration
// ─────────────────────────────────────────────

type SceneConfig = {
  variant: EmptyVariant;
  iconColor: string;
  bgColor: string;
  /** 图标大小 */
  iconSize: number;
  icon: (color: string, size: number) => React.ReactNode;
  en: { title: string; body: string; cta?: string; secondary?: string };
  zh: { title: string; body: string; cta?: string; secondary?: string };
};

function buildScenes(t: AppTheme): Record<EmptyScenario, SceneConfig> {
  return {
    'home-empty': {
      variant: 'default',
      iconColor: t.colors.primary,
      bgColor: t.colors.primaryLight,
      iconSize: 24,
      icon: (c, s) => <RefreshCw size={s} color={c} strokeWidth={2} />,
      en: {
        title: "You've seen it all for now.",
        body: "Great taste takes time. Come back later and we'll have fresh picks ready — or browse by area below.",
        cta: 'Explore nearby',
        secondary: 'Adjust preferences',
      },
      zh: {
        title: '今天的推荐都看完了',
        body: '不用担心，我们正在准备更多符合你口味的选项。也可以去探索附近的餐厅。',
        cta: '探索附近',
        secondary: '调整偏好',
      },
    },

    'home-quota': {
      variant: 'quota',
      iconColor: t.colors.warning,
      bgColor: t.colors.warningLight,
      iconSize: 24,
      icon: (c, s) => <Crown size={s} color={c} strokeWidth={2} />,
      en: {
        title: "You've used today's free picks.",
        body: 'Free plan includes 5 smart saves per day. Upgrade to Pro and every decision is unlimited — for less than a coffee a week.',
        cta: 'Unlock unlimited picks',
        secondary: 'Come back tomorrow',
      },
      zh: {
        title: '今日免费推荐次数已用完',
        body: '免费版每天提供 5 次智能推荐。升级到 Pro，每天无限次，一杯咖啡不到的价格。',
        cta: '解锁无限推荐',
        secondary: '明天再来',
      },
    },

    'explore-search': {
      variant: 'neutral',
      iconColor: t.colors.subtle,
      bgColor: t.colors.surfaceMuted,
      iconSize: 24,
      icon: (c, s) => <Search size={s} color={c} strokeWidth={2} />,
      en: {
        title: 'No matches found.',
        body: "We couldn't find anything matching your search. Try a neighborhood, cuisine, or dish name instead.",
        cta: 'Clear search',
        secondary: 'Try "Downtown"',
      },
      zh: {
        title: '没找到相关推荐',
        body: '试试换个关键词——比如街区名、菜系或菜品名称。',
        cta: '清除搜索',
        secondary: '试试"附近"',
      },
    },

    'explore-nearby': {
      variant: 'neutral',
      iconColor: t.colors.subtle,
      bgColor: t.colors.surfaceMuted,
      iconSize: 20,
      icon: (c, s) => <MapPin size={s} color={c} strokeWidth={2} />,
      en: {
        title: 'Nothing nearby yet.',
        body: "We couldn't find restaurants close to your current area. Try entering a specific street or neighborhood.",
        cta: 'Enter an area',
        secondary: 'Use current location',
      },
      zh: {
        title: '附近暂时没有结果',
        body: '当前区域没有找到餐厅，试试输入具体街道或街区名。',
        cta: '输入区域',
        secondary: '使用当前位置',
      },
    },

    'favorites-empty': {
      variant: 'default',
      iconColor: t.colors.primary,
      bgColor: t.colors.primaryLight,
      iconSize: 28,
      icon: (c, s) => <Heart size={s} color={c} strokeWidth={2} />,
      en: {
        title: 'Your saved picks live here.',
        body: 'Swipe right on a dish to save it. When dinner decisions get hard, this is where the good answers are.',
        cta: 'Start swiping',
        secondary: 'Browse explore',
      },
      zh: {
        title: '这里存放你保存的好选择',
        body: '在主页向右滑动保存菜品。当你不知道吃什么时，直接来这里找答案。',
        cta: '开始滑动',
        secondary: '浏览探索',
      },
    },

    'history-empty': {
      variant: 'neutral',
      iconColor: t.colors.subtle,
      bgColor: t.colors.surfaceMuted,
      iconSize: 28,
      icon: (c, s) => <ClipboardList size={s} color={c} strokeWidth={1.5} />,
      en: {
        title: 'No decisions yet.',
        body: 'Every dish you swipe on appears here. It helps the app learn your taste faster — and makes repeat decisions easier.',
        cta: 'Make your first pick',
      },
      zh: {
        title: '还没有决策记录',
        body: '每次滑动的菜品都会显示在这里，帮助 APP 更快了解你的口味，也让下次选择更容易。',
        cta: '做第一个决定',
      },
    },

    'network-error': {
      variant: 'error',
      iconColor: t.colors.error,
      bgColor: t.colors.errorLight,
      iconSize: 24,
      icon: (c, s) => <WifiOff size={s} color={c} strokeWidth={2} />,
      en: {
        title: "Can't connect right now.",
        body: 'Check your connection and try again. Your saved preferences still work offline.',
        cta: 'Try again',
        secondary: 'Use offline mode',
      },
      zh: {
        title: '暂时无法连接',
        body: '请检查网络后重试。你保存的偏好设置在离线状态下仍然有效。',
        cta: '重试',
        secondary: '使用离线模式',
      },
    },

    'location-error': {
      variant: 'neutral',
      iconColor: t.colors.subtle,
      bgColor: t.colors.surfaceMuted,
      iconSize: 24,
      icon: (c, s) => <MapPinOff size={s} color={c} strokeWidth={2} />,
      en: {
        title: 'Location unavailable.',
        body: "We couldn't find your location. Enter an area manually to get nearby restaurant picks.",
        cta: 'Enter area manually',
        secondary: 'Allow location in Settings',
      },
      zh: {
        title: '无法获取位置',
        body: '请手动输入你所在的区域，即可获得附近餐厅的推荐。',
        cta: '手动输入区域',
        secondary: '在设置中允许定位',
      },
    },
  };
}

// ─────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────

export function EmptyState({
  scenario,
  language = 'en',
  onCta,
  onSecondary,
  searchQuery,
  compact = false,
}: EmptyStateProps) {
  const t = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const scenes = buildScenes(t);
  const scene = scenes[scenario];
  const copy = scene[language];

  // Dynamic title/body for explore-search
  let title = copy.title;
  let body = copy.body;
  if (scenario === 'explore-search' && searchQuery) {
    title = language === 'en'
      ? `No matches for "${searchQuery}"`
      : `没找到"${searchQuery}"相关的推荐`;
    body = language === 'en'
      ? `We couldn't find anything that fits "${searchQuery}" right now. Try a neighborhood, cuisine, or dish name instead.`
      : `试试换个关键词——比如街区名、菜系或菜品名称。`;
  }

  if (compact) {
    return (
      <View style={styles.compactWrapper}>
        {scene.icon(scene.iconColor, 16)}
        <Text style={styles.compactTitle}>{title}</Text>
        {onCta && copy.cta ? (
          <Pressable
            style={({ pressed }) => [styles.compactCta, pressed && { opacity: 0.75 }]}
            onPress={onCta}
            accessibilityRole="button"
          >
            <Text style={styles.compactCtaText}>{copy.cta}</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  // Full-screen variant
  const ctaBgColor: Record<EmptyVariant, string> = {
    default: t.colors.primary,
    quota: t.colors.warning,
    error: t.colors.error,
    neutral: t.colors.foreground,
  };

  return (
    <View style={styles.wrapper}>
      {/* Icon circle */}
      <View style={[styles.iconBg, { backgroundColor: scene.bgColor }]}>
        {scene.icon(scene.iconColor, scene.iconSize)}
      </View>

      {/* Text */}
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.body}>{body}</Text>

      {/* Primary CTA */}
      {onCta && copy.cta ? (
        <Pressable
          style={({ pressed }) => [
            styles.cta,
            { backgroundColor: ctaBgColor[scene.variant] },
            pressed && { opacity: 0.85 },
          ]}
          onPress={onCta}
          accessibilityRole="button"
        >
          <Text style={styles.ctaText}>{copy.cta}</Text>
        </Pressable>
      ) : null}

      {/* Secondary link */}
      {onSecondary && copy.secondary ? (
        <Pressable
          style={({ pressed }) => [styles.secondaryBtn, pressed && { opacity: 0.75 }]}
          onPress={onSecondary}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryText}>{copy.secondary}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// ─────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    wrapper: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: t.spacing.xl,   // 32pt
      paddingVertical: t.spacing.lg,     // 24pt
    },
    iconBg: {
      width: 88,
      height: 88,
      borderRadius: 44,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: t.spacing.lg,
    },
    title: {
      fontSize: 20,
      lineHeight: 28,
      fontWeight: '700',
      color: t.colors.foreground,
      textAlign: 'center',
      marginBottom: t.spacing.xs,
    },
    body: {
      fontSize: 14,
      lineHeight: 21,
      color: t.colors.subtle,
      textAlign: 'center',
      marginBottom: t.spacing.lg,
    },
    cta: {
      borderRadius: t.radius.full,
      paddingHorizontal: t.spacing.lg,
      paddingVertical: t.spacing.sm,
      minHeight: 46,
      alignItems: 'center',
      justifyContent: 'center',
      width: '100%',
      marginBottom: t.spacing.xs,
    },
    ctaText: {
      fontSize: 15,
      fontWeight: '700',
      color: '#FFFFFF',
    },
    secondaryBtn: {
      marginTop: t.spacing.sm,
      minHeight: 36,
      alignItems: 'center',
      justifyContent: 'center',
    },
    secondaryText: {
      fontSize: 14,
      fontWeight: '600',
      color: t.colors.primary,
    },

    // Compact (inline) styles
    compactWrapper: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      paddingVertical: t.spacing.sm,
      paddingHorizontal: t.spacing.md,
      backgroundColor: t.colors.surfaceMuted,
      borderRadius: t.surface.cardRadius,
    },
    compactTitle: {
      flex: 1,
      fontSize: 14,
      color: t.colors.subtle,
      fontWeight: '600',
    },
    compactCta: {
      minHeight: 32,
      borderRadius: t.radius.full,
      paddingHorizontal: 12,
      backgroundColor: t.colors.surface,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor: t.colors.borderLight,
    },
    compactCtaText: {
      fontSize: 13,
      fontWeight: '700',
      color: t.colors.primary,
    },
  });
}
