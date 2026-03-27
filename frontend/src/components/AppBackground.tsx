import React, { PropsWithChildren } from 'react';
import { ImageBackground, StyleSheet, View } from 'react-native';

import { theme } from '@/theme';

const BACKGROUND_IMAGE = require('../../assets/app-background.png');

export const AppBackground = ({ children }: PropsWithChildren) => {
  return (
    <ImageBackground source={BACKGROUND_IMAGE} style={styles.background} resizeMode="cover">
      <View style={styles.overlay}>
        <View style={styles.vignette} />
        {children}
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
    paddingHorizontal: 20,
    paddingBottom: 20,
  },
  vignette: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(3, 10, 8, 0.18)',
  },
});

