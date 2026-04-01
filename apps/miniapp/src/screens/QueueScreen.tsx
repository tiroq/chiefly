import { useNavigate } from "react-router-dom";
import { Layout } from "../components/Layout";
import { QueueItem } from "../components/QueueItem";
import { ScreenContent, Chip, EmptyState } from "../components/ui";
import { useQueue, QueueFilter } from "../hooks/useQueue";

export function QueueScreen() {
  const navigate = useNavigate();
  const { items, counts, filter, setFilter, loading, error, refresh } = useQueue();

  const tabs: { id: QueueFilter; label: string; count?: number }[] = [
    { id: null, label: "All", count: counts.total },
    { id: "pending", label: "Pending", count: counts.pending },
    { id: "queued", label: "Queued", count: counts.queued },
    { id: "ambiguous", label: "Ambiguous" },
  ];

  const rightAction = (
    <button 
      onClick={refresh}
      className="p-2 text-tg-link active:opacity-70"
      disabled={loading}
    >
      <svg className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
      </svg>
    </button>
  );

  const footer = (
    <nav className="sticky bottom-0 border-t border-tg-secondary-bg/50 bg-tg-bg pb-safe">
      <div className="flex justify-center gap-12 pt-3 pb-2">
        <button 
          onClick={() => navigate("/projects")}
          className="flex flex-col items-center text-tg-hint active:text-tg-link transition-colors"
        >
          <svg className="w-6 h-6 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          <span className="text-xs font-medium">Projects</span>
        </button>
        <button 
          onClick={() => navigate("/settings")}
          className="flex flex-col items-center text-tg-hint active:text-tg-link transition-colors"
        >
          <svg className="w-6 h-6 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span className="text-xs font-medium">Settings</span>
        </button>
      </div>
    </nav>
  );

  return (
    <Layout title="Queue" showBack={false} rightAction={rightAction} footer={footer}>
      <ScreenContent>
        <div className="flex overflow-x-auto hide-scrollbar gap-2 pb-1 -mt-1 mb-3">
          {tabs.map((tab) => (
            <Chip
              key={tab.id || "all"}
              selected={filter === tab.id}
              onClick={() => setFilter(tab.id)}
            >
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className={`ml-1.5 px-2 py-0.5 rounded-full text-[11px] ${
                  filter === tab.id ? "bg-white/20" : "bg-tg-hint/20"
                }`}>
                  {tab.count}
                </span>
              )}
            </Chip>
          ))}
        </div>

        {error && (
          <div className="bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 p-3 rounded-xl mb-4 text-sm flex justify-between items-center">
            <span>{error}</span>
            <button onClick={refresh} className="font-medium underline">Retry</button>
          </div>
        )}

        {loading && items.length === 0 ? (
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 border-4 border-tg-secondary-bg border-t-tg-button rounded-full animate-spin"></div>
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            title="Queue is clear"
            subtitle="No tasks need review right now."
            action={
              <button onClick={refresh} className="text-sm text-tg-link font-medium">
                Refresh
              </button>
            }
          />
        ) : (
          <div className="flex flex-col">
            {items.map((item) => (
              <QueueItem 
                key={item.stable_id} 
                item={item} 
                onClick={() => navigate(`/review/${item.stable_id}`)} 
              />
            ))}
          </div>
        )}
      </ScreenContent>
    </Layout>
  );
}
