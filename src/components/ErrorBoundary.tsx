import React, { Component, type ErrorInfo, type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { TriangleAlert } from 'lucide-react-native';
import { theme } from '../theme';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('App Error:', error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      return (
        <View style={styles.container}>
          <View style={styles.iconWrap}>
            <TriangleAlert size={32} color={theme.colors.error} strokeWidth={2} />
          </View>
          <Text style={styles.title}>Something went wrong</Text>
          <Text style={styles.message}>{this.state.error?.message || 'Please try again in a moment.'}</Text>
          <Pressable style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.9, transform: [{ scale: 0.97 }] }]} onPress={this.handleRetry} accessibilityRole="button" accessibilityLabel="Retry">
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      );
    }
    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: theme.colors.background,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: theme.spacing.xl,
  },
  iconWrap: {
    width: 80,
    height: 80,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.errorLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: theme.spacing.md,
  },
  title: {
    ...theme.typography.h1,
    color: theme.colors.foreground,
    marginBottom: theme.spacing.xs,
    textAlign: 'center',
  },
  message: {
    ...theme.typography.body,
    color: theme.colors.muted,
    textAlign: 'center',
    marginBottom: theme.spacing.lg,
  },
  retryBtn: {
    backgroundColor: theme.colors.primary,
    paddingHorizontal: theme.spacing.xl,
    paddingVertical: theme.spacing.sm,
    borderRadius: theme.radius.full,
    ...theme.shadows.md,
  },
  retryText: {
    ...theme.typography.h2,
    color: theme.colors.surface,
  },
});
