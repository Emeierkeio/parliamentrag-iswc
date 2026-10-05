"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { History } from "lucide-react";
import { AppBar } from "@/components/shell/AppBar";
import { fetchReadyTopics } from "@/components/shell/CommandPalette";
import { HomeLanding } from "@/components/home/HomeLanding";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { NewsletterSignup } from "@/components/feedback/NewsletterSignup";
import { ChatArea } from "@/components/chat";
import { LiveDossier } from "@/components/dossier/LiveDossier";
import { HistoryModal } from "@/components/shared/HistoryModal";
import { useChat } from "@/hooks";
import { isFactualQuestion, stenografoUrl } from "@/lib/question-kind";
import { ArrowUpRight } from "lucide-react";

/* A dossier for this exact topic, if one is already saved. */
async function readyDossier(topic: string): Promise<string | null> {
  const needle = topic.trim().toLowerCase();
  const ready = await Promise.race([
    fetchReadyTopics(),
    new Promise<[]>((resolve) => setTimeout(() => resolve([]), 2500)),
  ]);
  const hit = ready.find((d) => d.id && d.topic.toLowerCase() === needle);
  if (hit?.id) return hit.id;
  try {
    // A busy local backend runs one pipeline at a time: past this wait the
    // topic is composed live instead of blocking on the lookup.
    const res = await fetch(`/api/topics/match?q=${encodeURIComponent(topic.trim())}`, {
      signal: AbortSignal.timeout(2500),
    });
    if (!res.ok) return null;
    return (await res.json()).id ?? null;
  } catch {
    return null;
  }
}

function HomeView() {
  const t = useTranslations("Home");
  const tw = useTranslations("WelcomeScreen");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { messages, isLoading, progress, lastCompletedProgress, sendMessage, cancelRequest, loadChat } = useChat();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const askedHere = useRef(false);
  const handledQuery = useRef<string | null>(null);

  const ask = useCallback(
    (text: string) => {
      askedHere.current = true;
      sendMessage(text);
    },
    [sendMessage],
  );

  /* A topic opens its saved dossier; without one the pipeline composes it. */
  const askTopic = useCallback(
    async (topic: string) => {
      setOpening(true);
      const id = await readyDossier(topic);
      if (id) {
        router.push(`/tema/${id}`);
        return;
      }
      setOpening(false);
      ask(tw("topicQuery", { topic }));
    },
    [ask, router, tw],
  );

  /* Free text: a factual question is pointed to Stenografo first, a bare
     topic name may match a dossier, anything else goes to the pipeline. */
  const [factual, setFactual] = useState<string | null>(null);
  const askText = useCallback(
    async (text: string, force = false) => {
      if (!force && isFactualQuestion(text)) {
        setFactual(text);
        return;
      }
      setFactual(null);
      if (text.trim().split(/\s+/).length <= 5 && !text.includes("?")) {
        await askTopic(text);
        return;
      }
      ask(text);
    },
    [ask, askTopic],
  );

  useEffect(() => {
    // Internal links (the Cmd+K palette) ask at once; external ?q= links only
    // prefill the box (ChatInput acceptHandoff) and wait for the reader.
    const q = searchParams.get("chiedi");
    if (!q || handledQuery.current === q) return;
    handledQuery.current = q;
    void Promise.resolve().then(() => askTopic(q));
  }, [searchParams, askTopic]);

  useEffect(() => {
    const pending = sessionStorage.getItem("pendingChat");
    if (pending) {
      sessionStorage.removeItem("pendingChat");
      try {
        loadChat(JSON.parse(pending));
      } catch (err) {
        console.error("Failed to load pending chat:", err);
      }
    }
  }, [loadChat]);

  /* An answer composed here becomes its dossier as soon as it is saved. */
  const savedId = messages.findLast((m) => m.role === "assistant")?.chatId;
  useEffect(() => {
    if (askedHere.current && !isLoading && savedId) router.push(`/tema/${savedId}`);
  }, [isLoading, savedId, router]);

  const historyButton = (
    <button
      type="button"
      onClick={() => setHistoryOpen(true)}
      aria-label={tw("historyLabel")}
      title={tw("historyLabel")}
      className="inline-flex size-10 shrink-0 items-center justify-center rounded-full text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg"
    >
      <History className="size-[18px]" aria-hidden />
    </button>
  );

  const showLanding = messages.length === 0 && !isLoading;
  const lastAssistant = messages.findLast((m) => m.role === "assistant");

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-bg">
      <AppBar actions={historyButton} />
      <HistoryModal
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onLoadChat={(chat: { id: string }) => router.push(`/tema/${chat.id}`)}
      />
      {opening && (
        <div role="status" className="fixed inset-x-0 top-[var(--header-h)] z-overlay h-0.5 overflow-hidden bg-brand-soft">
          <span className="sr-only">{t("opening")}</span>
          <span className="block h-full w-1/3 animate-[shell-progress_1.1s_var(--ease-standard)_infinite] bg-brand" />
        </div>
      )}
      <main className="min-h-0 flex-1 overflow-y-auto">
        {showLanding ? (
          <>
            {factual && (
              <div className="container-page pt-6">
                <div role="status" className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5 md:flex-row md:items-center md:p-6">
                  <div className="flex min-w-0 flex-col gap-1">
                    <p className="label-mono text-fg-muted">{t("factualTitle")}</p>
                    <p className="text-[15px] leading-relaxed">
                      {t("factualBody")} <span className="text-fg-secondary">«{factual}»</span>
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2 md:ml-auto">
                    <a
                      href={stenografoUrl(factual)}
                      className="inline-flex h-10 items-center gap-1.5 rounded-full bg-brand px-4 text-sm font-medium text-on-brand hover:bg-brand-hover"
                    >
                      {t("factualStenografo")}
                      <ArrowUpRight className="size-4" aria-hidden />
                    </a>
                    <button
                      type="button"
                      onClick={() => askText(factual, true)}
                      className="inline-flex h-10 items-center rounded-full border border-line-strong bg-surface px-4 text-sm hover:bg-surface-muted"
                    >
                      {t("factualAnyway")}
                    </button>
                  </div>
                </div>
              </div>
            )}
            <HomeLanding onAsk={askText} onAskTopic={askTopic} />
            <div className="container-page pb-16">
              <NewsletterSignup source="home" variant="panel" />
            </div>
            <SiteFooter />
          </>
        ) : !lastAssistant?.gate ? (
          <LiveDossier
            query={messages.findLast((m) => m.role === "user")?.content ?? ""}
            answer={lastAssistant}
            progress={progress}
            onCancel={cancelRequest}
          />
        ) : (
          <ChatArea
            messages={messages}
            isLoading={isLoading}
            progress={progress}
            lastCompletedProgress={lastCompletedProgress}
            onSendMessage={ask}
            onCancelRequest={cancelRequest}
            hideTopBar
          />
        )}
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <Suspense fallback={null}>
      <HomeView />
    </Suspense>
  );
}
