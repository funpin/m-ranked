package org.mranked.query.domain;

public record PublicationPresentation(String displayExternalId,boolean repost,boolean joint,
        int additionalAuthorCount,boolean ambiguousAlbumReactions) {
    public static final PublicationPresentation EMPTY=new PublicationPresentation(null,false,false,0,false);
}
