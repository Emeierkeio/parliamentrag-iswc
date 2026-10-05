"use client";

import { useState } from "react";

interface DeputyAvatarProps {
  photo: string | null;
  firstName: string;
  lastName: string;
  /** Diameter in px */
  size: number;
}

/** Round deputy photo; camera.it photos are sometimes missing or 404, so the
    fallback is the initials on a neutral disc. */
export function DeputyAvatar({ photo, firstName, lastName, size }: DeputyAvatarProps) {
  const [failed, setFailed] = useState(false);
  const initials = `${firstName.trim().charAt(0)}${lastName.trim().charAt(0)}`.toUpperCase();

  if (!photo || failed) {
    return (
      <span
        aria-hidden="true"
        className="inline-flex shrink-0 select-none items-center justify-center rounded-full bg-surface-sunken font-mono font-medium text-fg-muted"
        style={{ width: size, height: size, fontSize: Math.round(size * 0.32) }}
      >
        {initials}
      </span>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- external camera.it photos, onError needed
    <img
      src={photo}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      className="shrink-0 rounded-full bg-surface-muted object-cover"
      style={{ width: size, height: size }}
      onError={() => setFailed(true)}
    />
  );
}
