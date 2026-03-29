import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Animated, {
  useAnimatedStyle,
  withTiming,
  useSharedValue,
  withSpring,
} from 'react-native-reanimated';
import { theme } from '../theme';
import { CUISINES } from '../data/mockData';
import { useApp } from '../context/AppContext';

type NavProp = NativeStackNavigationProp<any>;

export function OnboardingCuisines() {
  const navigation = useNavigation<NavProp>();
  const { setCuisines } = useApp();
  const [selected, setSelected] = useState<string[]>(['Sichuan', 'Western']);

  const toggleSelect = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleNext = async () => {
    await setCuisines(selected);
    navigation.navigate('OnboardingRestrictions');
  };

  const progressWidth = useSharedValue(33.3);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <View style={{ width: 40 }} />
        <Text style={styles.skipText} onPress={() => navigation.navigate('MainTabs')}>
          Skip
        </Text>
      </View>

      <View style={styles.progressContainer}>
        <View style={styles.progressTrack}>
          <Animated.View style={[styles.progressBar, { width: `${33.3}%` }]} />
        </View>
        <Text style={styles.stepLabel}>1/3</Text>
      </View>

      <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent}>
        <Text style={styles.title}>
          Which cuisines do you{'\n'}like?
        </Text>
        <Text style={styles.subtitle}>Select multiple to personalize your food journey.</Text>

        <View style={styles.cuisineGrid}>
          {CUISINES.map((item) => {
            const isSelected = selected.includes(item.id);
            return (
              <TouchableOpacity
                key={item.id}
                style={[
                  styles.cuisineCard,
                  isSelected && styles.cuisineCardSelected,
                ]}
                onPress={() => toggleSelect(item.id)}
                activeOpacity={0.7}
              >
                <View style={styles.cuisineLeft}>
                  <Text style={styles.cuisineIcon}>{item.icon}</Text>
                  <Text
                    style={[
                      styles.cuisineLabel,
                      isSelected && styles.cuisineLabelSelected,
                    ]}
                  >
                    {item.label}
                  </Text>
                </View>
                <View style={styles.checkmark}>
                  {isSelected ? (
                    <Text style={styles.checkmarkIcon}>✓</Text>
                  ) : (
                    <View style={styles.circleEmpty} />
                  )}
                </View>
              </TouchableOpacity>
            );
          })}
        </View>

        <View style={styles.banner}>
          <Image
            source={{ uri: 'https://images.unsplash.com/photo-1540420773420-3366772f4999?w=800' }}
            style={styles.bannerImage}
          />
          <View style={styles.bannerOverlay}>
            <Text style={styles.bannerText}>
              Customize your palate to get the best{'\n'}recommendations every day.
            </Text>
          </View>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <TouchableOpacity style={styles.nextButton} onPress={handleNext} activeOpacity={0.8}>
          <Text style={styles.nextButtonText}>Next</Text>
          <Text style={styles.arrowIcon}>→</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.surface,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  skipText: {
    fontSize: 13,
    color: '#9ca3af',
    fontWeight: '500',
  },
  progressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    marginBottom: 24,
    gap: 8,
  },
  progressTrack: {
    flex: 1,
    height: 4,
    backgroundColor: '#e5e7eb',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressBar: {
    height: '100%',
    backgroundColor: theme.colors.brand,
    borderRadius: 2,
  },
  stepLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: theme.colors.brand,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 16,
    paddingBottom: 24,
  },
  title: {
    fontSize: 26,
    fontWeight: '700',
    color: theme.colors.foreground,
    marginBottom: 8,
    lineHeight: 34,
  },
  subtitle: {
    fontSize: 14,
    color: '#6b7280',
    marginBottom: 24,
  },
  cuisineGrid: {
    gap: 10,
    marginBottom: 24,
  },
  cuisineCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#ffffff',
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderWidth: 1.5,
    borderColor: 'transparent',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  cuisineCardSelected: {
    backgroundColor: theme.colors.brandLight,
    borderColor: theme.colors.brand,
  },
  cuisineLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  cuisineIcon: {
    fontSize: 18,
  },
  cuisineLabel: {
    fontSize: 15,
    fontWeight: '500',
    color: '#374151',
  },
  cuisineLabelSelected: {
    color: theme.colors.brandDark,
    fontWeight: '600',
  },
  checkmark: {
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkmarkIcon: {
    fontSize: 16,
    color: theme.colors.brand,
    fontWeight: '700',
  },
  circleEmpty: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: '#d1d5db',
  },
  banner: {
    borderRadius: 14,
    overflow: 'hidden',
    height: 128,
  },
  bannerImage: {
    width: '100%',
    height: '100%',
    position: 'absolute',
  },
  bannerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.35)',
    justifyContent: 'flex-end',
    padding: 16,
  },
  bannerText: {
    fontSize: 12,
    color: '#ffffff',
    fontWeight: '500',
    lineHeight: 18,
  },
  footer: {
    paddingHorizontal: 16,
    paddingVertical: 16,
    backgroundColor: '#ffffff',
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
  },
  nextButton: {
    backgroundColor: theme.colors.brandAccent,
    borderRadius: 30,
    paddingVertical: 15,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  nextButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '700',
  },
  arrowIcon: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '700',
  },
});
