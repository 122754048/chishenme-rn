import React, { useEffect, useState } from 'react';
import { View, Text, Pressable, StyleSheet, Modal } from 'react-native';
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
        if (seen !== 'true') setVisible(true);
      } catch {
        // Keep default hidden on storage failure.
      }
    }
    void checkGuide();
  }, []);

  const handleDismiss = async () => {
    try {
      await AsyncStorage.setItem(GUIDE_KEY, 'true');
    } catch {
      // Ignore write failure.
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <Modal transparent animationType="fade" visible={visible} onRequestClose={handleDismiss} statusBarTranslucent>
      <View style={styles.overlay}>
        <View style={styles.content}>
          <Text style={styles.gestureText}>左滑跳过，右滑想吃</Text>
          <Text style={styles.gestureTextSub}>点开卡片就能看推荐理由、风险提示和备选方案</Text>

          <View style={styles.swipeIndicator}>
            <View style={styles.swipeArrow}>
              <Text style={styles.swipeArrowText}>左滑</Text>
              <Text style={styles.swipeLabel}>先跳过</Text>
            </View>
            <View style={styles.cardPlaceholder}>
              <Text style={styles.cardPlaceholderText}>今晚吃什么</Text>
            </View>
            <View style={styles.swipeArrow}>
              <Text style={styles.swipeArrowText}>右滑</Text>
              <Text style={styles.swipeLabel}>这个想吃</Text>
            </View>
          </View>

          <Pressable style={({ pressed }) => [styles.dismissBtn, pressed && styles.dismissBtnPressed]} onPress={handleDismiss}>
            <Text style={styles.dismissBtnText}>开始推荐</Text>
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
    },
    gestureTextSub: {
      fontSize: 16,
      fontWeight: '600',
      color: 'rgba(255, 255, 255, 0.82)',
      textAlign: 'center',
      lineHeight: 24,
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
      color: 'rgba(255, 255, 255, 0.7)',
    },
    cardPlaceholder: {
      width: 98,
      height: 118,
      borderRadius: 12,
      backgroundColor: 'rgba(255, 255, 255, 0.14)',
      borderWidth: 2,
      borderColor: 'rgba(255, 255, 255, 0.28)',
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: 12,
    },
    cardPlaceholderText: {
      fontSize: 18,
      fontWeight: '700',
      color: '#FFFFFF',
      textAlign: 'center',
      lineHeight: 24,
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
    },
  });
}
