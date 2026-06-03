import React, { useEffect, useRef, useState } from 'react';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Modal, PanResponder, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { theme } from '@/theme';
import { getLayoutMetrics } from '@/utils/layout';

type DatePickerModalProps = {
  visible: boolean;
  value: Date;
  onChange: (value: Date) => void;
  onClose: () => void;
};

const WEEKDAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'] as const;
const MONTH_FORMATTER = new Intl.DateTimeFormat('ru-RU', {
  month: 'long',
  year: 'numeric',
});

const getMonthLabel = (value: Date) => {
  const formatted = MONTH_FORMATTER.format(value);
  return formatted.charAt(0).toUpperCase() + formatted.slice(1);
};

const getMonthStart = (value: Date) => new Date(value.getFullYear(), value.getMonth(), 1);

const moveMonth = (value: Date, delta: number) => new Date(value.getFullYear(), value.getMonth() + delta, 1);

const mergeCalendarDate = (source: Date, target: Date) => {
  const next = new Date(source);
  next.setFullYear(target.getFullYear(), target.getMonth(), target.getDate());
  return next;
};

const isSameDay = (left: Date, right: Date) =>
  left.getFullYear() === right.getFullYear() &&
  left.getMonth() === right.getMonth() &&
  left.getDate() === right.getDate();

const buildCalendarDays = (visibleMonth: Date, sourceDate: Date) => {
  const monthStart = getMonthStart(visibleMonth);
  const weekDayOffset = (monthStart.getDay() + 6) % 7;
  const gridStart = new Date(monthStart);
  gridStart.setDate(gridStart.getDate() - weekDayOffset);

  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(gridStart);
    day.setDate(gridStart.getDate() + index);
    return mergeCalendarDate(sourceDate, day);
  });
};

const DayButton = ({
  day,
  inCurrentMonth,
  isSelected,
  isToday,
  onPress,
}: {
  day: Date;
  inCurrentMonth: boolean;
  isSelected: boolean;
  isToday: boolean;
  onPress: () => void;
}) => (
  <View style={styles.dayCell}>
    <Pressable
      onPress={onPress}
      style={[styles.dayButton, isSelected && styles.dayButtonSelected, isToday && !isSelected && styles.dayButtonToday]}
    >
      <Text style={[styles.dayLabel, !inCurrentMonth && styles.dayLabelMuted, isSelected && styles.dayLabelSelected]}>
        {day.getDate()}
      </Text>
    </Pressable>
  </View>
);

export const DatePickerModal = ({ visible, value, onChange, onClose }: DatePickerModalProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const [draftDate, setDraftDate] = useState(value);
  const [visibleMonth, setVisibleMonth] = useState(getMonthStart(value));
  const draftDateRef = useRef(value);

  useEffect(() => {
    if (!visible) {
      return;
    }

    setDraftDate(value);
    draftDateRef.current = value;
    setVisibleMonth(getMonthStart(value));
  }, [value, visible]);

  const panResponder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_event, gestureState) =>
        Math.abs(gestureState.dx) > 14 && Math.abs(gestureState.dx) > Math.abs(gestureState.dy),
      onPanResponderRelease: (_event, gestureState) => {
        if (gestureState.dx >= 48) {
          setVisibleMonth((current) => moveMonth(current, -1));
        }
        if (gestureState.dx <= -48) {
          setVisibleMonth((current) => moveMonth(current, 1));
        }
      },
    }),
  ).current;

  const handleSelectDay = (selectedDay: Date) => {
    setDraftDate((current) => {
      const next = mergeCalendarDate(current, selectedDay);
      draftDateRef.current = next;
      return next;
    });
    setVisibleMonth(getMonthStart(selectedDay));
  };

  const applyDraft = () => {
    onChange(draftDateRef.current);
    onClose();
  };

  if (!visible) {
    return null;
  }

  const calendarDays = buildCalendarDays(visibleMonth, draftDate);
  const today = new Date();
  const cardMaxHeight = metrics.isHandset ? Math.min(height - 24, 640) : Math.min(height - 48, 700);

  return (
    <Modal transparent visible={visible} animationType="fade" onRequestClose={onClose}>
      <View
        style={[
          styles.modalRoot,
          {
            paddingHorizontal: metrics.horizontalPadding,
            paddingTop: metrics.isHandset ? 12 : 24,
            paddingBottom: metrics.isHandset ? 12 : 24,
            justifyContent: metrics.isHandset ? 'flex-end' : 'center',
          },
        ]}
      >
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />

        <View
          style={[
            styles.card,
            metrics.isHandset ? styles.cardMobile : styles.cardDesktop,
            { maxHeight: cardMaxHeight },
          ]}
        >
          <View style={styles.header}>
            <Text style={[styles.title, { fontSize: metrics.isHandset ? 18 : 20 }]}>Выберите дату</Text>
            <Pressable onPress={onClose} hitSlop={12} accessibilityRole="button" accessibilityLabel="Закрыть календарь">
              <MaterialCommunityIcons name="close" size={24} color={theme.colors.textSecondary} />
            </Pressable>
          </View>

          <View style={styles.monthRow}>
            <Pressable onPress={() => setVisibleMonth((current) => moveMonth(current, -1))} hitSlop={12}>
              <MaterialCommunityIcons name="chevron-left" size={28} color={theme.colors.textPrimary} />
            </Pressable>
            <Text style={styles.monthLabel}>{getMonthLabel(visibleMonth)}</Text>
            <Pressable onPress={() => setVisibleMonth((current) => moveMonth(current, 1))} hitSlop={12}>
              <MaterialCommunityIcons name="chevron-right" size={28} color={theme.colors.textPrimary} />
            </Pressable>
          </View>

          <View style={styles.weekdaysRow}>
            {WEEKDAY_LABELS.map((label) => (
              <View key={label} style={styles.dayCell}>
                <Text style={styles.weekdayLabel}>{label}</Text>
              </View>
            ))}
          </View>

          <View style={styles.daysGrid} {...panResponder.panHandlers}>
            {calendarDays.map((day) => (
              <DayButton
                key={day.toISOString()}
                day={day}
                inCurrentMonth={day.getMonth() === visibleMonth.getMonth()}
                isSelected={isSameDay(day, draftDate)}
                isToday={isSameDay(day, today)}
                onPress={() => handleSelectDay(day)}
              />
            ))}
          </View>

          <View style={styles.footer}>
            <Pressable onPress={onClose} style={[styles.footerButton, styles.footerButtonSecondary]}>
              <Text style={styles.footerButtonText}>Отмена</Text>
            </Pressable>
            <Pressable onPress={applyDraft} style={[styles.footerButton, styles.footerButtonPrimary]}>
              <Text style={styles.footerButtonText}>Готово</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  modalRoot: {
    flex: 1,
  },
  card: {
    alignSelf: 'center',
    width: '100%',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: 'rgba(11, 24, 19, 0.98)',
    padding: 18,
    gap: 16,
  },
  cardDesktop: {
    maxWidth: 440,
  },
  cardMobile: {
    maxWidth: 400,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  title: {
    color: theme.colors.textPrimary,
    fontWeight: '600',
  },
  monthRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  monthLabel: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontSize: 18,
    fontWeight: '600',
    textAlign: 'center',
  },
  weekdaysRow: {
    flexDirection: 'row',
  },
  weekdayLabel: {
    color: theme.colors.textMuted,
    fontSize: 13,
    textAlign: 'center',
  },
  daysGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginHorizontal: -2,
  },
  dayCell: {
    width: '14.2857%',
    padding: 2,
  },
  dayButton: {
    minHeight: 44,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'transparent',
  },
  dayButtonSelected: {
    backgroundColor: theme.colors.cardStrong,
    borderColor: theme.colors.border,
  },
  dayButtonToday: {
    borderColor: theme.colors.border,
  },
  dayLabel: {
    color: theme.colors.textPrimary,
    fontSize: 16,
    fontWeight: '500',
  },
  dayLabelMuted: {
    color: theme.colors.textMuted,
    opacity: 0.72,
  },
  dayLabelSelected: {
    color: theme.colors.textPrimary,
    fontWeight: '700',
  },
  footer: {
    flexDirection: 'row',
    gap: 10,
  },
  footerButton: {
    flex: 1,
    minHeight: 48,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  footerButtonPrimary: {
    backgroundColor: theme.colors.cardStrong,
  },
  footerButtonSecondary: {
    backgroundColor: theme.colors.card,
  },
  footerButtonText: {
    color: theme.colors.textPrimary,
    fontSize: 16,
    fontWeight: '600',
  },
});
