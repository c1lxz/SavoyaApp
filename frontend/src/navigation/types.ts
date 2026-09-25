import type { BottomTabScreenProps } from '@react-navigation/bottom-tabs';
import type { CompositeScreenProps, NavigatorScreenParams } from '@react-navigation/native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';

export type MainTabParamList = {
  OpenBarrier: undefined;
  Wickets: undefined;
  MyPasses: undefined;
  News: { postId?: number } | undefined;
};

export type RootStackParamList = {
  Auth: undefined;
  ProfileSetup: undefined;
  Admin: undefined;
  AdminMonitor: undefined;
  AdminRequests: undefined;
  AdminUsers: undefined;
  Home: NavigatorScreenParams<MainTabParamList> | undefined;
  Account: undefined;
  CreatePass: undefined;
  NewsArchive: undefined;
  NewsEditor: { postId?: number } | undefined;
};

export type MainTabScreenProps<T extends keyof MainTabParamList> = CompositeScreenProps<
  BottomTabScreenProps<MainTabParamList, T>,
  NativeStackScreenProps<RootStackParamList>
>;
