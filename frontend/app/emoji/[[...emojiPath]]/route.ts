import { createEmojiRoute, legacyEmojiRouteNotFound } from "@/lib/emoji-route";

const customEmoji = createEmojiRoute();

export async function GET(
  _request: Request,
  context: { params: Promise<{ emojiPath?: string[] }> },
): Promise<Response> {
  const { emojiPath } = await context.params;
  if (emojiPath?.length !== 1 || emojiPath[0]!.includes("/")) {
    return legacyEmojiRouteNotFound();
  }
  return customEmoji(emojiPath[0]!);
}
