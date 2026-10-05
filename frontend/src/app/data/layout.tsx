import type { ReactNode } from "react";
import { centroMetadata } from "@/lib/centro-metadata";

export const generateMetadata = () => centroMetadata("data", "/data");

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
