import React from 'react';
import { Image, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;

const LOGO_IMAGE = require('../../assets/home-logo-reference.png');
const LOGO_IMAGE_RATIO = 711 / 586;

export const HomeScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const logout = useAuthStore((state) => state.logout);

  const logoWidth = Math.min(metrics.heroLogoWidth, width - metrics.horizontalPadding * 2);
  const logoMaxHeight = metrics.isDesktop ? 248 : metrics.isTablet ? 220 : metrics.isCompactHeight ? 124 : 150;
  const contentGap = metrics.isHandset ? (metrics.isCompactHeight ? 8 : 12) : metrics.isDesktop ? metrics.panelGap + 2 : metrics.panelGap;
  const subtitleFontSize = metrics.isDesktop ? 22 : metrics.isTablet ? 20 : metrics.isMobile ? 16 : 18;
  const pagePaddingTop = metrics.isHandset ? (metrics.isCompactHeight ? 8 : 18) : metrics.isCompactHeight ? 2 : 12;
  const pagePaddingBottom = metrics.isHandset ? (metrics.isCompactHeight ? 10 : 14) : metrics.isCompactHeight ? 4 : 12;

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View
          style={[
            styles.page,
            {
              gap: contentGap,
              paddingTop: pagePaddingTop,
              paddingBottom: pagePaddingBottom,
              justifyContent: metrics.isHandset ? 'flex-start' : 'center',
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
            <AppButton title="Создать пропуск" onPress={() => navigation.push('CreatePass')} />
            <AppButton title="Открыть шлагбаум" onPress={() => navigation.push('OpenBarrier')} />
            <AppButton title="Калитки" onPress={() => navigation.push('Wickets')} />
            <AppButton title="Мои пропуски" onPress={() => navigation.push('MyPasses')} />
            <AppButton title="Выход" onPress={logout} />
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
    minHeight: '100%',
    alignItems: 'center',
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
