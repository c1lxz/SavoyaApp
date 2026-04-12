import * as Clipboard from 'expo-clipboard';

export const copyToClipboard = async (value: string): Promise<void> => {
  const text = value.trim();
  if (!text) {
    return;
  }

  await Clipboard.setStringAsync(text);
};
