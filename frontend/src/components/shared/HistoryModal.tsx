"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
} from "@/components/ui/sheet";
import {
  History,
  Trash2,
  Check,
  X,
  Loader2,
  MessageCircle,
  Clock,
  Inbox,
  AlertCircle,
} from "lucide-react";
import { config } from "@/config";
import { useTranslations } from "next-intl";

interface HistoryModalProps {
  open: boolean;
  onClose: () => void;
  onLoadChat?: (chat: any) => void;
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return isMobile;
}

export function HistoryModal({ open, onClose, onLoadChat }: HistoryModalProps) {
  const isMobile = useIsMobile();
  const t = useTranslations("HistoryModal");
  const [history, setHistory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [deleteConfirmationId, setDeleteConfirmationId] = useState<string | null>(null);

  const fetchHistory = async () => {
    setIsLoading(true);
    setError("");
    try {
      const res = await fetch(`${config.api.baseUrl}/history`);
      if (!res.ok) throw new Error("Failed to load history");
      const data = await res.json();
      setHistory(data.history || []);
    } catch (err) {
      console.error(err);
      setError(t("loadError"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectChat = async (id: string) => {
    setIsLoading(true);
    try {
      const res = await fetch(`${config.api.baseUrl}/history/${id}`);
      if (!res.ok) throw new Error("Failed to load chat details");
      const data = await res.json();
      if (onLoadChat) {
        onLoadChat(data);
        onClose();
      } else {
        sessionStorage.setItem("pendingChat", JSON.stringify(data));
        window.location.href = "/home";
      }
    } catch (err) {
      console.error(err);
      setError(t("loadChatError"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRequestDelete = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation();
    setDeleteConfirmationId(id);
  };

  const handleCancelDelete = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation();
    setDeleteConfirmationId(null);
  };

  const handleConfirmDelete = async (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation();
    try {
      const res = await fetch(`${config.api.baseUrl}/history/${id}`, { method: "DELETE" });
      if (res.ok) {
        setHistory((prev) => prev.filter((h) => h.id !== id));
      }
    } catch (err) {
      console.error(err);
    } finally {
      setDeleteConfirmationId(null);
    }
  };

  useEffect(() => {
    if (open) {
      fetchHistory();
    }
  }, [open]);

  // ── Lista voci (condivisa) ───────────────────────────────────────────────
  const historyItems = history.map((item) => (
    <div
      key={item.id}
      onClick={() => handleSelectChat(item.id)}
      className="group flex items-start gap-3 p-3 rounded-md bg-surface-muted hover:bg-surface-sunken cursor-pointer transition-colors"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-brand-soft mt-0.5">
        <MessageCircle className="h-4 w-4 text-brand-fg" />
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <span className="font-medium text-sm line-clamp-2 text-fg">
          {item.query}
        </span>
        {item.preview && (
          <p className="text-xs text-fg-muted line-clamp-1">{item.preview}</p>
        )}
        <div className="flex items-center gap-1.5 pt-0.5">
          <Clock className="h-3 w-3 text-fg-muted" />
          <span className="text-[11px] text-fg-muted">
            {new Date(item.timestamp).toLocaleDateString("it-IT", {
              day: "2-digit",
              month: "short",
              year: "numeric",
            })}{" "}
            ·{" "}
            {new Date(item.timestamp).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
      </div>
      <div className="shrink-0 pt-1">
        {deleteConfirmationId === item.id ? (
          <div className="flex gap-1">
            <Button
              variant="secondary"
              size="icon"
              className="h-9 w-9 min-tap-none bg-surface hover:bg-surface-sunken"
              onClick={handleCancelDelete}
            >
              <X className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="destructive"
              size="icon"
              className="h-9 w-9 min-tap-none"
              onClick={(e) => handleConfirmDelete(e, item.id)}
            >
              <Check className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9 min-tap-none opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 [@media(pointer:coarse)]:opacity-100 transition-opacity text-fg-muted hover:text-danger-fg hover:bg-danger-soft"
            onClick={(e) => handleRequestDelete(e, item.id)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </div>
  ));

  // Stato vuoto / loading / errore (condiviso)
  const emptyState = isLoading && history.length === 0 ? (
    <div className="flex flex-col items-center justify-center gap-3 py-10">
      <Loader2 className="h-6 w-6 text-brand-fg animate-spin" />
      <span className="text-sm text-fg-muted">{t("loading")}</span>
    </div>
  ) : error ? (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-10">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-danger-soft">
        <AlertCircle className="h-6 w-6 text-danger-fg" />
      </div>
      <p className="text-sm text-fg-muted text-center">{error}</p>
    </div>
  ) : history.length === 0 ? (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-10">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-muted">
        <Inbox className="h-6 w-6 text-fg-muted" />
      </div>
      <div className="text-center space-y-1">
        <p className="text-sm font-medium text-fg">{t("noConversations")}</p>
        <p className="text-xs text-fg-muted">{t("noConversationsDesc")}</p>
      </div>
    </div>
  ) : null;

  // ── Mobile: bottom sheet ─────────────────────────────────────────────────
  if (isMobile) {
    return (
      <Sheet open={open} onOpenChange={onClose}>
        <SheetContent side="bottom" showCloseButton={false} className="rounded-t-2xl bg-surface shadow-overlay max-h-[85vh] flex flex-col p-0">
          <SheetHeader className="px-6 py-4 border-b border-line shrink-0">
            <div className="flex items-center justify-between">
              <SheetTitle className="serif-display flex items-center gap-2 text-xl text-fg">
                <History className="h-5 w-5 text-brand-fg" />
                {t("title")}
              </SheetTitle>
              <SheetClose asChild>
                <button className="inline-flex items-center justify-center h-8 w-8 rounded-full text-fg-muted hover:text-fg hover:bg-surface-muted transition-colors">
                  <X className="h-4 w-4" />
                </button>
              </SheetClose>
            </div>
            <div className="flex items-center gap-4 mt-2 text-xs text-fg-muted">
              <span className="flex items-center gap-1">
                <MessageCircle className="h-3 w-3" />
                {history.length} {history.length === 1 ? t("oneConversation") : t("manyConversations")}
              </span>
              <span className="text-fg-faint">{t("previousConversations")}</span>
            </div>
          </SheetHeader>
          {/* Mobile: overflow-y-auto nativo, identico al filter sheet */}
          <div className="flex-1 overflow-y-auto px-6 py-4 pb-10">
            {emptyState ?? <div className="space-y-2">{historyItems}</div>}
          </div>
        </SheetContent>
      </Sheet>
    );
  }

  // ── Desktop: modal centrato con ScrollArea ───────────────────────────────
  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-[95vw] sm:max-w-xl bg-surface border border-line shadow-overlay p-0 gap-0 overflow-hidden rounded-xl h-[85vh] sm:h-[80vh] flex flex-col">
        <DialogHeader className="px-6 py-4 border-b border-line shrink-0">
          <DialogTitle className="serif-display flex items-center gap-2 text-xl text-fg">
            <History className="h-5 w-5 text-brand-fg" />
            <span>{t("title")}</span>
          </DialogTitle>
          <div className="flex items-center gap-4 mt-2 text-xs text-fg-muted">
            <span className="flex items-center gap-1">
              <MessageCircle className="h-3 w-3" />
              {history.length} {history.length === 1 ? t("oneConversation") : t("manyConversations")}
            </span>
            <span className="text-fg-faint">{t("previousConversations")}</span>
          </div>
        </DialogHeader>
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          {emptyState ? (
            <div className="flex flex-col items-center justify-center flex-1">{emptyState}</div>
          ) : (
            <ScrollArea className="flex-1 h-0 [&_[data-radix-scroll-area-viewport]>div]:!block">
              <div className="px-6 py-4 space-y-2 pb-8">{historyItems}</div>
            </ScrollArea>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
