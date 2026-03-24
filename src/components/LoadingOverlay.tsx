import React from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { theme } from '@/theme';

type LoadingOverlayProps = {
  visible: boolean;
};

export const LoadingOverlay = ({ visible }: LoadingOverlayProps) => {
  if (!visible) {
    return null;
  }

  return (
    <View style={styles.overlay}>
      <ActivityIndicator size="large" color={theme.colors.textPrimary} />
    </View>
  );
};

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(4, 10, 7, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
});

