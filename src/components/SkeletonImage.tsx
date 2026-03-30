import React, { useState } from 'react';
import { View, Image, Text, StyleSheet, ViewStyle } from 'react-native';

interface SkeletonImageProps {
  src: string;
  alt: string;
  style?: ViewStyle;
}

// Issue #6: Removed `className` prop (meaningless in RN). Replaced with proper `style` prop.
export function SkeletonImage({ src, alt, style }: SkeletonImageProps) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  return (
    <View style={[styles.container, style]}>
      {!loaded && !error && <View style={styles.skeleton} />}
      {error ? (
        <View style={styles.errorPlaceholder}>
          <Text style={styles.errorIcon}>🍽️</Text>
        </View>
      ) : (
        <Image
          source={{ uri: src }}
          style={[styles.image, loaded ? styles.imageLoaded : styles.imageHidden]}
          onLoad={() => setLoaded(true)}
          onError={() => setError(true)}
          resizeMode="cover"
          accessibilityLabel={alt}
        />
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
    backgroundColor: '#e5e7eb',
  },
  errorPlaceholder: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: '#e5e7eb',
    alignItems: 'center',
    justifyContent: 'center',
  },
  errorIcon: {
    fontSize: 32,
  },
  image: {
    width: '100%',
    height: '100%',
  },
  imageHidden: {
    opacity: 0,
  },
  imageLoaded: {
    opacity: 1,
  },
});
