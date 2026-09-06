package org.mranked.operations.infrastructure;

import java.net.InetAddress;

/** Conservative unicast policy. Reject every answer set containing a special/private address. */
final class PublicAddressPolicy {
    private PublicAddressPolicy() {}

    static boolean allowed(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) return false;
        byte[] bytes = address.getAddress();
        int a = bytes[0] & 255, b = bytes[1] & 255;
        if (bytes.length == 4) {
            int c = bytes[2] & 255;
            return !(a == 0 || a == 10 || a == 127 || a >= 224
                    || a == 100 && b >= 64 && b <= 127
                    || a == 169 && b == 254 || a == 172 && b >= 16 && b <= 31
                    || a == 192 && (b == 168 || b == 0 && (c == 0 || c == 2) || b == 88 && c == 99)
                    || a == 198 && (b == 18 || b == 19 || b == 51 && c == 100)
                    || a == 203 && b == 0 && c == 113);
        }
        if (bytes.length != 16 || (a & 0xe0) != 0x20) return false; // only global 2000::/3
        int c = bytes[2] & 255, d = bytes[3] & 255;
        return !(a == 0x20 && b == 1 && (c <= 1 || c == 0x0d && d == 0xb8)
                || a == 0x20 && b == 2 || a == 0x3f && b == 0xff && (c & 0xf0) == 0);
    }
}
