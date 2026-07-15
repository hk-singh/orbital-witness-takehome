import { FileText, Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { MAX_DOCUMENTS } from "../lib/constants";
import type { Document, Message } from "../types";
import { ChatInput } from "./ChatInput";
import { EmptyState } from "./EmptyState";
import { MessageBubble, StreamingBubble } from "./MessageBubble";

interface ChatWindowProps {
	messages: Message[];
	loading: boolean;
	error: string | null;
	streaming: boolean;
	streamingContent: string;
	documents: Document[];
	uploading: boolean;
	conversationId: string | null;
	onSend: (content: string) => void;
	onUpload: (file: File) => void;
	onCitationClick: (documentId: string, page: number) => void;
}

/** Compact strip of the documents loaded into the current conversation. */
function DocumentBar({
	documents,
	onOpen,
}: {
	documents: Document[];
	onOpen: (documentId: string) => void;
}) {
	return (
		<div className="flex flex-wrap items-center gap-1.5 border-b border-neutral-100 bg-neutral-50/60 px-4 py-2">
			<span className="text-xs font-medium text-neutral-400">
				{documents.length} document{documents.length !== 1 ? "s" : ""}:
			</span>
			{documents.map((doc) => (
				<button
					key={doc.id}
					type="button"
					onClick={() => onOpen(doc.id)}
					title={`Open ${doc.filename}`}
					className="flex max-w-[200px] items-center gap-1 rounded-full border border-neutral-200 bg-white px-2.5 py-1 text-xs text-neutral-600 transition-colors hover:border-neutral-300 hover:bg-neutral-100"
				>
					<FileText className="h-3 w-3 flex-shrink-0 text-neutral-400" />
					<span className="truncate">{doc.filename}</span>
				</button>
			))}
		</div>
	);
}

export function ChatWindow({
	messages,
	loading,
	error,
	streaming,
	streamingContent,
	documents,
	uploading,
	conversationId,
	onSend,
	onUpload,
	onCitationClick,
}: ChatWindowProps) {
	const scrollRef = useRef<HTMLDivElement>(null);

	// Auto-scroll to bottom when new messages arrive or during streaming
	const messagesLength = messages.length;
	// biome-ignore lint/correctness/useExhaustiveDependencies: messages and streamingContent are intentional triggers for auto-scroll
	useEffect(() => {
		if (scrollRef.current) {
			scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
		}
	}, [messagesLength, streamingContent]);

	const hasDocuments = documents.length > 0;
	const atLimit = documents.length >= MAX_DOCUMENTS;

	// No conversation selected
	if (!conversationId) {
		return (
			<div className="flex flex-1 items-center justify-center bg-neutral-50">
				<div className="text-center">
					<p className="text-sm text-neutral-400">
						Select a conversation or create a new one
					</p>
				</div>
			</div>
		);
	}

	// Loading messages
	if (loading) {
		return (
			<div className="flex flex-1 items-center justify-center bg-white">
				<Loader2 className="h-6 w-6 animate-spin text-neutral-400" />
			</div>
		);
	}

	// Empty conversation - show upload prompt or a ready-to-ask hint
	if (messages.length === 0 && !streaming) {
		return (
			<div className="flex flex-1 flex-col bg-white">
				{hasDocuments && (
					<DocumentBar
						documents={documents}
						onOpen={(id) => onCitationClick(id, 1)}
					/>
				)}
				<div className="flex flex-1 items-center justify-center">
					{hasDocuments ? (
						<div className="max-w-sm text-center">
							<p className="text-sm text-neutral-500">
								{documents.length === 1
									? "Document loaded. Ask a question to get started."
									: `${documents.length} documents loaded. Ask a question across any or all of them.`}
							</p>
							<p className="mt-1 text-xs text-neutral-400">
								Answers cite the exact source — click a citation to jump to it.
							</p>
						</div>
					) : (
						<EmptyState onUpload={onUpload} uploading={uploading} />
					)}
				</div>
				<ChatInput
					onSend={onSend}
					onUpload={onUpload}
					disabled={streaming}
					uploading={uploading}
					documentCount={documents.length}
					atLimit={atLimit}
				/>
			</div>
		);
	}

	return (
		<div className="flex flex-1 flex-col bg-white">
			{hasDocuments && (
				<DocumentBar
					documents={documents}
					onOpen={(id) => onCitationClick(id, 1)}
				/>
			)}

			{error && (
				<div className="mx-4 mt-2 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
					{error}
				</div>
			)}

			<div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4">
				<div className="mx-auto max-w-2xl space-y-1">
					{messages.map((message) => (
						<MessageBubble
							key={message.id}
							message={message}
							onCitationClick={onCitationClick}
						/>
					))}
					{streaming && <StreamingBubble content={streamingContent} />}
				</div>
			</div>

			<ChatInput
				onSend={onSend}
				onUpload={onUpload}
				disabled={streaming}
				uploading={uploading}
				documentCount={documents.length}
				atLimit={atLimit}
			/>
		</div>
	);
}
