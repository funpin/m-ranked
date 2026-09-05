package org.mranked.cache.application;

import org.mranked.cache.domain.DatasetRevision;

public interface DatasetRevisionProvider {
    DatasetRevision current();
}
