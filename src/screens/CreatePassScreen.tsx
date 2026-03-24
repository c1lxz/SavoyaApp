import React, { useMemo, useState } from 'react';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import DateTimePicker, { DateTimePickerEvent } from '@react-native-community/datetimepicker';
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
  const { createPass, createState, error } = usePassesStore();

  const [carNumber, setCarNumber] = useState('A123BC 77');
  const [plotNumber, setPlotNumber] = useState('25');
  const [isPermanent, setIsPermanent] = useState(false);
  const [expiresAt, setExpiresAt] = useState(new Date());
  const [showPicker, setShowPicker] = useState(false);

  const dateLabel = useMemo(() => formatDate(expiresAt.toISOString()), [expiresAt]);

  const onDateChange = (event: DateTimePickerEvent, selectedDate?: Date) => {
    if (Platform.OS === 'android') {
      setShowPicker(false);
    }
    if (selectedDate) {
      setExpiresAt(selectedDate);
    }
  };

  const onCreate = async () => {
    const success = await createPass({
      carNumber: carNumber.trim(),
      plotNumber: plotNumber.trim(),
      expiresAt: isPermanent ? null : toIsoDate(expiresAt),
      isPermanent,
    });

    if (success) {
      navigation.navigate('MyPasses');
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
            <Pressable style={styles.dateButton} onPress={() => setShowPicker(true)} disabled={isPermanent}>
              <Text style={styles.dateValue}>{`До ${dateLabel}`}</Text>
            </Pressable>
          </View>

          <Pressable style={styles.checkboxRow} onPress={() => setIsPermanent((prev) => !prev)}>
            <View style={[styles.checkbox, isPermanent && styles.checkboxChecked]} />
            <Text style={styles.checkboxText}>Постоянный пропуск</Text>
          </Pressable>

          {error ? <Text style={styles.error}>{error}</Text> : null}

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
    justifyContent: 'center',
    paddingHorizontal: theme.spacing.md,
  },
  dateValue: {
    color: theme.colors.textPrimary,
    fontSize: 20,
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

