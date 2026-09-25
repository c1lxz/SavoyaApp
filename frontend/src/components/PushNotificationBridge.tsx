import { useEffect } from "react";
import { AppState, Platform } from "react-native";
import { navigationRef } from "@/navigation/RootNavigator";
import {
  beginNewsNotificationSession,
  registerNewsNotifications,
} from "@/services/newsNotifications";
import { useAuthStore } from "@/store/authStore";

let handledResponse: string | null = null;
export const PushNotificationBridge = () => {
  const userId = useAuthStore((state) => state.user?.id);
  const requiresProfile = useAuthStore(
    (state) => state.requiresProfileCompletion,
  );
  // Completing a profile rebuilds navigation listeners, not the auth session.
  // Keep any in-flight permission/token request valid across that transition.
  useEffect(() => {
    if (Platform.OS === "android" && userId) beginNewsNotificationSession();
  }, [userId]);
  useEffect(() => {
    if (Platform.OS !== "android" || !userId) return;
    let cancelled = false;
    let responseSubscription: { remove(): void } | undefined;
    let tokenSubscription: { remove(): void } | undefined;
    let readyTimer: ReturnType<typeof setTimeout> | undefined;
    const setup = async () => {
      const Notifications = await import("expo-notifications");
      if (cancelled) return;
      Notifications.setNotificationHandler({
        handleNotification: async () => ({
          shouldShowAlert: true,
          shouldPlaySound: true,
          shouldSetBadge: false,
        }),
      });
      const open = (
        response: import("expo-notifications").NotificationResponse,
      ) => {
        const id = response.notification.request.identifier;
        const postId = Number(
          response.notification.request.content.data.news_id,
        );
        if (
          cancelled ||
          requiresProfile ||
          handledResponse === id ||
          !Number.isSafeInteger(postId) ||
          postId < 1
        )
          return;
        const navigateWhenReady = () => {
          if (cancelled) return;
          if (!navigationRef.isReady()) {
            readyTimer = setTimeout(navigateWhenReady, 250);
            return;
          }
          handledResponse = id;
          navigationRef.navigate("Home", {
            screen: "News",
            params: { postId },
          });
        };
        navigateWhenReady();
      };
      responseSubscription =
        Notifications.addNotificationResponseReceivedListener(open);
      tokenSubscription = Notifications.addPushTokenListener(() => {
        void registerNewsNotifications();
      });
      const lastResponse =
        await Notifications.getLastNotificationResponseAsync();
      if (lastResponse) open(lastResponse);
      if (!cancelled) void registerNewsNotifications(true);
    };
    void setup().catch(() => {
      /* Registration status and retry are available in the account screen. */
    });
    const appStateSubscription = AppState.addEventListener(
      "change",
      (state) => {
        if (state === "active") void registerNewsNotifications();
      },
    );
    return () => {
      cancelled = true;
      responseSubscription?.remove();
      tokenSubscription?.remove();
      appStateSubscription.remove();
      if (readyTimer) clearTimeout(readyTimer);
    };
  }, [userId, requiresProfile]);
  return null;
};
