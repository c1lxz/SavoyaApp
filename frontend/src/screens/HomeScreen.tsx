import React from 'react';
import { Image, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { RootStackParamList } from '@/navigation/types';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;

const LOGO_IMAGE = require('../../assets/home-logo-reference.png');

export const HomeScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const logoViewportHeight = metrics.isDesktop ? 170 : metrics.isTablet ? 144 : metrics.isCompactHeight ? 96 : 114;
  const logoViewportWidth = Math.min(
    metrics.formMaxWidth,
    metrics.isDesktop ? 410 : metrics.isTablet ? 350 : width - metrics.horizontalPadding * 2,
  );
  const logoScale = metrics.isDesktop ? 1.08 : metrics.isTablet ? 1.14 : metrics.isCompactHeight ? 1.28 : 1.22;
  const contentGap = metrics.isCompactHeight ? 10 : metrics.panelGap;

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          contentContainerStyle={[
            styles.scrollContent,
            {
              gap: contentGap,
              paddingTop: metrics.isCompactHeight ? 2 : 12,
              paddingBottom: metrics.isCompactHeight ? 6 : 12,
            },
          ]}
          showsVerticalScrollIndicator={false}
        >
          <View style={[styles.logoBlock, { marginBottom: metrics.isCompactHeight ? 2 : 6 }]}>
            <View style={[styles.logoViewport, { height: logoViewportHeight, maxWidth: logoViewportWidth }]}>
              <Image
                source={LOGO_IMAGE}
                style={[
                  styles.logoImage,
                  {
                    transform: [{ scale: logoScale }],
                  },
                ]}
                resizeMode="contain"
              />
            </View>
          </View>

          <View style={[styles.actions, { maxWidth: metrics.formMaxWidth, gap: contentGap }]}>
            <AppButton title="Создать пропуск" onPress={() => navigation.navigate('CreatePass')} />
            <AppButton title="Открыть шлагбаум" onPress={() => navigation.navigate('OpenBarrier')} />
            <AppButton title="Калитки" onPress={() => navigation.navigate('Wickets')} />
            <AppButton title="Мои пропуски" onPress={() => navigation.navigate('MyPasses')} />
          </View>
        </ScrollView>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  logoBlock: {
    alignItems: 'center',
  },
  logoViewport: {
    width: '100%',
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoImage: {
    width: '100%',
    height: '100%',
  },
  actions: {
    width: '100%',
    alignSelf: 'center',
  },
});
