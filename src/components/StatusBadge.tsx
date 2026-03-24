import React from 'react';
import { StyleSheet, Text } from 'react-native';

import { theme } from '@/theme';
import { PassStatus } from '@/types';

type StatusBadgeProps = {
  status: PassStatus;
};

const statusLabel: Record<PassStatus, string> = {
  active: 'Пропуск активен',
  expired: 'Истек',
  permanent: 'Постоянный',
};

export const StatusBadge = ({ status }: StatusBadgeProps) => {
  return <Text style={[styles.badge, status === 'expired' && styles.expired]}>{statusLabel[status]}</Text>;
};

const styles = StyleSheet.create({
  badge: {
    color: theme.colors.success,
    fontSize: 18,
    fontWeight: '500',
  },
  expired: {
    color: theme.colors.danger,
  },
});

