"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { useTranslations } from "next-intl";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** Light/dark switch for the sidebar; the label names the theme it switches to. */
export function ThemeToggle({ isCollapsed = false }: { isCollapsed?: boolean }) {
  const t = useTranslations("Sidebar");
  const { resolvedTheme, setTheme } = useTheme();
  // The resolved theme is only known on the client; render a stable label first.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const isDark = mounted && resolvedTheme === "dark";
  const label = isDark ? t("themeLight") : t("themeDark");
  const Icon = isDark ? Sun : Moon;

  const button = (
    <Button
      variant="ghost"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={label}
      className={cn(
        "rounded-md text-fg-secondary hover:bg-surface hover:text-fg transition-colors",
        isCollapsed ? "w-9 h-9 justify-center px-0 mx-auto" : "w-full justify-start gap-2.5 h-8 mb-0.5 text-[13px]"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!isCollapsed && <span className="truncate">{label}</span>}
    </Button>
  );

  if (!isCollapsed) return button;
  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="right" sideOffset={10}>{label}</TooltipContent>
    </Tooltip>
  );
}
