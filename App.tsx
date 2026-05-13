import React, { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { useColorScheme } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import {
  useFonts,
  Nunito_400Regular,
  Nunito_500Medium,
  Nunito_600SemiBold,
  Nunito_700Bold,
  Nunito_800ExtraBold,
} from '@expo-google-fonts/nunito';
import { AppProvider } from './src/context/AppContext';
import { AppNavigator } from './src/navigation/AppNavigator';
import { ErrorBoundary } from './src/components/ErrorBoundary';
import { ToastProvider } from './src/components/ToastProvider';
import { initI18n } from './src/i18n';
import { initSentry, initAnalytics, track, EventName } from './src/monitoring';

export default function App() {
  const colorScheme = useColorScheme();
  const [bootstrapReady, setBootstrapReady] = useState(false);

  const [fontsLoaded] = useFonts({
    Nunito_400Regular,
    Nunito_500Medium,
    Nunito_600SemiBold,
    Nunito_700Bold,
    Nunito_800ExtraBold,
  });

  // One-shot bootstrap: Sentry first (so it captures any later init errors),
  // then analytics, then i18n. We don't block render on fonts (system fallback OK).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Sentry is sync init — call it first so subsequent failures get reported.
      initSentry();
      await Promise.allSettled([initAnalytics(), initI18n()]);
      if (!cancelled) {
        setBootstrapReady(true);
        track(EventName.AppOpened);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Render shell even before bootstrap completes — i18n falls back to keys
  // which are immediately replaced once init resolves. This is intentional:
  // we want first-paint < 100ms and accept brief key flashes in worst case.
  // (Splash screen is the right long-term answer; not in this PR.)
  void bootstrapReady;
  void fontsLoaded;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ErrorBoundary>
        <SafeAreaProvider>
          <AppProvider>
            {/* ToastProvider wraps NavigationContainer so any screen can call useToast() */}
            <ToastProvider>
              <StatusBar style={colorScheme === 'dark' ? 'light' : 'dark'} />
              <AppNavigator />
            </ToastProvider>
          </AppProvider>
        </SafeAreaProvider>
      </ErrorBoundary>
    </GestureHandlerRootView>
  );
}
