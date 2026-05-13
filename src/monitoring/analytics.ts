/**
 * Product analytics (thin PostHog wrapper).
 *
 * Why a wrapper:
 *   1. One place to gate via remote-config / opt-out / dev mode
 *   2. Forces canonical event names (see EventName below) to prevent
 *      the dreaded "checkout_started" / "checkoutStarted" / "Checkout Started"
 *      schema drift after a few months
 *   3. Easy to pipe to a second sink (e.g. Amplitude) later
 *
 * Init key: EXPO_PUBLIC_POSTHOG_KEY (missing => disabled).
 * Host:     EXPO_PUBLIC_POSTHOG_HOST (defaults to EU cloud for GDPR).
 *
 * IMPORTANT: never log PII (email, real name, phone). Send anonymised
 * userId only. Properties should be enums or numbers when possible.
 */
import PostHog from 'posthog-react-native';

const KEY = process.env.EXPO_PUBLIC_POSTHOG_KEY ?? '';
const HOST = process.env.EXPO_PUBLIC_POSTHOG_HOST ?? 'https://eu.i.posthog.com';

let client: PostHog | null = null;

/**
 * Canonical event names. Add new ones here — never inline-string at the call site.
 * Naming: snake_case, verb_object, present-tense.
 */
export const EventName = {
  AppOpened: 'app_opened',
  OnboardingStarted: 'onboarding_started',
  OnboardingStepCompleted: 'onboarding_step_completed',
  OnboardingCompleted: 'onboarding_completed',
  PickRequested: 'pick_requested',
  PickShown: 'pick_shown',
  PickLiked: 'pick_liked',
  PickPassed: 'pick_passed',
  QuotaExhausted: 'quota_exhausted',
  PaywallViewed: 'paywall_viewed',
  PaywallPlanSelected: 'paywall_plan_selected',
  CheckoutStarted: 'checkout_started',
  CheckoutCompleted: 'checkout_completed',
  CheckoutFailed: 'checkout_failed',
  SubscriptionRestored: 'subscription_restored',
  LanguageChanged: 'language_changed',
  ScreenViewed: 'screen_viewed',
} as const;
export type EventNameValue = (typeof EventName)[keyof typeof EventName];

type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type EventProperties = Record<string, JsonValue>;

export async function initAnalytics(): Promise<void> {
  if (!KEY) {
    if (__DEV__) console.info('[analytics] disabled (no EXPO_PUBLIC_POSTHOG_KEY)');
    return;
  }
  client = new PostHog(KEY, {
    host: HOST,
    // We don't enable autocapture — it generates noisy events on RN.
    // We rely on explicit track() calls only.
    captureAppLifecycleEvents: true,
    flushAt: 20,
    flushInterval: 30_000,
  });
}

export function track(event: EventNameValue, properties?: EventProperties): void {
  if (!client) {
    if (__DEV__) console.log('[track]', event, properties);
    return;
  }
  client.capture(event, properties);
}

export function identify(userId: string, properties?: EventProperties): void {
  if (!client) return;
  client.identify(userId, properties);
}

export function resetAnalytics(): void {
  if (!client) return;
  client.reset();
}

export function screen(name: string, properties?: EventProperties): void {
  if (!client) {
    if (__DEV__) console.log('[screen]', name, properties);
    return;
  }
  client.screen(name, properties);
}
