import React from 'react';
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type ScreenHeaderProps = {
  title: string;
  onBack?: () => void;
};

export const ScreenHeader = ({ title, onBack }: ScreenHeaderProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const backControlWidth = metrics.isDesktop ? 104 : 64;

  return (
    <View style={[styles.root, { marginBottom: metrics.panelGap + 2 }]}>
      <View style={styles.topRow}>
        {onBack ? (
          <Pressable onPress={onBack} hitSlop={10} style={[styles.backButton, { minWidth: backControlWidth }]}>
            <Text style={styles.backArrow}>←</Text>
            {metrics.isDesktop ? <Text style={styles.backLabel}>Назад</Text> : null}
          </Pressable>
        ) : (
          <View style={[styles.spacer, { width: backControlWidth }]} />
        )}
        <Text style={[styles.title, { fontSize: metrics.titleFontSize }]} numberOfLines={2}>
          {title}
        </Text>
        <View style={[styles.spacer, { width: backControlWidth }]} />
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
  backButton: {
    minHeight: 38,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  backArrow: {
    color: theme.colors.textSecondary,
    fontSize: 28,
    lineHeight: 28,
    fontWeight: '500',
  },
  backLabel: {
    color: theme.colors.textSecondary,
    fontSize: 16,
    fontWeight: '500',
  },
  title: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontWeight: '600',
    textAlign: 'center',
  },
  spacer: {
    flexShrink: 0,
  },
  line: {
    height: 1,
    backgroundColor: theme.colors.border,
  },
});
