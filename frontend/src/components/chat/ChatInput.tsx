"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { config } from "@/config";
import { takeHandoffQuery } from "@/lib/handoff";
import { Send, Square } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface ChatInputProps {
  onSend: (message: string) => void;
  onCancel?: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
  /** Fill the box from a ?q= hand-off link (see lib/handoff). */
  acceptHandoff?: boolean;
}

export function ChatInput({
  onSend,
  onCancel,
  isLoading = false,
  disabled = false,
  className,
  placeholder,
  acceptHandoff = false,
}: ChatInputProps) {
  const t = useTranslations("Chat");
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!acceptHandoff) return;
    const handed = takeHandoffQuery();
    if (!handed) return;
    // Deferred so the value lands after mount; the cursor goes to the end.
    requestAnimationFrame(() => {
      setValue(handed);
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(handed.length, handed.length);
      });
    });
  }, [acceptHandoff]);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [value]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (trimmed && !disabled && !isLoading) {
      onSend(trimmed);
      setValue("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleCancel = () => {
    onCancel?.();
  };

  const charCount = value.length;
  const isNearLimit = charCount > config.ui.chat.maxMessageLength * 0.9;
  const isOverLimit = charCount > config.ui.chat.maxMessageLength;

  return (
    <div className={cn("relative", className)}>
      <div className="group relative rounded-xl border border-line-control bg-surface shadow-float transition-[border-color] duration-200 focus-within:border-focus hover:border-fg-faint">
        <div className="flex items-center min-h-[48px] pr-2 gap-2">
          {/* Textarea */}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className={cn(
              "flex-1 resize-none bg-transparent px-4 py-3 text-base text-fg placeholder:text-fg-muted focus:outline-none disabled:cursor-not-allowed disabled:opacity-45",
              "scrollbar-thin max-h-[200px]"
            )}
          />

          {/* Action button. Cancelling loses no saved work (the analysis can
              be re-run), so the stop acts immediately, but it must read as
              "stop the analysis", never as an error state. */}
          {isLoading ? (
            <Tooltip delayDuration={200}>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  variant="secondary"
                  onClick={handleCancel}
                  aria-label={t("stopAnalysis")}
                  className="h-9 w-9 shrink-0"
                >
                  <Square className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <p className="text-[11px]">{t("stopAnalysis")}</p>
              </TooltipContent>
            </Tooltip>
          ) : (
            <Button
              size="icon"
              onClick={handleSubmit}
              disabled={disabled || !value.trim() || isOverLimit}
              aria-label={t("placeholder")}
              className={cn(
                "h-9 w-9 shrink-0 transition-[opacity,transform] duration-200 motion-reduce:transition-none",
                value.trim() ? "opacity-100 scale-100" : "opacity-0 scale-90 w-0 h-0 p-0 overflow-hidden"
              )}
            >
              <Send className="h-4 w-4" aria-hidden="true" />
            </Button>
          )}
        </div>

        {/* Character count: absolute position to avoid layout shifts, only show when near limit */}
        {value.length > config.ui.chat.maxMessageLength * 0.8 && (
          <div className="absolute bottom-1 right-4">
            <span
              className={cn(
                "font-mono text-[10px] tabular bg-surface/80 px-1 rounded-xs",
                isOverLimit
                  ? "text-danger-fg font-medium"
                  : isNearLimit
                  ? "text-notice-fg"
                  : "text-fg-muted"
              )}
            >
              {charCount}/{config.ui.chat.maxMessageLength}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
