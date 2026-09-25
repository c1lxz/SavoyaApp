import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import { Platform } from "react-native";
import { apiRequest } from "@/services/api/httpClient";
import { getAccessToken } from "@/services/api/tokenStore";

const TOKEN_KEY = "savoya:news-device:v1";
export type NotificationStatus =
  | "idle"
  | "loading"
  | "enabled"
  | "denied"
  | "unavailable"
  | "error";
let status: NotificationStatus = "idle";
const listeners = new Set<() => void>();
const update = (next: NotificationStatus) => {
  status = next;
  listeners.forEach((listener) => listener());
};
export const subscribeNotifications = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
export const getNotificationStatus = () => status;
let registering: Promise<void> | null = null;
let sessionGeneration = 0;
let suspended = false;

export const beginNewsNotificationSession = () => {
  sessionGeneration += 1;
  suspended = false;
};

export const registerNewsNotifications = (
  requestPermission = false,
): Promise<void> => {
  if (suspended) return Promise.resolve();
  if (registering) return registering;
  const generation = sessionGeneration;
  registering = (async () => {
    if (
      Platform.OS !== "android" ||
      !Constants.expoConfig?.extra?.newsPushConfigured
    ) {
      update("unavailable");
      return;
    }
    const sessionToken = getAccessToken();
    if (!sessionToken) return;
    update("loading");
    try {
      const Notifications = await import("expo-notifications");
      await Notifications.setNotificationChannelAsync("news", {
        name: "Новости посёлка",
        importance: Notifications.AndroidImportance.DEFAULT,
        vibrationPattern: [0, 200],
        lightColor: "#98D37A",
      });
      let permission = await Notifications.getPermissionsAsync();
      if (!permission.granted && requestPermission && permission.canAskAgain)
        permission = await Notifications.requestPermissionsAsync();
      if (!permission.granted) {
        update("denied");
        return;
      }
      const deviceToken = (await Notifications.getDevicePushTokenAsync()).data;
      if (typeof deviceToken !== "string")
        throw new Error("Unsupported push token");
      if (sessionToken !== getAccessToken() || generation !== sessionGeneration) return;
      await apiRequest("/api/news/devices", {
        method: "POST",
        body: { token: deviceToken, platform: "android" },
        timeoutMs: 15000,
      });
      await AsyncStorage.setItem(TOKEN_KEY, deviceToken);
      if (generation === sessionGeneration) update("enabled");
    } catch {
      if (generation === sessionGeneration) update("error");
    }
  })().finally(() => {
    registering = null;
  });
  return registering;
};

/** Unregister while the account token is still available, before logout. */
export const unregisterNewsNotifications = async () => {
  if (Platform.OS !== "android") return;
  suspended = true;
  sessionGeneration += 1;
  await registering?.catch(() => {});
  const deviceToken = await AsyncStorage.getItem(TOKEN_KEY);
  try {
    if (deviceToken && getAccessToken())
      await apiRequest("/api/news/devices", {
        method: "DELETE",
        body: { token: deviceToken, platform: "android" },
        timeoutMs: 8000,
      });
  } finally {
    // Invalidate the native FCM token even when the server is unreachable at logout.
    if (Constants.expoConfig?.extra?.newsPushConfigured) {
      const Notifications = await import("expo-notifications");
      await Notifications.unregisterForNotificationsAsync();
    }
    await AsyncStorage.removeItem(TOKEN_KEY);
    update("idle");
  }
};
