import { motion } from "framer-motion";
import { Bot, CircleHelp, ShieldCheck, TriangleAlert } from "lucide-react";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";
import type { Citation, Confidence, Message } from "../types";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

interface MessageBubbleProps {
	message: Message;
	onCitationClick: (documentId: string, page: number) => void;
}

const CONFIDENCE_META: Record<
	Confidence,
	{
		label: string;
		explanation: string;
		icon: typeof ShieldCheck;
		className: string;
	}
> = {
	grounded: {
		label: "Grounded",
		explanation:
			"Well-supported: multiple claims are backed by verified citations into your documents.",
		icon: ShieldCheck,
		className: "bg-emerald-50 text-emerald-700 border-emerald-200",
	},
	partial: {
		label: "Partially supported",
		explanation:
			"Some claims are cited, but support is thin or mixed. Verify the cited sources before relying on this.",
		icon: TriangleAlert,
		className: "bg-amber-50 text-amber-700 border-amber-200",
	},
	unsupported: {
		label: "Unverified",
		explanation:
			"No verifiable citations into your documents. Treat this answer with caution — it may not be grounded in the uploaded material.",
		icon: CircleHelp,
		className: "bg-neutral-100 text-neutral-600 border-neutral-200",
	},
};

function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
	const meta = CONFIDENCE_META[confidence];
	const Icon = meta.icon;
	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<span
					className={`inline-flex cursor-default items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${meta.className}`}
				>
					<Icon className="h-3 w-3" />
					{meta.label}
				</span>
			</TooltipTrigger>
			<TooltipContent className="max-w-xs">{meta.explanation}</TooltipContent>
		</Tooltip>
	);
}

/**
 * Turn inline [Sn] markers into clickable markdown links so the citation is
 * clickable right where it appears in the answer. Only markers that resolved to
 * a real source are linkified; anything else is left as plain text.
 */
function linkifyCitations(content: string, citations: Citation[]): string {
	if (citations.length === 0) return content;
	const valid = new Set(citations.map((c) => c.marker));
	return content.replace(/\[S(\d+)\]/g, (match, n: string) => {
		const marker = `S${n}`;
		return valid.has(marker) ? `[${marker}](#cite-${marker})` : match;
	});
}

function CitationList({
	citations,
	onCitationClick,
}: {
	citations: Citation[];
	onCitationClick: (documentId: string, page: number) => void;
}) {
	return (
		<div className="mt-2.5 border-t border-neutral-100 pt-2">
			<p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-neutral-400">
				Sources
			</p>
			<div className="flex flex-wrap gap-1.5">
				{citations.map((c) => (
					<Tooltip key={c.marker}>
						<TooltipTrigger asChild>
							<button
								type="button"
								onClick={() => onCitationClick(c.document_id, c.page)}
								className="flex max-w-[280px] items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2 py-1 text-left text-xs text-neutral-600 transition-colors hover:border-neutral-300 hover:bg-neutral-50"
							>
								<span className="rounded bg-neutral-900 px-1 py-0.5 text-[10px] font-semibold text-white">
									{c.marker}
								</span>
								<span className="truncate">
									{c.filename} · p.{c.page}
									{c.heading ? ` · cl. ${c.heading}` : ""}
								</span>
							</button>
						</TooltipTrigger>
						<TooltipContent className="max-w-sm">
							<span className="text-xs leading-snug">{c.snippet}</span>
						</TooltipContent>
					</Tooltip>
				))}
			</div>
		</div>
	);
}

export function MessageBubble({
	message,
	onCitationClick,
}: MessageBubbleProps) {
	if (message.role === "system") {
		return (
			<motion.div
				initial={{ opacity: 0 }}
				animate={{ opacity: 1 }}
				transition={{ duration: 0.2 }}
				className="flex justify-center py-2"
			>
				<p className="text-xs text-neutral-400">{message.content}</p>
			</motion.div>
		);
	}

	if (message.role === "user") {
		return (
			<motion.div
				initial={{ opacity: 0, y: 8 }}
				animate={{ opacity: 1, y: 0 }}
				transition={{ duration: 0.2 }}
				className="flex justify-end py-1.5"
			>
				<div className="max-w-[75%] rounded-2xl rounded-br-md bg-neutral-100 px-4 py-2.5">
					<p className="whitespace-pre-wrap text-sm text-neutral-800">
						{message.content}
					</p>
				</div>
			</motion.div>
		);
	}

	// Assistant message
	const citations = message.citations ?? [];
	const rendered = linkifyCitations(message.content, citations);

	// Intercept clicks on inline citation links (href="#cite-Sn").
	const handleClickCapture = (e: React.MouseEvent<HTMLDivElement>) => {
		const anchor = (e.target as HTMLElement).closest("a");
		if (!anchor) return;
		const href = anchor.getAttribute("href") ?? "";
		if (!href.startsWith("#cite-")) return;
		e.preventDefault();
		const marker = href.slice("#cite-".length);
		const citation = citations.find((c) => c.marker === marker);
		if (citation) onCitationClick(citation.document_id, citation.page);
	};

	return (
		<motion.div
			initial={{ opacity: 0, y: 8 }}
			animate={{ opacity: 1, y: 0 }}
			transition={{ duration: 0.2 }}
			className="flex gap-3 py-1.5"
		>
			<div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-neutral-900">
				<Bot className="h-4 w-4 text-white" />
			</div>
			<div className="min-w-0 max-w-[80%]">
				{message.confidence && (
					<div className="mb-1.5">
						<ConfidenceBadge confidence={message.confidence} />
					</div>
				)}
				<div className="prose" onClickCapture={handleClickCapture}>
					<Streamdown>{rendered}</Streamdown>
				</div>
				{citations.length > 0 && (
					<CitationList
						citations={citations}
						onCitationClick={onCitationClick}
					/>
				)}
			</div>
		</motion.div>
	);
}

interface StreamingBubbleProps {
	content: string;
}

export function StreamingBubble({ content }: StreamingBubbleProps) {
	return (
		<div className="flex gap-3 py-1.5">
			<div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-neutral-900">
				<Bot className="h-4 w-4 text-white" />
			</div>
			<div className="min-w-0 max-w-[80%]">
				{content ? (
					<div className="prose">
						<Streamdown mode="streaming">{content}</Streamdown>
					</div>
				) : (
					<div className="flex items-center gap-1 py-2">
						<span className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-400" />
						<span
							className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-400"
							style={{ animationDelay: "0.15s" }}
						/>
						<span
							className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-400"
							style={{ animationDelay: "0.3s" }}
						/>
					</div>
				)}
				<span className="inline-block h-4 w-0.5 animate-pulse bg-neutral-400" />
			</div>
		</div>
	);
}
