"use client";

import React, { useState } from "react";
import { Star } from "lucide-react";
import { cn } from "@/lib/utils";

interface StarRatingProps {
  value: number;
  onChange: (value: number) => void;
  max?: number;
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  showLabel?: boolean;
  className?: string;
}

const LABELS = ["", "Insufficiente", "Scarso", "Sufficiente", "Buono", "Eccellente"];

const sizeClasses = {
  sm: "w-5 h-5",
  md: "w-6 h-6",
  lg: "w-8 h-8",
};

export function StarRating({
  value,
  onChange,
  max = 5,
  size = "md",
  disabled = false,
  showLabel = true,
  className,
}: StarRatingProps) {
  const [hoverValue, setHoverValue] = useState(0);

  const displayValue = hoverValue || value;

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex items-center gap-1">
        {Array.from({ length: max }, (_, i) => i + 1).map((starValue) => {
          const isFilled = starValue <= displayValue;
          const isHovered = starValue <= hoverValue;

          return (
            <button
              key={starValue}
              type="button"
              disabled={disabled}
              onClick={() => onChange(starValue)}
              onMouseEnter={() => !disabled && setHoverValue(starValue)}
              onMouseLeave={() => setHoverValue(0)}
              className={cn(
                "transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-focus rounded-full",
                disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:scale-110"
              )}
              aria-label={`${starValue} su ${max} stelle`}
            >
              <Star
                className={cn(
                  sizeClasses[size],
                  "transition-colors duration-150",
                  isFilled
                    ? "fill-brand text-brand"
                    : "fill-transparent text-line-control",
                  isHovered && !isFilled && "text-brand/50"
                )}
              />
            </button>
          );
        })}
        {showLabel && value > 0 && (
          <span
            className="ml-2 text-sm font-medium text-fg-secondary transition-opacity duration-150"
          >
            {LABELS[value]}
          </span>
        )}
      </div>
    </div>
  );
}
