/**
 * src/monitoring/navigationTracking.ts
 *
 * Auto-fires analytics screen events when React Navigation route changes.
 * Wired into <NavigationContainer onStateChange/onReady> in AppNavigator.
 *
 * Why this layer instead of putting useEffect on every screen:
 *   - One source of truth: every screen is tracked the same way.
 *   - Picks up nested-tab and modal transitions for free.
 *   - Survives screen rename (you only update the navigator config, not 11 files).
 *
 * Privacy:
 *   - We track route name only — never params (which could carry user input).
 *   - PostHog client is no-op without DSN, so this file is safe in dev.
 */
import type { NavigationContainerRef, NavigationState, PartialState } from '@react-navigation/native';
import { screen, track, EventName } from './analytics';
import { addBreadcrumb } from './sentry';

/**
 * Walk down nested navigator state to find the leaf route name.
 * React Navigation nests tab navigators inside stack navigators; we want the
 * deepest visible screen, not "MainTabs".
 */
export function getActiveRouteName(
  state: NavigationState | PartialState<NavigationState> | undefined,
): string | undefined {
  if (!state) return undefined;
  const route = state.routes[state.index ?? 0];
  if (!route) return undefined;
  if (route.state) {
    return getActiveRouteName(route.state as NavigationState);
  }
  return route.name;
}

/**
 * Factory: returns an onStateChange handler bound to a navigation ref.
 *
 * Usage in AppNavigator:
 *   const navRef = useRef<NavigationContainerRef<RootStackParamList>>(null);
 *   const onStateChange = createNavigationStateTracker(navRef);
 *   <NavigationContainer
 *     ref={navRef}
 *     onReady={() => onStateChange(navRef.current?.getRootState())}
 *     onStateChange={onStateChange}
 *   >
 */
export function createNavigationStateTracker<ParamList extends object>(
  navRef: React.RefObject<NavigationContainerRef<ParamList> | null>,
) {
  let lastRouteName: string | undefined;

  return function onStateChange(state: NavigationState | undefined): void {
    const next = getActiveRouteName(state ?? navRef.current?.getRootState());
    if (!next || next === lastRouteName) return;

    const previous = lastRouteName;
    lastRouteName = next;

    // Sentry breadcrumb — tiny, no-op when SDK disabled.
    addBreadcrumb({
      category: 'navigation',
      message: `${previous ?? '(initial)'} -> ${next}`,
      level: 'info',
    });

    // PostHog screen + screen_viewed event.
    // We send both because PostHog's $screen is special-cased for funnels,
    // and our canonical EventName.ScreenViewed lets us join with custom props.
    screen(next, { previous_screen: previous ?? null });
    track(EventName.ScreenViewed, {
      screen_name: next,
      previous_screen: previous ?? null,
    });
  };
}
