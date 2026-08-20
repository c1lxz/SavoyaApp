import React, { memo, useEffect, useRef } from 'react';
import {
  ActivityIndicator,
  Animated,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { NativeStackScreenProps } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppBackground } from '@/components/AppBackground';
import { ScreenHeader } from '@/components/ScreenHeader';
import { RootStackParamList } from '@/navigation/types';
import { useAuthStore } from '@/store/authStore';
import { useGateStore } from '@/store/gateStore';
import { theme } from '@/theme';
import { goBackOrHome } from '@/utils/backNavigation';
import { getGateActionFeedback } from '@/utils/gateActionFeedback';
import { getLayoutMetrics } from '@/utils/layout';

type Props = NativeStackScreenProps<RootStackParamList, 'OpenBarrier'>;

type BarrierButtonProps = {
  title: string;
  onPress: () => void;
  disabled: boolean;
  iconSource: number;
  isLoading: boolean;
  isAnyLoading: boolean;
};

const ENTRY_ICON = require('../../assets/barrier-entry.png');
const EXIT_ICON = require('../../assets/barrier-exit.png');

const BarrierActionButton = memo(({ title, onPress, disabled, iconSource, isLoading, isAnyLoading }: BarrierButtonProps) => {
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
          styles.barrierButton,
          isLoading && styles.barrierButtonLoading,
          isAnyLoading && !isLoading && styles.barrierButtonDimmed,
        ]}
      >
        <Animated.View style={[styles.barrierRow, isLoading && { opacity: pulseOpacity }]}>
          {isLoading ? (
            <ActivityIndicator size="large" color={theme.colors.textPrimary} style={styles.barrierIcon} />
          ) : (
            <Image source={iconSource} style={styles.barrierIcon} resizeMode="contain" />
          )}
          <Text style={[styles.barrierLabel, isLoading && styles.barrierLabelLoading]}>{title}</Text>
        </Animated.View>
      </Pressable>
    </Animated.View>
  );
});
BarrierActionButton.displayName = 'BarrierActionButton';

export const OpenBarrierScreen = ({ navigation }: Props) => {
  const { width, height } = useWindowDimensions();
  const metrics = getLayoutMetrics(width, height);

  const user = useAuthStore((state) => state.user);
  const gateState = useGateStore((state) => state.gateState);
  const loadingAction = useGateStore((state) => state.loadingAction);
  const result = useGateStore((state) => state.result);
  const error = useGateStore((state) => state.error);
  const openEntry = useGateStore((state) => state.openEntry);
  const openExit = useGateStore((state) => state.openExit);
  const resetGateState = useGateStore((state) => state.resetGateState);

  useEffect(() => {
    resetGateState();
  }, [resetGateState]);

  const isAnyLoading = gateState === 'loading';
  const feedbackMessage = result ? getGateActionFeedback(result, Boolean(user?.isAdmin)) : null;

  return (
    <AppBackground>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          scrollEnabled={false}
          showsVerticalScrollIndicator={false}
          bounces={false}
          alwaysBounceVertical={false}
          overScrollMode="never"
        >
          <View style={[styles.panel, { maxWidth: metrics.formMaxWidth }]}>
            <ScreenHeader title="Открыть шлагбаум" onBack={() => goBackOrHome(navigation)} />

            <View style={[styles.actions, { gap: metrics.panelGap }]}>
              <BarrierActionButton
                title="Въезд"
                onPress={openEntry}
                disabled={isAnyLoading}
                iconSource={ENTRY_ICON}
                isLoading={loadingAction === 'entry'}
                isAnyLoading={isAnyLoading}
              />
              <BarrierActionButton
                title="Выезд"
                onPress={openExit}
                disabled={isAnyLoading}
                iconSource={EXIT_ICON}
                isLoading={loadingAction === 'exit'}
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
  },
  panel: {
    width: '100%',
    alignSelf: 'center',
  },
  actions: {
    marginTop: 8,
  },
  barrierButton: {
    minHeight: 86,
    borderRadius: theme.radius.lg,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    justifyContent: 'center',
    paddingHorizontal: 22,
  },
  barrierButtonLoading: {
    borderColor: 'rgba(219, 193, 134, 0.92)',
    backgroundColor: 'rgba(38, 62, 48, 0.9)',
  },
  barrierButtonDimmed: {
    opacity: 0.45,
  },
  barrierRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 18,
  },
  barrierIcon: {
    width: 58,
    height: 40,
  },
  barrierLabel: {
    color: theme.colors.textPrimary,
    fontSize: 19,
    fontWeight: '600',
  },
  barrierLabelLoading: {
    color: theme.colors.textSecondary,
  },
  feedback: {
    marginTop: theme.spacing.xl,
    minHeight: 80,
  },
  feedbackCard: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    padding: theme.spacing.md,
    gap: 8,
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
