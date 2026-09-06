package org.mranked.operations.infrastructure;

import io.micrometer.core.instrument.FunctionCounter;
import io.micrometer.core.instrument.FunctionTimer;
import io.micrometer.core.instrument.binder.MeterBinder;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.sql.CallableStatement;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.LongAdder;
import javax.sql.DataSource;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DelegatingDataSource;

/** Counts actual JDBC execute calls. SQL, parameters and identifiers never become labels. */
@Configuration(proxyBeanMethods=false)
public class JdbcQueryMetricsConfiguration {
    @Bean static QueryCounters jdbcQueryCounters() { return new QueryCounters(); }

    @Bean static BeanPostProcessor meterJdbcDataSources(QueryCounters counters) {
        return new BeanPostProcessor() {
            @Override public Object postProcessAfterInitialization(Object bean,String name) {
                return bean instanceof DataSource source && !(bean instanceof MeteredDataSource)
                        ? new MeteredDataSource(source,counters) : bean;
            }
        };
    }

    @Bean MeterBinder jdbcQueryMetrics(QueryCounters counters) {
        return registry -> {
            FunctionTimer.builder("mranked.jdbc.executions",counters,
                    QueryCounters::count,QueryCounters::nanoseconds,TimeUnit.NANOSECONDS).register(registry);
            FunctionCounter.builder("mranked.jdbc.errors",counters,QueryCounters::errors).register(registry);
        };
    }

    static final class QueryCounters {
        private final LongAdder count=new LongAdder(), nanos=new LongAdder(), errors=new LongAdder();
        long count() { return count.sum(); }
        double nanoseconds() { return nanos.sum(); }
        double errors() { return errors.sum(); }
    }

    static final class MeteredDataSource extends DelegatingDataSource {
        private final QueryCounters counters;
        MeteredDataSource(DataSource source,QueryCounters counters) { super(source); this.counters=counters; }
        @Override public Connection getConnection() throws SQLException { return wrap(super.getConnection()); }
        @Override public Connection getConnection(String user,String password) throws SQLException { return wrap(super.getConnection(user,password)); }
        private Connection wrap(Connection connection) {
            return (Connection)Proxy.newProxyInstance(Connection.class.getClassLoader(),new Class<?>[]{Connection.class},
                (proxy,method,args) -> {
                    try {
                        Object result=method.invoke(connection,args);
                        return result instanceof Statement statement ? wrap(statement) : result;
                    } catch(InvocationTargetException failure) { throw failure.getCause(); }
                });
        }
        private Statement wrap(Statement statement) {
            Class<?> type=statement instanceof CallableStatement ? CallableStatement.class
                    : statement instanceof PreparedStatement ? PreparedStatement.class : Statement.class;
            return (Statement)Proxy.newProxyInstance(Statement.class.getClassLoader(),new Class<?>[]{type},
                (proxy,method,args) -> {
                    boolean execution=switch(method.getName()) {
                        case "execute","executeQuery","executeUpdate","executeLargeUpdate","executeBatch","executeLargeBatch" -> true;
                        default -> false;
                    };
                    long start=execution?System.nanoTime():0;
                    try { return method.invoke(statement,args); }
                    catch(InvocationTargetException failure) {
                        if(execution) counters.errors.increment();
                        throw failure.getCause();
                    } finally {
                        if(execution) { counters.count.increment(); counters.nanos.add(System.nanoTime()-start); }
                    }
                });
        }
    }
}
