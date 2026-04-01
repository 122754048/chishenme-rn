import React, { useState, useEffect } from 'react';
import { View, Image, StyleSheet, ViewStyle } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  withDelay,
  Easing,
} from 'react-native-reanimated';
import { UtensilsCrossed } from 'lucide-react-native';
import { theme } from '../theme';

interface SkeletonImageProps {
  src: string;
  alt: string;
  style?: ViewStyle;
}

export function SkeletonImage({ src, alt, style }: SkeletonImageProps) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  // Shimmer animation
  const shimmerX = useSharedValue(-1);
  useEffect(() => {
    if (!loaded && !error) {
      shimmerX.value = withRepeat(
        withDelay(300, withTiming(1, { duration: 1000, easing: Easing.inOut(Easing.ease) })),
        -1,
        false
      );
    }
  }, [loaded, error]);

  const shimmerStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: shimmerX.value * 200 }],
  }));

  // Image fade-in
  const imageOpacity = useSharedValue(0);
  const handleLoad = () => {
    setLoaded(true);
    imageOpacity.value = withTiming(1, { duration: 300, easing: Easing.out(Easing.ease) });
  };

  const imageAnimStyle = useAnimatedStyle(() => ({
    opacity: imageOpacity.value,
  }));

  return (
    <View style={[styles.container, style]}>
      {/* Skeleton with shimmer */}
      {!loaded && !error && (
        <View style={styles.skeleton}>
          <Animated.View style={[styles.shimmer, shimmerStyle]} />
        </View>
      )}

      {/* Error placeholder */}
      {error && (
        <View style={styles.errorPlaceholder}>
          <UtensilsCrossed size={28} color={theme.colors.subtle} strokeWidth={1.5} />
        </View>
      )}

      {/* Actual image with fade-in */}
      {!error && (
        <Animated.View style={[styles.imageWrap, imageAnimStyle]}>
          <Image
            source={{ uri: src }}
            style={styles.image}
            onLoad={handleLoad}
            onError={() => setError(true)}
            resizeMode="cover"
            accessibilityLabel={alt}
          />
        </Animated.View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'relative',
    overflow: 'hidden',
    width: '100%',
    height: '100%',
  },
  skeleton: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: '#E8E8E8',
    overflow: 'hidden',
  },
  shimmer: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 120,
    backgroundColor: 'rgba(255,255,255,0.4)',
    // Slight skew for more natural shimmer feel
    transform: [{ skewX: '-15deg' }],
  },
  errorPlaceholder: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: theme.colors.borderLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  imageWrap: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  image: {
    width: '100%',
    height: '100%',
  },
});
