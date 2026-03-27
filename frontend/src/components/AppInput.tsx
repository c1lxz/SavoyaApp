import React from 'react';
import { StyleSheet, Text, TextInput, TextInputProps, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { theme } from '@/theme';

type AppInputProps = TextInputProps & {
  label?: string;
  icon?: keyof typeof MaterialCommunityIcons.glyphMap;
  rightSlot?: React.ReactNode;
};

export const AppInput = ({ label, icon, rightSlot, style, ...props }: AppInputProps) => {
  return (
    <View style={styles.wrapper}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <View style={styles.inputRow}>
        {icon ? <MaterialCommunityIcons name={icon} size={26} color={theme.colors.textSecondary} /> : null}
        <TextInput
          placeholderTextColor={theme.colors.textMuted}
          style={[styles.input, style]}
          {...props}
        />
        {rightSlot}
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
    fontSize: 18,
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
    paddingHorizontal: theme.spacing.md,
    minHeight: 62,
  },
  input: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontSize: 20,
    paddingVertical: 0,
  },
});

