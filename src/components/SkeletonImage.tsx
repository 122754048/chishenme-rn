import React, { useState } from 'react';
import { View, Image, StyleSheet } from 'react-native';

interface SkeletonImageProps {
  src: string;
  alt: string;
  className?: string;
}

export function SkeletonImage({ src, alt, className = '' }: SkeletonImageProps) {
  const [loaded, setLoaded] = useState(false);

  return (
    <View style={[styles.container, className as any]}>
      {!loaded && <View style={styles.skeleton} />}
      <Image
        source={{ uri: src }}
        style={[styles.image, loaded ? styles.imageLoaded : styles.imageHidden]}
        onLoad={() => setLoaded(true)}
        resizeMode="cover"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'relative',
    overflow: 'hidden',
  },
  skeleton: {
    position: 'absolute',
    inset: 0,
    backgroundColor: '#e5e7eb',
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
