import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
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

type Props = NativeStackScreenProps<RootStackParamList, 'Auth'>;

export const AuthScreen = ({ navigation }: Props) => {
  const login = useAuthStore((state) => state.login);
  const loginState = useAuthStore((state) => state.loginState);
  const error = useAuthStore((state) => state.error);

  const [loginValue, setLoginValue] = useState('demo');
  const [password, setPassword] = useState('demo123');
  const [secure, setSecure] = useState(true);

  const onSubmit = async () => {
    const success = await login(loginValue.trim(), password);
    if (success) {
      navigation.replace('Home');
    }
  };

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScreenHeader title="Регистрация" />

        <Text style={styles.description}>Введите ваш логин и пароль, которые вы получили от администратора.</Text>

        <View style={styles.form}>
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
            rightSlot={(
              <Pressable onPress={() => setSecure((value) => !value)} hitSlop={8}>
                <MaterialCommunityIcons
                  name={secure ? 'eye-outline' : 'eye-off-outline'}
                  size={24}
                  color={theme.colors.textSecondary}
                />
              </Pressable>
            )}
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <AppButton title="Зарегистрироваться" onPress={onSubmit} loading={loginState === 'loading'} />
        </View>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    paddingTop: 8,
  },
  description: {
    color: theme.colors.textSecondary,
    textAlign: 'center',
    fontSize: 22,
    lineHeight: 30,
    marginTop: 12,
    marginBottom: 24,
  },
  form: {
    gap: theme.spacing.md,
  },
  error: {
    color: theme.colors.danger,
    fontSize: 16,
    marginTop: -4,
  },
});
