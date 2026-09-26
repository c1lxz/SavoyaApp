import AsyncStorage from "@react-native-async-storage/async-storage";
import Constants from "expo-constants";
import { Platform } from "react-native";
import { getAccessToken } from "@/services/api/tokenStore";
import { newsUrl } from "@/services/newsService";

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
let activeDeviceToken: string | null = null;
let storageQueue: Promise<void> = Promise.resolve();
const NATIVE_TIMEOUT_MS = 15000;
const LOGOUT_TIMEOUT_MS = 8000;

const within = <T>(promise: Promise<T>, timeoutMs: number): Promise<T> =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("Notification operation timed out")),
      timeoutMs,
    );
    promise.then(resolve, reject).finally(() => clearTimeout(timer));
  });

// Capture this session's authorization. A late cleanup must never borrow a new
// account's token or clear that account's auth state on an old-session 401.
const deviceRequest = async (
  method: "POST" | "DELETE",
  deviceToken: string,
  accessToken: string,
  timeoutMs = NATIVE_TIMEOUT_MS,
) => {
  const controller = new AbortController();
  try {
    const response = await within(
      fetch(newsUrl("/api/news/devices"), {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ token: deviceToken, platform: "android" }),
        credentials: "omit",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal: controller.signal,
      }),
      timeoutMs,
    );
    if (!response.ok) throw new Error("Notification registration failed");
  } finally {
    controller.abort();
  }
};

export const beginNewsNotificationSession = () => {
  sessionGeneration += 1;
  suspended = false;
  // Old native promises cannot be cancelled, but cannot own the new session.
  registering = null;
};

export const registerNewsNotifications = (
  requestPermission = false,
): Promise<void> => {
  if (suspended) return Promise.resolve();
  if (registering) return registering;
  const generation = sessionGeneration;
  const sessionToken = getAccessToken();
  const isCurrent = () =>
    !suspended &&
    generation === sessionGeneration &&
    sessionToken === getAccessToken();
  const attempt = (async () => {
    if (
      Platform.OS !== "android" ||
      !Constants.expoConfig?.extra?.newsPushConfigured
    ) {
      update("unavailable");
      return;
    }
    if (!sessionToken) return;
    update("loading");
    let postedDeviceToken: string | null = null;
    try {
      const Notifications = await within(
        import("expo-notifications"),
        NATIVE_TIMEOUT_MS,
      );
      if (!isCurrent()) return;
      await within(
        Notifications.setNotificationChannelAsync("news", {
          name: "Новости посёлка",
          importance: Notifications.AndroidImportance.DEFAULT,
          vibrationPattern: [0, 200],
          lightColor: "#98D37A",
        }),
        NATIVE_TIMEOUT_MS,
      );
      if (!isCurrent()) return;
      let permission = await within(
        Notifications.getPermissionsAsync(),
        NATIVE_TIMEOUT_MS,
      );
      if (!isCurrent()) return;
      if (!permission.granted && requestPermission && permission.canAskAgain)
        permission = await within(
          Notifications.requestPermissionsAsync(),
          60000,
        );
      if (!isCurrent()) return;
      if (!permission.granted) {
        update("denied");
        return;
      }
      // Android preserves the user's channel settings. The object returned by
      // setNotificationChannelAsync describes the requested defaults, so read
      // the stored channel before claiming that news alerts are enabled.
      const channel = await within(
        Notifications.getNotificationChannelAsync("news"),
        NATIVE_TIMEOUT_MS,
      );
      if (!isCurrent()) return;
      if (channel?.importance === Notifications.AndroidImportance.NONE) {
        update("denied");
        return;
      }
      const deviceToken = (
        await within(Notifications.getDevicePushTokenAsync(), NATIVE_TIMEOUT_MS)
      ).data;
      if (typeof deviceToken !== "string")
        throw new Error("Unsupported push token");
      if (!isCurrent()) return;
      activeDeviceToken = deviceToken;
      postedDeviceToken = deviceToken;
      await deviceRequest("POST", deviceToken, sessionToken);
      if (!isCurrent()) return;
      storageQueue = storageQueue
        .catch(() => {})
        .then(async () => {
          if (isCurrent()) await AsyncStorage.setItem(TOKEN_KEY, deviceToken);
        });
      await within(storageQueue, NATIVE_TIMEOUT_MS);
      if (isCurrent()) update("enabled");
    } catch {
      if (isCurrent()) update("error");
    } finally {
      // If a POST was already in flight at logout, revoke it after its response
      // as well as during logout. This closes POST-after-DELETE ordering races.
      if (
        postedDeviceToken &&
        (suspended || sessionToken !== getAccessToken())
      ) {
        await deviceRequest(
          "DELETE",
          postedDeviceToken,
          sessionToken,
          6000,
        ).catch(() => {});
      }
    }
  })().finally(() => {
    if (registering === attempt) registering = null;
  });
  registering = attempt;
  return attempt;
};

/** Unregister while the account token is still available, before logout. */
export const unregisterNewsNotifications = async () => {
  if (Platform.OS !== "android") return;
  suspended = true;
  sessionGeneration += 1;
  registering = null;
  const accessToken = getAccessToken();
  const knownDeviceToken = activeDeviceToken;
  activeDeviceToken = null;
  update("idle");
  const revokeServer = (async () => {
    const storedToken = await within(
      AsyncStorage.getItem(TOKEN_KEY),
      1000,
    ).catch(() => null);
    const tokens = new Set(
      [knownDeviceToken, storedToken].filter(
        (token): token is string => !!token,
      ),
    );
    if (accessToken)
      await Promise.allSettled(
        [...tokens].map((token) =>
          deviceRequest("DELETE", token, accessToken, 6000),
        ),
      );
  })();
  const revokeNative = (async () => {
    if (Constants.expoConfig?.extra?.newsPushConfigured) {
      const Notifications = await import("expo-notifications");
      await Notifications.unregisterForNotificationsAsync();
    }
  })();
  storageQueue = storageQueue
    .catch(() => {})
    .then(() => AsyncStorage.removeItem(TOKEN_KEY));
  // Never wait for an in-flight FCM getToken/deleteToken task during logout.
  // Google Play Services may leave those tasks unresolved while offline.
  await within(
    Promise.allSettled([revokeServer, revokeNative, storageQueue]),
    LOGOUT_TIMEOUT_MS,
  ).catch(() => {});
};
