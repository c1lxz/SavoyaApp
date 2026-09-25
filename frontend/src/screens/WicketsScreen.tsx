import React, { memo, useEffect, useRef } from 'react';
import {
  ActivityIndicator,
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { ScreenHeader } from '@/components/ScreenHeader';
import { MainTabScreenProps } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { useGateStore } from '@/store/gateStore';
import { theme } from '@/theme';
import { getGateActionFeedback } from '@/utils/gateActionFeedback';
import { getLayoutMetrics } from '@/utils/layout';

type Props = MainTabScreenProps<'Wickets'>;

type WicketButtonProps = {
  title: string;
  onPress: () => void;
  disabled: boolean;
  icon: React.ReactNode;
  isLoading: boolean;
  isAnyLoading: boolean;
};

const WicketActionButton = memo(({ title, onPress, disabled, icon, isLoading, isAnyLoading }: WicketButtonProps) => {
  const pressScale = useRef(new Animated.Value(1)).current;
  const pulseOpacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (!isLoading) {
      pulseOpacity.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseOpacity, { toValue: 0.55, duration: 650, useNativeDriver: true }),
        Animated.timing(pulseOpacity, { toValue: 1, duration: 650, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => {
      loop.stop();
      pulseOpacity.setValue(1);
    };
  }, [isLoading, pulseOpacity]);

  const handlePressIn = () => {
    Animated.spring(pressScale, {
      toValue: 0.93,
      useNativeDriver: true,
      speed: 50,
      bounciness: 2,
    }).start();
  };

  const handlePressOut = () => {
    Animated.spring(pressScale, {
      toValue: 1,
      useNativeDriver: true,
      speed: 22,
      bounciness: 10,
    }).start();
  };

  return (
    <Animated.View style={{ transform: [{ scale: pressScale }] }}>
      <Pressable
        onPress={onPress}
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        disabled={disabled}
        style={[
          styles.wicketButton,
          isLoading && styles.wicketButtonLoading,
          isAnyLoading && !isLoading && styles.wicketButtonDimmed,
        ]}
      >
        <Animated.View style={[styles.wicketRow, isLoading && { opacity: pulseOpacity }]}>
          <View style={styles.wicketIconWrap}>
            {isLoading ? (
              <ActivityIndicator size="small" color={theme.colors.textPrimary} />
            ) : (
              icon
            )}
          </View>
          <Text style={[styles.wicketLabel, isLoading && styles.wicketLabelLoading]} numberOfLines={2}>
            {title}
          </Text>
        </Animated.View>
      </Pressable>
    </Animated.View>
  );
});
WicketActionButton.displayName = 'WicketActionButton';

export const WicketsScreen = (_props: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const user = useAuthStore((state) => state.user);
  const gateState = useGateStore((state) => state.gateState);
  const loadingAction = useGateStore((state) => state.loadingAction);
  const result = useGateStore((state) => state.result);
  const error = useGateStore((state) => state.error);
  const openWicketNorth = useGateStore((state) => state.openWicketNorth);
  const openWicketLake = useGateStore((state) => state.openWicketLake);
  const openWicketAdmin = useGateStore((state) => state.openWicketAdmin);
  const openWicketForest = useGateStore((state) => state.openWicketForest);
  const resetGateState = useGateStore((state) => state.resetGateState);

  useEffect(() => {
    resetGateState();
  }, [resetGateState]);

  const isAnyLoading = gateState === 'loading';
  const feedbackMessage = result ? getGateActionFeedback(result, Boolean(user?.isAdmin)) : null;

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea} edges={['left', 'right']}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          bounces={false}
          alwaysBounceVertical={false}
          overScrollMode="never"
        >
          <View style={[styles.panel, { maxWidth: metrics.formMaxWidth }]}>
            <ScreenHeader title="Калитки" />

            <View style={[styles.actions, { gap: metrics.panelGap }]}>
              <WicketActionButton
                title="Калитка Северная (СНТ Пальмира)"
                onPress={openWicketNorth}
                disabled={isAnyLoading}
                icon={<MaterialCommunityIcons name="compass-outline" size={26} color={theme.colors.textPrimary} />}
                isLoading={loadingAction === 'wicket_north'}
                isAnyLoading={isAnyLoading}
              />
              <WicketActionButton
                title="Калитка Озеро (СНТ Вартемяки)"
                onPress={openWicketLake}
                disabled={isAnyLoading}
                icon={<MaterialCommunityIcons name="waves" size={26} color={theme.colors.textPrimary} />}
                isLoading={loadingAction === 'wicket_lake'}
                isAnyLoading={isAnyLoading}
              />
              <WicketActionButton
                title="Калитка у администрации"
                onPress={openWicketAdmin}
                disabled={isAnyLoading}
                icon={<MaterialCommunityIcons name="office-building-marker-outline" size={26} color={theme.colors.textPrimary} />}
                isLoading={loadingAction === 'wicket_admin'}
                isAnyLoading={isAnyLoading}
              />
              <WicketActionButton
                title="Калитка Лес"
                onPress={openWicketForest}
                disabled={isAnyLoading}
                icon={<MaterialCommunityIcons name="tree-outline" size={26} color={theme.colors.textPrimary} />}
                isLoading={loadingAction === 'wicket_forest'}
                isAnyLoading={isAnyLoading}
              />
            </View>

            <View style={styles.feedback}>
              {result ? (
                <View style={styles.feedbackCard}>
                  <View style={styles.feedbackRow}>
                    <MaterialCommunityIcons
                      name={result.success ? 'check-circle-outline' : 'alert-circle-outline'}
                      size={22}
                      color={result.success ? theme.colors.success : theme.colors.danger}
                    />
                    <Text style={[styles.feedbackText, !result.success && styles.feedbackError]}>{feedbackMessage}</Text>
                  </View>
                </View>
              ) : null}

              {error ? <Text style={styles.feedbackError}>{error}</Text> : null}
            </View>
          </View>
        </ScrollView>
      </SafeAreaView>
    </AppBackground>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  scroll: {
    flex: 1,
    width: '100%',
  },
  scrollContent: {
    flexGrow: 1,
    width: '100%',
    paddingBottom: 16,
  },
  panel: {
    width: '100%',
    alignSelf: 'center',
  },
  actions: {
    marginTop: 8,
  },
  wicketButton: {
    minHeight: 86,
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    justifyContent: 'center',
    paddingHorizontal: 18,
    paddingVertical: 10,
  },
  wicketButtonLoading: {
    borderColor: 'rgba(219, 193, 134, 0.92)',
    backgroundColor: 'rgba(38, 62, 48, 0.9)',
  },
  wicketButtonDimmed: {
    opacity: 0.45,
  },
  wicketRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  wicketIconWrap: {
    width: 30,
    alignItems: 'center',
  },
  wicketLabel: {
    flex: 1,
    color: theme.colors.textPrimary,
    fontSize: 19,
    fontWeight: '600',
    lineHeight: 24,
  },
  wicketLabelLoading: {
    color: theme.colors.textSecondary,
  },
  feedback: {
    marginTop: 14,
    minHeight: 70,
  },
  feedbackCard: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    minHeight: 86,
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 6,
  },
  feedbackRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  feedbackText: {
    color: theme.colors.textPrimary,
    fontSize: 18,
    flex: 1,
  },
  feedbackError: {
    color: theme.colors.danger,
    fontSize: 16,
  },
});
