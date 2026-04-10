import React, { PropsWithChildren } from 'react';
import { ImageBackground, StyleSheet, useWindowDimensions, View } from 'react-native';

import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

const BACKGROUND_IMAGE = require('../../assets/app-background.png');

export const AppBackground = ({ children }: PropsWithChildren) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  return (
    <ImageBackground source={BACKGROUND_IMAGE} style={styles.background} resizeMode="cover">
      <View
        style={[
          styles.overlay,
          {
            paddingHorizontal: metrics.horizontalPadding,
            paddingTop: metrics.isHandset ? (metrics.isCompactHeight ? 4 : 10) : metrics.isCompactHeight ? 8 : 16,
            paddingBottom: metrics.isHandset ? (metrics.isCompactHeight ? 8 : 12) : metrics.isCompactHeight ? 12 : 20,
          },
        ]}
      >
        <View style={styles.vignette} />
        <View style={[styles.content, { maxWidth: metrics.contentMaxWidth }]}>{children}</View>
      </View>
    </ImageBackground>
  );
};

const styles = StyleSheet.create({
  background: {
    flex: 1,
    width: '100%',
    backgroundColor: theme.colors.screenBackground,
  },
  overlay: {
    flex: 1,
    width: '100%',
    backgroundColor: theme.colors.overlay,
    alignItems: 'center',
    overflow: 'hidden',
  },
  content: {
    flex: 1,
    width: '100%',
    alignSelf: 'center',
  },
  vignette: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(3, 10, 8, 0.18)',
  },
});

