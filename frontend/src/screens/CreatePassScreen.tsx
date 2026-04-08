import React, { useEffect, useMemo, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View, useWindowDimensions } from 'react-native';
import DateTimePicker, { DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { loadCreatePassDraft, saveCreatePassDraft } from '@/services/formMemory';
import { useAuthStore } from '@/store/authStore';
import { usePassesStore } from '@/store/passesStore';
import { theme } from '@/theme';
import { formatDate, toIsoDate } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'CreatePass'>;

const hasAtLeastTwoWords = (value: string) => value.trim().split(/\s+/).filter(Boolean).length >= 2;

const renderClearButton = (onPress: () => void) => (
  <Pressable onPress={onPress} hitSlop={8}>
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
  const [dateInput, setDateInput] = useState(formatDate(new Date().toISOString()));
  const [showPicker, setShowPicker] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [draftLoaded, setDraftLoaded] = useState(false);

  const dateLabel = useMemo(() => formatDate(expiresAt.toISOString()), [expiresAt]);

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
  }, [user?.fullName, user?.id]);

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
  }, [carNumber, draftLoaded, fullName, isCourier, phoneNumber, user?.id, user?.phoneNumber]);

  const parseRuDate = (value: string): Date | null => {
    const match = value.trim().match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
    if (!match) {
      return null;
    }

    const day = Number(match[1]);
    const month = Number(match[2]);
    const year = Number(match[3]);
    const parsed = new Date(year, month - 1, day);

    if (
      parsed.getFullYear() !== year ||
      parsed.getMonth() !== month - 1 ||
      parsed.getDate() !== day
    ) {
      return null;
    }

    return parsed;
  };

  const onDateChange = (_event: DateTimePickerEvent, selectedDate?: Date) => {
    if (Platform.OS === 'android') {
      setShowPicker(false);
    }
    if (selectedDate) {
      setExpiresAt(selectedDate);
      setDateInput(formatDate(selectedDate.toISOString()));
    }
  };

  const onDateInputChange = (value: string) => {
    const sanitized = value.replace(/[^\d.]/g, '').slice(0, 10);
    setDateInput(sanitized);

    const parsedDate = parseRuDate(sanitized);
    if (parsedDate) {
      setExpiresAt(parsedDate);
    }
  };

  const onDateInputBlur = () => {
    const parsedDate = parseRuDate(dateInput);
    if (parsedDate) {
      setExpiresAt(parsedDate);
      setDateInput(formatDate(parsedDate.toISOString()));
      return;
    }

    setDateInput(dateLabel);
  };

  const onCreate = async () => {
    const normalizedFullName = fullName.trim();
    const normalizedCarNumber = carNumber.trim().toUpperCase();
    const normalizedPlotNumber = plotNumber.trim();
    const normalizedPhoneNumber = phoneNumber.trim();
    const parsedDate = parseRuDate(dateInput);

    if (!normalizedFullName || !hasAtLeastTwoWords(normalizedFullName)) {
      setFormError('Введите фамилию и имя');
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

    if (!normalizedPhoneNumber) {
      setFormError('Введите номер телефона');
      return;
    }

    const phoneDigits = normalizedPhoneNumber.replace(/\D/g, '');
    if (phoneDigits.length < 7 || phoneDigits.length > 15) {
      setFormError('Проверьте номер телефона');
      return;
    }

    if (!isPermanent && !parsedDate) {
      setFormError('Введите дату в формате ДД.ММ.ГГГГ');
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
      carNumber: normalizedCarNumber,
      plotNumber: normalizedPlotNumber,
      phoneNumber: normalizedPhoneNumber,
      expiresAt: isPermanent ? null : toIsoDate(parsedDate ?? expiresAt),
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
        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={[styles.formWrap, { maxWidth: metrics.formMaxWidth }]}>
            <ScreenHeader title="Создание пропуска" onBack={() => navigation.goBack()} />

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
                label="Номер телефона"
                icon="phone"
                value={phoneNumber}
                onChangeText={setPhoneNumber}
                keyboardType="phone-pad"
                placeholder="+7 999 123-45-67"
                rightSlot={phoneNumber ? renderClearButton(() => setPhoneNumber('')) : null}
              />

              <View style={[styles.dateWrap, isPermanent && styles.dateDisabled]}>
                <Text style={[styles.dateLabel, { fontSize: metrics.bodyFontSize }]}>Дата окончания</Text>
                <View style={[styles.dateButton, { minHeight: metrics.isCompactHeight ? 56 : 62 }]}>
                  <TextInput
                    value={dateInput}
                    onChangeText={onDateInputChange}
                    onBlur={onDateInputBlur}
                    editable={!isPermanent}
                    placeholder="ДД.ММ.ГГГГ"
                    placeholderTextColor={theme.colors.textMuted}
                    style={styles.dateValue}
                    keyboardType="number-pad"
                    maxLength={10}
                  />
                  <Pressable
                    onPress={() => setShowPicker(true)}
                    disabled={isPermanent}
                    hitSlop={8}
                    style={styles.calendarButton}
                  >
                    <MaterialCommunityIcons
                      name="calendar-month-outline"
                      size={24}
                      color={theme.colors.textSecondary}
                    />
                  </Pressable>
                </View>
              </View>

              <Pressable
                style={styles.checkboxRow}
                onPress={() =>
                  setIsPermanent((prev) => {
                    const next = !prev;
                    if (next) {
                      setIsCourier(false);
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
                  setIsCourier((prev) => {
                    const next = !prev;
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

        {showPicker ? (
          <DateTimePicker
            value={expiresAt}
            mode="date"
            display={Platform.OS === 'ios' ? 'spinner' : 'default'}
            onChange={onDateChange}
          />
        ) : null}
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
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
    paddingHorizontal: theme.spacing.md,
  },
  dateValue: {
    color: theme.colors.textPrimary,
    fontSize: 19,
    flex: 1,
    paddingVertical: 0,
  },
  calendarButton: {
    marginLeft: 12,
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
