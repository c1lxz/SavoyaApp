import React, { useCallback, useMemo } from 'react';
import { FlatList, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useFocusEffect } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { EmptyState } from '@/components/EmptyState';
import { LoadingOverlay } from '@/components/LoadingOverlay';
import { PassCard } from '@/components/PassCard';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { usePassesStore } from '@/store/passesStore';
import { theme } from '@/theme';
import { PassItem } from '@/types';
import { goBackOrHome } from '@/utils/backNavigation';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'MyPasses'>;

export const MyPassesScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const passes = usePassesStore((state) => state.passes);
  const loadMyPasses = usePassesStore((state) => state.loadMyPasses);
  const loadState = usePassesStore((state) => state.loadState);
  const loadError = usePassesStore((state) => state.loadError);

  const keyExtractor = useCallback((item: PassItem) => item.id, []);
  const renderItem = useCallback(({ item }: { item: PassItem }) => <PassCard item={item} />, []);
  const emptyState = useMemo(() => <EmptyState text="Нет активных пропусков" />, []);

  useFocusEffect(
    useCallback(() => {
      void loadMyPasses();
    }, [loadMyPasses]),
  );

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <View style={[styles.content, { maxWidth: metrics.contentMaxWidth }]}>
          <ScreenHeader title="Мои пропуски" onBack={() => goBackOrHome(navigation)} />

          <FlatList
            style={styles.list}
            data={passes}
            keyExtractor={keyExtractor}
            renderItem={renderItem}
            initialNumToRender={8}
            maxToRenderPerBatch={8}
            windowSize={7}
            removeClippedSubviews
            contentContainerStyle={styles.listContent}
            ListEmptyComponent={emptyState}
            showsVerticalScrollIndicator={false}
            bounces={false}
            alwaysBounceVertical={false}
          />

          <LoadingOverlay visible={loadState === 'loading'} />
          {loadError ? <Text style={styles.error}>{loadError}</Text> : null}
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
