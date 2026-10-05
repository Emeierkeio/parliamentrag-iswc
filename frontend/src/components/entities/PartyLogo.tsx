import Image from "next/image";
import { getGroupLogo } from "@/config";

/** Party logo from /public/groups, or nothing: unlike GroupLogo there is no
    colour-dot fallback, since the written abbreviation already identifies the
    group (Misto and its components have no logo). */
export function PartyLogo({ group, size = 18, className = "" }: { group: string; size?: number; className?: string }) {
  const src = getGroupLogo(group);
  if (!src) return null;
  return (
    <Image
      src={src}
      alt=""
      width={size}
      height={size}
      className={`shrink-0 object-contain ${className}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}
