package org.mranked.legacyexport.application;

import java.io.OutputStream;
import java.time.Instant;
import java.util.Arrays;
import org.mranked.cache.domain.DatasetRevision;

public class LegacyCsvHeapProbe {
    public static void main(String[] args) throws Exception {
        long start=System.nanoTime(); long[] rows={0},bytes={0};
        var cells=Arrays.asList("Юникод".repeat(20),"101","2026-08-01T12:00:00+00:00","1","0",null,"0","-2","1.0");
        var service=new LegacyCsvService((format,revision,consumer)->{
            for(int i=0;i<600_000;i++) {consumer.accept(cells);rows[0]++;}
        },()->new DatasetRevision(29,Instant.EPOCH));
        try {
            service.write(new LegacyCsvFormat("posts","telegram"),29,new OutputStream(){
                @Override public void write(int value){bytes[0]++;}
                @Override public void write(byte[] value,int offset,int length){bytes[0]+=length;}
            });
        } finally {service.close();}
        if(rows[0]!=600_000||bytes[0]<100_000_000)throw new AssertionError("Large CSV was truncated");
        System.out.println("{\"status\":\"pass\",\"rows\":"+rows[0]+",\"bytes\":"+bytes[0]
            +",\"heapMaxBytes\":"+Runtime.getRuntime().maxMemory()+",\"durationSeconds\":"+(System.nanoTime()-start)/1e9+"}");
    }
}
