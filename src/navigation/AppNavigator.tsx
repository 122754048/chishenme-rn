import React, { useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withSequence,
  withTiming,
  Easing,
} from 'react-native-reanimated';
import { Home as HomeIcon, Search, Heart, User } from 'lucide-react-native';
import { useApp } from '../context/AppContext';
import { useThemedStyles, useThemeColors } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import type { RootStackParamList, MainTabParamList } from './types';

import { Home } from '../screens/Home';
import { Explore } from '../screens/Explore';
import { Favorites } from '../screens/Favorites';
import { Profile } from '../screens/Profile';
import { Detail } from '../screens/Detail';
import { History } from '../screens/History';
import { Upgrade } from '../screens/Upgrade';
import { Checkout } from '../screens/Checkout';
import { OnboardingCuisines } from '../screens/OnboardingCuisines';
import { OnboardingRestrictions } from '../screens/OnboardingRestrictions';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<MainTabParamList>();

function MainTabs() {
  const theme = useThemeColors();
  const insets = useSafeAreaInsets();

  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          height: theme.tabBarHeight + insets.bottom,
          backgroundColor: theme.colors.surface,
          borderTopWidth: 0,
          paddingTop: 8,
          paddingBottom: insets.bottom > 0 ? insets.bottom : 8,
          ...theme.shadows.md,
        },
        tabBarActiveTintColor: theme.colors.primary,
        tabBarInactiveTintColor: theme.colors.subtle,
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: '600',
          marginTop: 2,
        },
      }}
    >
      <Tab.Screen
        name="Home"
        component={Home}
        options={{
          tabBarLabel: '首页',
          tabBarIcon: ({ focused, color }) => (
            <HomeIcon
              size={22}
              color={color}
              strokeWidth={focused ? 2.2 : 1.8}
              fill={focused ? theme.colors.primaryLight : 'transparent'}
            />
          ),
        }}
      />
      <Tab.Screen
        name="Explore"
        component={Explore}
        options={{
          tabBarLabel: '发现',
          tabBarIcon: ({ focused, color }) => (
            <Search size={22} color={color} strokeWidth={focused ? 2.2 : 1.8} />
          ),
        }}
      />
      <Tab.Screen
        name="Favorites"
        component={Favorites}
        options={{
          tabBarLabel: '收藏',
          tabBarIcon: ({ focused, color }) => (
            <Heart
              size={22}
              color={color}
              strokeWidth={focused ? 2.2 : 1.8}
              fill={focused ? theme.colors.primary : 'transparent'}
            />
          ),
        }}
      />
      <Tab.Screen
        name="Profile"
        component={Profile}
        options={{
          tabBarLabel: '我的',
          tabBarIcon: ({ focused, color }) => (
            <User size={22} color={color} strokeWidth={focused ? 2.2 : 1.8} />
          ),
        }}
      />
    </Tab.Navigator>
  );
}

function LoadingScreen() {
  const styles = useThemedStyles(makeStyles);
  const scale = useSharedValue(1);
  const opacity = useSharedValue(0.65);

  useEffect(() => {
    scale.value = withRepeat(
      withSequence(
        withTiming(1.12, { duration: 700, easing: Easing.inOut(Easing.ease) }),
        withTiming(1, { duration: 700, easing: Easing.inOut(Easing.ease) })
      ),
      -1,
      true
    );
    opacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 700, easing: Easing.inOut(Easing.ease) }),
        withTiming(0.65, { duration: 700, easing: Easing.inOut(Easing.ease) })
      ),
      -1,
      true
    );
  }, [opacity, scale]);

  const iconStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    opacity: opacity.value,
  }));

  return (
    <View style={styles.loading}>
      <Animated.View style={[styles.loadingIconWrap, iconStyle]}>
        <Text style={styles.loadingIcon}>CS</Text>
      </Animated.View>
      <Text style={styles.loadingTitle}>ChiShenMe</Text>
      <Text style={styles.loadingSubtitle}>正在整理更适合你的用餐选择</Text>
    </View>
  );
}

export function AppNavigator() {
  const { onboardingComplete, isLoading } = useApp();

  if (isLoading) {
    return <LoadingScreen />;
  }

  return (
    <NavigationContainer>
      <Stack.Navigator
        screenOptions={{
          headerShown: false,
          animation: 'fade',
          animationDuration: 250,
        }}
        initialRouteName={onboardingComplete ? 'MainTabs' : 'OnboardingCuisines'}
      >
        <Stack.Screen
          name="OnboardingCuisines"
          component={OnboardingCuisines}
          options={{ animation: 'slide_from_right', animationDuration: 300 }}
        />
        <Stack.Screen
          name="OnboardingRestrictions"
          component={OnboardingRestrictions}
          options={{ animation: 'slide_from_right', animationDuration: 300 }}
        />
        <Stack.Screen
          name="Upgrade"
          component={Upgrade}
          options={{ animation: 'slide_from_bottom', animationDuration: 350 }}
        />
        <Stack.Screen
          name="Checkout"
          component={Checkout}
          options={{ animation: 'slide_from_right', animationDuration: 300 }}
        />
        <Stack.Screen name="MainTabs" component={MainTabs} options={{ animation: 'fade' }} />
        <Stack.Screen
          name="Detail"
          component={Detail}
          options={{ animation: 'slide_from_right', animationDuration: 300 }}
        />
        <Stack.Screen
          name="History"
          component={History}
          options={{ animation: 'slide_from_right', animationDuration: 300 }}
        />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

function makeStyles(t: AppTheme) {
  return StyleSheet.create({
    loading: {
      flex: 1,
      backgroundColor: t.colors.background,
      alignItems: 'center',
      justifyContent: 'center',
    },
    loadingIconWrap: {
      width: 80,
      height: 80,
      borderRadius: t.radius.lg,
      backgroundColor: t.colors.primaryLight,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: 16,
    },
    loadingIcon: {
      fontSize: 28,
      fontWeight: '800',
      color: t.colors.primary,
    },
    loadingTitle: {
      ...t.typography.display,
      color: t.colors.primary,
      marginBottom: 8,
    },
    loadingSubtitle: {
      ...t.typography.body,
      color: t.colors.subtle,
    },
  });
}
