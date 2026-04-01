import { ListRow } from "./ui/ListRow";

interface ToggleSettingProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Pass false for the last row in a group to remove the border */
  border?: boolean;
}

export function ToggleSetting({ label, description, checked, onChange, border = true }: ToggleSettingProps) {
  return (
    <ListRow onClick={() => onChange(!checked)} border={border}>
      <div className="flex-1 pr-4">
        <div className="text-sm font-medium text-tg-text">{label}</div>
        <div className="text-xs text-tg-hint">{description}</div>
      </div>
      
      <div className="relative inline-flex items-center cursor-pointer shrink-0">
        <div className={`w-11 h-6 rounded-full transition-colors duration-200 ease-in-out ${checked ? 'bg-tg-button' : 'bg-tg-hint/30'}`}>
          <div 
            className={`absolute top-[2px] left-[2px] bg-white w-5 h-5 rounded-full shadow-sm transition-transform duration-200 ease-in-out ${checked ? 'translate-x-5' : 'translate-x-0'}`}
          />
        </div>
      </div>
    </ListRow>
  );
}
