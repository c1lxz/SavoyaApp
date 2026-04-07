import AsyncStorage from '@react-native-async-storage/async-storage';

export type CreatePassDraft = {
  residentName: string;
  carNumber: string;
};

const EMPTY_DRAFT: CreatePassDraft = {
  residentName: '',
  carNumber: '',
};

const buildCreatePassDraftKey = (userId?: string | null) => `create-pass-draft:v1:${userId ?? 'anonymous'}`;

const normalizeDraft = (draft: Partial<CreatePassDraft>): CreatePassDraft => ({
  residentName: String(draft.residentName ?? '').trim(),
  carNumber: String(draft.carNumber ?? '')
    .trim()
    .toUpperCase(),
});

export const loadCreatePassDraft = async (userId?: string | null): Promise<CreatePassDraft> => {
  try {
    const raw = await AsyncStorage.getItem(buildCreatePassDraftKey(userId));
    if (!raw) {
      return EMPTY_DRAFT;
    }

    const parsed = JSON.parse(raw) as Partial<CreatePassDraft>;
    return normalizeDraft(parsed);
  } catch {
    return EMPTY_DRAFT;
  }
};

export const saveCreatePassDraft = async (
  userId: string | null | undefined,
  draft: Partial<CreatePassDraft>,
): Promise<void> => {
  try {
    await AsyncStorage.setItem(buildCreatePassDraftKey(userId), JSON.stringify(normalizeDraft(draft)));
  } catch {
    // Ignore storage errors and keep the form usable.
  }
};
