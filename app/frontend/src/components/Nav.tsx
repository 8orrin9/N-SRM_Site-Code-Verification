"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const MENUS = [
  { href: "/upload", label: "1. Data Upload" },
  { href: "/standardize", label: "2. Standardization" },
  { href: "/dedup", label: "3. Deduplication" },
  { href: "/similarity", label: "4. Similarity Search" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="gnb-menu">
      {MENUS.map((m) => (
        <Link key={m.href} href={m.href} className={pathname === m.href ? "active" : ""}>
          {m.label}
        </Link>
      ))}
    </nav>
  );
}
