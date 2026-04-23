import React from 'react';
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';

import { theme } from '@/theme';
import { AdminRequestItem } from '@/types';
import { formatAdminRequestKey } from '@/utils/adminRequests';
import { formatDateTime } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';

type AdminRequestCardProps = {
  item: AdminRequestItem;
  onCopyRequest: (item: AdminRequestItem) => void;
  onCopyText: (value: string) => void;
  onDeleteRequest: (item: AdminRequestItem) => void;
};

const statusMeta: Record<
  AdminRequestItem['status'],
  {
    label: string;
    color: string;
  }
> = {
  active: {
    label: 'Активна',
    color: theme.colors.success,
  },
  expired: {
    label: 'Истекла',
    color: theme.colors.danger,
  },
  permanent: {
    label: 'Постоянная',
    color: theme.colors.textPrimary,
  },
  cancelled: {
    label: 'Отменена',
    color: theme.colors.textMuted,
  },
  completed: {
    label: 'Завершена',
    color: theme.colors.textMuted,
  },
};

const ActionButton = ({
  label,
  icon,
  onPress,
  danger = false,
}: {
  label: string;
  icon: string;
  onPress: () => void;
  danger?: boolean;
}) => (
  <Pressable style={[styles.actionButton, danger && styles.actionButtonDanger]} onPress={onPress}>
    <MaterialCommunityIcons
      name={icon as never}
      size={18}
      color={danger ? theme.colors.danger : theme.colors.textPrimary}
    />
    <Text style={[styles.actionLabel, danger && styles.actionLabelDanger]}>{label}</Text>
  </Pressable>
);

const MetaLine = ({ label, value }: { label: string; value: string }) => (
  <View style={styles.metaLine}>
    <Text style={styles.metaLabel}>{label}</Text>
    <Text style={styles.metaValue}>{value}</Text>
  </View>
);

const AdminRequestCardComponent = ({ item, onCopyRequest, onCopyText, onDeleteRequest }: AdminRequestCardProps) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const resolvedKey = formatAdminRequestKey(item);
  const status = statusMeta[item.status];
  const residentName = item.resident.fullName || 'Без имени';

  return (
    <View style={[styles.card, { padding: metrics.isHandset ? theme.spacing.md : theme.spacing.lg }]}>
      <View style={styles.topRow}>
        <View style={styles.titleWrap}>
          <Text style={[styles.keyValue, { fontSize: metrics.isDesktop ? 24 : 21 }]}>{resolvedKey}</Text>
          <Text style={styles.subhead}>
            {item.keyType === 'VehicleNumber' ? 'Пропуск по номеру ТС' : 'Телефонный пропуск'}
          </Text>
        </View>
        <View style={styles.statusWrap}>
          <Text style={[styles.statusText, { color: status.color }]}>{status.label}</Text>
          <Text style={styles.cardId}>#{item.id}</Text>
        </View>
      </View>

      <View style={styles.section}>
        <MetaLine label="Создана" value={formatDateTime(item.createdAt)} />
        <MetaLine label="Житель" value={residentName} />
        <MetaLine label="Логин" value={item.resident.login || 'Не задан'} />
        <MetaLine label="Телефон жителя" value={item.resident.phone || 'Не задан'} />
        <MetaLine label="Участок жителя" value={item.resident.plotNumber || 'Не задан'} />
        <MetaLine label="Участок в заявке" value={item.plotNumber || 'Не задан'} />
        {item.phoneNumber ? <MetaLine label="Контактный телефон" value={item.phoneNumber} /> : null}
        <MetaLine
          label="Срок"
          value={item.isPermanent ? 'Без срока' : item.expiresAt ? formatDateTime(item.expiresAt) : 'Не задан'}
        />
        <MetaLine
          label="Точки доступа"
          value={item.accessPointIds.length ? item.accessPointIds.join(', ') : 'Не заданы'}
        />
        {item.isCourier ? <MetaLine label="Тип" value="Курьерский пропуск" /> : null}
      </View>

      <View style={styles.actionsRow}>
        <ActionButton label="Копировать заявку" icon="content-copy" onPress={() => onCopyRequest(item)} />
        <ActionButton label="Копировать значение" icon="clipboard-text-outline" onPress={() => onCopyText(resolvedKey)} />
        {item.phoneNumber ? (
          <ActionButton label="Копировать телефон" icon="phone-outline" onPress={() => onCopyText(item.phoneNumber ?? '')} />
        ) : null}
        <ActionButton
          label="Удалить пропуск"
          icon="trash-can-outline"
          onPress={() => onDeleteRequest(item)}
          danger
        />
      </View>
    </View>
  );
};

export const AdminRequestCard = React.memo(AdminRequestCardComponent);
AdminRequestCard.displayName = 'AdminRequestCard';

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    gap: theme.spacing.md,
  },
  topRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: theme.spacing.md,
  },
  titleWrap: {
    flex: 1,
    gap: 6,
  },
  keyValue: {
    color: theme.colors.textPrimary,
    fontWeight: '700',
  },
  subhead: {
    color: theme.colors.textSecondary,
    fontSize: 15,
  },
  statusWrap: {
    alignItems: 'flex-end',
    gap: 4,
  },
  statusText: {
    fontSize: 16,
    fontWeight: '700',
  },
  cardId: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  section: {
    gap: 8,
  },
  metaLine: {
    gap: 2,
  },
  metaLabel: {
    color: theme.colors.textMuted,
    fontSize: 13,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  metaValue: {
    color: theme.colors.textPrimary,
    fontSize: 16,
  },
  actionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  actionButton: {
    minHeight: 38,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
  },
  actionButtonDanger: {
    backgroundColor: 'rgba(88, 41, 41, 0.32)',
    borderColor: 'rgba(225, 132, 132, 0.45)',
  },
  actionLabel: {
    color: theme.colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
  },
  actionLabelDanger: {
    color: theme.colors.danger,
  },
});
