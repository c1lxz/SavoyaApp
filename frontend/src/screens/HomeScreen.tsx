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

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          contentContainerStyle={[
            styles.scrollContent,
            {
              justifyContent: metrics.isShortHeight ? 'flex-start' : 'center',
              gap: metrics.panelGap,
            },
          ]}
          showsVerticalScrollIndicator={false}
        >
          <View
            style={[
              styles.logoBlock,
              {
                minHeight: metrics.isShortHeight ? 110 : 180,
                marginBottom: metrics.panelGap,
              },
            ]}
          >
            <Image
              source={LOGO_IMAGE}
              style={[
                styles.logoImage,
                {
                  width: metrics.heroLogoWidth,
                  maxWidth: metrics.heroLogoWidth,
                },
              ]}
              resizeMode="contain"
            />
          </View>

          <View style={[styles.actions, { maxWidth: metrics.formMaxWidth, gap: metrics.panelGap }]}>
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
    paddingBottom: 8,
  },
  logoBlock: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoImage: {
    aspectRatio: 711 / 586,
  },
  actions: {
    width: '100%',
    alignSelf: 'center',
  },
});
