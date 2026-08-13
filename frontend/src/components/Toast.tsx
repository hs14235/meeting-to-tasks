import { createContext, useContext, useState } from "react";

type Kind = "success" | "error" | "info";
type ToastItem = { id: string; title: string; detail?: unknown; kind: Kind };
type ToastContextValue = { push: (toast: Omit<ToastItem, "id">) => void };

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  function push(toast: Omit<ToastItem, "id">) {
    const id = crypto.randomUUID();
    setItems((current) => [...current, { ...toast, id }]);
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 4200);
  }

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toastHost" role="status" aria-live="polite">
        {items.map((toast) => (
          <div key={toast.id} className={`toast is-${toast.kind}`}>
            <strong>{toast.title}</strong>
            {toast.detail != null && (
              <pre>{typeof toast.detail === "string" ? toast.detail : JSON.stringify(toast.detail, null, 2)}</pre>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return {
    success: (title: string, detail?: unknown) => context.push({ kind: "success", title, detail }),
    error: (title: string, detail?: unknown) => context.push({ kind: "error", title, detail }),
    info: (title: string, detail?: unknown) => context.push({ kind: "info", title, detail }),
  };
}
