"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowUpRight, BookOpen, CalendarDays, Landmark, MessageSquare, User, Users } from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { getGroupAbbrev } from "@/config";
import { deputySlug } from "@/lib/graph";
import { isFactualQuestion, stenografoUrl } from "@/lib/question-kind";

export interface ReadyTopic {
  topic: string;
  id: string | null;
  interventions: number | null;
}

interface DeputyHit {
  id: string;
  first_name: string;
  last_name: string;
}

interface GroupHit {
  name: string;
  member_count: number;
}

/* Topic dossiers are fetched once per page load and shared by the palette
   and the home index. */
let topicsPromise: Promise<ReadyTopic[]> | null = null;
export function fetchReadyTopics(): Promise<ReadyTopic[]> {
  topicsPromise ??= fetch("/api/topics")
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  return topicsPromise;
}

let groupsPromise: Promise<GroupHit[]> | null = null;
function fetchGroups(): Promise<GroupHit[]> {
  groupsPromise ??= fetch("/api/search/groups")
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  return groupsPromise;
}

function titleCase(name: string): string {
  return name.toLowerCase().replace(/(^|[\s'-])(\p{L})/gu, (_, sep, c) => sep + c.toUpperCase());
}

export function askHref(q: string): string {
  return `/home?chiedi=${encodeURIComponent(q)}`;
}

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useTranslations("Shell");
  const router = useRouter();
  const [q, setQ] = useState("");
  const [topics, setTopics] = useState<ReadyTopic[]>([]);
  const [groups, setGroups] = useState<GroupHit[]>([]);
  const [deputies, setDeputies] = useState<DeputyHit[]>([]);

  useEffect(() => {
    if (!open) return;
    fetchReadyTopics().then(setTopics);
    fetchGroups().then(setGroups);
  }, [open]);

  const query = q.trim();
  useEffect(() => {
    if (query.length < 3) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetch(`/api/search/deputies?q=${encodeURIComponent(query)}&limit=6`, { signal: ctrl.signal })
        .then((r) => (r.ok ? r.json() : []))
        .then(setDeputies)
        .catch(() => {});
    }, 180);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [query]);

  const lower = query.toLowerCase();
  const topicHits = topics.filter((tp) => tp.id && (!lower || tp.topic.toLowerCase().includes(lower)));
  const groupHits = lower
    ? groups.filter((g) => g.name.toLowerCase().includes(lower) || getGroupAbbrev(g.name).toLowerCase() === lower)
    : [];
  const deputyHits = query.length >= 3 ? deputies : [];

  const go = (href: string) => {
    onOpenChange(false);
    setQ("");
    if (href.startsWith("http")) window.open(href, "_blank", "noopener");
    else router.push(href);
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("searchTrigger")}
      description={t("placeholder")}
      className="top-[12vh] translate-y-0 rounded-xl border-line bg-surface shadow-overlay sm:max-w-xl"
      showCloseButton={false}
    >
      <CommandInput value={q} onValueChange={setQ} placeholder={t("placeholder")} className="text-base" />
      <CommandList className="max-h-[min(60vh,28rem)]">
        <CommandEmpty>{t("empty")}</CommandEmpty>

        {query.length >= 2 && (
          <CommandGroup heading={t("groupAsk")}>
            {(isFactualQuestion(query)
              ? (["stenografo", "ask"] as const)
              : (["ask", "stenografo"] as const)
            ).map((kind) =>
              kind === "ask" ? (
                <CommandItem key="ask" value={`ask ${query}`} onSelect={() => go(askHref(query))}>
                  <MessageSquare className="text-brand-fg" />
                  <span className="truncate">{t("askPositions", { q: query })}</span>
                </CommandItem>
              ) : (
                <CommandItem key="stenografo" value={`stenografo ${query}`} onSelect={() => go(stenografoUrl(query))}>
                  <ArrowUpRight />
                  <span className="truncate">{t("askStenografo")}</span>
                </CommandItem>
              ),
            )}
          </CommandGroup>
        )}

        {topicHits.length > 0 && (
          <CommandGroup heading={t("groupTopics")}>
            {topicHits.map((tp) => (
              <CommandItem key={tp.topic} value={`topic ${tp.topic}`} onSelect={() => go(`/tema/${tp.id}`)}>
                <BookOpen />
                <span className="flex-1 truncate">{tp.topic.charAt(0).toUpperCase() + tp.topic.slice(1)}</span>
                {tp.interventions != null && (
                  <span className="font-mono text-xs text-fg-muted">{t("topicMeta", { n: tp.interventions })}</span>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {deputyHits.length > 0 && (
          <CommandGroup heading={t("groupDeputies")}>
            {deputyHits.map((d) => (
              <CommandItem
                key={d.id}
                value={`deputy ${d.first_name} ${d.last_name}`}
                onSelect={() => go(`/parlamentari/${deputySlug(d.id)}`)}
              >
                <User />
                <span className="truncate">{titleCase(`${d.first_name} ${d.last_name}`)}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {groupHits.length > 0 && (
          <CommandGroup heading={t("groupGroups")}>
            {groupHits.map((g) => (
              <CommandItem
                key={g.name}
                value={`group ${g.name}`}
                onSelect={() => go(`/gruppi/${getGroupAbbrev(g.name).toLowerCase()}`)}
              >
                <Landmark />
                <span className="flex-1 truncate">{titleCase(g.name)}</span>
                <span className="font-mono text-xs text-fg-muted">{getGroupAbbrev(g.name)}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {!query && (
          <CommandGroup heading={t("groupGo")}>
            <CommandItem value="go aula" onSelect={() => go("/timeline")}>
              <CalendarDays />
              {t("navAula")}
            </CommandItem>
            <CommandItem value="go deputati" onSelect={() => go("/parlamentari")}>
              <User />
              {t("navDeputies")}
            </CommandItem>
            <CommandItem value="go gruppi" onSelect={() => go("/gruppi")}>
              <Users />
              {t("navGroups")}
            </CommandItem>
          </CommandGroup>
        )}
      </CommandList>
      <div className="flex items-center gap-4 border-t border-line px-3 py-2 font-mono text-[11px] text-fg-muted">
        <span>{t("hintOpen")}</span>
        <span>{t("hintClose")}</span>
      </div>
    </CommandDialog>
  );
}
