import React from 'react';
import { Image, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { RootStackParamList } from '@/navigation/types';
import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;

const LOGO_IMAGE = require('../../assets/home-logo-reference.png');
const LOGO_IMAGE_RATIO = 711 / 586;

export const HomeScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const logoWidth = Math.min(metrics.heroLogoWidth, width - metrics.horizontalPadding * 2);
  const logoMaxHeight = metrics.isDesktop ? 248 : metrics.isTablet ? 220 : metrics.isCompactHeight ? 132 : 164;
  const contentGap = metrics.isCompactHeight ? 10 : metrics.isDesktop ? metrics.panelGap + 2 : metrics.panelGap;
  const subtitleFontSize = metrics.isDesktop ? 22 : metrics.isTablet ? 20 : metrics.isMobile ? 16 : 18;

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View
          style={[
            styles.page,
            {
              gap: contentGap,
              paddingTop: metrics.isCompactHeight ? 2 : metrics.isHandset ? 6 : 12,
              paddingBottom: metrics.isCompactHeight ? 4 : metrics.isHandset ? 8 : 12,
            },
          ]}
        >
          <View style={styles.logoBlock}>
            <Image
              source={LOGO_IMAGE}
              style={[
                styles.logoImage,
                {
                  width: logoWidth,
                  maxHeight: logoMaxHeight,
                },
              ]}
              resizeMode="contain"
            />
            <Text style={[styles.subtitle, { fontSize: subtitleFontSize }]}>Коттеджный посёлок</Text>
          </View>

          <View style={[styles.actions, { maxWidth: metrics.formMaxWidth, gap: contentGap }]}>
            <AppButton title="Создать пропуск" onPress={() => navigation.navigate('CreatePass')} />
            <AppButton title="Открыть шлагбаум" onPress={() => navigation.navigate('OpenBarrier')} />
            <AppButton title="Калитки" onPress={() => navigation.navigate('Wickets')} />
            <AppButton title="Мои пропуски" onPress={() => navigation.navigate('MyPasses')} />
          </View>
        </View>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  page: {
    flex: 1,
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoBlock: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  logoImage: {
    alignSelf: 'center',
    aspectRatio: LOGO_IMAGE_RATIO,
  },
  subtitle: {
    color: theme.colors.textSecondary,
    fontWeight: '600',
    letterSpacing: 0.3,
    textAlign: 'center',
  },
  actions: {
    width: '100%',
    alignSelf: 'center',
  },
});
