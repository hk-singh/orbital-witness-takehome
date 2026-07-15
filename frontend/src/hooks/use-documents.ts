import { useCallback, useEffect, useState } from "react";
import * as api from "../lib/api";
import type { Document } from "../types";

export interface JumpTarget {
	documentId: string;
	page: number;
	nonce: number; // changes on every request so repeated jumps re-fire
}

/**
 * Manages the set of documents in a conversation, which one is shown in the
 * reader panel, and "jump to this document + page" requests coming from
 * citation clicks.
 */
export function useDocuments(conversationId: string | null) {
	const [documents, setDocuments] = useState<Document[]>([]);
	const [activeId, setActiveId] = useState<string | null>(null);
	const [jumpTarget, setJumpTarget] = useState<JumpTarget | null>(null);
	const [uploading, setUploading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const refresh = useCallback(async () => {
		if (!conversationId) {
			setDocuments([]);
			setActiveId(null);
			return;
		}
		try {
			setError(null);
			const docs = await api.fetchDocuments(conversationId);
			setDocuments(docs);
			// Keep a valid active document: preserve the current one if it still
			// exists, otherwise fall back to the first.
			setActiveId((prev) => {
				if (prev && docs.some((d) => d.id === prev)) return prev;
				return docs[0]?.id ?? null;
			});
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load documents");
		}
	}, [conversationId]);

	// Reset when switching conversations, then load that conversation's docs.
	useEffect(() => {
		setDocuments([]);
		setActiveId(null);
		setJumpTarget(null);
		refresh();
	}, [refresh]);

	const upload = useCallback(
		async (file: File) => {
			if (!conversationId) return null;
			try {
				setUploading(true);
				setError(null);
				const doc = await api.uploadDocument(conversationId, file);
				setDocuments((prev) => [...prev, doc]);
				setActiveId(doc.id); // show the freshly uploaded document
				return doc;
			} catch (err) {
				setError(
					err instanceof Error ? err.message : "Failed to upload document",
				);
				return null;
			} finally {
				setUploading(false);
			}
		},
		[conversationId],
	);

	const selectDocument = useCallback((id: string) => {
		setActiveId(id);
	}, []);

	// Called when a citation is clicked: show the cited document and scroll it
	// to the cited page.
	const viewDocumentAt = useCallback((documentId: string, page: number) => {
		setActiveId(documentId);
		setJumpTarget({ documentId, page, nonce: Date.now() });
	}, []);

	const activeDocument =
		documents.find((d) => d.id === activeId) ?? documents[0] ?? null;

	return {
		documents,
		activeDocument,
		activeId: activeDocument?.id ?? null,
		jumpTarget,
		uploading,
		error,
		refresh,
		upload,
		selectDocument,
		viewDocumentAt,
	};
}
