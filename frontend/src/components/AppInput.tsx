import React from 'react';
import { StyleSheet, Text, TextInput, TextInputProps, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type AppInputProps = TextInputProps & {
  label?: string;
  icon?: keyof typeof MaterialCommunityIcons.glyphMap;
  rightSlot?: React.ReactNode;
};

export const AppInput = ({ label, icon, rightSlot, style, ...props }: AppInputProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const hasRightSlot = Boolean(rightSlot);

  return (
    <View style={styles.wrapper}>
      {label ? <Text style={[styles.label, { fontSize: metrics.bodyFontSize }]}>{label}</Text> : null}
      <View style={[styles.inputRow, { minHeight: metrics.isCompactHeight ? 56 : 62 }]}>
        {icon ? <MaterialCommunityIcons name={icon} size={24} color={theme.colors.textSecondary} /> : null}
        <TextInput
          placeholderTextColor={theme.colors.textMuted}
          style={[styles.input, hasRightSlot && styles.inputWithRightSlot, style]}
          {...props}
        />
        {hasRightSlot ? <View style={styles.rightSlot}>{rightSlot}</View> : null}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    gap: 8,
  },
  label: {
    color: theme.colors.textSecondary,
    marginLeft: 4,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.inputBg,
    paddingLeft: theme.spacing.md,
    paddingRight: theme.spacing.sm,
  },
  input: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontSize: 19,
    paddingVertical: 0,
  },
  inputWithRightSlot: {
    paddingRight: theme.spacing.sm,
  },
  rightSlot: {
    minWidth: 40,
    alignItems: 'center',
    justifyContent: 'center',
    paddingLeft: 4,
    paddingRight: 8,
  },
});
