package io.doctrail;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
public class DocTrailApplication {
    public static void main(String[] args) { SpringApplication.run(DocTrailApplication.class, args); }
}
