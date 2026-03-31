import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { theme } from '@/theme';

type Props = NativeStackScreenProps<RootStackParamList, 'ProfileSetup'>;

export const ProfileSetupScreen = ({ navigation }: Props) => {
  const user = useAuthStore((state) => state.user);
  const updateProfile = useAuthStore((state) => state.updateProfile);
  const profileState = useAuthStore((state) => state.profileState);
  const error = useAuthStore((state) => state.error);

  const [fullName, setFullName] = useState(user?.fullName ?? '');
  const [plotNumber, setPlotNumber] = useState(user?.plotNumber ?? '');
  const [formError, setFormError] = useState<string | null>(null);

  const onSave = async () => {
    const normalized = fullName.trim();
    if (normalized.length < 2) {
      setFormError('Введите ФИО');
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
        <ScreenHeader title="Ваш профиль" />
        <Text style={styles.description}>Заполните ФИО один раз. Дальше оно будет подставляться автоматически.</Text>

        <View style={styles.form}>
          <AppInput
            label="ФИО"
            icon="account"
            value={fullName}
            onChangeText={setFullName}
            autoCapitalize="words"
            placeholder="Иванов Иван Иванович"
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
    fontSize: 18,
    lineHeight: 24,
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
