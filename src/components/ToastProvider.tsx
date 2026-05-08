/**
 * ToastProvider.tsx — Context Provider + useToast hook
 *
 * 使用方式：
 *
 * 1. App.tsx 根节点：
 *    <ToastProvider>
 *      <NavigationContainer>...</NavigationContainer>
 *    </ToastProvider>
 *
 * 2. 任意组件中：
 *    const { showToast, hideToast } = useToast();
 *    showToast({ type: 'success', title: 'Good call.', body: 'Saved.' });
 */

import React, { createContext, useCallback, useContext, useState } from 'react';
import { ToastPortal } from './Toast';
import type { ToastConfig, ToastState } from './Toast';

// ─────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────

interface ToastContextValue {
  showToast: (config: ToastConfig) => string;
  hideToast: (id?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// ─────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastState[]>([]);

  const showToast = useCallback((config: ToastConfig): string => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const newToast: ToastState = { ...config, id };
    // Only keep up to 3 toasts visible at a time — oldest first
    setToasts((prev) => {
      const next = [...prev, newToast];
      return next.length > 3 ? next.slice(next.length - 3) : next;
    });
    return id;
  }, []);

  const hideToast = useCallback((id?: string) => {
    if (id) {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    } else {
      // Hide the most recent if no id provided
      setToasts((prev) => prev.slice(0, -1));
    }
  }, []);

  return (
    <ToastContext.Provider value={{ showToast, hideToast }}>
      {children}
      {/* Portal renders above everything */}
      <ToastPortal toasts={toasts} onHide={hideToast} />
    </ToastContext.Provider>
  );
}

// ─────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────

/**
 * useToast — 获取 showToast / hideToast 方法
 *
 * @throws 若在 ToastProvider 外部使用会抛出错误
 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within a <ToastProvider>');
  }
  return ctx;
}
