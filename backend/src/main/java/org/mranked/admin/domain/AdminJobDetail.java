package org.mranked.admin.domain;

import java.util.List;

public record AdminJobDetail(
        AdminJobSummary job,
        List<AdminAccountResult> accountResults,
        boolean accountResultsTruncated
) {
    public AdminJobDetail {
        accountResults = List.copyOf(accountResults);
    }
}
