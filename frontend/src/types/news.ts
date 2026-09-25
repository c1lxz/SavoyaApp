export type NewsMedia = {
  id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  kind: "image" | "video" | "document";
  url: string;
  thumbnail_url: string | null;
};

export type NewsPost = {
  id: number;
  text: string;
  media: NewsMedia[];
  author_name: string;
  created_at: string;
  updated_at: string;
  version: number;
};

export type NewsPage = { items: NewsPost[]; next_cursor: number | null };
export type NewsPayload = { text: string; media_ids: string[] };
export type NewsFile = {
  uri: string;
  name: string;
  mimeType: string;
  size?: number;
  file?: File;
};
