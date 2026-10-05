import type { ReactNode } from "react";
import { centroMetadata } from "@/lib/centro-metadata";

export const generateMetadata = () => centroMetadata("method", "/method");

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
