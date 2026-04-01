import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { backButton } from "@telegram-apps/sdk-react";

interface LayoutProps {
  title: string;
  children: React.ReactNode;
  showBack?: boolean;
  onBack?: () => void;
  rightAction?: React.ReactNode;
  footer?: React.ReactNode;
}

export function Layout({ title, children, showBack = true, onBack, rightAction, footer }: LayoutProps) {
  const navigate = useNavigate();

  useEffect(() => {
    document.title = title;
  }, [title]);

  useEffect(() => {
    if (showBack) {
      backButton.show();
      
      const handleBack = () => {
        if (onBack) {
          onBack();
        } else {
          navigate(-1);
        }
      };
      
      const unsub = backButton.onClick(handleBack);
      
      return () => {
        unsub();
        backButton.hide();
      };
    } else {
      backButton.hide();
    }
  }, [showBack, onBack, navigate]);

  return (
    <div className="min-h-screen bg-tg-bg text-tg-text flex flex-col">
      <div className="sticky top-0 z-10 bg-tg-bg border-b border-tg-secondary-bg/50 px-4 py-3 flex justify-between items-center">
        <div className="text-lg font-semibold text-tg-text">{title}</div>
        {rightAction && <div>{rightAction}</div>}
      </div>
      <div className="flex-1 overflow-y-auto pb-safe">
        {children}
      </div>
      {footer}
    </div>
  );
}
