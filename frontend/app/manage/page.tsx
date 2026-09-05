import type { Metadata } from "next";
import { AdminConsole } from "./admin-console";

// Administrative routes must never inherit Next's public static-page cache.
// The shell contains no credentials, but making the response dynamic also
// gives the future same-origin Nginx route an explicit fail-safe no-store
// policy before any browser session is established.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = {
  title: "Управление сбором",
  description: "Закрытая консоль просмотра запусков сбора и управления состоянием аккаунтов.",
  referrer: "no-referrer",
  robots: { index: false, follow: false, nocache: true },
};

export default function ManagePage() {
  return <AdminConsole />;
}
