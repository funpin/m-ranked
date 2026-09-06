package org.mranked.operations.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import java.net.InetAddress;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class PinnedHttpsClientNetworkTest {
    @Test void realDnsTlsRedirectRebindingAndDeadline(@TempDir Path output) throws Exception {
        assertThat(HttpsNetworkRehearsal.run(output,false)).containsEntry("status","pass");
    }
    @Test void rejectsSpecialIpv4Ipv6AndMappedAddresses() throws Exception {
        for(String address:List.of("0.0.0.0","10.0.0.1","100.64.0.1","127.0.0.1","169.254.169.254","172.16.0.1",
                "192.168.1.1","192.0.2.1","198.18.0.1","198.51.100.1","203.0.113.1","224.0.0.1","255.255.255.255",
                "::","::1","::ffff:127.0.0.1","fc00::1","fe80::1","ff02::1","64:ff9b::a00:1","2001:db8::1","2002:7f00:1::","3fff::1"))
            assertThat(PublicAddressPolicy.allowed(InetAddress.getByName(address))).as(address).isFalse();
        for(String address:List.of("1.1.1.1","93.184.216.34","2606:4700:4700::1111"))
            assertThat(PublicAddressPolicy.allowed(InetAddress.getByName(address))).as(address).isTrue();
    }
}
