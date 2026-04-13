import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { useEffect, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { brand } from '../config/brand';
import { useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

const GUIDE_KEY = '@teller/has_seen_guide';
const LEGACY_GUIDE_KEY = '@chishenme/has_seen_guide';

export function OnboardingGuide() {
  const [visible, setVisible] = useState(false);
  const styles = useThemedStyles(makeStyles);

  useEffect(() => {
    async function checkGuide() {
      try {
        // Migrate legacy key if present
        const legacySeen = await AsyncStorage.getItem(LEGACY_GUIDE_KEY);
        if (legacySeen === 'true') {
          await AsyncStorage.setItem(GUIDE_KEY, 'true');
          await AsyncStorage.removeItem(LEGACY_GUIDE_KEY);
        }
        const seen = await AsyncStorage.getItem(GUIDE_KEY);
        if (seen !== 'true') setVisible(true);
      } catch {
        // Ignore storage read failures.
      }
    }

    void checkGuide();
  }, []);

  const handleDismiss = async () => {
    try {
      await AsyncStorage.setItem(GUIDE_KEY, 'true');
    } catch {
      // Ignore storage write failures.
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <Modal transparent animationType="fade" visible={visible} onRequestClose={handleDismiss} statusBarTranslucent>
      <View style={styles.overlay}>
        <View style={styles.content}>
          <Text style={styles.gestureText}>Swipe left to pass. Swipe right to keep it.</Text>
          <Text style={styles.gestureTextSub}>
            Each card pairs one nearby restaurant with one signature dish, plus the reason it fits now.
          </Text>

          <View style={styles.swipeIndicator}>
            <View style={styles.swipeArrow}>
              <Text style={styles.swipeArrowText}>Left</Text>
              <Text style={styles.swipeLabel}>Pass</Text>
            </View>
            <View style={styles.cardPlaceholder}>
              <Text style={styles.cardPlaceholderText}>Tonight&apos;s pick</Text>
            </View>
            <View style={styles.swipeArrow}>
              <Text style={styles.swipeArrowText}>Right</Text>
              <Text style={styles.swipeLabel}>Pick it</Text>
            </View>
          </View>

          <Pressable style={({ pressed }) => [styles.dismissBtn, pressed && styles.dismissBtnPressed]} onPress={handleDismiss}>
            <Text style={styles.dismissBtnText}>Start with {brand.appName}</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    overlay: {
      flex: 1,
      backgroundColor: 'rgba(0, 0, 0, 0.72)',
      justifyContent: 'center',
      alignItems: 'center',
      paddingHorizontal: 32,
    },
    content: {
      maxWidth: 320,
      alignItems: 'center',
      gap: 24,
    },
    gestureText: {
      fontSize: 22,
      fontWeight: '700',
      color: '#FFFFFF',
      textAlign: 'center',
    },
    gestureTextSub: {
      fontSize: 15,
      fontWeight: '500',
      color: 'rgba(255,255,255,0.84)',
      textAlign: 'center',
      lineHeight: 22,
      marginTop: -8,
    },
    swipeIndicator: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 20,
      marginVertical: 16,
    },
    swipeArrow: {
      alignItems: 'center',
      gap: 6,
    },
    swipeArrowText: {
      fontSize: 18,
      fontWeight: '700',
      color: '#FFFFFF',
    },
    swipeLabel: {
      fontSize: 14,
      fontWeight: '600',
      color: 'rgba(255,255,255,0.7)',
    },
    cardPlaceholder: {
      width: 112,
      height: 128,
      borderRadius: 12,
      backgroundColor: 'rgba(255,255,255,0.14)',
      borderWidth: 2,
      borderColor: 'rgba(255,255,255,0.28)',
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: 12,
    },
    cardPlaceholderText: {
      fontSize: 17,
      fontWeight: '700',
      color: '#FFFFFF',
      textAlign: 'center',
      lineHeight: 22,
    },
    dismissBtn: {
      backgroundColor: t.colors.primary,
      paddingHorizontal: 36,
      paddingVertical: 14,
      borderRadius: t.radius.full,
      marginTop: 8,
    },
    dismissBtnPressed: {
      opacity: 0.88,
      transform: [{ scale: 0.98 }],
    },
    dismissBtnText: {
      fontSize: 16,
      fontWeight: '700',
      color: '#FFFFFF',
    },
  });
}
