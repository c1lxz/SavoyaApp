import React, { useEffect, useState } from 'react';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import { Keyboard, Platform, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { theme } from '@/theme';

const icons: Record<string, React.ComponentProps<typeof MaterialCommunityIcons>['name']> = {
  OpenBarrier: 'boom-gate',
  Wickets: 'door',
  MyPasses: 'card-account-details-outline',
  News: 'newspaper-variant-outline',
};

/** In normal layout flow: the dock never covers a list, button or media player. */
export const BottomDock = ({ state, descriptors, navigation, insets }: BottomTabBarProps) => {
  const { width } = useWindowDimensions();
  const [keyboardVisible, setKeyboardVisible] = useState(false);

  useEffect(() => {
    const show = Keyboard.addListener(Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow', () => setKeyboardVisible(true));
    const hide = Keyboard.addListener(Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide', () => setKeyboardVisible(false));
    return () => { show.remove(); hide.remove(); };
  }, []);

  if (keyboardVisible) return null;

  return (
    <View style={[styles.shell, { paddingBottom: Math.max(insets.bottom, 10), paddingLeft: Math.max(insets.left, 8), paddingRight: Math.max(insets.right, 8) }]}>
      <View style={styles.dock} accessibilityRole="tablist">
        {state.routes.map((route, index) => {
          const selected = state.index === index;
          const { options } = descriptors[route.key];
          const label = options.title ?? route.name;
          return (
            <Pressable
              key={route.key}
              accessibilityRole="tab"
              accessibilityLabel={options.tabBarAccessibilityLabel ?? label}
              accessibilityState={{ selected }}
              onPress={() => {
                const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
                if (!selected && !event.defaultPrevented) navigation.navigate(route.name, route.params);
              }}
              onLongPress={() => navigation.emit({ type: 'tabLongPress', target: route.key })}
              style={({ pressed }) => [styles.item, selected && styles.selected, pressed && styles.pressed]}
            >
              <MaterialCommunityIcons name={icons[route.name]} size={24} color={selected ? theme.colors.textPrimary : theme.colors.textMuted} />
              <Text
                numberOfLines={1}
                maxFontSizeMultiplier={1.2}
                style={[styles.label, { fontSize: width < 360 ? 10 : width < 480 ? 11 : 13 }, selected && styles.selectedLabel]}
              >
                {label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  shell: { backgroundColor: '#0C1812', paddingTop: 8, borderTopWidth: 1, borderTopColor: 'rgba(219, 193, 134, 0.14)' },
  dock: {
    width: '100%',
    maxWidth: 660,
    alignSelf: 'center',
    flexDirection: 'row',
    padding: 4,
    gap: 3,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: '#192C21',
  },
  item: { flex: 1, minWidth: 0, minHeight: 57, alignItems: 'center', justifyContent: 'center', gap: 4, borderRadius: 19, paddingHorizontal: 2, paddingVertical: 6 },
  selected: { backgroundColor: 'rgba(219, 193, 134, 0.14)' },
  pressed: { opacity: 0.72 },
  label: { color: theme.colors.textMuted, fontWeight: '500' },
  selectedLabel: { color: theme.colors.textPrimary, fontWeight: '700' },
});
