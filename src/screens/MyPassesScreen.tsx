import React, { useCallback } from 'react';
import { FlatList, StyleSheet } from 'react-native';
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

type Props = NativeStackScreenProps<RootStackParamList, 'MyPasses'>;

export const MyPassesScreen = ({ navigation }: Props) => {
  const { passes, loadMyPasses, loadState } = usePassesStore();

  useFocusEffect(
    useCallback(() => {
      void loadMyPasses();
    }, [loadMyPasses]),
  );

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScreenHeader title="Мои пропуски" onBack={() => navigation.goBack()} />

        <FlatList
          data={passes}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => <PassCard item={item} />}
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={<EmptyState text="Нет активных пропусков" />}
        />

        <LoadingOverlay visible={loadState === 'loading'} />
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  listContent: {
    paddingBottom: theme.spacing.xl,
  },
});

