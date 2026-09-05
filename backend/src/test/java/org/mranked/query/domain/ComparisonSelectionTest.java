package org.mranked.query.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import java.util.stream.LongStream;
import org.junit.jupiter.api.Test;

class ComparisonSelectionTest {
    @Test
    void preservesExplicitLegacyIdOrderAndDefensivelyCopiesIt() {
        var source = new java.util.ArrayList<>(List.of(31L, 7L, 31L, 19L));

        ComparisonSelection selection = new ComparisonSelection(
                ComparisonSelectionType.CHANNELS, source
        );
        source.clear();

        assertThat(selection.explicit()).isTrue();
        assertThat(selection.type()).isEqualTo(ComparisonSelectionType.CHANNELS);
        assertThat(selection.legacyIds()).containsExactly(31L, 7L, 19L);
        assertThatThrownBy(() -> selection.legacyIds().add(4L))
                .isInstanceOf(UnsupportedOperationException.class);
    }

    @Test
    void rejectsNonPositiveAndExcessSelections() {
        assertThatThrownBy(() -> new ComparisonSelection(
                ComparisonSelectionType.CHANNELS, List.of(0L)
        ))
                .isInstanceOf(InvalidComparisonSelectionException.class)
                .hasMessageContaining("positive integers");
        assertThatThrownBy(() -> new ComparisonSelection(
                ComparisonSelectionType.INSTITUTIONS,
                LongStream.rangeClosed(1, 51).boxed().toList()
        ))
                .isInstanceOf(InvalidComparisonSelectionException.class)
                .hasMessageContaining("At most 50");
    }

    @Test
    void emptySelectionMeansTheBoundedDefaultCohortSlice() {
        assertThat(ComparisonSelection.defaults(ComparisonSelectionType.INSTITUTIONS).explicit())
                .isFalse();
        assertThat(ComparisonSelection.defaults(ComparisonSelectionType.CHANNELS).legacyIds())
                .isEmpty();
    }
}
