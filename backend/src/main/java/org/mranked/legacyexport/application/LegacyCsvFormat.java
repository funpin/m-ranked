package org.mranked.legacyexport.application;

import java.io.IOException;
import java.io.Writer;
import java.util.List;
import java.util.Locale;

/** Frozen Python csv.writer dialect. Deliberately separate from the modern safe CSV. */
public record LegacyCsvFormat(String kind, String platform) {
    public LegacyCsvFormat {
        if (!List.of("posts", "snapshots").contains(kind)) throw new IllegalArgumentException("Unknown CSV kind");
        platform = platform == null ? "telegram" : pythonStrip(platform).toLowerCase(Locale.ROOT);
        platform = switch (platform) {case "tg" -> "telegram"; case "общий" -> "all"; default -> platform;};
        if (!List.of("all", "telegram", "vk", "max", "rutube").contains(platform)) platform = "telegram";
    }
    private static String pythonStrip(String value) {
        int first=0,last=value.length();
        while(first<last&&pythonSpace(value.codePointAt(first)))first+=Character.charCount(value.codePointAt(first));
        while(last>first&&pythonSpace(value.codePointBefore(last)))last-=Character.charCount(value.codePointBefore(last));
        return value.substring(first,last);
    }
    private static boolean pythonSpace(int point) {return Character.isWhitespace(point)||Character.isSpaceChar(point)||point==0x85;}
    public String namespace() {return platform.equals("telegram") ? "telegram" : "generic";}
    public String filename() {return kind + (platform.equals("telegram") ? "" : "-" + platform) + ".csv";}
    public List<String> headers() {
        if (kind.equals("snapshots")) {
            return platform.equals("telegram")
                ? List.of("канал", "id_публикации", "опубликовано", "измерено", "возраст_часов", "реакций_всего",
                    "изменение_реакций", "просмотры", "изменение_просмотров", "комментарии", "изменение_комментариев", "реакции_json")
                : List.of("площадка", "вуз", "аккаунт", "id_публикации", "опубликовано", "измерено", "возраст_часов",
                    "просмотры", "реакции", "комментарии", "репосты", "сырой_json");
        }
        return platform.equals("telegram")
            ? List.of("канал", "id_публикации", "опубликовано", "полная_история", "последнее_число_реакций",
                "последнее_число_просмотров", "последнее_число_комментариев", "максимальный_скачок", "возраст_скачка_часов")
            : List.of("площадка", "вуз", "аккаунт", "id_публикации", "опубликовано", "тип", "ссылка",
                "последние_просмотры", "последние_реакции", "последние_комментарии", "последние_репосты");
    }
    public static void writeRecord(Writer writer, List<String> cells) throws IOException {
        for (int i = 0; i < cells.size(); i++) {
            if (i != 0) writer.write(',');
            String cell = cells.get(i) == null ? "" : cells.get(i);
            boolean quote = cell.indexOf(',') >= 0 || cell.indexOf('"') >= 0 || cell.indexOf('\r') >= 0 || cell.indexOf('\n') >= 0
                || (cells.size() == 1 && cell.isEmpty());
            if (quote) writer.write('"');
            for (int j = 0; j < cell.length(); j++) {
                char c = cell.charAt(j);
                writer.write(c);
                if (c == '"') writer.write('"');
            }
            if (quote) writer.write('"');
        }
        writer.write("\r\n");
    }
}
