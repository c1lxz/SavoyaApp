import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';
import { RegisterAccountResult } from '@/types';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'RegisterAccount'>;

const hasAtLeastTwoWords = (value: string) => value.trim().split(/\s+/).filter(Boolean).length >= 2;

export const RegisterAccountScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const registerAccount = useAuthStore((state) => state.registerAccount);
  const registerState = useAuthStore((state) => state.registerState);
  const error = useAuthStore((state) => state.error);

  const [fullName, setFullName] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [plotNumber, setPlotNumber] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<RegisterAccountResult | null>(null);

  const onSubmit = async () => {
    const normalizedFullName = fullName.trim();
    const normalizedPhone = phoneNumber.trim();
    const normalizedPlot = plotNumber.trim();

    if (!hasAtLeastTwoWords(normalizedFullName)) {
      setFormError('Укажите ФИО');
      return;
    }

    if (!normalizedPhone) {
      setFormError('Введите номер телефона');
      return;
    }

    if (!normalizedPlot) {
      setFormError('Введите номер участка');
      return;
    }

    setFormError(null);
    const result = await registerAccount({
      fullName: normalizedFullName,
      phoneNumber: normalizedPhone,
      plotNumber: normalizedPlot,
    });

    if (result) {
      setCredentials(result);
    }
  };

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[styles.scrollContent, { justifyContent: metrics.isShortHeight ? 'flex-start' : 'center' }]}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          bounces={false}
          alwaysBounceVertical={false}
          overScrollMode="never"
        >
          <View style={[styles.formWrap, { maxWidth: metrics.formMaxWidth, gap: metrics.panelGap }]}>
            <ScreenHeader title={credentials ? 'Аккаунт создан' : 'Создать аккаунт'} />

            {credentials ? (
              <View style={[styles.credentialsCard, { gap: metrics.panelGap }]}>
                <Text style={[styles.description, { fontSize: metrics.bodyFontSize + 1 }]}>
                  Сохраните эти данные. Они понадобятся для входа в аккаунт.
                </Text>

                <View style={styles.credentialsBlock}>
                  <Text style={styles.credentialsLabel}>Логин</Text>
                  <Text style={styles.credentialsValue}>{credentials.login}</Text>
                </View>

                <View style={styles.credentialsBlock}>
                  <Text style={styles.credentialsLabel}>Пароль</Text>
                  <Text style={styles.credentialsValue}>{credentials.password}</Text>
                </View>

                {credentials.linkedExistingPasses ? (
                  <Text style={styles.linkedNotice}>
                    Найден существующий доступ по телефону. Пропуск уже доступен в приложении.
                  </Text>
                ) : null}

                <View style={styles.actions}>
                  <AppButton title="Войти в учётную запись" onPress={() => navigation.replace('Auth')} />
                  <AppButton title="У меня уже есть логин и пароль" onPress={() => navigation.replace('Auth')} variant="card" />
                </View>
              </View>
            ) : (
              <>
                <Text style={[styles.description, { fontSize: metrics.bodyFontSize + 1 }]}>
                  Заполните данные собственника. После создания система покажет ваш логин и сгенерированный пароль.
                </Text>

                <View style={[styles.form, { gap: metrics.panelGap }]}>
                  <AppInput
                    label="ФИО"
                    icon="account"
                    value={fullName}
                    onChangeText={setFullName}
                    autoCapitalize="words"
                    placeholder="Иванов Иван Иванович"
                  />

                  <AppInput
                    label="Номер телефона"
                    icon="phone"
                    value={phoneNumber}
                    onChangeText={setPhoneNumber}
                    keyboardType="phone-pad"
                    placeholder="+79991234567"
                  />

                  <AppInput
                    label="Номер участка"
                    icon="home"
                    value={plotNumber}
                    onChangeText={setPlotNumber}
                    keyboardType="number-pad"
                    placeholder="25"
                  />

                  {formError ? <Text style={styles.error}>{formError}</Text> : null}
                  {error ? <Text style={styles.error}>{error}</Text> : null}

                  <View style={styles.actions}>
                    <AppButton title="Создать аккаунт" onPress={() => void onSubmit()} loading={registerState === 'loading'} />
                    <AppButton
                      title="У меня уже есть логин и пароль"
                      onPress={() => navigation.replace('Auth')}
                      variant="card"
                      disabled={registerState === 'loading'}
                    />
                  </View>
                </View>
              </>
            )}
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
  form: {},
  description: {
    color: theme.colors.textSecondary,
    textAlign: 'center',
    lineHeight: 26,
  },
  credentialsCard: {
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
    padding: theme.spacing.lg,
  },
  credentialsBlock: {
    gap: 6,
  },
  credentialsLabel: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  credentialsValue: {
    color: theme.colors.textPrimary,
    fontSize: 20,
    fontWeight: '700',
  },
  linkedNotice: {
    color: theme.colors.success,
    fontSize: 15,
    lineHeight: 22,
    fontWeight: '600',
  },
  actions: {
    gap: theme.spacing.sm,
  },
  error: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});
