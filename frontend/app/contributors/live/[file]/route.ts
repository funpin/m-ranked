import { readFile } from "node:fs/promises";
import path from "node:path";
import { contributorsDirectory } from "@/lib/contributors.server";

const FILE = /^[A-Za-z0-9-]{1,39}-[0-9a-f]{12}\.(png|jpg|webp)$/;
const TYPES: Record<string, string> = { png: "image/png", jpg: "image/jpeg", webp: "image/webp" };

/** Аватар автора из каталога на сервере. В имени — хеш содержимого,
 *  поэтому файл кэшируется навсегда: новая картинка получает новое имя. */
export async function GET(_request: Request, { params }: { params: Promise<{ file: string }> }) {
  const { file } = await params;
  const match = FILE.exec(file);
  const directory = contributorsDirectory();
  if (!match || !directory) return new Response(null, { status: 404 });
  try {
    const body = await readFile(path.join(directory, "avatars", file));
    return new Response(new Uint8Array(body), { headers: {
      "Content-Type": TYPES[match[1]],
      "Cache-Control": "public, max-age=31536000, immutable",
      "X-Accel-Expires": "86400",
      "X-Content-Type-Options": "nosniff",
    } });
  } catch {
    return new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });
  }
}
