package org.mranked.operations.infrastructure;

import com.sun.net.httpserver.HttpsConfigurator;
import com.sun.net.httpserver.HttpsServer;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import javax.net.ssl.*;
import tools.jackson.databind.json.JsonMapper;

/** Executable network evidence producer. All DNS and HTTPS fixtures bind only loopback.
 * The standalone run additionally requires Docker --network none before testing egress. */
public final class HttpsNetworkRehearsal {
    static final Set<String> HOSTS=Set.of("t.me","cdn.telegram.org","wrong.telegram.org");
    static final byte[] PNG=Base64.getDecoder().decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS1sAAAAASUVORK5CYII=");

    public static void main(String[] args) throws Exception {
        if(args.length!=2 || !args[1].equals("--require-egress-denied"))
            throw new IllegalArgumentException("output directory and --require-egress-denied required");
        Path output=Path.of(args[0]);Files.createDirectories(output);
        Map<String,Object> report=run(output,true);
        System.out.println(new JsonMapper().writeValueAsString(report));
    }

    static Map<String,Object> run(Path output,boolean requireEgress) throws Exception {
        var cases=new ArrayList<Map<String,Object>>();long started=System.nanoTime();
        try(var fixture=new Fixture(output)) {
            fixture.mode="allowed";
            try(var client=fixture.client(false)) {
                var response=client.fetch(URI.create("https://t.me/good"),2048,Duration.ofSeconds(3),HOSTS);
                check(response.statusCode()==200 && Arrays.equals(response.body(),PNG),"real PNG bytes");
                check(fixture.dnsQueries.get()==1,"one DNS resolution used by actual TCP connection");
                cases.add(Map.of("case","actual-dns-tls-pinned-connect","status","pass","dnsQueries",1,
                        "bytes",response.body().length,"sha256",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(response.body()))));
                int before=fixture.httpRequests.get();
                var redirect=client.fetch(URI.create("https://t.me/relative"),2048,Duration.ofSeconds(3),HOSTS);
                check(redirect.statusCode()==302 && fixture.httpRequests.get()==before+1,"redirect is never automatic");
                var followed=client.fetch(URI.create("https://t.me/relative").resolve(redirect.location()),2048,Duration.ofSeconds(3),HOSTS);
                check(Arrays.equals(followed.body(),PNG),"allowed manual relative redirect");
                cases.add(Map.of("case","manual-relative-redirect","status","pass","httpRequests",2));
                var evil=client.fetch(URI.create("https://t.me/evil"),2048,Duration.ofSeconds(3),HOSTS);
                int dnsBefore=fixture.dnsQueries.get();before=fixture.httpRequests.get();
                denied(() -> client.fetch(URI.create(evil.location()),2048,Duration.ofSeconds(3),HOSTS));
                check(fixture.dnsQueries.get()==dnsBefore && fixture.httpRequests.get()==before,"redirect denied before DNS/TCP");
                cases.add(Map.of("case","private-redirect-rejected-before-network","status","pass"));
                for(String target:List.of("http://t.me/good","https://user@t.me/good","https://t.me:444/good",
                        "https://t.me/good#part","https://t.me.evil.invalid/good","https://127.0.0.1/good"))
                    denied(() -> client.fetch(URI.create(target),2048,Duration.ofSeconds(1),HOSTS));
                check(fixture.dnsQueries.get()==dnsBefore,"invalid URI corpus never resolves DNS");
                cases.add(Map.of("case","scheme-host-port-userinfo-fragment-corpus","status","pass","cases",6));
                before=fixture.httpRequests.get();
                denied(() -> client.fetch(URI.create("https://wrong.telegram.org/good"),2048,Duration.ofSeconds(3),HOSTS));
                check(fixture.httpRequests.get()==before,"wrong TLS peer name never reaches HTTP handler");
                cases.add(Map.of("case","tls-peer-hostname-mismatch","status","pass"));
                var large=client.fetch(URI.create("https://t.me/large"),1024,Duration.ofSeconds(3),HOSTS);
                check(large.body().length==1025,"oversized body retained only max+1 bytes");
                cases.add(Map.of("case","stream-byte-cap-and-cancel","status","pass","retainedBytes",1025));
                long timeoutStarted=System.nanoTime();
                denied(() -> client.fetch(URI.create("https://t.me/slow"),2048,Duration.ofMillis(150),HOSTS));
                long elapsed=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-timeoutStarted);
                check(elapsed<2000,"total slow response deadline");
                cases.add(Map.of("case","slow-body-total-deadline","status","pass","durationMs",elapsed));
                denied(() -> client.fetch(URI.create("https://t.me/headers"),2048,Duration.ofSeconds(2),HOSTS));
                cases.add(Map.of("case","header-count-cap","status","pass"));
            }
            fixture.mode="allowed";
            int before=fixture.httpRequests.get();
            try(var productionPolicy=fixture.client(true)) {
                denied(() -> productionPolicy.fetch(URI.create("https://t.me/good"),2048,Duration.ofSeconds(2),HOSTS));
            }
            check(fixture.httpRequests.get()==before,"production policy refuses loopback DNS answer before TCP");
            cases.add(Map.of("case","production-private-ip-policy","status","pass","httpRequests",0));
            fixture.mode="mixed";
            try(var client=fixture.client(false)) {
                denied(() -> client.fetch(URI.create("https://t.me/good"),2048,Duration.ofSeconds(2),HOSTS));
            }
            check(fixture.httpRequests.get()==before,"mixed DNS answer set is rejected in full");
            cases.add(Map.of("case","mixed-public-private-answer-set","status","pass","httpRequests",0));
            fixture.mode="rebind";fixture.rebindingQueries.set(0);
            try(var client=fixture.client(false)) {
                var redirect=client.fetch(URI.create("https://t.me/rebind"),2048,Duration.ofSeconds(3),HOSTS);
                check(redirect.statusCode()==302,"first DNS answer made a real HTTPS redirect");
                denied(() -> client.fetch(URI.create(redirect.location()),2048,Duration.ofSeconds(3),HOSTS));
            }
            check(fixture.rebindingQueries.get()==2 && fixture.httpRequests.get()==before+1,
                    "rebinding second DNS answer cannot reach HTTP");
            cases.add(Map.of("case","dns-rebinding-between-redirect-hops","status","pass","dnsQueries",2,"httpRequests",1));
        }
        if(requireEgress) {
            var interfaces=Collections.list(NetworkInterface.getNetworkInterfaces());
            check(interfaces.stream().noneMatch(network -> {
                try {return network.isUp()&&!network.isLoopback();}catch(SocketException failure){throw new RuntimeException(failure);}
            }),"rehearsal must run with no non-loopback network interface");
            try(var socket=new Socket()) {
                denied(() -> {socket.connect(new InetSocketAddress(InetAddress.getByAddress(new byte[]{(byte)198,51,100,1}),443),500);return null;});
            }
            cases.add(Map.of("case","kernel-network-namespace-egress-denied","status","pass",
                    "policy","Docker --network none; only loopback exists","destination","RFC5737 TEST-NET-2:443"));
        }
        var report=new LinkedHashMap<String,Object>();report.put("reportVersion",1);report.put("status","pass");
        report.put("environment","isolated-local-dns-tls");report.put("productionAcceptance",false);
        report.put("externalEgressPolicyExercised",requireEgress);report.put("cases",cases);
        report.put("durationSeconds",(System.nanoTime()-started)/1e9);
        report.put("limitations",List.of("Test-only constructor permits exactly 127.0.0.1 for the positive TLS fixture; default production policy is separately proven to reject it",
                "No request to live Telegram/CDN or production egress configuration; live provider acceptance and approved network policy remain external gates"));
        String encoded=new JsonMapper().writerWithDefaultPrettyPrinter().writeValueAsString(report)+"\n";
        Files.writeString(output.resolve("https-network.json"),encoded);
        Files.writeString(output.resolve("https-network.json.sha256"),HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(encoded.getBytes(StandardCharsets.UTF_8)))+"  https-network.json\n");
        return report;
    }

    private static void check(boolean condition,String label) {if(!condition)throw new AssertionError(label);}
    @FunctionalInterface interface Checked {Object call() throws Exception;}
    private static void denied(Checked operation) throws Exception {
        try {operation.call();}catch(IOException expected){return;}
        throw new AssertionError("prohibited network operation unexpectedly succeeded");
    }

    static final class Fixture implements AutoCloseable {
        final HttpsServer https;
        final DatagramSocket dnsSocket=new DatagramSocket(new InetSocketAddress("127.0.0.1",0));
        final ExecutorService workers=Executors.newCachedThreadPool();
        final AtomicInteger dnsQueries=new AtomicInteger(),httpRequests=new AtomicInteger(),rebindingQueries=new AtomicInteger();
        final SSLContext ssl;
        volatile String mode="allowed";
        volatile boolean closed;
        Fixture(Path output) throws Exception {
            Files.createDirectories(output);Path store=output.resolve("fixture.p12");
            String password=UUID.randomUUID().toString();
            Process keytool=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","keytool").toString(),
                    "-genkeypair","-alias","fixture","-keyalg","RSA","-keysize","2048","-validity","2",
                    "-dname","CN=t.me","-ext","SAN=dns:t.me,dns:cdn.telegram.org","-storetype","PKCS12",
                    "-keystore",store.toString(),"-storepass",password,"-keypass",password,"-noprompt")
                    .redirectErrorStream(true).redirectOutput(output.resolve("keytool.log").toFile()).start();
            check(keytool.waitFor(30,TimeUnit.SECONDS)&&keytool.exitValue()==0,"fixture TLS identity generation");
            var keys=KeyStore.getInstance("PKCS12");try(var input=Files.newInputStream(store)){keys.load(input,password.toCharArray());}
            var keyManagers=KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());keyManagers.init(keys,password.toCharArray());
            var trusts=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());trusts.init(keys);
            ssl=SSLContext.getInstance("TLS");ssl.init(keyManagers.getKeyManagers(),trusts.getTrustManagers(),null);
            Files.delete(store); // ephemeral private key never becomes published evidence
            https=HttpsServer.create(new InetSocketAddress("127.0.0.1",0),0);
            https.setHttpsConfigurator(new HttpsConfigurator(ssl));https.setExecutor(workers);
            https.createContext("/",exchange -> {
                httpRequests.incrementAndGet();String path=exchange.getRequestURI().getPath();
                try {
                    exchange.getResponseHeaders().set("Content-Type","image/png");
                    if(Set.of("/relative","/evil","/rebind").contains(path)) {
                        exchange.getResponseHeaders().set("Location",path.equals("/relative")?"/good":path.equals("/evil")?"https://127.0.0.1/private":"https://t.me/good");
                        exchange.sendResponseHeaders(302,-1);
                    } else if(path.equals("/large")) {
                        exchange.sendResponseHeaders(200,8*1024*1024);
                        byte[] block=new byte[8192];for(int n=0;n<1024;n++)exchange.getResponseBody().write(block);
                    } else if(path.equals("/slow")) {
                        exchange.sendResponseHeaders(200,0);
                        for(int n=0;n<100;n++){exchange.getResponseBody().write(1);exchange.getResponseBody().flush();Thread.sleep(50);}
                    } else {
                        if(path.equals("/headers"))for(int n=0;n<110;n++)exchange.getResponseHeaders().add("X-Header-"+n,"value");
                        exchange.sendResponseHeaders(200,PNG.length);exchange.getResponseBody().write(PNG);
                    }
                }catch(IOException disconnected) {}catch(InterruptedException interrupted){Thread.currentThread().interrupt();}
                finally{exchange.close();}
            });https.start();workers.submit(this::dnsServer);
        }

        PinnedHttpsClient client(boolean production) {
            return new PinnedHttpsClient(this::lookup,production?PublicAddressPolicy::allowed:
                    address -> address.getHostAddress().equals("127.0.0.1")||PublicAddressPolicy.allowed(address),ssl,https.getAddress().getPort());
        }

        void dnsServer() {
            while(!closed) try {
                var packet=new DatagramPacket(new byte[2048],2048);dnsSocket.receive(packet);
                byte[] request=Arrays.copyOf(packet.getData(),packet.getLength());dnsQueries.incrementAndGet();
                List<byte[]> addresses=mode.equals("mixed")?List.of(new byte[]{127,0,0,1},new byte[]{10,0,0,1}):
                        List.of(new byte[]{127,0,0,(byte)(mode.equals("rebind")&&rebindingQueries.incrementAndGet()>1?2:1)});
                var output=new ByteArrayOutputStream();var data=new DataOutputStream(output);
                data.writeShort(((request[0]&255)<<8)|(request[1]&255));data.writeShort(0x8180);data.writeShort(1);
                data.writeShort(addresses.size());data.writeShort(0);data.writeShort(0);data.write(request,12,request.length-12);
                for(byte[] address:addresses){data.writeShort(0xc00c);data.writeShort(1);data.writeShort(1);data.writeInt(0);data.writeShort(4);data.write(address);}
                byte[] answer=output.toByteArray();dnsSocket.send(new DatagramPacket(answer,answer.length,packet.getSocketAddress()));
            }catch(IOException failure){if(!closed)throw new UncheckedIOException(failure);}
        }

        InetAddress[] lookup(String host) throws UnknownHostException {
            try(var socket=new DatagramSocket(new InetSocketAddress("127.0.0.1",0))) {
                socket.setSoTimeout(1000);var output=new ByteArrayOutputStream();var data=new DataOutputStream(output);
                data.writeShort(42);data.writeShort(0x100);data.writeShort(1);data.writeShort(0);data.writeShort(0);data.writeShort(0);
                for(String label:host.split("\\.")){byte[] bytes=label.getBytes(StandardCharsets.US_ASCII);data.writeByte(bytes.length);data.write(bytes);}
                data.writeByte(0);data.writeShort(1);data.writeShort(1);byte[] question=output.toByteArray();
                socket.send(new DatagramPacket(question,question.length,dnsSocket.getLocalSocketAddress()));
                var packet=new DatagramPacket(new byte[2048],2048);socket.receive(packet);
                var input=new DataInputStream(new ByteArrayInputStream(packet.getData(),0,packet.getLength()));
                check(input.readUnsignedShort()==42,"DNS transaction ID");input.readUnsignedShort();input.readUnsignedShort();int count=input.readUnsignedShort();
                input.readUnsignedShort();input.readUnsignedShort();input.skipNBytes(question.length-12);
                var addresses=new InetAddress[count];
                for(int index=0;index<count;index++){input.readUnsignedShort();check(input.readUnsignedShort()==1,"DNS A record");input.readUnsignedShort();input.readInt();check(input.readUnsignedShort()==4,"DNS IPv4 width");addresses[index]=InetAddress.getByAddress(input.readNBytes(4));}
                return addresses;
            }catch(IOException failure){throw new UnknownHostException("local DNS fixture failed");}
        }

        public void close() throws InterruptedException {
            closed=true;dnsSocket.close();https.stop(0);workers.shutdownNow();check(workers.awaitTermination(5,TimeUnit.SECONDS),"fixture workers stopped");
        }
    }
}
