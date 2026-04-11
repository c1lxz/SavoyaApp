import React from 'react';
import { StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { theme } from '@/theme';
import { PassItem } from '@/types';
import { formatDate } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';
import { StatusBadge } from './StatusBadge';

type PassCardProps = {
  item: PassItem;
};

const PassCardComponent = ({ item }: PassCardProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  return (
    <View style={styles.card}>
      <View style={[styles.row, metrics.isShortHeight && styles.rowCompact]}>
        <View style={styles.content}>
          <Text style={[styles.car, { fontSize: metrics.isCompactHeight ? 22 : 24 }]}>{item.keyValue}</Text>
          <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>
            {item.keyType === 'Phone' ? 'Телефонный пропуск' : 'Пропуск по номеру ТС'}
          </Text>
          <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>Участок №{item.plotNumber}</Text>
          {item.isCourier ? (
            <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>Курьерский пропуск</Text>
          ) : null}
          {item.phoneNumber && item.keyType !== 'Phone' ? (
            <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>Телефон: {item.phoneNumber}</Text>
          ) : null}
          <Text style={[styles.meta, { fontSize: metrics.bodyFontSize }]}>
            {item.isPermanent ? 'Без срока' : `До ${item.expiresAt ? formatDate(item.expiresAt) : '-'}`}
          </Text>
        </View>
        <View style={[styles.statusWrap, metrics.isShortHeight && styles.statusWrapCompact]}>
          <Ionicons name="checkmark-circle" size={36} color={theme.colors.success} />
          <StatusBadge status={item.status} />
        </View>
      </View>
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
});
