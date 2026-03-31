import { ReviewQueueItem } from "../api/client";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { KindBadge } from "./KindBadge";

interface QueueItemProps {
  item: ReviewQueueItem;
  onClick: () => void;
}

export function QueueItem({ item, onClick }: QueueItemProps) {
  const date = new Date(item.created_at);
  const timeString = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div 
      onClick={onClick}
      className="bg-tg-section-bg rounded-xl p-4 mb-3 shadow-sm active:opacity-70 transition-opacity cursor-pointer"
    >
      <div className="flex justify-between items-start mb-2">
        <div className="flex gap-2 flex-wrap">
          <KindBadge kind={item.kind} />
          <ConfidenceBadge confidence={item.confidence} />
          {item.has_ambiguity && (
            <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400">
              AMBIGUOUS
            </span>
          )}
        </div>
        <span className="text-tg-hint text-xs">{timeString}</span>
      </div>
      
      <h3 className="text-tg-text font-semibold text-base mb-1 leading-tight">
        {item.normalized_title}
      </h3>
      
      <p className="text-tg-subtitle text-sm line-clamp-2 mb-3">
        {item.raw_text}
      </p>
      
      <div className="flex items-center text-xs text-tg-hint">
        <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        {item.project_name || "Inbox"}
      </div>
    </div>
  );
}
