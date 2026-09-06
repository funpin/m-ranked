package org.mranked.admin.infrastructure;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.HexFormat;
import java.util.regex.Pattern;
import org.mranked.admin.domain.OfficialRating;
import org.mranked.admin.domain.OfficialRatingDataset;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

final class OfficialRatingParser {
    private static final JsonMapper JSON=new JsonMapper();
    private static final Map<String,String> CATEGORIES=Map.of("social","social","telegram","tg","vk","vk","max","ok","rutube","rt");
    private static final Map<Integer,String> CASEFOLD=loadCasefold();
    private OfficialRatingParser() { }
    static int year(String config) {
        var match=Pattern.compile("\\byear\\s*:\\s*(\\d{4})").matcher(config);
        if(!match.find()) throw new IllegalArgumentException("Official rating year is missing"); return Integer.parseInt(match.group(1));
    }
    static String ratingsPath(String config) {
        var match=Pattern.compile("\\bratingsJson\\s*:\\s*[\"']([^\"']+)[\"']").matcher(config);
        if(!match.find() || match.group(1).length()>2048) throw new IllegalArgumentException("Official rating source is missing"); return match.group(1);
    }
    static OfficialRatingDataset parse(byte[] bytes,int year,String sourceUrl,Instant fetchedAt) {
        var months=JSON.readTree(bytes).path("months");
        if(!months.isArray() || months.size()>120) throw new IllegalArgumentException("Invalid official rating months");
        JsonNode selected=null;
        for(int index=months.size()-1;index>=0 && selected==null;index--) {
            var month=months.get(index);var items=month.path("items");
            if(items.isMissingNode() || items.isNull()) continue;
            if(!items.isArray() || items.size()>10000) throw new IllegalArgumentException("Invalid official rating items");
            for(var item:items) if(CATEGORIES.values().stream().anyMatch(key->!item.path("scores").path(key).isMissingNode() && !item.path("scores").path(key).isNull())) {
                selected=month;break;
            }
        }
        if(selected==null) throw new IllegalArgumentException("No official social rating is available");
        String name=pythonString(selected.path("name"),false);
        if(name.length()>200) throw new IllegalArgumentException("Invalid official period");
        String period=name+" "+year;
        Map<String,Map<String,OfficialRating>> rankings=new LinkedHashMap<>();
        for(var category:CATEGORIES.entrySet()) {
            var candidates=new ArrayList<Candidate>();
            for(var item:selected.path("items")) {
                var score=item.path("scores").path(category.getValue());
                if(score.isMissingNode() || score.isNull()) continue;
                double numeric=number(score);
                if(!Double.isFinite(numeric)) throw new IllegalArgumentException("Invalid official score");
                String code=pythonStrip(pythonString(item.path("code"),true));
                String title=pythonString(item.path("name"),true);
                if(code.length()>200 || title.length()>1000) throw new IllegalArgumentException("Invalid official institution");
                candidates.add(new Candidate(code,title,numeric));
            }
            candidates.sort((left,right)->left.score()>right.score()?-1:left.score()<right.score()?1:
                compareCodePoints(casefold(left.name()),casefold(right.name())));
            Map<String,OfficialRating> ranking=new LinkedHashMap<>();
            for(int index=0;index<candidates.size();index++) {
                var item=candidates.get(index);if(!item.code().isEmpty()) ranking.put(item.code(),new OfficialRating(index+1,BigDecimal.valueOf(item.score())));
            }
            rankings.put(category.getKey(),Map.copyOf(ranking));
        }
        // Retrievable allowlisted evidence excludes unknown provider fields.
        List<Map<String,Object>> evidenceItems=new ArrayList<>();
        for(var item:selected.path("items")) {
            Map<String,Object> values=new LinkedHashMap<>();values.put("code",item.path("code").asString(""));values.put("name",item.path("name").asString(""));
            Map<String,Object> scores=new LinkedHashMap<>();
            for(String key:CATEGORIES.values()) if(!item.path("scores").path(key).isMissingNode() && !item.path("scores").path(key).isNull())
                scores.put(key,BigDecimal.valueOf(number(item.path("scores").path(key))));
            values.put("scores",scores);evidenceItems.add(values);
        }
        try {
            String digest=HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
            return new OfficialRatingDataset(period,Map.copyOf(rankings),sourceUrl,digest,fetchedAt,Map.of("year",year,"month",name,"items",evidenceItems));
        } catch(java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private record Candidate(String code,String name,double score) { }
    private static double number(JsonNode value) {
        double number=value.isBoolean()?(value.booleanValue()?1:0):Double.parseDouble(value.asString());
        if(!Double.isFinite(number)) throw new IllegalArgumentException("Invalid official score");return number;
    }
    private static String pythonString(JsonNode value,boolean emptyWhenFalse) {
        if(value.isMissingNode() || value.isNull()) return emptyWhenFalse?"":"None";
        if(emptyWhenFalse && (value.isBoolean()&&!value.booleanValue() || value.isNumber()&&value.doubleValue()==0)) return "";
        if(value.isBoolean()) return value.booleanValue()?"True":"False";
        if(value.isContainer()) throw new IllegalArgumentException("Invalid official text field");
        return value.asString();
    }
    private static String pythonStrip(String value) {
        return value.replaceAll("^[\\x{0009}-\\x{000D}\\x{001C}-\\x{0020}\\x{0085}\\x{00A0}\\x{1680}\\x{2000}-\\x{200A}\\x{2028}\\x{2029}\\x{202F}\\x{205F}\\x{3000}]+|[\\x{0009}-\\x{000D}\\x{001C}-\\x{0020}\\x{0085}\\x{00A0}\\x{1680}\\x{2000}-\\x{200A}\\x{2028}\\x{2029}\\x{202F}\\x{205F}\\x{3000}]+$", "");
    }
    private static int compareCodePoints(String left,String right) {
        var a=left.codePoints().iterator();var b=right.codePoints().iterator();
        while(a.hasNext() && b.hasNext()) { int comparison=Integer.compare(a.nextInt(),b.nextInt());if(comparison!=0) return comparison; }
        return Boolean.compare(a.hasNext(),b.hasNext());
    }
    static String casefold(String value) {
        var result=new StringBuilder();value.codePoints().forEach(code->result.append(CASEFOLD.getOrDefault(code,new String(Character.toChars(code)))));return result.toString();
    }
    private static Map<Integer,String> loadCasefold() {
        try(var input=OfficialRatingParser.class.getResourceAsStream("/admin/legacy-unicode-casefold.json")) {
            if(input==null) throw new IllegalStateException("Legacy casefold mapping is missing");
            Map<Integer,String> result=new LinkedHashMap<>();
            JSON.readTree(input).properties().forEach(property->result.put(Integer.valueOf(property.getKey()),property.getValue().asString()));return Map.copyOf(result);
        } catch(java.io.IOException failure) { throw new IllegalStateException("Cannot read legacy casefold mapping",failure); }
    }
}
