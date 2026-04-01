import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Home as HomeIcon, Search, Heart, User } from 'lucide-react-native';
import { useApp } from '../context/AppContext';
import { theme } from '../theme';
import type { RootStackParamList, MainTabParamList } from './types';

import { Home } from '../screens/Home';
import { Explore } from '../screens/Explore';
import { Favorites } from '../screens/Favorites';
import { Profile } from '../screens/Profile';
import { Detail } from '../screens/Detail';
import { History } from '../screens/History';
import { Upgrade } from '../screens/Upgrade';
import { OnboardingCuisines } from '../screens/OnboardingCuisines';
import { OnboardingRestrictions } from '../screens/OnboardingRestrictions';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<MainTabParamList>();

function MainTabs() {
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
          tabBarLabel: 'Home',
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
          tabBarLabel: 'Explore',
          tabBarIcon: ({ focused, color }) => (
            <Search size={22} color={color} strokeWidth={focused ? 2.2 : 1.8} />
          ),
        }}
      />
      <Tab.Screen
        name="Favorites"
        component={Favorites}
        options={{
          tabBarLabel: 'Favorites',
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
          tabBarLabel: 'Profile',
          tabBarIcon: ({ focused, color }) => (
            <User size={22} color={color} strokeWidth={focused ? 2.2 : 1.8} />
          ),
        }}
      />
    </Tab.Navigator>
  );
}

export function AppNavigator() {
  const { onboardingComplete, isLoading } = useApp();

  if (isLoading) {
    return (
      <View style={styles.loading}>
        <View style={styles.loadingIconWrap}>
          <Text style={styles.loadingIcon}>🍽️</Text>
        </View>
        <Text style={styles.loadingTitle}>ChiShenMe</Text>
        <Text style={styles.loadingSubtitle}>Deciding what to eat...</Text>
      </View>
    );
  }

  return (
    <NavigationContainer>
      <Stack.Navigator
        screenOptions={{ headerShown: false }}
        initialRouteName={onboardingComplete ? 'MainTabs' : 'OnboardingCuisines'}
      >
        {/* Onboarding flow */}
        <Stack.Screen name="OnboardingCuisines" component={OnboardingCuisines} />
        <Stack.Screen name="OnboardingRestrictions" component={OnboardingRestrictions} />
        <Stack.Screen name="Upgrade" component={Upgrade} />

        {/* Main Tab */}
        <Stack.Screen name="MainTabs" component={MainTabs} />

        {/* Detail pages */}
        <Stack.Screen
          name="Detail"
          component={Detail}
          options={{ animation: 'slide_from_right' }}
        />
        <Stack.Screen
          name="History"
          component={History}
          options={{ animation: 'slide_from_right' }}
        />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    backgroundColor: theme.colors.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingIconWrap: {
    width: 80,
    height: 80,
    borderRadius: theme.radius.lg,
    backgroundColor: theme.colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  loadingIcon: {
    fontSize: 40,
  },
  loadingTitle: {
    ...theme.typography.display,
    color: theme.colors.primary,
    marginBottom: 8,
  },
  loadingSubtitle: {
    ...theme.typography.body,
    color: theme.colors.subtle,
  },
});
