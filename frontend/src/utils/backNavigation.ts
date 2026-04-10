import { RootStackParamList } from '@/navigation/types';

type BackNavigation = {
  canGoBack: () => boolean;
  goBack: () => void;
  navigate: (route: keyof RootStackParamList) => void;
};

export const goBackOrHome = (
  navigation: BackNavigation,
  fallbackRoute: keyof RootStackParamList = 'Home',
) => {
  if (navigation.canGoBack()) {
    navigation.goBack();
    return;
  }

  navigation.navigate(fallbackRoute);
};
