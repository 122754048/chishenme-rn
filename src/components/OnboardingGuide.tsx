import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Modal,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';

const GUIDE_KEY = '@chishenme/has_seen_guide';

export function OnboardingGuide() {
  const [visible, setVisible] = useState(false);
  const styles = useThemedStyles(makeStyles);

  useEffect(() => {
    async function checkGuide() {
      try {
        const seen = await AsyncStorage.getItem(GUIDE_KEY);
        if (seen !== 'true') {
          setVisible(true);
        }
      } catch {
        // If read fails, don't show guide (safe default)
      }
    }
    checkGuide();
  }, []);

  const handleDismiss = async () => {
    try {
      await AsyncStorage.setItem(GUIDE_KEY, 'true');
    } catch {
      // Ignore write failure
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <Modal
      transparent
      animationType="fade"
      visible={visible}
      onRequestClose={handleDismiss}
      statusBarTranslucent
    >
      <View style={styles.overlay}>
        <View style={styles.content}>
          {/* Gesture hints */}
          <Text style={styles.gestureText}>
            👈 左滑跳过 / 右滑喜欢 👉
          </Text>
          <Text style={styles.gestureTextSub}>
            ⬇️ 下滑查看详情
          </Text>

          {/* Visual swipe indicator */}
          <View style={styles.swipeIndicator}>
            <View style={styles.swipeArrowLeft}>
              <Text style={styles.swipeArrowText}>✕</Text>
              <Text style={styles.swipeLabel}>跳过</Text>
            </View>
            <View style={styles.cardPlaceholder}>
              <Text style={styles.cardPlaceholderEmoji}>🍽️</Text>
            </View>
            <View style={styles.swipeArrowRight}>
              <Text style={styles.swipeArrowText}>❤️</Text>
              <Text style={styles.swipeLabel}>喜欢</Text>
            </View>
          </View>

          {/* Dismiss button */}
          <Pressable
            style={({ pressed }) => [styles.dismissBtn, pressed && styles.dismissBtnPressed]}
            onPress={handleDismiss}
          >
            <Text style={styles.dismissBtnText}>知道了</Text>
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
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      justifyContent: 'center',
      alignItems: 'center',
      paddingHorizontal: 32,
    },
    content: {
      alignItems: 'center',
      gap: 24,
    },
    gestureText: {
      fontSize: 22,
      fontWeight: '700',
      color: '#FFFFFF',
      textAlign: 'center',
      letterSpacing: 1,
    },
    gestureTextSub: {
      fontSize: 18,
      fontWeight: '600',
      color: 'rgba(255, 255, 255, 0.8)',
      textAlign: 'center',
      marginTop: -8,
    },
    swipeIndicator: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 24,
      marginVertical: 16,
    },
    swipeArrowLeft: {
      alignItems: 'center',
      gap: 4,
    },
    swipeArrowRight: {
      alignItems: 'center',
      gap: 4,
    },
    swipeArrowText: {
      fontSize: 32,
    },
    swipeLabel: {
      fontSize: 14,
      fontWeight: '600',
      color: 'rgba(255, 255, 255, 0.7)',
    },
    cardPlaceholder: {
      width: 80,
      height: 100,
      borderRadius: 12,
      backgroundColor: 'rgba(255, 255, 255, 0.15)',
      borderWidth: 2,
      borderColor: 'rgba(255, 255, 255, 0.3)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    cardPlaceholderEmoji: {
      fontSize: 36,
    },
    dismissBtn: {
      backgroundColor: t.colors.primary,
      paddingHorizontal: 48,
      paddingVertical: 14,
      borderRadius: t.radius.full,
      marginTop: 8,
    },
    dismissBtnPressed: {
      opacity: 0.85,
      transform: [{ scale: 0.97 }],
    },
    dismissBtnText: {
      fontSize: 16,
      fontWeight: '700',
      color: '#FFFFFF',
      letterSpacing: 1,
    },
  });
}
