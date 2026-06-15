import { useState, useEffect } from "react";

/**
 * Lightweight contextual tutorial that shows once per page.
 * Dismissed state is stored in localStorage.
 */
export function Tutorial({
  id,
  title,
  steps,
}: {
  id: string;
  title: string;
  steps: string[];
}) {
  const storageKey = `tutorial_dismissed_${id}`;
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const dismissed = localStorage.getItem(storageKey);
    if (!dismissed) setVisible(true);
  }, [storageKey]);

  function dismiss() {
    localStorage.setItem(storageKey, "1");
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 mb-4 relative">
      <button
        onClick={dismiss}
        className="absolute top-2 right-2 text-blue-400 hover:text-blue-600 text-sm"
        title="关闭"
      >
        ✕
      </button>
      <h3 className="text-sm font-medium text-blue-800 mb-1.5">{title}</h3>
      <ol className="list-decimal list-inside space-y-0.5">
        {steps.map((step, i) => (
          <li key={i} className="text-xs text-blue-700">{step}</li>
        ))}
      </ol>
    </div>
  );
}
