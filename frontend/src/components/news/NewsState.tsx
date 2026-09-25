import React from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { theme } from "@/theme";

export const NewsState = ({
  loading,
  title,
  description,
  onRetry,
}: {
  loading?: boolean;
  title: string;
  description?: string;
  onRetry?: () => void;
}) => (
  <View style={styles.panel} accessibilityLiveRegion="polite">
    {loading ? (
      <ActivityIndicator size="large" color={theme.colors.textPrimary} />
    ) : (
      <View style={styles.icon}>
        <MaterialCommunityIcons
          name={onRetry ? "wifi-alert" : "newspaper-variant-outline"}
          size={30}
          color={theme.colors.textPrimary}
        />
      </View>
    )}
    <Text style={styles.title}>{title}</Text>
    {description ? <Text style={styles.description}>{description}</Text> : null}
    {onRetry ? (
      <Pressable
        accessibilityRole="button"
        onPress={onRetry}
        style={styles.retry}
      >
        <MaterialCommunityIcons
          name="refresh"
          size={20}
          color={theme.colors.textPrimary}
        />
        <Text style={styles.retryText}>Попробовать ещё раз</Text>
      </Pressable>
    ) : null}
  </View>
);

export const newsStyles = StyleSheet.create({
  safe: { flex: 1 },
  page: {
    width: "100%",
    maxWidth: 760,
    alignSelf: "center",
    paddingBottom: 22,
  },
  intro: { marginBottom: 22, gap: 8 },
  eyebrow: {
    color: theme.colors.textMuted,
    fontSize: 12,
    letterSpacing: 2,
    fontWeight: "600",
  },
  heading: { color: theme.colors.textPrimary, fontSize: 32, fontWeight: "600" },
  subtitle: { color: theme.colors.textSecondary, fontSize: 15, lineHeight: 23 },
  archive: {
    minHeight: 56,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 18,
    padding: 15,
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 18,
    backgroundColor: theme.colors.card,
  },
  archiveText: {
    color: theme.colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    flexShrink: 1,
  },
  create: {
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 52,
    borderRadius: 16,
    backgroundColor: "#DCCA96",
    padding: 14,
    marginBottom: 20,
  },
  createText: { color: "#1C3026", fontSize: 16, fontWeight: "700" },
  error: {
    color: theme.colors.danger,
    fontSize: 14,
    lineHeight: 21,
    marginVertical: 12,
  },
});

const styles = StyleSheet.create({
  panel: {
    padding: 30,
    borderRadius: 22,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
    alignItems: "center",
    gap: 14,
  },
  icon: {
    width: 64,
    height: 64,
    borderRadius: 22,
    backgroundColor: theme.colors.cardStrong,
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    fontSize: 19,
    fontWeight: "600",
    color: theme.colors.textPrimary,
    textAlign: "center",
  },
  description: {
    fontSize: 15,
    lineHeight: 23,
    color: theme.colors.textMuted,
    textAlign: "center",
  },
  retry: {
    minHeight: 48,
    padding: 12,
    flexDirection: "row",
    gap: 8,
    alignItems: "center",
  },
  retryText: {
    color: theme.colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
  },
});
