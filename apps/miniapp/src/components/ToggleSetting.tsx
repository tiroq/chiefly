interface ToggleSettingProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function ToggleSetting({ label, description, checked, onChange }: ToggleSettingProps) {
  return (
    <div 
      className="flex items-center justify-between py-3 px-4 bg-tg-section-bg border-b border-tg-secondary-bg last:border-b-0 active:bg-tg-secondary-bg transition-colors cursor-pointer"
      onClick={() => onChange(!checked)}
    >
      <div className="flex-1 pr-4">
        <div className="text-base font-medium text-tg-text mb-0.5">{label}</div>
        <div className="text-sm text-tg-subtitle leading-tight">{description}</div>
      </div>
      
      <div className="relative inline-flex items-center cursor-pointer shrink-0">
        <div className={`w-11 h-6 rounded-full transition-colors duration-200 ease-in-out ${checked ? 'bg-tg-button' : 'bg-tg-hint/30'}`}>
          <div 
            className={`absolute top-[2px] left-[2px] bg-white w-5 h-5 rounded-full shadow-sm transition-transform duration-200 ease-in-out ${checked ? 'translate-x-5' : 'translate-x-0'}`}
          />
        </div>
      </div>
    </div>
  );
}
