import { useNavigate } from "react-router-dom";
import { Layout } from "../components/Layout";
import { QueueItem } from "../components/QueueItem";
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

  return (
    <Layout title="Queue" showBack={false}>
      <div className="p-4">
        <div className="flex justify-between items-center mb-4">
          <h1 className="text-2xl font-bold text-tg-text">Review Queue</h1>
          <button 
            onClick={refresh}
            className="p-2 text-tg-link active:opacity-70"
            disabled={loading}
          >
            <svg className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>

        <div className="flex overflow-x-auto hide-scrollbar gap-2 mb-4 pb-1">
          {tabs.map((tab) => (
            <button
              key={tab.id || "all"}
              onClick={() => setFilter(tab.id)}
              className={`flex items-center whitespace-nowrap px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                filter === tab.id 
                  ? "bg-tg-button text-tg-button-text" 
                  : "bg-tg-secondary-bg text-tg-hint active:bg-tg-secondary-bg/80"
              }`}
            >
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className={`ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] ${
                  filter === tab.id ? "bg-white/20" : "bg-tg-hint/20"
                }`}>
                  {tab.count}
                </span>
              )}
            </button>
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
          <div className="text-center py-12 text-tg-hint">
            <div className="text-4xl mb-3">✨</div>
            <p>No items in queue</p>
          </div>
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

        <div className="mt-8 flex justify-center gap-6 border-t border-tg-secondary-bg pt-6">
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
      </div>
    </Layout>
  );
}
