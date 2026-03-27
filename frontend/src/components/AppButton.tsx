import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { theme } from '@/theme';

type AppButtonProps = {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: 'primary' | 'card';
  leftIcon?: React.ReactNode;
};

const AppButtonComponent = ({
  title,
  onPress,
  disabled = false,
  loading = false,
  variant = 'primary',
  leftIcon,
}: AppButtonProps) => {
  return (
    <Pressable
      style={[styles.button, variant === 'card' ? styles.cardButton : styles.primaryButton, (disabled || loading) && styles.disabled]}
      onPress={onPress}
      disabled={disabled || loading}
    >
      <View style={styles.content}>
        {loading ? (
          <ActivityIndicator color={theme.colors.textPrimary} />
        ) : (
          <View style={styles.row}>
            {leftIcon ? <View style={styles.iconWrap}>{leftIcon}</View> : null}
            <Text style={styles.label}>{title}</Text>
          </View>
        )}
      </View>
    </Pressable>
  );
};

export const AppButton = React.memo(AppButtonComponent);
AppButton.displayName = 'AppButton';

const styles = StyleSheet.create({
  button: {
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    minHeight: 70,
    justifyContent: 'center',
  },
  primaryButton: {
    backgroundColor: theme.colors.cardStrong,
  },
  cardButton: {
    backgroundColor: theme.colors.card,
  },
  content: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: theme.spacing.lg,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  iconWrap: {
    width: 24,
    alignItems: 'center',
  },
  label: {
    color: theme.colors.textPrimary,
    fontSize: 18,
    fontWeight: '600',
    letterSpacing: 0.2,
  },
  disabled: {
    opacity: 0.75,
  },
});
