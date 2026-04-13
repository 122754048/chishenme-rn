import React, { useEffect } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Heart, Home as HomeIcon, Search, User } from 'lucide-react-native';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { OnboardingGuide } from '../components/OnboardingGuide';
import { useApp } from '../context/AppContext';
import { brand } from '../config/brand';
import { Checkout } from '../screens/Checkout';
import { DeveloperMode } from '../screens/DeveloperMode';
import { Detail } from '../screens/Detail';
import { Explore } from '../screens/Explore';
import { Favorites } from '../screens/Favorites';
import { History } from '../screens/History';
import { Home } from '../screens/Home';
import { MenuScan } from '../screens/MenuScan';
import { OnboardingCuisines } from '../screens/OnboardingCuisines';
import { OnboardingRestrictions } from '../screens/OnboardingRestrictions';
import { Profile } from '../screens/Profile';
import { Upgrade } from '../screens/Upgrade';
import { useThemeColors, useThemedStyles } from '../theme';
import type { AppTheme } from '../theme/useTheme';
import type { MainTabParamList, RootStackParamList } from './types';

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
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: theme.tabBarHeight + Math.max(insets.bottom, 8),
          backgroundColor: theme.colors.surface,
          borderTopWidth: 1,
          borderTopColor: theme.colors.borderLight,
          borderRadius: 0,
          paddingTop: 6,
          paddingBottom: Math.max(insets.bottom, 8),
        },
        tabBarItemStyle: {
          borderRadius: 12,
          marginHorizontal: 0,
        },
        tabBarActiveTintColor: theme.colors.primary,
        tabBarInactiveTintColor: theme.colors.subtle,
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '600',
          marginTop: 0,
        },
      }}
    >
      <Tab.Screen
        name="Home"
        component={Home}
        options={{
          tabBarLabel: 'Home',
          tabBarIcon: ({ color, focused }) => (
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
          tabBarLabel: 'Explore',
          tabBarIcon: ({ color, focused }) => <Search size={22} color={color} strokeWidth={focused ? 2.2 : 1.8} />,
        }}
      />
      <Tab.Screen
        name="Favorites"
        component={Favorites}
        options={{
          tabBarLabel: 'Saved',
          tabBarIcon: ({ color, focused }) => (
            <Heart
              size={22}
              color={color}
              strokeWidth={focused ? 2.2 : 1.8}
              fill={focused ? theme.colors.primaryLight : 'transparent'}
            />
          ),
        }}
      />
      <Tab.Screen
        name="Profile"
        component={Profile}
        options={{
          tabBarLabel: 'Profile',
          tabBarIcon: ({ color, focused }) => <User size={22} color={color} strokeWidth={focused ? 2.2 : 1.8} />,
        }}
      />
    </Tab.Navigator>
  );
}

function LoadingScreen() {
  const styles = useThemedStyles(makeStyles);
  const scale = useSharedValue(1);
  const opacity = useSharedValue(0.7);

  useEffect(() => {
    scale.value = withRepeat(
      withSequence(
        withTiming(1.08, { duration: 700, easing: Easing.inOut(Easing.ease) }),
        withTiming(1, { duration: 700, easing: Easing.inOut(Easing.ease) })
      ),
      -1,
      true
    );
    opacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 700, easing: Easing.inOut(Easing.ease) }),
        withTiming(0.7, { duration: 700, easing: Easing.inOut(Easing.ease) })
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
        <Text style={styles.loadingIcon}>T</Text>
      </Animated.View>
      <Text style={styles.loadingTitle}>{brand.appName}</Text>
      <Text style={styles.loadingSubtitle}>Finding a better pick for right now.</Text>
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
          animationDuration: 240,
        }}
        initialRouteName={onboardingComplete ? 'MainTabs' : 'OnboardingCuisines'}
      >
        <Stack.Screen name="OnboardingCuisines" component={OnboardingCuisines} options={{ animation: 'slide_from_right' }} />
        <Stack.Screen
          name="OnboardingRestrictions"
          component={OnboardingRestrictions}
          options={{ animation: 'slide_from_right' }}
        />
        <Stack.Screen name="Upgrade" component={Upgrade} options={{ animation: 'slide_from_bottom' }} />
        <Stack.Screen name="DeveloperMode" component={DeveloperMode} options={{ presentation: 'modal', animation: 'slide_from_bottom' }} />
        <Stack.Screen name="Checkout" component={Checkout} options={{ presentation: 'modal', animation: 'slide_from_bottom' }} />
        <Stack.Screen name="MainTabs" component={MainTabs} options={{ animation: 'fade' }} />
        <Stack.Screen name="Detail" component={Detail} options={{ animation: 'fade_from_bottom', fullScreenGestureEnabled: true }} />
        <Stack.Screen name="History" component={History} options={{ animation: 'slide_from_right' }} />
        <Stack.Screen name="MenuScan" component={MenuScan} options={{ presentation: 'modal', animation: 'slide_from_bottom' }} />
      </Stack.Navigator>
      <OnboardingGuide />
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
      fontSize: 32,
      fontWeight: '800',
      color: t.colors.primary,
    },
    loadingTitle: {
      ...t.typography.display,
      color: t.colors.foreground,
      marginBottom: 8,
    },
    loadingSubtitle: {
      ...t.typography.body,
      color: t.colors.subtle,
    },
  });
}
