import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { theme } from '@/theme';

type EmptyStateProps = {
  text: string;
};

export const EmptyState = ({ text }: EmptyStateProps) => {
  return (
    <View style={styles.root}>
      <Text style={styles.text}>{text}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  root: {
    marginTop: 'auto',
    marginBottom: 32,
    alignItems: 'center',
  },
  text: {
    color: theme.colors.textMuted,
    fontSize: 18,
  },
});

