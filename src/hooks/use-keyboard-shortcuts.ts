/**
 * useKeyboardShortcuts - global keyboard shortcuts (#27).
 *
 * Cmd+K / Ctrl+K -> focus chat input
 * Esc -> close inspector / blur input
 * Cmd+Enter -> send message
 */
import { useEffect } from "react";

export function useKeyboardShortcuts({
  onFocusInput,
  onCloseInspector,
  onSendMessage,
}: {
  onFocusInput?: () => void;
  onCloseInspector?: () => void;
  onSendMessage?: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Cmd+K / Ctrl+K -> focus chat input
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onFocusInput?.();
      }
      // Esc -> close inspector
      if (e.key === "Escape") {
        onCloseInspector?.();
      }
      // Cmd+Enter / Ctrl+Enter -> send
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        onSendMessage?.();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onFocusInput, onCloseInspector, onSendMessage]);
}
