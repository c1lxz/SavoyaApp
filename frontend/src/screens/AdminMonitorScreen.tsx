import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
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

const eventStatusColor = (item: AdminMonitorEventItem): string => {
  if (item.status === 'success' || item.gateEventCode === 2 || item.gateEventCode === 8 || item.gateEventCode === 56) {
    return theme.colors.success;
  }
  if (item.status === 'failed' || item.message?.toLowerCase().includes('нет доступа')) {
    return theme.colors.danger;
  }
  return theme.colors.textSecondary;
};

const eventTitle = (item: AdminMonitorEventItem): string => {
  if (item.source === 'app') {
    return item.actorName || item.actorLogin || item.actorPhone || 'Пользователь приложения';
  }
  return item.gateName || item.gateUnit || 'Событие Gate';
};

const eventSubtitle = (item: AdminMonitorEventItem): string => {
  const point = item.accessPointName || (item.accessPointId ? `Точка ${item.accessPointId}` : 'Точка не указана');
  if (item.source === 'app') {
    return `${point} · заявка ${item.appRequestId ?? '-'} · Gate key ${item.gateKeyId ?? '-'}`;
  }
  return `${point} · event ${item.gateEventIndex ?? '-'} · code ${item.gateEventCode ?? '-'}`;
};

const EventCard = ({ item }: { item: AdminMonitorEventItem }) => {
  const color = eventStatusColor(item);
  const sourceLabel = item.source === 'app' ? 'Приложение' : 'Gate';

  return (
    <View style={styles.eventCard}>
      <View style={styles.eventHeader}>
        <View style={styles.eventTitleBlock}>
          <Text style={styles.eventTitle}>{eventTitle(item)}</Text>
          <Text style={styles.eventSubtitle}>{eventSubtitle(item)}</Text>
        </View>
        <View style={[styles.sourceBadge, { borderColor: color }]}>
          <Text style={[styles.sourceBadgeText, { color }]}>{sourceLabel}</Text>
        </View>
      </View>

      <Text style={styles.eventTime}>{formatDateTime(item.createdAt)}</Text>
      {item.message ? <Text style={[styles.eventMessage, { color }]}>{item.message}</Text> : null}

      <View style={styles.metaGrid}>
        {item.actorLogin ? <Text style={styles.metaText}>Логин: {item.actorLogin}</Text> : null}
        {item.actorPhone ? <Text style={styles.metaText}>Телефон: {item.actorPhone}</Text> : null}
        {item.gateUserPtr ? <Text style={styles.metaText}>UserPtr: {item.gateUserPtr}</Text> : null}
        {item.requestId ? <Text style={styles.metaText}>Audit: {item.requestId}</Text> : null}
      </View>
    </View>
  );
};

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

  const listHeader = useMemo(
    () => (
      <View style={styles.headerBlock}>
        <View style={styles.monitorSummary}>
          <View style={styles.summaryTitleRow}>
            <MaterialCommunityIcons name="monitor-eye" size={24} color={theme.colors.textPrimary} />
            <Text style={[styles.summaryTitle, { fontSize: metrics.isDesktop ? 22 : 19 }]}>Мониторинг доступа</Text>
          </View>
          <Text style={styles.summaryText}>
            Лента соединяет действия из приложения с фактическими событиями Gate. Открытие остаётся через Gate Terminal,
            а реальный инициатор фиксируется здесь.
          </Text>
          {lastUpdated ? <Text style={styles.summaryMeta}>Обновлено: {formatDateTime(lastUpdated)}</Text> : null}
          {gateError ? <Text style={styles.warningText}>Gate events: {gateError}</Text> : null}
          {error ? <Text style={styles.errorText}>{error}</Text> : null}
          <Pressable style={styles.refreshButton} onPress={() => void loadEvents(true)}>
            <Text style={styles.refreshButtonText}>Обновить</Text>
          </Pressable>
        </View>
      </View>
    ),
    [error, gateError, lastUpdated, loadEvents, metrics.isDesktop],
  );

  const renderItem = useCallback(
    ({ item }: { item: AdminMonitorEventItem }) => (
      <View style={[styles.eventWrap, metrics.isDesktop && styles.eventWrapDesktop]}>
        <EventCard item={item} />
      </View>
    ),
    [metrics.isDesktop],
  );

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View style={[styles.content, { maxWidth: metrics.isDesktop ? 1200 : metrics.contentMaxWidth }]}>
          <ScreenHeader title="Мониторинг" onBack={() => goBackOrHome(navigation, 'Admin')} />

          <FlatList
            data={events}
            key={`monitor-${metrics.isDesktop ? 'desktop' : 'mobile'}`}
            numColumns={metrics.isDesktop ? 2 : 1}
            keyExtractor={(item) => item.id}
            renderItem={renderItem}
            ListHeaderComponent={listHeader}
            ListEmptyComponent={loadState === 'loading' ? null : <EmptyState text="События не найдены" />}
            contentContainerStyle={styles.listContent}
            columnWrapperStyle={metrics.isDesktop ? styles.desktopColumns : undefined}
            showsVerticalScrollIndicator={false}
          />

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
  listContent: {
    paddingBottom: theme.spacing.xl,
    gap: theme.spacing.md,
  },
  headerBlock: {
    marginBottom: theme.spacing.lg,
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
  eventWrap: {
    width: '100%',
    marginBottom: theme.spacing.md,
  },
  eventWrapDesktop: {
    flex: 1,
  },
  desktopColumns: {
    gap: theme.spacing.md,
  },
  eventCard: {
    flex: 1,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    padding: theme.spacing.lg,
    gap: 10,
  },
  eventHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: theme.spacing.md,
  },
  eventTitleBlock: {
    flex: 1,
    gap: 4,
  },
  eventTitle: {
    color: theme.colors.textPrimary,
    fontSize: 18,
    fontWeight: '700',
  },
  eventSubtitle: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  sourceBadge: {
    minHeight: 30,
    justifyContent: 'center',
    borderRadius: 8,
    borderWidth: 1,
    paddingHorizontal: 10,
  },
  sourceBadgeText: {
    fontSize: 13,
    fontWeight: '700',
  },
  eventTime: {
    color: theme.colors.textMuted,
    fontSize: 14,
  },
  eventMessage: {
    fontSize: 16,
    fontWeight: '700',
  },
  metaGrid: {
    gap: 4,
  },
  metaText: {
    color: theme.colors.textSecondary,
    fontSize: 14,
  },
});
