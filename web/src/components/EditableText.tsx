import { useState, useRef, useEffect } from "react";

function renderSimpleMarkdown(text: string): React.ReactNode {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let key = 0;

  for (const line of lines) {
    if (line.startsWith("### ")) {
      elements.push(
        <h4 key={key++} className="text-sm font-semibold text-gray-700 mt-3 mb-1">
          {line.slice(4)}
        </h4>
      );
    } else if (line.startsWith("## ")) {
      elements.push(
        <h3 key={key++} className="text-base font-bold text-gray-800 mt-4 mb-1">
          {line.slice(3)}
        </h3>
      );
    } else if (line.startsWith("# ")) {
      elements.push(
        <h2 key={key++} className="text-lg font-bold text-gray-900 mt-2 mb-2">
          {line.slice(2)}
        </h2>
      );
    } else if (line.trim() === "") {
      elements.push(<div key={key++} className="h-2" />);
    } else {
      elements.push(
        <p key={key++} className="text-sm text-gray-600 leading-relaxed">
          {line}
        </p>
      );
    }
  }
  return <>{elements}</>;
}

/**
 * Inline-editable text area. Shows as read-only text until user clicks edit.
 * On save, calls onSave with the new value.
 */
export function EditableText({
  value,
  onSave,
  label,
  placeholder = "点击编辑...",
  multiline = true,
  className = "",
}: {
  value: string;
  onSave: (newValue: string) => Promise<void>;
  label?: string;
  placeholder?: string;
  multiline?: boolean;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.selectionStart = textareaRef.current.value.length;
    }
  }, [editing]);

  async function handleSave() {
    if (draft === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  function handleCancel() {
    setDraft(value);
    setEditing(false);
  }

  if (!editing) {
    return (
      <div className={`group relative ${className}`}>
        {label && <p className="text-xs text-gray-400 mb-1">{label}</p>}
        <div
          onClick={() => setEditing(true)}
          className="cursor-pointer rounded px-2 py-1.5 hover:bg-gray-50 border border-transparent hover:border-gray-200 transition-colors"
        >
          {value ? (
            <div className="text-sm whitespace-pre-wrap prose prose-sm prose-gray max-w-none">
              {renderSimpleMarkdown(value)}
            </div>
          ) : (
            <div className="text-sm text-gray-300 italic">{placeholder}</div>
          )}
        </div>
        <button
          onClick={() => setEditing(true)}
          className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 text-[10px] px-1.5 py-0.5 bg-gray-100 rounded text-gray-500 hover:bg-gray-200 transition-opacity"
        >
          编辑
        </button>
      </div>
    );
  }

  return (
    <div className={className}>
      {label && <p className="text-xs text-gray-400 mb-1">{label}</p>}
      {multiline ? (
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full border rounded px-2 py-1.5 text-sm min-h-[120px] resize-y focus:ring-1 focus:ring-red-300 focus:border-red-300"
          disabled={saving}
        />
      ) : (
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full border rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-red-300 focus:border-red-300"
          disabled={saving}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
            if (e.key === "Escape") handleCancel();
          }}
        />
      )}
      <div className="flex gap-1.5 mt-1.5">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-2.5 py-1 bg-red-500 text-white rounded text-xs hover:bg-red-600 disabled:opacity-50"
        >
          {saving ? "保存中..." : "保存"}
        </button>
        <button
          onClick={handleCancel}
          disabled={saving}
          className="px-2.5 py-1 border rounded text-xs hover:bg-gray-50"
        >
          取消
        </button>
      </div>
    </div>
  );
}
