import React, { useMemo, useState } from 'react';
import { Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import DateTimePicker, { DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { AppInput } from '@/components/AppInput';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { usePassesStore } from '@/store/passesStore';
import { theme } from '@/theme';
import { formatDate, toIsoDate } from '@/utils/date';

type Props = NativeStackScreenProps<RootStackParamList, 'CreatePass'>;

export const CreatePassScreen = ({ navigation }: Props) => {
  const createPass = usePassesStore((state) => state.createPass);
  const createState = usePassesStore((state) => state.createState);
  const createError = usePassesStore((state) => state.createError);

  const [carNumber, setCarNumber] = useState('');
  const [plotNumber, setPlotNumber] = useState('');
  const [isPermanent, setIsPermanent] = useState(false);
  const [expiresAt, setExpiresAt] = useState(new Date());
  const [dateInput, setDateInput] = useState(formatDate(new Date().toISOString()));
  const [showPicker, setShowPicker] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const dateLabel = useMemo(() => formatDate(expiresAt.toISOString()), [expiresAt]);

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

  const onDateChange = (event: DateTimePickerEvent, selectedDate?: Date) => {
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
    const normalizedCarNumber = carNumber.trim().toUpperCase();
    const normalizedPlotNumber = plotNumber.trim();
    const parsedDate = parseRuDate(dateInput);

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

    if (!isPermanent && !parsedDate) {
      setFormError('Введите дату в формате ДД.ММ.ГГГГ');
      return;
    }

    setFormError(null);

    const success = await createPass({
      carNumber: normalizedCarNumber,
      plotNumber: normalizedPlotNumber,
      expiresAt: isPermanent ? null : toIsoDate(parsedDate ?? expiresAt),
      isPermanent,
    });

    if (success) {
      navigation.navigate('Home');
    }
  };

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScreenHeader title="Создание пропуска" onBack={() => navigation.goBack()} />

        <View style={styles.form}>
          <AppInput
            label="Номер автомобиля"
            icon="car"
            value={carNumber}
            onChangeText={setCarNumber}
            autoCapitalize="characters"
          />

          <AppInput label="Номер участка" icon="home" value={plotNumber} onChangeText={setPlotNumber} keyboardType="number-pad" />

          <View style={[styles.dateWrap, isPermanent && styles.dateDisabled]}>
            <Text style={styles.dateLabel}>Дата окончания</Text>
            <View style={styles.dateButton}>
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
              <Pressable onPress={() => setShowPicker(true)} disabled={isPermanent} hitSlop={8} style={styles.calendarButton}>
                <MaterialCommunityIcons name="calendar-month-outline" size={24} color={theme.colors.textSecondary} />
              </Pressable>
            </View>
          </View>

          <Pressable style={styles.checkboxRow} onPress={() => setIsPermanent((prev) => !prev)}>
            <View style={[styles.checkbox, isPermanent && styles.checkboxChecked]} />
            <Text style={styles.checkboxText}>Постоянный пропуск</Text>
          </Pressable>

          {formError ? <Text style={styles.error}>{formError}</Text> : null}
          {createError ? <Text style={styles.error}>{createError}</Text> : null}

          <AppButton title="Создать пропуск" onPress={onCreate} loading={createState === 'loading'} />
        </View>

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
  form: {
    gap: theme.spacing.md,
  },
  dateWrap: {
    gap: 8,
  },
  dateDisabled: {
    opacity: 0.6,
  },
  dateLabel: {
    color: theme.colors.textSecondary,
    fontSize: 18,
    marginLeft: 4,
  },
  dateButton: {
    minHeight: 62,
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
    fontSize: 20,
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
    fontSize: 18,
  },
  error: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});
