import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { theme } from '@/theme';
import { PassItem } from '@/types';
import { formatDate } from '@/utils/date';
import { StatusBadge } from './StatusBadge';

type PassCardProps = {
  item: PassItem;
};

export const PassCard = ({ item }: PassCardProps) => {
  return (
    <View style={styles.card}>
      <View style={styles.row}>
        <View style={styles.content}>
          <Text style={styles.car}>{item.carNumber}</Text>
          <Text style={styles.meta}>Участок №{item.plotNumber}</Text>
          <Text style={styles.meta}>{item.isPermanent ? 'Без срока' : `До ${item.expiresAt ? formatDate(item.expiresAt) : '-'}`}</Text>
        </View>
        <View style={styles.statusWrap}>
          <Ionicons name="checkmark-circle" size={36} color={theme.colors.success} />
          <StatusBadge status={item.status} />
        </View>
      </View>
    </View>
  );
};

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
  content: {
    flex: 1,
    gap: 6,
  },
  car: {
    color: theme.colors.textPrimary,
    fontSize: 24,
    fontWeight: '700',
  },
  meta: {
    color: theme.colors.textSecondary,
    fontSize: 18,
  },
  statusWrap: {
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    minHeight: 110,
  },
});

