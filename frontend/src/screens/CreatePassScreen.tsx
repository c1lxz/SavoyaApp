import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { DatePickerModal } from '@/components/DatePickerModal';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { loadCreatePassDraft, saveCreatePassDraft } from '@/services/formMemory';
import { useAuthStore } from '@/store/authStore';
import { usePassesStore } from '@/store/passesStore';
import { theme } from '@/theme';
import { PassPurpose } from '@/types';
import { goBackOrHome } from '@/utils/backNavigation';
import { addDays, endOfDay, formatDate, formatDateInput, formatDateTime, parseDateInput, toIsoDate } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'CreatePass'>;

const hasAtLeastTwoWords = (value: string) => value.trim().split(/\s+/).filter(Boolean).length >= 2;

const PASS_PURPOSE_OPTIONS: { value: PassPurpose; label: string }[] = [
  { value: 'courier', label: 'Курьер' },
  { value: 'taxi', label: 'Такси' },
  { value: 'other', label: 'Другое' },
];

const renderClearButton = (onPress: () => void) => (
  <Pressable onPress={onPress} hitSlop={12}>
    <MaterialCommunityIcons name="close-circle-outline" size={24} color={theme.colors.textSecondary} />
  </Pressable>
);

export const CreatePassScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const user = useAuthStore((state) => state.user);
  const createPass = usePassesStore((state) => state.createPass);
  const createState = usePassesStore((state) => state.createState);
  const createError = usePassesStore((state) => state.createError);

  const [fullName, setFullName] = useState(user?.fullName ?? '');
  const [carNumber, setCarNumber] = useState('');
  const [plotNumber, setPlotNumber] = useState(user?.plotNumber ?? '');
  const [isPermanent, setIsPermanent] = useState(false);
  const [passPurpose, setPassPurpose] = useState<PassPurpose | null>(null);
  const [expiresAtInput, setExpiresAtInput] = useState('');
  const [showPicker, setShowPicker] = useState(false);
  const [pickerValue, setPickerValue] = useState(() => new Date());
  const [formError, setFormError] = useState<string | null>(null);
  const [draftLoaded, setDraftLoaded] = useState(false);

  const parsedExpiresAt = parseDateInput(expiresAtInput);
  const actualExpiresAtPreview = parsedExpiresAt ? endOfDay(parsedExpiresAt) : null;
  const displayedPassDatePreview = parsedExpiresAt ? addDays(parsedExpiresAt, 1) : null;

  useEffect(() => {
    let isCancelled = false;

    const restoreDraft = async () => {
      const draft = await loadCreatePassDraft(user?.id);
      if (isCancelled) {
        return;
      }

      setFullName(draft.residentName || user?.fullName || '');
      setCarNumber(draft.carNumber);
      setPassPurpose(draft.passPurpose);
      setDraftLoaded(true);
    };

    void restoreDraft();

    return () => {
      isCancelled = true;
    };
  }, [user?.fullName, user?.id]);

  useEffect(() => {
    if (!draftLoaded) {
      return;
    }

    void saveCreatePassDraft(user?.id, {
      residentName: fullName,
      carNumber,
      passPurpose,
    });
  }, [carNumber, draftLoaded, fullName, passPurpose, user?.id]);

  const onExpiresAtChange = (value: string) => {
    setExpiresAtInput(formatDateInput(value));
    if (formError) {
      setFormError(null);
    }
  };

  const onDatePicked = (value: Date) => {
    setExpiresAtInput(formatDate(value));
    setShowPicker(false);
    if (formError) {
      setFormError(null);
    }
  };

  const openDatePicker = () => {
    setPickerValue(parsedExpiresAt ?? new Date());
    setShowPicker(true);
  };

  const onCreate = async () => {
    const normalizedFullName = fullName.trim();
    const normalizedCarNumber = carNumber.trim().toUpperCase();
    const normalizedPlotNumber = plotNumber.trim();
    const normalizedExpiresAtInput = expiresAtInput.trim();
    const normalizedExpiresAt = parseDateInput(normalizedExpiresAtInput);

    if (!normalizedFullName || !hasAtLeastTwoWords(normalizedFullName)) {
      setFormError('Введите ФИО');
      return;
    }

    if (!normalizedCarNumber) {
      setFormError('Введите номер автомобиля');
      return;
    }

    if (!/^[A-ZА-Я0-9\s-]{6,12}$/i.test(normalizedCarNumber)) {
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

    if (!isPermanent && !normalizedExpiresAtInput) {
      setFormError('Введите дату окончания');
      return;
    }

    if (!isPermanent && !normalizedExpiresAt) {
      setFormError('Введите дату в формате ДД.ММ.ГГГГ');
      return;
    }

    setFormError(null);

    // ФИО на форме — это имя гостя/владельца ТС для пропуска, а не имя владельца
    // аккаунта. Раньше тут вызывался updateProfile, из-за чего создание пропуска на
    // другого человека перезаписывало профиль текущего пользователя.
    const success = await createPass({
      carNumber: normalizedCarNumber,
      residentName: normalizedFullName || undefined,
      plotNumber: normalizedPlotNumber,
      expiresAt: isPermanent ? null : toIsoDate(normalizedExpiresAt as Date),
      isPermanent,
      isCourier: passPurpose !== null,
      passPurpose,
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
                label="ФИО"
                icon="account"
                value={fullName}
                onChangeText={setFullName}
                autoCapitalize="words"
                placeholder="Иванов Иван Иванович"
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

              <View style={isPermanent && styles.dateDisabled}>
                <AppInput
                  label="По"
                  value={expiresAtInput}
                  onChangeText={onExpiresAtChange}
                  placeholder="ДД.ММ.ГГГГ"
                  keyboardType="number-pad"
                  maxLength={10}
                  editable={!isPermanent}
                  rightSlot={
                    <>
                      {expiresAtInput ? renderClearButton(() => setExpiresAtInput('')) : null}
                      <Pressable
                        onPress={openDatePicker}
                        hitSlop={12}
                        disabled={isPermanent}
                        accessibilityRole="button"
                        accessibilityLabel="Открыть календарь"
                      >
                        <MaterialCommunityIcons
                          name="calendar-month-outline"
                          size={24}
                          color={theme.colors.textSecondary}
                        />
                      </Pressable>
                    </>
                  }
                />
              </View>

              {!isPermanent && actualExpiresAtPreview ? (
                <View style={styles.datePreviewWrap}>
                  <Text style={styles.datePreviewText}>{`На экране: По ${formatDate(displayedPassDatePreview as Date)}`}</Text>
                  <Text style={styles.datePreviewText}>{`Фактически работает до ${formatDateTime(actualExpiresAtPreview)}`}</Text>
                </View>
              ) : null}

              <Pressable
                style={styles.checkboxRow}
                onPress={() =>
                  setIsPermanent((previous) => {
                    const next = !previous;
                    if (next) {
                      setPassPurpose(null);
                      setShowPicker(false);
                    }
                    return next;
                  })
                }
              >
                <View style={[styles.checkbox, isPermanent && styles.checkboxChecked]} />
                <Text style={[styles.checkboxText, { fontSize: metrics.bodyFontSize }]}>Постоянный пропуск</Text>
              </Pressable>

              <View style={styles.purposeGroup}>
                {PASS_PURPOSE_OPTIONS.map((option) => (
                  <Pressable
                    key={option.value}
                    style={styles.checkboxRow}
                    onPress={() =>
                      setPassPurpose((previous) => {
                        const next = previous === option.value ? null : option.value;
                        if (next) {
                          setIsPermanent(false);
                        }
                        return next;
                      })
                    }
                  >
                    <View style={[styles.checkbox, passPurpose === option.value && styles.checkboxChecked]} />
                    <Text style={[styles.checkboxText, { fontSize: metrics.bodyFontSize }]}>{option.label}</Text>
                  </Pressable>
                ))}
              </View>

              {formError ? <Text style={styles.error}>{formError}</Text> : null}
              {createError ? <Text style={styles.error}>{createError}</Text> : null}

              <AppButton
                title="Создать пропуск"
                loadingLabel="Создаём пропуск..."
                onPress={onCreate}
                loading={createState === 'loading'}
              />
            </View>
          </View>
        </ScrollView>

        <DatePickerModal
          visible={showPicker}
          value={pickerValue}
          onChange={onDatePicked}
          onClose={() => setShowPicker(false)}
        />
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
  dateDisabled: {
    opacity: 0.6,
  },
  datePreviewWrap: {
    gap: 4,
  },
  datePreviewText: {
    color: theme.colors.textMuted,
    fontSize: 14,
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
  purposeGroup: {
    gap: 10,
  },
  error: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});
