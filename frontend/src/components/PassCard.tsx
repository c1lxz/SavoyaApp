import React from 'react';
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Ionicons, MaterialCommunityIcons } from '@expo/vector-icons';

import { theme } from '@/theme';
import { PassItem } from '@/types';
import { addDays, formatDate, formatDateTime } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';
import { formatVehicleLabel } from '@/utils/vehicleCountry';
import { StatusBadge } from './StatusBadge';

type PassCardProps = {
  item: PassItem;
  onDelete?: (item: PassItem) => void;
  deleting?: boolean;
};

const PassCardComponent = ({ item, onDelete, deleting = false }: PassCardProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const displayDate = item.expiresAt ? addDays(item.expiresAt, 1) : null;

  return (
    <View style={styles.card}>
      <View style={[styles.row, metrics.isShortHeight && styles.rowCompact]}>
        <View style={styles.content}>
          <Text style={[styles.car, { fontSize: metrics.isCompactHeight ? 22 : 24 }]}>
            {item.keyType === 'VehicleNumber' ? formatVehicleLabel(item.keyValue) : item.keyValue}
          </Text>
          <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>
            {item.keyType === 'Phone' ? 'Телефонный пропуск' : 'Пропуск по номеру ТС'}
          </Text>
          <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>{`Участок №${item.plotNumber}`}</Text>
          {item.isCourier ? (
            <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>Курьерский пропуск</Text>
          ) : null}
          {item.phoneNumber && item.keyType !== 'Phone' ? (
            <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>{`Телефон: ${item.phoneNumber}`}</Text>
          ) : null}
          <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>
            {item.isPermanent ? 'Без срока' : `По ${displayDate ? formatDate(displayDate) : '-'}`}
          </Text>
          {!item.isPermanent && item.expiresAt ? (
            <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>
              {`Фактически работает до ${formatDateTime(item.expiresAt)}`}
            </Text>
          ) : null}
          <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>{`Создан: ${formatDateTime(item.createdAt)}`}</Text>
        </View>
        <View style={[styles.statusWrap, metrics.isShortHeight && styles.statusWrapCompact]}>
          <Ionicons name="checkmark-circle" size={36} color={theme.colors.success} />
          <StatusBadge status={item.status} />
        </View>
      </View>

      {onDelete ? (
        <Pressable
          style={[styles.deleteButton, deleting && styles.deleteButtonDisabled]}
          onPress={() => onDelete(item)}
          disabled={deleting}
          accessibilityRole="button"
          accessibilityLabel="Удалить пропуск"
        >
          <MaterialCommunityIcons name="trash-can-outline" size={18} color={theme.colors.danger} />
          <Text style={styles.deleteButtonText}>{deleting ? 'Удаление…' : 'Удалить пропуск'}</Text>
        </Pressable>
      ) : null}
    </View>
  );
};

export const PassCard = React.memo(PassCardComponent);
PassCard.displayName = 'PassCard';

const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    padding: theme.spacing.md,
    marginBottom: theme.spacing.md,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: theme.spacing.md,
  },
  rowCompact: {
    flexDirection: 'column',
  },
  content: {
    flex: 1,
    gap: 6,
  },
  car: {
    color: theme.colors.textPrimary,
    fontWeight: '700',
  },
  meta: {
    color: theme.colors.textSecondary,
  },
  statusWrap: {
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    minHeight: 110,
  },
  statusWrapCompact: {
    minHeight: 0,
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: 12,
    marginTop: 12,
  },
  deleteButton: {
    marginTop: theme.spacing.md,
    minHeight: 42,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(225, 132, 132, 0.45)',
    backgroundColor: 'rgba(88, 41, 41, 0.32)',
  },
  deleteButtonDisabled: {
    opacity: 0.6,
  },
  deleteButtonText: {
    color: theme.colors.danger,
    fontSize: 15,
    fontWeight: '700',
  },
});
