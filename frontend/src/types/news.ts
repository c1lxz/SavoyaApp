export type NewsMedia = {
  id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  kind: "image" | "video" | "document";
  url: string;
  thumbnail_url: string | null;
};

export type NewsPollDefinition = { question: string; options: string[] };
export type NewsPoll = {
  id: number;
  question: string;
  options: { id: number; text: string; votes: number }[];
  total_votes: number;
  my_option_id: number | null;
  is_closed: boolean;
  closed_at: string | null;
  can_edit: boolean;
};

export type NewsPost = {
  id: number;
  text: string;
  media: NewsMedia[];
  author_name: string;
  created_at: string;
  updated_at: string;
  version: number;
  poll?: NewsPoll | null;
};

export type NewsPage = { items: NewsPost[]; next_cursor: number | null };
export type NewsPayload = {
  text: string;
  media_ids: string[];
  // Omission preserves an existing poll and every vote on text/media edits.
  poll?: NewsPollDefinition | null;
};
export type NewsFile = {
  uri: string;
  name: string;
  mimeType: string;
  size?: number;
  file?: File;
};
