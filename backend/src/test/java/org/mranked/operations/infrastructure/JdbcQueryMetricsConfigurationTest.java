package org.mranked.operations.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import javax.sql.DataSource;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class JdbcQueryMetricsConfigurationTest {
    @Test void countsExecutionsAndFailuresWhilePreservingCloseAndExceptionSemantics() throws Exception {
        var calls=new AtomicInteger();
        var statementClosed=new AtomicBoolean();var connectionClosed=new AtomicBoolean();
        var statement=proxy(PreparedStatement.class,(p,m,a)-> {
            if(m.getName().equals("executeQuery") && calls.incrementAndGet()>1) throw new SQLException("test failure","57014");
            if(m.getName().equals("close")) statementClosed.set(true);
            return null;
        });
        var connection=proxy(Connection.class,(p,m,a)-> {
            if(m.getName().equals("prepareStatement")) return statement;
            if(m.getName().equals("close")) connectionClosed.set(true);
            return null;
        });
        var source=proxy(DataSource.class,(p,m,a)->m.getName().equals("getConnection")?connection:null);
        var counters=new JdbcQueryMetricsConfiguration.QueryCounters();
        var wrapped=new JdbcQueryMetricsConfiguration.MeteredDataSource(source,counters);
        try(var acquired=wrapped.getConnection();var query=acquired.prepareStatement("SELECT confidential_value WHERE secret=?")) {
            query.setString(1,"sensitive");
            assertThat(counters.count()).isZero();
            query.executeQuery();
            assertThat(counters.count()).isEqualTo(1);
            assertThatThrownBy(query::executeQuery).isInstanceOf(SQLException.class)
                    .extracting(error->((SQLException)error).getSQLState()).isEqualTo("57014");
        }
        assertThat(counters.count()).isEqualTo(2);
        assertThat(counters.errors()).isEqualTo(1);
        assertThat(counters.nanoseconds()).isGreaterThan(0);
        assertThat(connectionClosed).isTrue();assertThat(statementClosed).isTrue();
    }
    private static <T> T proxy(Class<T> type,InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(),new Class<?>[]{type},handler));
    }
}
