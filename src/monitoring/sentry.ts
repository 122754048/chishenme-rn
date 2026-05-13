/**
 * Crash & error reporting (thin Sentry wrapper).
 *
 * Why a wrapper instead of using @sentry/react-native directly:
 *   1. We can swap providers (Bugsnag, Crashlytics) without touching call sites.
 *   2. We can no-op in development & test to avoid noisy local data.
 *   3. Centralised tag/context shape keeps reports filterable.
 *
 * DSN comes from EXPO_PUBLIC_SENTRY_DSN — empty/missing means logging
 * is disabled (safe default; keeps local dev silent).
 *
 * Call initSentry() once, early in App bootstrap (before render).
 */
import * as Sentry from '@sentry/react-native';

const DSN = process.env.EXPO_PUBLIC_SENTRY_DSN ?? '';
const ENV = process.env.EXPO_PUBLIC_APP_ENV ?? (__DEV__ ? 'dev' : 'prod');

let enabled = false;

export function initSentry(): void {
  if (!DSN) {
    if (__DEV__) console.info('[sentry] disabled (no EXPO_PUBLIC_SENTRY_DSN)');
    return;
  }
  Sentry.init({
    dsn: DSN,
    environment: ENV,
    // Tracing sample rate kept conservative to control cost; tune via remote config later.
    tracesSampleRate: ENV === 'prod' ? 0.1 : 1.0,
    // Don't ship PII to Sentry — we'll attach our own anonymised user id via setUser.
    sendDefaultPii: false,
    // No native auto-instrumentation in v1 — keeps bundle size and review surface smaller.
    enableAutoPerformanceTracing: false,
    enableAutoSessionTracking: true,
  });
  enabled = true;
}

export function captureException(error: unknown, context?: Record<string, unknown>): void {
  if (!enabled) {
    if (__DEV__) console.error('[captureException]', error, context);
    return;
  }
  Sentry.withScope((scope) => {
    if (context) scope.setContext('app', context);
    Sentry.captureException(error);
  });
}

export function captureMessage(message: string, level: 'info' | 'warning' | 'error' = 'info'): void {
  if (!enabled) {
    if (__DEV__) console.log(`[captureMessage:${level}]`, message);
    return;
  }
  Sentry.captureMessage(message, level);
}

/** Anonymised user id only — never email/name. */
export function setSentryUser(userId: string | null): void {
  if (!enabled) return;
  if (userId) Sentry.setUser({ id: userId });
  else Sentry.setUser(null);
}

type BreadcrumbInput =
  | string
  | {
      message?: string;
      category?: string;
      level?: 'fatal' | 'error' | 'warning' | 'info' | 'debug';
      data?: Record<string, unknown>;
    };

export function addBreadcrumb(input: BreadcrumbInput, data?: Record<string, unknown>): void {
  // Two call shapes:
  //   addBreadcrumb('user clicked X', { id })                  — legacy
  //   addBreadcrumb({ category: 'navigation', message: ... })  — typed
  const crumb =
    typeof input === 'string'
      ? { message: input, data, level: 'info' as const }
      : { level: 'info' as const, ...input };
  if (!enabled) {
    if (__DEV__) console.log('[breadcrumb]', crumb.category ?? '-', crumb.message ?? '', crumb.data ?? '');
    return;
  }
  Sentry.addBreadcrumb(crumb);
}
