import React, { PropsWithChildren } from 'react';
import { ImageBackground, StyleSheet, useWindowDimensions, View } from 'react-native';

import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

const BACKGROUND_IMAGE = require('../../assets/app-background.png');

export const AppBackground = ({ children }: PropsWithChildren) => {
  const { width } = useWindowDimensions();
  const metrics = getLayoutMetrics(width);

  return (
    <ImageBackground source={BACKGROUND_IMAGE} style={styles.background} resizeMode="cover">
      <View style={[styles.overlay, { paddingHorizontal: metrics.horizontalPadding }]}>
        <View style={styles.vignette} />
        <View style={[styles.content, { maxWidth: metrics.contentMaxWidth }]}>{children}</View>
      </View>
    </ImageBackground>
  );
};

const styles = StyleSheet.create({
  background: {
    flex: 1,
    backgroundColor: theme.colors.screenBackground,
  },
  overlay: {
    flex: 1,
    backgroundColor: theme.colors.overlay,
    paddingBottom: 20,
    alignItems: 'center',
  },
  content: {
    flex: 1,
    width: '100%',
  },
  vignette: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(3, 10, 8, 0.18)',
  },
});

