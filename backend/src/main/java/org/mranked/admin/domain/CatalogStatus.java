package org.mranked.admin.domain;
import java.util.List;
public record CatalogStatus(long channelCount,long platformCount,long institutionCount,MRating mRating,
        List<Integration> integrations,Storage storage) {
    public record MRating(String period,String updatedAt,String error) { }
    public record Integration(String platform,String status,String detail) { }
    public record Storage(Long diskTotalBytes,Long diskFreeBytes,Long projectBytes,Long databaseBytes) { }
}
