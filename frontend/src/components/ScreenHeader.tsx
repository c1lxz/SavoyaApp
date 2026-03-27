import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MaterialIcons } from '@expo/vector-icons';

import { theme } from '@/theme';

type ScreenHeaderProps = {
  title: string;
  onBack?: () => void;
};

export const ScreenHeader = ({ title, onBack }: ScreenHeaderProps) => {
  return (
    <View style={styles.root}>
      <View style={styles.topRow}>
        {onBack ? (
          <Pressable onPress={onBack} hitSlop={10}>
            <MaterialIcons name="chevron-left" size={34} color={theme.colors.textSecondary} />
          </Pressable>
        ) : (
          <View style={styles.spacer} />
        )}
        <Text style={styles.title}>{title}</Text>
        <View style={styles.spacer} />
      </View>
      <View style={styles.line} />
    </View>
  );
};

const styles = StyleSheet.create({
  root: {
    paddingTop: theme.spacing.sm,
    marginBottom: theme.spacing.lg,
  },
  topRow: {
    minHeight: 46,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  title: {
    color: theme.colors.textPrimary,
    fontSize: 24,
    fontWeight: '600',
  },
  spacer: {
    width: 34,
  },
  line: {
    height: 1,
    backgroundColor: theme.colors.border,
  },
});

