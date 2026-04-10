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
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'ProfileSetup'>;

const hasAtLeastTwoWords = (value: string) => value.trim().split(/\s+/).filter(Boolean).length >= 2;

export const ProfileSetupScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const user = useAuthStore((state) => state.user);
  const updateProfile = useAuthStore((state) => state.updateProfile);
  const profileState = useAuthStore((state) => state.profileState);
  const error = useAuthStore((state) => state.error);

  const [fullName, setFullName] = useState(user?.fullName ?? '');
  const [plotNumber, setPlotNumber] = useState(user?.plotNumber ?? '');
  const [formError, setFormError] = useState<string | null>(null);

  const onSave = async () => {
    const normalized = fullName.trim();
    if (!hasAtLeastTwoWords(normalized)) {
      setFormError('Введите фамилию и имя');
      return;
    }

    setFormError(null);
    const ok = await updateProfile(normalized, plotNumber.trim());
    if (ok) {
      navigation.replace('Home');
    }
  };

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          bounces={false}
          alwaysBounceVertical={false}
        >
          <View style={[styles.formWrap, { maxWidth: metrics.formMaxWidth }]}>
            <ScreenHeader title="Ваш профиль" />
            <Text style={[styles.description, { fontSize: metrics.bodyFontSize }]}>
              Укажите фамилию и имя один раз. Отчество можно не заполнять.
            </Text>

            <View style={[styles.form, { gap: metrics.panelGap }]}>
              <AppInput
                label="Фамилия и имя"
                icon="account"
                value={fullName}
                onChangeText={setFullName}
                autoCapitalize="words"
                placeholder="Иванов Иван"
              />
              <AppInput
                label="Номер участка"
                icon="home"
                value={plotNumber}
                onChangeText={setPlotNumber}
                keyboardType="number-pad"
              />
              {formError ? <Text style={styles.error}>{formError}</Text> : null}
              {error ? <Text style={styles.error}>{error}</Text> : null}
              <AppButton title="Сохранить" onPress={onSave} loading={profileState === 'loading'} />
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
    lineHeight: 24,
    marginTop: 12,
    marginBottom: 24,
  },
  form: {},
  error: {
    color: theme.colors.danger,
    fontSize: 16,
    marginTop: -4,
  },
});
