// Mirror of the backend's max_documents_per_conversation. The server is the
// source of truth and enforces this too; the client uses it only to guide the
// UI (disabling the upload control and explaining why) before a request fails.
export const MAX_DOCUMENTS = 10;
