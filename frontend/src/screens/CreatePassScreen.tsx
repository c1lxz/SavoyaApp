import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { DatePickerModal } from '@/components/DatePickerModal';
import { AppInput } from '@/components/AppInput';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { loadCreatePassDraft, saveCreatePassDraft } from '@/services/formMemory';
import { useAuthStore } from '@/store/authStore';
import { usePassesStore } from '@/store/passesStore';
import { theme } from '@/theme';
import { goBackOrHome } from '@/utils/backNavigation';
import { formatDate, toIsoDate } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'CreatePass'>;

const hasAtLeastTwoWords = (value: string) => value.trim().split(/\s+/).filter(Boolean).length >= 2;

const renderClearButton = (onPress: () => void) => (
  <Pressable onPress={onPress} hitSlop={12}>
    <MaterialCommunityIcons name="close-circle-outline" size={24} color={theme.colors.textSecondary} />
  </Pressable>
);

export const CreatePassScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const user = useAuthStore((state) => state.user);
  const updateProfile = useAuthStore((state) => state.updateProfile);
  const profileState = useAuthStore((state) => state.profileState);
  const createPass = usePassesStore((state) => state.createPass);
  const createState = usePassesStore((state) => state.createState);
  const createError = usePassesStore((state) => state.createError);

  const [fullName, setFullName] = useState(user?.fullName ?? '');
  const [carNumber, setCarNumber] = useState('');
  const [plotNumber, setPlotNumber] = useState(user?.plotNumber ?? '');
  const [phoneNumber, setPhoneNumber] = useState(user?.phoneNumber ?? '');
  const [isPermanent, setIsPermanent] = useState(false);
  const [isCourier, setIsCourier] = useState(false);
  const [expiresAt, setExpiresAt] = useState(new Date());
  const [showPicker, setShowPicker] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [draftLoaded, setDraftLoaded] = useState(false);

  const dateLabel = formatDate(expiresAt);

  useEffect(() => {
    let isCancelled = false;

    const restoreDraft = async () => {
      const draft = await loadCreatePassDraft(user?.id);
      if (isCancelled) {
        return;
      }

      setFullName(draft.residentName || user?.fullName || '');
      setCarNumber(draft.carNumber);
      setPhoneNumber(draft.phoneNumber || user?.phoneNumber || '');
      setIsCourier(Boolean(draft.isCourier));
      setDraftLoaded(true);
    };

    void restoreDraft();

    return () => {
      isCancelled = true;
    };
  }, [user?.fullName, user?.id, user?.phoneNumber]);

  useEffect(() => {
    if (!draftLoaded) {
      return;
    }

    void saveCreatePassDraft(user?.id, {
      residentName: fullName,
      carNumber,
      phoneNumber,
      isCourier,
    });
  }, [carNumber, draftLoaded, fullName, isCourier, phoneNumber, user?.id]);

  const onCreate = async () => {
    const normalizedFullName = fullName.trim();
    const normalizedCarNumber = carNumber.trim().toUpperCase();
    const normalizedPlotNumber = plotNumber.trim();
    const normalizedPhoneNumber = phoneNumber.replace(/\D/g, '');

    if (!normalizedFullName || !hasAtLeastTwoWords(normalizedFullName)) {
      setFormError('Введите фамилию и имя');
      return;
    }

    if (normalizedCarNumber && !/^[A-ZА-Я0-9\s-]{6,12}$/i.test(normalizedCarNumber)) {
      setFormError('Проверьте формат номера автомобиля');
      return;
    }

    if (!normalizedPlotNumber) {
      setFormError('Введите номер участка');
      return;
    }

    if (!/^\d{1,4}$/.test(normalizedPlotNumber)) {
      setFormError('Номер участка должен содержать только цифры');
      return;
    }

    if (!normalizedCarNumber && !normalizedPhoneNumber) {
      setFormError('Введите номер телефона или номер автомобиля');
      return;
    }

    if (normalizedPhoneNumber && (normalizedPhoneNumber.length < 7 || normalizedPhoneNumber.length > 15)) {
      setFormError('Проверьте номер телефона');
      return;
    }

    setFormError(null);

    if (user && (normalizedFullName !== user.fullName || normalizedPlotNumber !== user.plotNumber)) {
      const saved = await updateProfile(normalizedFullName, normalizedPlotNumber);
      if (!saved) {
        setFormError('Не удалось сохранить фамилию и имя');
        return;
      }
    }

    const success = await createPass({
      carNumber: normalizedCarNumber || undefined,
      plotNumber: normalizedPlotNumber,
      phoneNumber: normalizedPhoneNumber || undefined,
      expiresAt: isPermanent ? null : toIsoDate(expiresAt),
      isPermanent,
      isCourier,
    });

    if (success) {
      navigation.navigate('Home');
    }
  };

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          scrollEnabled={false}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          bounces={false}
          alwaysBounceVertical={false}
          overScrollMode="never"
        >
          <View style={[styles.formWrap, { maxWidth: metrics.formMaxWidth }]}>
            <ScreenHeader title="Создание пропуска" onBack={() => goBackOrHome(navigation)} />

            <View style={[styles.form, { gap: metrics.panelGap }]}>
              <AppInput
                label="Фамилия и имя"
                icon="account"
                value={fullName}
                onChangeText={setFullName}
                autoCapitalize="words"
                placeholder="Иванов Иван"
                rightSlot={fullName ? renderClearButton(() => setFullName('')) : null}
              />

              <AppInput
                label="Номер автомобиля"
                icon="car"
                value={carNumber}
                onChangeText={setCarNumber}
                autoCapitalize="characters"
                rightSlot={carNumber ? renderClearButton(() => setCarNumber('')) : null}
              />

              <AppInput
                label="Номер участка"
                icon="home"
                value={plotNumber}
                onChangeText={setPlotNumber}
                keyboardType="number-pad"
              />

              <AppInput
                label="Номер телефона без +"
                icon="phone"
                value={phoneNumber}
                onChangeText={setPhoneNumber}
                keyboardType="phone-pad"
                placeholder="79991234567"
                rightSlot={phoneNumber ? renderClearButton(() => setPhoneNumber('')) : null}
              />

              <View style={[styles.dateWrap, isPermanent && styles.dateDisabled]}>
                <Text style={[styles.dateLabel, { fontSize: metrics.bodyFontSize }]}>Дата окончания</Text>
                <Pressable
                  style={[styles.dateButton, { minHeight: metrics.isCompactHeight ? 56 : 62 }]}
                  onPress={() => setShowPicker(true)}
                  disabled={isPermanent}
                >
                  <Text style={styles.dateValue}>{dateLabel}</Text>
                  <View style={styles.dateIconWrap}>
                    <MaterialCommunityIcons
                      name="calendar-month-outline"
                      size={24}
                      color={theme.colors.textSecondary}
                    />
                  </View>
                </Pressable>
              </View>

              <Pressable
                style={styles.checkboxRow}
                onPress={() =>
                  setIsPermanent((previous) => {
                    const next = !previous;
                    if (next) {
                      setIsCourier(false);
                      setShowPicker(false);
                    }
                    return next;
                  })
                }
              >
                <View style={[styles.checkbox, isPermanent && styles.checkboxChecked]} />
                <Text style={[styles.checkboxText, { fontSize: metrics.bodyFontSize }]}>Постоянный пропуск</Text>
              </Pressable>

              <Pressable
                style={styles.checkboxRow}
                onPress={() =>
                  setIsCourier((previous) => {
                    const next = !previous;
                    if (next) {
                      setIsPermanent(false);
                    }
                    return next;
                  })
                }
              >
                <View style={[styles.checkbox, isCourier && styles.checkboxChecked]} />
                <Text style={[styles.checkboxText, { fontSize: metrics.bodyFontSize }]}>Курьер</Text>
              </Pressable>

              {formError ? <Text style={styles.error}>{formError}</Text> : null}
              {createError ? <Text style={styles.error}>{createError}</Text> : null}

              <AppButton
                title="Создать пропуск"
                onPress={onCreate}
                loading={createState === 'loading' || profileState === 'loading'}
              />
            </View>
          </View>
        </ScrollView>

        <DatePickerModal visible={showPicker} value={expiresAt} onChange={setExpiresAt} onClose={() => setShowPicker(false)} />
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
  dateWrap: {
    gap: 8,
  },
  dateDisabled: {
    opacity: 0.6,
  },
  dateLabel: {
    color: theme.colors.textSecondary,
    marginLeft: 4,
  },
  dateButton: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.inputBg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingLeft: theme.spacing.md,
    paddingRight: theme.spacing.md,
    gap: 14,
  },
  dateValue: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontSize: 19,
  },
  dateIconWrap: {
    minWidth: 34,
    alignItems: 'center',
    justifyContent: 'center',
    paddingRight: 6,
  },
  checkboxRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  checkbox: {
    width: 24,
    height: 24,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 6,
    backgroundColor: 'transparent',
  },
  checkboxChecked: {
    backgroundColor: theme.colors.success,
  },
  checkboxText: {
    color: theme.colors.textSecondary,
  },
  error: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});
