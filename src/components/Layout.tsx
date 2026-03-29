import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Platform,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { theme } from '../theme';

interface TopNavProps {
  title?: React.ReactNode;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  onLeftClick?: () => void;
  onRightClick?: () => void;
  transparent?: boolean;
  insets?: { top: number };
}

export function TopNav({
  title,
  leftIcon,
  rightIcon,
  onLeftClick,
  onRightClick,
  transparent = false,
  insets,
}: TopNavProps) {
  const paddingTop = insets?.top ?? 0;

  return (
    <View
      style={[
        styles.topNav,
        { paddingTop: paddingTop + 4 },
        transparent ? styles.transparent : styles.solid,
      ]}
    >
      <TouchableOpacity
        style={styles.iconBtn}
        onPress={onLeftClick}
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
      >
        {leftIcon ?? <View style={styles.chevronPlaceholder} />}
      </TouchableOpacity>
      <View style={styles.titleContainer}>
        {typeof title === 'string' ? (
          <Text
            style={[styles.title, transparent ? styles.titleTransparent : styles.titleSolid]}
            numberOfLines={1}
          >
            {title}
          </Text>
        ) : (
          title
        )}
      </View>
      <TouchableOpacity
        style={styles.iconBtnRight}
        onPress={onRightClick}
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
      >
        {rightIcon}
      </TouchableOpacity>
    </View>
  );
}

interface BottomNavProps {
  currentRoute: string;
  onNavigate: (route: string) => void;
}

const NAV_ITEMS = [
  { key: 'Home', label: 'Home', iconName: 'home' },
  { key: 'Explore', label: 'Explore', iconName: 'search' },
  { key: 'Favorites', label: 'Favorites', iconName: 'heart' },
  { key: 'Profile', label: 'Profile', iconName: 'user' },
];

// Simple SVG-like icons using Text for this prototype
function Icon({ name, focused }: { name: string; focused: boolean }) {
  const color = focused ? theme.colors.brand : '#9ca3af';
  const size = 22;
  if (name === 'home') {
    return (
      <Text style={{ fontSize: size, color }}>🏠</Text>
    );
  }
  if (name === 'search') {
    return (
      <Text style={{ fontSize: size, color }}>🔍</Text>
    );
  }
  if (name === 'heart') {
    return (
      <Text style={{ fontSize: size, color }}>❤️</Text>
    );
  }
  if (name === 'user') {
    return (
      <Text style={{ fontSize: size, color }}>👤</Text>
    );
  }
  return null;
}

export function BottomNav({ currentRoute, onNavigate }: BottomNavProps) {
  const insets = useSafeAreaInsets();

  const routeMap: Record<string, string> = {
    Home: '/',
    Explore: '/explore',
    Favorites: '/favorites',
    Profile: '/profile',
  };

  return (
    <View style={[styles.bottomNav, { paddingBottom: insets.bottom > 0 ? insets.bottom : 8 }]}>
      {NAV_ITEMS.map((item) => {
        const isActive = currentRoute === item.key;
        return (
          <TouchableOpacity
            key={item.key}
            style={styles.navItem}
            onPress={() => onNavigate(routeMap[item.key])}
          >
            <Icon name={item.iconName} focused={isActive} />
            <Text
              style={[
                styles.navLabel,
                { color: isActive ? theme.colors.brand : '#9ca3af' },
              ]}
            >
              {item.label}
            </Text>
            {isActive && <View style={styles.activeDot} />}
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  topNav: {
    height: theme.topNavHeight + (Platform.OS === 'ios' ? 0 : 4),
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    zIndex: 50,
  },
  solid: {
    backgroundColor: theme.colors.surface,
  },
  transparent: {
    backgroundColor: 'transparent',
  },
  iconBtn: {
    width: 40,
    height: 40,
    alignItems: 'flex-start',
    justifyContent: 'center',
  },
  iconBtnRight: {
    width: 40,
    height: 40,
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
  chevronPlaceholder: {
    width: 24,
    height: 24,
  },
  titleContainer: {
    flex: 1,
    alignItems: 'center',
  },
  title: {
    fontSize: 16,
    fontWeight: '500',
  },
  titleTransparent: {
    color: '#ffffff',
  },
  titleSolid: {
    color: theme.colors.foreground,
  },
  bottomNav: {
    flexDirection: 'row',
    backgroundColor: '#ffffff',
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
    paddingTop: 8,
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  navLabel: {
    fontSize: 10,
    fontWeight: '500',
  },
  activeDot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: theme.colors.brand,
    marginTop: 1,
  },
});
