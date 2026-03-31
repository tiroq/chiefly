import { useState, useRef, useEffect } from "react";

interface FieldEditorProps {
  value: string;
  onSave: (newValue: string) => void;
  label: string;
}

export function FieldEditor({ value, onSave, label }: FieldEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.setSelectionRange(inputRef.current.value.length, inputRef.current.value.length);
    }
  }, [isEditing]);

  const handleSave = () => {
    if (editValue.trim() !== value) {
      onSave(editValue.trim());
    }
    setIsEditing(false);
  };

  const handleCancel = () => {
    setEditValue(value);
    setIsEditing(false);
  };

  if (isEditing) {
    return (
      <div className="bg-tg-section-bg rounded-xl p-3 border border-tg-link">
        <div className="text-xs text-tg-hint mb-1">{label}</div>
        <textarea
          ref={inputRef}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          className="w-full bg-transparent text-tg-text text-base outline-none resize-none min-h-[60px]"
          rows={3}
        />
        <div className="flex justify-end gap-3 mt-2">
          <button 
            onClick={handleCancel}
            className="px-3 py-1.5 text-sm font-medium text-tg-hint active:opacity-70"
          >
            Cancel
          </button>
          <button 
            onClick={handleSave}
            className="px-3 py-1.5 text-sm font-medium bg-tg-button text-tg-button-text rounded-lg active:opacity-70"
          >
            Save
          </button>
        </div>
      </div>
    );
  }

  return (
    <div 
      onClick={() => setIsEditing(true)}
      className="bg-tg-section-bg rounded-xl p-3 active:bg-tg-secondary-bg transition-colors cursor-pointer group"
    >
      <div className="flex justify-between items-start">
        <div className="text-xs text-tg-hint mb-1">{label}</div>
        <svg className="w-4 h-4 text-tg-hint opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
        </svg>
      </div>
      <div className="text-tg-text text-base font-medium leading-snug">
        {value}
      </div>
    </div>
  );
}
