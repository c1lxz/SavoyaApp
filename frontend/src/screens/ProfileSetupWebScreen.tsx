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

const TEXT = {
  requiredName: '\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0424\u0418\u041e',
  title: '\u0412\u0430\u0448 \u043f\u0440\u043e\u0444\u0438\u043b\u044c',
  description:
    '\u0417\u0430\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u0424\u0418\u041e \u043e\u0434\u0438\u043d \u0440\u0430\u0437. \u0414\u0430\u043b\u044c\u0448\u0435 \u043e\u043d\u043e \u0431\u0443\u0434\u0435\u0442 \u043f\u043e\u0434\u0441\u0442\u0430\u0432\u043b\u044f\u0442\u044c\u0441\u044f \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438.',
  fullNameLabel: '\u0424\u0418\u041e',
  fullNamePlaceholder: '\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d \u0418\u0432\u0430\u043d\u043e\u0432\u0438\u0447',
  plotLabel: '\u041d\u043e\u043c\u0435\u0440 \u0443\u0447\u0430\u0441\u0442\u043a\u0430',
  save: '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c',
} as const;

export const ProfileSetupWebScreen = ({ navigation }: Props) => {
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
      setFormError(TEXT.requiredName);
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
        <ScreenHeader title={TEXT.title} />
        <Text style={styles.description}>{TEXT.description}</Text>

        <View style={styles.form}>
          <AppInput
            label={TEXT.fullNameLabel}
            icon="account"
            value={fullName}
            onChangeText={setFullName}
            autoCapitalize="words"
            placeholder={TEXT.fullNamePlaceholder}
          />
          <AppInput
            label={TEXT.plotLabel}
            icon="home"
            value={plotNumber}
            onChangeText={setPlotNumber}
            keyboardType="number-pad"
          />
          {formError ? <Text style={styles.error}>{formError}</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <AppButton title={TEXT.save} onPress={onSave} loading={profileState === 'loading'} />
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
