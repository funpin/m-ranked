package org.mranked.query.domain;

/** A reaction label and signed count in the source's visible order. */
public record ReactionBreakdownEntry(String reaction,long count) { }
