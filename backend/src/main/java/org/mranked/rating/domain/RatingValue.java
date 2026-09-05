package org.mranked.rating.domain;

import java.math.BigDecimal;

public record RatingValue(Integer rank, BigDecimal score) {
}
