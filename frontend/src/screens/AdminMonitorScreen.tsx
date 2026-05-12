import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { EmptyState } from '@/components/EmptyState';
import { LoadingOverlay } from '@/components/LoadingOverlay';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { apiAdminService } from '@/services/api/apiAdminService';
import { theme } from '@/theme';
import { AdminMonitorEventItem, RequestState } from '@/types';
import { goBackOrHome } from '@/utils/backNavigation';
import { formatDateTime } from '@/utils/date';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'AdminMonitor'>;

const MONITOR_REFRESH_MS = 5000;
const MOSCOW_TIMEZONE = 'Europe/Moscow';

const COLUMNS = {
  time: 156,
  name: 210,
  point: 250,
  event: 240,
  status: 104,
} as const;

const TABLE_WIDTH = Object.values(COLUMNS).reduce((sum, width) => sum + width, 0);

const formatMonitorTime = (input: string): string =>
  new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: MOSCOW_TIMEZONE,
  }).format(new Date(input));

const eventStatusColor = (item: AdminMonitorEventItem): string => {
  if (item.status === 'success' || item.gateEventCode === 2 || item.gateEventCode === 8 || item.gateEventCode === 56) {
    return theme.colors.success;
  }
  if (item.status === 'failed' || item.message?.toLowerCase().includes('нет доступа')) {
    return theme.colors.danger;
  }
  return theme.colors.textSecondary;
};

const statusLabel = (item: AdminMonitorEventItem): string => {
  if (item.status === 'success') {
    return 'Успешно';
  }
  if (item.status === 'failed') {
    return 'Ошибка';
  }
  return 'Событие';
};

const actorName = (item: AdminMonitorEventItem): string =>
  item.actorName || item.actorLogin || item.gateName || 'Не определён';

const pointName = (item: AdminMonitorEventItem): string =>
  item.accessPointName || item.gateUnit || (item.accessPointId ? `Точка ${item.accessPointId}` : '-');

const eventLabel = (item: AdminMonitorEventItem): string => {
  if (item.message) {
    return item.message;
  }
  if (item.source === 'app') {
    return 'Команда открытия';
  }
  return 'Событие Gate';
};

const TableCell = ({
  width,
  children,
  header = false,
  color,
}: {
  width: number;
  children: React.ReactNode;
  header?: boolean;
  color?: string;
}) => (
  <View style={[styles.cell, { width }]}>
    {typeof children === 'string' ? (
      <Text
        numberOfLines={2}
        style={[header ? styles.headerCellText : styles.cellText, color ? { color } : null]}
      >
        {children}
      </Text>
    ) : (
      children
    )}
  </View>
);

const MonitorActorCell = ({ item }: { item: AdminMonitorEventItem }) => (
  <View style={styles.actorCell}>
    <Text numberOfLines={2} style={styles.actorNameText}>
      {actorName(item)}
    </Text>
  </View>
);

const MonitorTable = ({ events }: { events: AdminMonitorEventItem[] }) => (
  <ScrollView horizontal showsHorizontalScrollIndicator>
    <View style={[styles.table, { width: TABLE_WIDTH }]}>
      <View style={[styles.tableRow, styles.tableHeader]}>
        <TableCell header width={COLUMNS.time}>Время</TableCell>
        <TableCell header width={COLUMNS.name}>ФИО</TableCell>
        <TableCell header width={COLUMNS.point}>Точка доступа</TableCell>
        <TableCell header width={COLUMNS.event}>Событие</TableCell>
        <TableCell header width={COLUMNS.status}>Статус</TableCell>
      </View>

      {events.map((item, index) => {
        const color = eventStatusColor(item);
        return (
          <View key={item.id} style={[styles.tableRow, index % 2 === 1 ? styles.tableRowAlt : null]}>
            <TableCell width={COLUMNS.time}>{formatMonitorTime(item.createdAt)}</TableCell>
            <TableCell width={COLUMNS.name}>
              <MonitorActorCell item={item} />
            </TableCell>
            <TableCell width={COLUMNS.point}>{pointName(item)}</TableCell>
            <TableCell width={COLUMNS.event} color={color}>
              {eventLabel(item)}
            </TableCell>
            <TableCell width={COLUMNS.status} color={color}>
              {statusLabel(item)}
            </TableCell>
          </View>
        );
      })}
    </View>
  </ScrollView>
);

export const AdminMonitorScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const [events, setEvents] = useState<AdminMonitorEventItem[]>([]);
  const [loadState, setLoadState] = useState<RequestState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const loadEvents = useCallback(async (showLoading = false) => {
    if (showLoading) {
      setLoadState('loading');
    }
    setError(null);

    try {
      const result = await apiAdminService.getMonitor(160);
      setEvents(result.items);
      setGateError(result.gateError ?? null);
      setLastUpdated(new Date().toISOString());
      setLoadState('success');
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : 'Не удалось загрузить мониторинг';
      setError(message);
      setLoadState('error');
    }
  }, []);

  useEffect(() => {
    void loadEvents(true);
    const intervalId = setInterval(() => {
      void loadEvents(false);
    }, MONITOR_REFRESH_MS);
    const unsubscribe = navigation.addListener('focus', () => {
      void loadEvents(false);
    });

    return () => {
      clearInterval(intervalId);
      unsubscribe();
    };
  }, [loadEvents, navigation]);

  const summary = useMemo(
    () => (
      <View style={styles.monitorSummary}>
        <View style={styles.summaryTitleRow}>
          <MaterialCommunityIcons name="monitor-eye" size={24} color={theme.colors.textPrimary} />
          <Text style={[styles.summaryTitle, { fontSize: metrics.isDesktop ? 22 : 19 }]}>Мониторинг доступа</Text>
        </View>
        <Text style={styles.summaryText}>
          ФИО и номер берутся из приложения, даже когда Gate фиксирует открытие от имени администратора.
        </Text>
        <View style={styles.summaryMetaRow}>
          <Text style={styles.summaryMeta}>Строк: {events.length}</Text>
          {lastUpdated ? <Text style={styles.summaryMeta}>Обновлено: {formatDateTime(lastUpdated)}</Text> : null}
        </View>
        {gateError ? <Text style={styles.warningText}>Gate events: {gateError}</Text> : null}
        {error ? <Text style={styles.errorText}>{error}</Text> : null}
        <Pressable style={styles.refreshButton} onPress={() => void loadEvents(true)}>
          <Text style={styles.refreshButtonText}>Обновить</Text>
        </Pressable>
      </View>
    ),
    [error, events.length, gateError, lastUpdated, loadEvents, metrics.isDesktop],
  );

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View style={[styles.content, { maxWidth: metrics.isDesktop ? 1320 : metrics.contentMaxWidth }]}>
          <ScreenHeader title="Мониторинг" onBack={() => goBackOrHome(navigation, 'Admin')} />

          <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
            {summary}
            {events.length > 0 ? (
              <MonitorTable events={events} />
            ) : loadState === 'loading' ? null : (
              <EmptyState text="События не найдены" />
            )}
          </ScrollView>

          <LoadingOverlay visible={loadState === 'loading'} />
        </View>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  content: {
    flex: 1,
    width: '100%',
    alignSelf: 'center',
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: theme.spacing.xl,
    gap: theme.spacing.md,
  },
  monitorSummary: {
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.cardStrong,
    padding: theme.spacing.lg,
    gap: 10,
  },
  summaryTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  summaryTitle: {
    color: theme.colors.textPrimary,
    fontWeight: '700',
  },
  summaryText: {
    color: theme.colors.textSecondary,
    fontSize: 16,
    lineHeight: 24,
  },
  summaryMetaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: theme.spacing.md,
  },
  summaryMeta: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  warningText: {
    color: theme.colors.textSecondary,
    fontSize: 14,
  },
  errorText: {
    color: theme.colors.danger,
    fontSize: 14,
  },
  refreshButton: {
    alignSelf: 'flex-start',
    minHeight: 42,
    justifyContent: 'center',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 18,
    backgroundColor: theme.colors.card,
  },
  refreshButtonText: {
    color: theme.colors.textPrimary,
    fontSize: 15,
    fontWeight: '700',
  },
  table: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 8,
    overflow: 'hidden',
    backgroundColor: theme.colors.card,
  },
  tableRow: {
    minHeight: 48,
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(219, 193, 134, 0.22)',
  },
  tableHeader: {
    minHeight: 44,
    backgroundColor: theme.colors.cardStrong,
  },
  tableRowAlt: {
    backgroundColor: 'rgba(255, 255, 255, 0.035)',
  },
  cell: {
    justifyContent: 'center',
    borderRightWidth: 1,
    borderRightColor: 'rgba(219, 193, 134, 0.2)',
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  headerCellText: {
    color: theme.colors.textPrimary,
    fontSize: 13,
    fontWeight: '700',
  },
  cellText: {
    color: theme.colors.textSecondary,
    fontSize: 14,
    lineHeight: 18,
  },
  actorCell: {
    gap: 2,
  },
  actorNameText: {
    color: theme.colors.textSecondary,
    fontSize: 14,
    lineHeight: 18,
  },
});
