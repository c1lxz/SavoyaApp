import React from 'react';
import { Image, StyleSheet, View } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { RootStackParamList } from '@/navigation/types';
import { theme } from '@/theme';

type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;

const LOGO_IMAGE = require('../../assets/home-logo-fit.png');

export const HomeScreen = ({ navigation }: Props) => {
  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.logoBlock}>
          <Image source={LOGO_IMAGE} style={styles.logoImage} resizeMode="contain" />
        </View>

        <View style={styles.actions}>
          <AppButton title="Создать пропуск" onPress={() => navigation.navigate('CreatePass')} />
          <AppButton title="Открыть шлагбаум" onPress={() => navigation.navigate('OpenBarrier')} />
          <AppButton title="Калитки" onPress={() => navigation.navigate('Wickets')} />
          <AppButton title="Мои пропуски" onPress={() => navigation.navigate('MyPasses')} />
        </View>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    justifyContent: 'center',
    paddingTop: 12,
    paddingBottom: 16,
  },
  logoBlock: {
    alignItems: 'center',
    marginBottom: 30,
    minHeight: 164,
    justifyContent: 'center',
  },
  logoImage: {
    width: '86%',
    maxWidth: 350,
    aspectRatio: 1296 / 760,
  },
  actions: {
    gap: 14,
    paddingHorizontal: 2,
  },
});

