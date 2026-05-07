/**
 * haptics.ts — Haptic Feedback 封装
 *
 * 依赖：expo-haptics（Expo SDK 47+，项目中已包含）
 *
 * 平台说明：
 *  - iOS 物理设备：全功能支持
 *  - iOS Simulator：静默，无震动
 *  - Android：fallback 到 Vibration.vibrate()，效果较弱
 *
 * 使用示例：
 *   import { haptics } from '../utils/haptics';
 *   haptics.swipeRight();       // 向右滑卡
 *   haptics.choose();           // 确认选择
 *   haptics.favoriteToggle();   // 收藏/取消
 */

import * as Haptics from 'expo-haptics';

// ─────────────────────────────────────────────
// Raw wrappers（带错误抑制，避免非设备环境 crash）
// ─────────────────────────────────────────────

function safeImpact(style: Haptics.ImpactFeedbackStyle): void {
  Haptics.impactAsync(style).catch(() => {
    // 静默：Simulator / Android fallback / 权限不足
  });
}

function safeNotification(type: Haptics.NotificationFeedbackType): void {
  Haptics.notificationAsync(type).catch(() => {});
}

function safeSelection(): void {
  Haptics.selectionAsync().catch(() => {});
}

// ─────────────────────────────────────────────
// Named exports — 语义化 API
// ─────────────────────────────────────────────

export const haptics = {
  /**
   * 向右滑卡（Save）— Medium Impact
   * 比左滑更重，让"保存"感觉更有分量
   */
  swipeRight(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Medium);
  },

  /**
   * 向左滑卡（Skip）— Light Impact
   * 轻触感，快速跳过
   */
  swipeLeft(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Light);
  },

  /**
   * 卡片 snap-back（未达阈值松手）— Light Impact
   * 微弱感知，告知手势被取消
   */
  snapBack(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Light);
  },

  /**
   * 点击 "Choose" 确认 — Heavy Impact
   * 最重，表示"最终决策"
   */
  choose(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Heavy);
  },

  /**
   * 收藏 / 取消收藏 — Selection
   * 轻微 tick，表示状态切换
   */
  favoriteToggle(): void {
    safeSelection();
  },

  /**
   * 滑卡时的 selection tick — Selection
   * 用于牌堆切换、轮播翻页等 UI 选择场景
   */
  selection(): void {
    safeSelection();
  },

  /**
   * 订阅成功 — Notification Success
   * 正向完成事件
   */
  subscribeSuccess(): void {
    safeNotification(Haptics.NotificationFeedbackType.Success);
  },

  /**
   * 支付失败 — Notification Error
   * 明确告知操作失败
   */
  paymentError(): void {
    safeNotification(Haptics.NotificationFeedbackType.Error);
  },

  /**
   * 配额用完（blocked swipe）— Notification Warning
   * 提示限制，不阻断但要感知到
   */
  quotaBlocked(): void {
    safeNotification(Haptics.NotificationFeedbackType.Warning);
  },

  /**
   * 任意成功通知 — Notification Success
   * 通用正向反馈（如 Toast success 弹出时配合使用）
   */
  success(): void {
    safeNotification(Haptics.NotificationFeedbackType.Success);
  },

  /**
   * 任意警告通知 — Notification Warning
   */
  warning(): void {
    safeNotification(Haptics.NotificationFeedbackType.Warning);
  },

  /**
   * 任意错误通知 — Notification Error
   */
  error(): void {
    safeNotification(Haptics.NotificationFeedbackType.Error);
  },

  /**
   * 长按开始（预留，未来功能）— Rigid Impact
   */
  longPress(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Rigid);
  },

  // ─── 低级别直接访问（如需覆盖） ───────────────

  light(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Light);
  },

  medium(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Medium);
  },

  heavy(): void {
    safeImpact(Haptics.ImpactFeedbackStyle.Heavy);
  },
} as const;

// ─────────────────────────────────────────────
// 场景 → 震动类型 映射表（文档用）
// ─────────────────────────────────────────────
//
// | 场景                          | 方法                     | API                                      |
// |-------------------------------|--------------------------|------------------------------------------|
// | 向右滑卡 (Save)               | haptics.swipeRight()     | impactAsync(Medium)                      |
// | 向左滑卡 (Skip)               | haptics.swipeLeft()      | impactAsync(Light)                       |
// | 卡片 snap-back                | haptics.snapBack()       | impactAsync(Light)                       |
// | 点击 "Choose" 确认            | haptics.choose()         | impactAsync(Heavy)                       |
// | 收藏 / 取消收藏               | haptics.favoriteToggle() | selectionAsync()                         |
// | 牌堆翻页 / UI selection       | haptics.selection()      | selectionAsync()                         |
// | 订阅成功                      | haptics.subscribeSuccess()| notificationAsync(Success)              |
// | 支付失败                      | haptics.paymentError()   | notificationAsync(Error)                 |
// | 配额用完（blocked swipe）     | haptics.quotaBlocked()   | notificationAsync(Warning)               |
// | 长按（future）                | haptics.longPress()      | impactAsync(Rigid)                       |
