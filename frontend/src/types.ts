export interface Conversation {
	id: string;
	title: string;
	created_at: string;
	updated_at: string;
	has_document: boolean;
}

export type Confidence = "grounded" | "partial" | "unsupported";

export interface Citation {
	marker: string; // e.g. "S1"
	document_id: string;
	filename: string;
	page: number;
	heading: string | null;
	snippet: string;
}

export interface Message {
	id: string;
	conversation_id: string;
	role: "user" | "assistant" | "system";
	content: string;
	sources_cited: number;
	confidence?: Confidence | null;
	citations?: Citation[] | null;
	created_at: string;
}

export interface Document {
	id: string;
	conversation_id: string;
	filename: string;
	page_count: number;
	uploaded_at: string;
}

export interface ConversationDetail extends Conversation {
	documents: Document[];
}
