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

	// Upload one or more files sequentially. Sequential (not parallel) keeps the
	// server-side document-cap check race-free and surfaces the first failure
	// (e.g. hitting the limit) clearly.
	const upload = useCallback(
		async (files: File[]) => {
			if (!conversationId || files.length === 0) return 0;
			setUploading(true);
			setError(null);
			let uploaded = 0;
			try {
				for (const file of files) {
					try {
						const doc = await api.uploadDocument(conversationId, file);
						setDocuments((prev) => [...prev, doc]);
						setActiveId(doc.id); // show the most recently uploaded document
						uploaded += 1;
					} catch (err) {
						setError(
							err instanceof Error ? err.message : "Failed to upload document",
						);
						break; // stop the batch on the first error (e.g. limit reached)
					}
				}
			} finally {
				setUploading(false);
			}
			return uploaded;
		},
		[conversationId],
	);

	const removeDocument = useCallback(async (id: string) => {
		try {
			setError(null);
			await api.deleteDocument(id);
			setDocuments((prev) => prev.filter((d) => d.id !== id));
			// If we removed the active document, fall back to the first remaining
			// one (the derived activeDocument handles the empty case).
			setActiveId((prev) => (prev === id ? null : prev));
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to remove document",
			);
		}
	}, []);

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
		removeDocument,
		selectDocument,
		viewDocumentAt,
	};
}
