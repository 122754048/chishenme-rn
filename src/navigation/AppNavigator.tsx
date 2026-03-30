import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { useApp } from '../context/AppContext';
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

// Issue #2: Removed unused `TabIcon` component (dead code).

// P2: Extracted inline tab icon styles into TabBarIcon component + tabStyles StyleSheet.
function TabBarIcon({ emoji, focused }: { emoji: string; focused: boolean }) {
  return (
    <View style={tabStyles.iconContainer}>
      <View style={[tabStyles.iconBg, focused && tabStyles.iconBgFocused]}>
        <View style={focused ? tabStyles.iconScaleFocused : tabStyles.iconScale}>
          <Text style={tabStyles.emoji}>{emoji}</Text>
        </View>
      </View>
    </View>
  );
}

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          height: 60,
          backgroundColor: '#ffffff',
          borderTopWidth: 1,
          borderTopColor: '#f3f4f6',
          paddingBottom: 4,
          paddingTop: 4,
        },
        tabBarActiveTintColor: '#4CAF50',
        tabBarInactiveTintColor: '#9ca3af',
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '500',
        },
      }}
    >
      <Tab.Screen
        name="Home"
        component={Home}
        options={{
          tabBarLabel: 'Home',
          tabBarIcon: ({ focused }) => <TabBarIcon emoji="🏠" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="Explore"
        component={Explore}
        options={{
          tabBarLabel: 'Explore',
          tabBarIcon: ({ focused }) => <TabBarIcon emoji="🔍" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="Favorites"
        component={Favorites}
        options={{
          tabBarLabel: 'Favorites',
          tabBarIcon: ({ focused }) => <TabBarIcon emoji="❤️" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="Profile"
        component={Profile}
        options={{
          tabBarLabel: 'Profile',
          tabBarIcon: ({ focused }) => <TabBarIcon emoji="👤" focused={focused} />,
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
        <Text style={styles.loadingIcon}>🍽️</Text>
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
    backgroundColor: '#f5f5f5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  loadingIcon: {
    fontSize: 64,
    marginBottom: 16,
  },
  loadingTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: '#4CAF50',
    marginBottom: 8,
  },
  loadingSubtitle: {
    fontSize: 14,
    color: '#9ca3af',
    fontWeight: '500',
  },
});

const tabStyles = StyleSheet.create({
  iconContainer: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconBg: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: 'transparent',
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconBgFocused: {
    backgroundColor: '#E8F5E9',
  },
  iconScale: {
    transform: [{ scale: 0.95 }],
  },
  iconScaleFocused: {
    transform: [{ scale: 1.1 }],
  },
  emoji: {
    fontSize: 18,
  },
});
