import React from 'react';
import { Image, StyleSheet, View } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { RootStackParamList } from '@/navigation/types';

type Props = NativeStackScreenProps<RootStackParamList, 'Home'>;

const LOGO_IMAGE = require('../../assets/home-logo-reference.png');

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
    justifyContent: 'flex-start',
    paddingTop: 0,
    paddingBottom: 8,
  },
  logoBlock: {
    alignItems: 'center',
    marginTop: -10,
    marginBottom: 6,
    minHeight: 112,
    justifyContent: 'center',
  },
  logoImage: {
    width: '56%',
    maxWidth: 240,
    aspectRatio: 711 / 586,
  },
  actions: {
    flex: 1,
    justifyContent: 'flex-end',
    gap: 16,
    paddingHorizontal: 4,
  },
});


