package org.mranked.admin.application;

import java.net.URI;
import java.util.Locale;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Set;
import java.util.UUID;

/** Normalizes the legacy forms before any command transaction begins. No network requests. */
public record AccountReference(String platform, String externalKey, String username, String title,
        String url, String accessMode) {
    public static AccountReference parse(String platform, String reference, String title, String suppliedUrl) {
        if(!Set.of("telegram","vk","max","rutube").contains(platform)) throw new IllegalArgumentException("Unsupported platform");
        String original=text(reference,2048,"Укажите аккаунт или ссылку");
        String key=original; String url=nullable(suppliedUrl,2048);
        if(platform.equals("telegram")) {
            key=original.replaceFirst("/+$","").replaceFirst("(?i)^(?:https?://)?t\\.me/","").replaceFirst("^@+","");
            var parts=java.util.Arrays.stream(key.split("/")).filter(part->!part.isEmpty()).toList();
            int index=!parts.isEmpty() && parts.getFirst().equalsIgnoreCase("s")?1:0;
            key=parts.size()>index?parts.get(index):"";
            if(!key.matches("[A-Za-z0-9_]{5,32}")) throw new IllegalArgumentException("Invalid Telegram channel username");
            url="https://t.me/"+key;
        } else if(platform.equals("vk")) {
            key=original.replaceFirst("/+$","").replaceFirst("(?i)^https?://(?:m\\.)?vk\\.(?:com|ru)/","");
            key=key.split("\\?",2)[0].split("/",2)[0].replaceFirst("^@+","");
            if(!key.matches("(?:club|public)?[A-Za-zА-Яа-яЁё0-9_.-]{2,64}"))
                throw new IllegalArgumentException("Не удалось определить сообщество ВКонтакте");
            if(url==null) url="https://vk.com/"+key;
        } else {
            URI parsed=URI.create(original.contains("://")?original:"https://placeholder/"+original);
            if(original.contains("://")) { requireWebUrl(original); if(url==null) url=original; }
            String path=parsed.getPath().replaceFirst("/+$","");
            key=path.substring(path.lastIndexOf('/')+1).replaceFirst("^@","");
            if(key.isBlank() || key.length()>200) throw new IllegalArgumentException("Не удалось определить аккаунт");
        }
        if(url!=null) requireWebUrl(url);
        return new AccountReference(platform,platform.equals("telegram")?key.toLowerCase(Locale.ROOT):key,key,nullable(title,1000),url,
                switch(platform) { case "telegram"->"public_web"; case "vk"->"official_api"; case "max"->"user_session"; default->"public_api"; });
    }
    public Map<String,Object> body(UUID institution) {
        Map<String,Object> body=new LinkedHashMap<>();
        body.put("institutionId",institution); body.put("platform",platform); body.put("externalKey",externalKey);
        body.put("username",username); body.put("title",title); body.put("url",url); body.put("accessMode",accessMode);
        return body;
    }
    static String text(String value,int max,String error) {
        String result=nullable(value,max); if(result==null) throw new IllegalArgumentException(error); return result;
    }
    static String nullable(String value,int max) {
        if(value==null || value.strip().isEmpty()) return null;
        String result=value.strip();
        if(result.length()>max || result.codePoints().anyMatch(Character::isISOControl)) throw new IllegalArgumentException("Invalid text field");
        return result;
    }
    private static void requireWebUrl(String value) {
        URI uri=URI.create(value);
        if(!Set.of("https","http").contains(uri.getScheme()==null?"":uri.getScheme().toLowerCase(Locale.ROOT)) || uri.getHost()==null || uri.getUserInfo()!=null)
            throw new IllegalArgumentException("Аккаунт должен использовать HTTP(S)-ссылку без учётных данных");
    }
}
