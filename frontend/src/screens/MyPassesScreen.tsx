import React, { useCallback, useMemo } from 'react';
import { Alert, FlatList, Platform, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { AppButton } from '@/components/AppButton';
import { EmptyState } from '@/components/EmptyState';
import { LoadingOverlay } from '@/components/LoadingOverlay';
import { PassCard } from '@/components/PassCard';
import { ScreenHeader } from '@/components/ScreenHeader';
import { MainTabScreenProps } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { usePassesStore } from '@/store/passesStore';
import { theme } from '@/theme';
import { PassItem } from '@/types';
import { formatVehicleLabel } from '@/utils/vehicleCountry';
import { getLayoutMetrics } from '@/utils/layout';

type Props = MainTabScreenProps<'MyPasses'>;

export const MyPassesScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);
  const isAdmin = useAuthStore((state) => state.user?.isAdmin);

  const passes = usePassesStore((state) => state.passes);
  const loadMyPasses = usePassesStore((state) => state.loadMyPasses);
  const loadState = usePassesStore((state) => state.loadState);
  const loadError = usePassesStore((state) => state.loadError);
  const cancelPass = usePassesStore((state) => state.cancelPass);
  const cancelState = usePassesStore((state) => state.cancelState);
  const cancelError = usePassesStore((state) => state.cancelError);

  const onDeletePass = useCallback(
    (item: PassItem) => {
      const label =
        item.keyType === 'VehicleNumber' ? formatVehicleLabel(item.keyValue) : item.keyValue;
      if (Platform.OS === 'web' && typeof globalThis.confirm === 'function') {
        if (globalThis.confirm(`Удалить пропуск?\n${label}`)) {
          void cancelPass(item.id);
        }
        return;
      }
      Alert.alert('Удалить пропуск?', label, [
        { text: 'Отмена', style: 'cancel' },
        { text: 'Удалить', style: 'destructive', onPress: () => void cancelPass(item.id) },
      ]);
    },
    [cancelPass],
  );

  const keyExtractor = useCallback((item: PassItem) => item.id, []);
  const renderItem = useCallback(
    ({ item }: { item: PassItem }) => (
      <PassCard item={item} onDelete={onDeletePass} deleting={cancelState === 'loading'} />
    ),
    [onDeletePass, cancelState],
  );
  const emptyState = useMemo(() => <EmptyState text="Нет активных пропусков" />, []);

  useFocusEffect(
    useCallback(() => {
      if (!isAdmin) void loadMyPasses();
    }, [loadMyPasses, isAdmin]),
  );

  if (isAdmin) {
    return (
      <AppBackground>
        <SafeAreaView style={styles.safeArea} edges={['left', 'right']}>
          <View style={[styles.content, { maxWidth: metrics.formMaxWidth }]}>
            <ScreenHeader title="Пропуски" />
            <Text style={styles.description}>Заявки жителей и действующие пропуска посёлка.</Text>
            <AppButton
              title="Все пропуски"
              onPress={() => navigation.navigate('AdminRequests')}
              leftIcon={<MaterialCommunityIcons name="clipboard-text-outline" size={22} color={theme.colors.textPrimary} />}
            />
          </View>
        </SafeAreaView>
      </AppBackground>
    );
  }

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea} edges={['left', 'right']}>
        <View style={[styles.content, { maxWidth: metrics.contentMaxWidth }]}>
          <ScreenHeader title="Мои пропуски" />
          <View style={styles.createAction}>
            <AppButton
              title="Создать пропуск"
              onPress={() => navigation.navigate('CreatePass')}
              leftIcon={<MaterialCommunityIcons name="plus" size={23} color={theme.colors.textPrimary} />}
            />
          </View>

          <FlatList
            style={styles.list}
            data={passes}
            keyExtractor={keyExtractor}
            renderItem={renderItem}
            scrollEnabled={true}
            initialNumToRender={8}
            maxToRenderPerBatch={8}
            windowSize={7}
            removeClippedSubviews
            contentContainerStyle={styles.listContent}
            ListEmptyComponent={emptyState}
            refreshing={loadState === 'loading'}
            onRefresh={() => void loadMyPasses()}
            showsVerticalScrollIndicator={true}
            bounces={true}
            alwaysBounceVertical={false}
            overScrollMode="always"
          />

          <LoadingOverlay visible={loadState === 'loading' || cancelState === 'loading'} />
          {loadError ? <Text style={styles.error}>{loadError}</Text> : null}
          {cancelError ? <Text style={styles.error}>{cancelError}</Text> : null}
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
  list: {
    flex: 1,
  },
  createAction: { marginBottom: 16 },
  description: { color: theme.colors.textSecondary, fontSize: 16, lineHeight: 24, marginBottom: 20 },
  listContent: {
    flexGrow: 1,
    paddingBottom: theme.spacing.xl,
  },
  error: {
    color: theme.colors.danger,
    fontSize: 16,
    textAlign: 'center',
    marginTop: 10,
  },
});
