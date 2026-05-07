/**
 * Toast.tsx — Toast 容器 + Portal 单例
 *
 * 用法：
 *   <ToastPortal /> 挂载在 App 根节点（NavigationContainer 外）
 *   通过 showToast() / hideToast() 从 useToast() 调用
 *
 * 规格：
 *   - 4 种类型：success / info / warning / error
 *   - 顶部 SafeArea + 8pt 偏移，spring 滑入
 *   - 全部使用 theme token，深色模式自动适配
 */

import React, { useCallback, useEffect, useRef } from 'react';
import {
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  XCircle,
} from 'lucide-react-native';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

export type ToastType = 'success' | 'info' | 'warning' | 'error';

export interface ToastConfig {
  type: ToastType;
  title: string;
  body?: string;
  /** ms，默认按类型: success=2800 / info=3200 / warning=3500 / error=5000 */
  duration?: number;
  action?: {
    label: string;
    onPress: () => void;
  };
  /** 覆盖默认图标 */
  icon?: React.ReactNode;
}

export interface ToastState extends ToastConfig {
  id: string;
}

// ─────────────────────────────────────────────
// Default durations
// ─────────────────────────────────────────────

const DEFAULT_DURATIONS: Record<ToastType, number> = {
  success: 2800,
  info: 3200,
  warning: 3500,
  error: 5000,
};

// ─────────────────────────────────────────────
// Icon mapping
// ─────────────────────────────────────────────

const ICON_COLOR: Record<ToastType, string> = {
  success: '#7C9D87',
  info: '#667FA4',
  warning: '#C99658',
  error: '#C96D60',
};

function DefaultIcon({ type }: { type: ToastType }) {
  const color = ICON_COLOR[type];
  switch (type) {
    case 'success':
      return <CheckCircle2 size={18} color={color} strokeWidth={2} />;
    case 'info':
      return <Info size={18} color={color} strokeWidth={2} />;
    case 'warning':
      return <AlertTriangle size={18} color={color} strokeWidth={2} />;
    case 'error':
      return <XCircle size={18} color={color} strokeWidth={2} />;
  }
}

// ─────────────────────────────────────────────
// Single Toast item
// ─────────────────────────────────────────────

interface ToastItemProps {
  toast: ToastState;
  onHide: (id: string) => void;
}

function ToastItem({ toast, onHide }: ToastItemProps) {
  const theme = useThemeColors();
  const styles = useThemedStyles(makeStyles);
  const insets = useSafeAreaInsets();

  const translateY = useRef(new Animated.Value(-100)).current;
  const opacity = useRef(new Animated.Value(0)).current;
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dismiss = useCallback(() => {
    if (dismissTimer.current) clearTimeout(dismissTimer.current);
    Animated.parallel([
      Animated.timing(translateY, {
        toValue: -80,
        duration: 200,
        easing: Easing.in(Easing.ease),
        useNativeDriver: true,
      }),
      Animated.timing(opacity, {
        toValue: 0,
        duration: 160,
        useNativeDriver: true,
      }),
    ]).start(() => onHide(toast.id));
  }, [onHide, opacity, toast.id, translateY]);

  useEffect(() => {
    // Enter animation
    Animated.parallel([
      Animated.timing(translateY, {
        toValue: 0,
        duration: 220,
        easing: Easing.out(Easing.ease),
        useNativeDriver: true,
      }),
      Animated.timing(opacity, {
        toValue: 1,
        duration: 180,
        useNativeDriver: true,
      }),
    ]).start();

    // Auto-dismiss
    const duration = toast.duration ?? DEFAULT_DURATIONS[toast.type];
    dismissTimer.current = setTimeout(dismiss, duration);

    return () => {
      if (dismissTimer.current) clearTimeout(dismissTimer.current);
    };
  }, [dismiss, opacity, toast.duration, toast.type, translateY]);

  const typeStyle = styles[`toast_${toast.type}` as keyof typeof styles];

  return (
    <Animated.View
      style={[
        styles.toastWrapper,
        { marginTop: insets.top + 8 },
        { transform: [{ translateY }], opacity },
      ]}
    >
      <Pressable
        style={[styles.toast, typeStyle]}
        onPress={dismiss}
        accessibilityRole="alert"
        accessibilityLabel={`${toast.type}: ${toast.title}`}
      >
        <View style={styles.iconWrap}>
          {toast.icon ?? <DefaultIcon type={toast.type} />}
        </View>
        <View style={styles.textBlock}>
          <Text style={styles.toastTitle}>{toast.title}</Text>
          {toast.body ? (
            <Text style={styles.toastBody}>{toast.body}</Text>
          ) : null}
          {toast.action ? (
            <Pressable
              style={styles.actionBtn}
              onPress={() => {
                dismiss();
                toast.action!.onPress();
              }}
              accessibilityRole="button"
            >
              <Text style={styles.actionText}>{toast.action.label}</Text>
            </Pressable>
          ) : null}
        </View>
      </Pressable>
    </Animated.View>
  );
}

// ─────────────────────────────────────────────
// ToastPortal — 全局渲染层
// ─────────────────────────────────────────────

export interface ToastPortalProps {
  toasts: ToastState[];
  onHide: (id: string) => void;
}

export function ToastPortal({ toasts, onHide }: ToastPortalProps) {
  if (toasts.length === 0) return null;

  return (
    <View style={portalStyles.container} pointerEvents="box-none">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onHide={onHide} />
      ))}
    </View>
  );
}

// ─────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────

const portalStyles = StyleSheet.create({
  container: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 9999,
    pointerEvents: 'box-none',
  },
});

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    toastWrapper: {
      paddingHorizontal: t.spacing.md, // 16pt each side
      width: '100%',
    },
    toast: {
      backgroundColor: t.colors.surface,
      borderRadius: t.radius.md,
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 12,
      paddingVertical: 14,
      paddingHorizontal: 16,
      borderLeftWidth: 4,
      ...t.shadows.md,
    },
    // Type-specific left border colours
    toast_success: { borderLeftColor: '#7C9D87' },
    toast_info: { borderLeftColor: '#667FA4' },
    toast_warning: { borderLeftColor: '#C99658' },
    toast_error: { borderLeftColor: '#C96D60' },

    iconWrap: { marginTop: 1 },
    textBlock: { flex: 1, gap: 2 },
    toastTitle: {
      fontSize: 15,
      fontWeight: '700',
      color: t.colors.foreground,
      lineHeight: 22,
    },
    toastBody: {
      fontSize: 13,
      color: t.colors.subtle,
      lineHeight: 19,
    },
    actionBtn: { marginTop: 6, alignSelf: 'flex-start' },
    actionText: {
      fontSize: 13,
      fontWeight: '700',
      color: t.colors.primary,
    },
  });
}
