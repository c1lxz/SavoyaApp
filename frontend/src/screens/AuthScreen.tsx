import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { ScreenHeader } from '@/components/ScreenHeader';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { RootStackParamList } from '@/navigation/types';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'Auth'>;

export const AuthScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const login = useAuthStore((state) => state.login);
  const loginState = useAuthStore((state) => state.loginState);
  const error = useAuthStore((state) => state.error);

  const [loginValue, setLoginValue] = useState('');
  const [password, setPassword] = useState('');
  const [secure, setSecure] = useState(true);

  const onSubmit = async () => {
    const success = await login(loginValue.trim(), password);
    if (success) {
      const { requiresProfileCompletion: shouldCompleteProfile, user } = useAuthStore.getState();
      navigation.replace(user?.isAdmin ? 'Admin' : shouldCompleteProfile ? 'ProfileSetup' : 'Home');
    }
  };

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[styles.scrollContent, { justifyContent: metrics.isShortHeight ? 'flex-start' : 'center' }]}
          scrollEnabled={false}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          bounces={false}
          alwaysBounceVertical={false}
          overScrollMode="never"
        >
          <View style={[styles.formWrap, { maxWidth: metrics.formMaxWidth, gap: metrics.panelGap }]}>
            <ScreenHeader title="Вход" />

            <Text style={[styles.description, { fontSize: metrics.bodyFontSize + 2 }]}>
              Введите ваш логин и пароль, которые вы получили от администратора.
            </Text>

            <View style={[styles.form, { gap: metrics.panelGap }]}>
              <AppInput
                icon="account"
                placeholder="Логин"
                value={loginValue}
                onChangeText={setLoginValue}
                autoCapitalize="none"
              />
              <AppInput
                icon="lock"
                placeholder="Пароль"
                value={password}
                onChangeText={setPassword}
                secureTextEntry={secure}
                rightSlot={
                  <Pressable onPress={() => setSecure((value) => !value)} hitSlop={8}>
                    <MaterialCommunityIcons
                      name={secure ? 'eye-outline' : 'eye-off-outline'}
                      size={24}
                      color={theme.colors.textSecondary}
                    />
                  </Pressable>
                }
              />

              {error ? <Text style={styles.error}>{error}</Text> : null}

              <AppButton title="Войти" onPress={onSubmit} loading={loginState === 'loading'} />
            </View>
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
  scroll: {
    flex: 1,
    width: '100%',
  },
  scrollContent: {
    flexGrow: 1,
    width: '100%',
  },
  formWrap: {
    width: '100%',
    alignSelf: 'center',
  },
  description: {
    color: theme.colors.textSecondary,
    textAlign: 'center',
    lineHeight: 28,
    marginTop: 6,
  },
  form: {},
  error: {
    color: theme.colors.danger,
    fontSize: 16,
    marginTop: -4,
  },
});
