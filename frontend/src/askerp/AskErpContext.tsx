import { createContext, useContext, useRef, useState, type ReactNode } from "react";

interface AskErpContextValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  /** Opens the panel and runs a preset query, e.g. from a dashboard "explain this" link. */
  ask: (text: string) => void;
  /** Used internally by AskErpPanel to receive queries triggered from elsewhere in the app. */
  registerRunner: (fn: (text: string) => void) => void;
}

const AskErpContext = createContext<AskErpContextValue | null>(null);

export function AskErpProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const runnerRef = useRef<((text: string) => void) | null>(null);

  const open = () => setIsOpen(true);
  const close = () => setIsOpen(false);

  const registerRunner = (fn: (text: string) => void) => {
    runnerRef.current = fn;
  };

  const ask = (text: string) => {
    setIsOpen(true);
    setTimeout(() => runnerRef.current?.(text), 150);
  };

  return (
    <AskErpContext.Provider value={{ isOpen, open, close, ask, registerRunner }}>{children}</AskErpContext.Provider>
  );
}

export function useAskErp(): AskErpContextValue {
  const ctx = useContext(AskErpContext);
  if (!ctx) throw new Error("useAskErp must be used within an AskErpProvider");
  return ctx;
}
