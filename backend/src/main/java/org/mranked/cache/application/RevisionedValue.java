package org.mranked.cache.application;

import org.mranked.cache.domain.DatasetRevision;

/** The revision actually read in the transaction that produced the value. */
public record RevisionedValue<T>(DatasetRevision revision, T value) {}
