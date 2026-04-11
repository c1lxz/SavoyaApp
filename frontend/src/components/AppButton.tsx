import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

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
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  return (
    <Pressable
      style={[
        styles.button,
        variant === 'card' ? styles.cardButton : styles.primaryButton,
        { minHeight: metrics.buttonMinHeight },
        (disabled || loading) && styles.disabled,
      ]}
      onPress={onPress}
      disabled={disabled || loading}
    >
      <View
        style={[
          styles.content,
          {
            paddingHorizontal: metrics.isHandset
              ? theme.spacing.md
              : metrics.isCompactHeight
                ? theme.spacing.md
                : theme.spacing.lg,
          },
        ]}
      >
        {loading ? (
          <ActivityIndicator color={theme.colors.textPrimary} />
        ) : (
          <View style={styles.row}>
            {leftIcon ? <View style={styles.iconWrap}>{leftIcon}</View> : null}
            <Text style={[styles.label, { fontSize: metrics.isHandset ? 16 : metrics.isCompactHeight ? 17 : 18 }]}>
              {title}
            </Text>
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
    fontWeight: '600',
    letterSpacing: 0.2,
    textAlign: 'center',
  },
  disabled: {
    opacity: 0.75,
  },
});
