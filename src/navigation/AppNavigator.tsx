import React from 'react';
import { View, StyleSheet, Text, ActivityIndicator } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { useApp } from '../context/AppContext';

import { Home } from '../screens/Home';
import { Explore } from '../screens/Explore';
import { Favorites } from '../screens/Favorites';
import { Profile } from '../screens/Profile';
import { Detail } from '../screens/Detail';
import { History } from '../screens/History';
import { Upgrade } from '../screens/Upgrade';
import { OnboardingCuisines } from '../screens/OnboardingCuisines';
import { OnboardingRestrictions } from '../screens/OnboardingRestrictions';
import { AccountInfo } from '../screens/AccountInfo';
import { MembershipInfo } from '../screens/MembershipInfo';
import { PrivacyPolicy } from '../screens/PrivacyPolicy';
import { About } from '../screens/About';

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

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
          tabBarIcon: ({ focused }) => (
            <View style={{ alignItems: 'center', justifyContent: 'center' }}>
              <View
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 13,
                  backgroundColor: focused ? '#E8F5E9' : 'transparent',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <View style={{ transform: [{ scale: focused ? 1.1 : 0.95 }] }}>
                  <TabIconEmoji emoji="🏠" />
                </View>
              </View>
            </View>
          ),
        }}
      />
      <Tab.Screen
        name="Explore"
        component={Explore}
        options={{
          tabBarLabel: 'Explore',
          tabBarIcon: ({ focused }) => (
            <View style={{ alignItems: 'center', justifyContent: 'center' }}>
              <View
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 13,
                  backgroundColor: focused ? '#E8F5E9' : 'transparent',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <TabIconEmoji emoji="🔍" />
              </View>
            </View>
          ),
        }}
      />
      <Tab.Screen
        name="Favorites"
        component={Favorites}
        options={{
          tabBarLabel: 'Favorites',
          tabBarIcon: ({ focused }) => (
            <View style={{ alignItems: 'center', justifyContent: 'center' }}>
              <View
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 13,
                  backgroundColor: focused ? '#E8F5E9' : 'transparent',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <TabIconEmoji emoji="❤️" />
              </View>
            </View>
          ),
        }}
      />
      <Tab.Screen
        name="Profile"
        component={Profile}
        options={{
          tabBarLabel: 'Profile',
          tabBarIcon: ({ focused }) => (
            <View style={{ alignItems: 'center', justifyContent: 'center' }}>
              <View
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 13,
                  backgroundColor: focused ? '#E8F5E9' : 'transparent',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <TabIconEmoji emoji="👤" />
              </View>
            </View>
          ),
        }}
      />
    </Tab.Navigator>
  );
}

function TabIconEmoji({ emoji }: { emoji: string }) {
  return (
    <Text style={styles.tabEmoji} accessibilityLabel="tab icon">
      {emoji}
    </Text>
  );
}

export function AppNavigator() {
  const { onboardingComplete, isLoading } = useApp();

  if (isLoading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="small" color="#4CAF50" />
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
        <Stack.Screen
          name="AccountInfo"
          component={AccountInfo}
          options={{ animation: 'slide_from_right' }}
        />
        <Stack.Screen
          name="MembershipInfo"
          component={MembershipInfo}
          options={{ animation: 'slide_from_right' }}
        />
        <Stack.Screen
          name="PrivacyPolicy"
          component={PrivacyPolicy}
          options={{ animation: 'slide_from_right' }}
        />
        <Stack.Screen
          name="About"
          component={About}
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
  tabEmoji: {
    fontSize: 14,
    lineHeight: 16,
  },
});
