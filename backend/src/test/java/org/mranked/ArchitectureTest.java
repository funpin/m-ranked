package org.mranked;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;

import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;
import org.mranked.cache.application.PublicDtoCache;

@AnalyzeClasses(packages = "org.mranked")
class ArchitectureTest {
    @ArchTest
    static final ArchRule domain_is_framework_and_persistence_free = noClasses()
            .that().resideInAPackage("..domain..")
            .should().dependOnClassesThat().resideInAnyPackage(
                    "org.springframework..",
                    "java.sql..",
                    "javax.sql..",
                    "jakarta.persistence.."
            );

    @ArchTest
    static final ArchRule operations_and_admin_never_use_public_dto_cache = noClasses()
            .that().resideInAnyPackage("..operations..", "..admin..")
            .should().dependOnClassesThat()
            .haveFullyQualifiedName(PublicDtoCache.class.getName());

    @ArchTest
    static final ArchRule streaming_exports_never_use_public_dto_cache = noClasses()
            .that().haveSimpleName("CsvExportController")
            .should().dependOnClassesThat()
            .haveFullyQualifiedName(PublicDtoCache.class.getName());

    @ArchTest
    static final ArchRule admin_application_does_not_depend_on_web_or_persistence_adapters = noClasses()
            .that().resideInAPackage("..admin.application..")
            .should().dependOnClassesThat().resideInAnyPackage(
                    "..admin.web..",
                    "..admin.infrastructure..",
                    "org.springframework.jdbc..",
                    "java.sql.."
            );

    @ArchTest
    static final ArchRule admin_web_does_not_bypass_application_ports = noClasses()
            .that().resideInAPackage("..admin.web..")
            .should().dependOnClassesThat().resideInAnyPackage(
                    "..admin.infrastructure..",
                    "org.springframework.jdbc..",
                    "java.sql.."
            );
}
