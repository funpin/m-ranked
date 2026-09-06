package org.mranked.query.infrastructure;

import org.mranked.query.domain.PublicationPresentation;
import tools.jackson.databind.json.JsonMapper;

final class PublicationPresentationMapper {
    private static final JsonMapper JSON=new JsonMapper();
    static PublicationPresentation map(String platform,String externalId,String publicUrl,boolean repost,
            String flags,int jointAuthors) {
        var evidence=JSON.readTree(flags==null?"{}":flags);
        int authors=Math.max(jointAuthors,Math.max(evidence.path("additional_author_count").asInt(0),
                evidence.path("legacy_additional_author_count").asInt(0)));
        String display=externalId;
        if("telegram".equals(platform)) {
            display=null;
            if(publicUrl!=null) {
                String path=java.net.URI.create(publicUrl).getPath();
                String tail=path.substring(path.lastIndexOf('/')+1);
                if(tail.matches("[0-9]+"))display=tail;
            }
            if(display==null&&externalId!=null&&externalId.startsWith("m:"))display=externalId.substring(2);
        }
        return new PublicationPresentation(display,repost,authors>0||evidence.path("joint_post").asBoolean(false)
                ||evidence.path("legacy_is_joint").asBoolean(false),authors,
                evidence.path("ambiguous_album_reactions").asBoolean(false)||evidence.path("ambiguous_reactions").asBoolean(false));
    }
}
