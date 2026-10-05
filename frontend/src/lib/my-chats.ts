/**
 * The chats this browser saved, kept in localStorage. The backend has no
 * per-user list: each chat is readable only by whoever holds its random id,
 * so the history modal shows exactly the ids stored here.
 */

export interface MyChatEntry {
  id: string;
  query: string;
  preview: string;
  timestamp: string;
}

const STORAGE_KEY = "parliamentrag-my-chats";
const MAX_ENTRIES = 50;

export function listMyChats(): MyChatEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((e): e is MyChatEntry => typeof e?.id === "string")
      : [];
  } catch {
    return [];
  }
}

function save(entries: MyChatEntry[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // Storage full or unavailable: the chat is still reachable by its link
  }
}

export function addMyChat(entry: MyChatEntry) {
  save([entry, ...listMyChats().filter((e) => e.id !== entry.id)]);
}

export function removeMyChat(id: string) {
  save(listMyChats().filter((e) => e.id !== id));
}
