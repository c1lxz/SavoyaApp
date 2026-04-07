import React from 'react';
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialIcons } from '@expo/vector-icons';

import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type ScreenHeaderProps = {
  title: string;
  onBack?: () => void;
};

export const ScreenHeader = ({ title, onBack }: ScreenHeaderProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  return (
    <View style={[styles.root, { marginBottom: metrics.panelGap + 2 }]}>
      <View style={styles.topRow}>
        {onBack ? (
          <Pressable onPress={onBack} hitSlop={10}>
            <MaterialIcons name="chevron-left" size={34} color={theme.colors.textSecondary} />
          </Pressable>
        ) : (
          <View style={styles.spacer} />
        )}
        <Text style={[styles.title, { fontSize: metrics.titleFontSize }]} numberOfLines={2}>
          {title}
        </Text>
        <View style={styles.spacer} />
      </View>
      <View style={styles.line} />
    </View>
  );
};

const styles = StyleSheet.create({
  root: {
    paddingTop: theme.spacing.sm,
  },
  topRow: {
    minHeight: 46,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
    gap: 12,
  },
  title: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontWeight: '600',
    textAlign: 'center',
  },
  spacer: {
    width: 34,
  },
  line: {
    height: 1,
    backgroundColor: theme.colors.border,
  },
});
