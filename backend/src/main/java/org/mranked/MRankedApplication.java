package org.mranked;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.security.autoconfigure.UserDetailsServiceAutoConfiguration;

@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
public class MRankedApplication {
    public static void main(String[] args) {
        SpringApplication.run(MRankedApplication.class, args);
    }
}
