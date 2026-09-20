/** Contract-shaped test double. It proves browser behavior, not PostgreSQL or legacy data parity. */
import { createServer } from "node:http";
import type { components } from "../../contracts/openapi/m-ranked-v1-client";

type Schema = components["schemas"];
// Недельный ряд: полный, с днём без публикаций посередине — так проверяется и
// провал, и то, что ряд не рвётся.
function weekly() {
  const counts = [3, 5, 0, 2, 4, 1, 2];
  const reactions = [5, 7, null, 4, 9, 3, 6];
  const views = [50, 80, null, 40, 95, 30, 60];
  // Суммы намеренно не повторяют медианы: по ним видно, что переключатель у
  // графика рисует другой ряд, а не тот же самый в другом масштабе.
  const totalReactions = [60, 140, 12, 44, 180, 18, 72];
  const totalViews = [900, 2400, 180, 640, 3100, 300, 1200];
  return counts.map((published, index) => ({
    day: new Date(Date.UTC(2026, 6, 1 + index)).toISOString().slice(0, 10),
    publishedCount: published,
    medianReactions: reactions[index],
    medianViews: views[index],
    totalReactions: totalReactions[index],
    totalViews: totalViews[index],
  }));
}

const asOf = "2026-08-01T12:00:00Z";
const revision = 17;
const uuid = (kind: number, id: number) => `${String(kind).padStart(8,"0")}-0000-4000-8000-${String(id).padStart(12,"0")}`;

const performanceFixture = process.env.REDESIGN_PERFORMANCE_FIXTURE === "true";
const names = performanceFixture ? Array.from({ length: 207 }, (_, index) => `Университет ${index + 1}`) : ["Альфа Университет", "Бета Институт"];
const selectionIds = names.map((_, index) => index + 1);
const aggregate = (value: number | null, size = 2): Schema["AggregateMetric"] => ({ value, asOf, datasetRevision: revision, sampleSize: size, coverage: size / 2, quality: value === null ? "unsupported" : "exact" });
const metric: Schema["OverviewMetric"] = { total: 12, median: 6, previousTotal: 10, previousMedian: 5, totalTrend: 2, medianTrend: 1,
  totalMetadata: aggregate(12), medianMetadata: aggregate(6), previousTotalMetadata: aggregate(10), previousMedianMetadata: aggregate(5) };
function item(id: number, platform: Schema["PlatformValue"]): Schema["OverviewRow"] {
  const accountKind = platform === "telegram" ? 1 : platform === "vk" ? 2 : platform === "max" ? 3 : 4;
  const accounts:Schema["OverviewAccount"][] = platform === "all" ? [] : [{
    accountId:uuid(accountKind,id),legacyId:id,legacyRoute:platform === "telegram" ? `/channels/${id}` : `/platform-accounts/${id}`,
    platform,canonicalExternalId:`external-${id}`,username:`fixture_${id}`,title:`Аккаунт ${id}`,
    url:`https://example.test/${platform}/${id}`,accessMode:"public",enabled:true,subscriberCount:100,
    subscriberDisplay:"100",subscriberObservedAt:asOf,latestPollStartedAt:asOf,latestPollCompletedAt:asOf,
    latestPollStatus:"success",latestErrorCode:null,
  }];
  return { entityId: platform === "telegram" ? uuid(1,id) : uuid(9,id), entityType: platform === "telegram" ? "channels" : "institutions", legacyId: id, legacyRoute: `/institutions/${id}`, institutionId: `institution-${id}`, institutionLegacyId: id,
    canonicalName: names[id - 1]!, shortName: null, platform, period: "1d", accounts, accountCount: 1, enabledAccountCount: 1, connectedPlatformCount: 1,
    subscriberCount: 100, lastCheckedAt: asOf, lastErrorCode: null, statusCode: "connected", ratingRank: id, ratingScore: 90,
    ratingPeriod: "2026-Q2", ratingFetchedAt: asOf, totalPublicationCount: 2, activityPublicationCount: 2, newPublicationCount: 0,
    views: metric, reactions: metric, comments: { ...metric, total: 0, totalMetadata: aggregate(0, 1) }, shares: { ...metric, total: null, totalMetadata: aggregate(null, 0) }, asOf };
}
function statisticsEntity(id: number, platform: "telegram" | "vk" | "max" | "rutube"): Schema["StatisticsEntity"] {
  return { rank:id, legacyRoute:`/institutions/${id}`, accountId:uuid(platform === "telegram" ? 1 : platform === "vk" ? 2 : platform === "max" ? 3 : 4,id), institutionId:uuid(9,id), institutionLegacyId:id,
    canonicalName:`Университет ${String(id).padStart(3,"0")}`,shortName:null,platform,publicationCount:20,
    interactionSampleSize:20,viewSampleSize:20,ervSampleSize:20,medianInteractions:id,
    interactions:id*20,views:id*200,erv:id===2?null:10 };
}
function statisticsPublication(id:number,platform:"telegram"|"vk"|"max"|"rutube"):Schema["StatisticsPublication"] {
  const type=platform==="telegram"?"posts":"platform_posts";
  return {rank:id,publicationId:uuid(7,id),platform,legacyId:id,legacyType:type,legacyRoute:`/${type}/${id}`,
    institutionId:uuid(9,id),institutionLegacyId:id,institutionCanonicalName:`Полное название университета ${String(id).padStart(3,"0")}`,
    institutionShortName:`Вуз ${String(id).padStart(3,"0")}`,accountId:uuid(2,id),accountLegacyId:id,accountUsername:`fixture_${id}`,
    accountTitle:`Аккаунт ${id}`,accountExternalId:`external-${id}`,externalId:String(id),
    publicUrl:`https://example.test/${platform}/${id}`,publishedAt:"2026-07-01T00:00:00Z",deletedAt:null,
    joint:false,additionalAuthorCount:0,repost:false,views:id===2?0:id*100,reactions:id,comments:platform==="max"?null:0,
    shares:platform==="vk"?0:null,interactions:id,erv:id===2?null:1,interactionsAvailable:true,ervEligible:id!==2};
}
const counter = (value:number|null):Schema["CounterMetric"] => ({value,observedAt:asOf,quality:value === null ? "unsupported" : "exact"});
function account(id:number,legacyType:"channels"|"platform_accounts"="channels"):Schema["Account"] {
  const platform=legacyType === "channels" ? "telegram" : id === 3 ? "max" : id === 4 ? "rutube" : "vk";
  return {accountId:uuid(platform === "telegram" ? 1 : platform === "vk" ? 2 : platform === "max" ? 3 : 4,id),legacyId:id,legacyType,channelLegacyId:platform === "telegram" ? id : null,platformAccountLegacyId:id,institutionId:`institution-${id}`,institutionLegacyId:id,institutionName:names[0]!,institutionShortName:null,platform,canonicalExternalId:`external-${id}`,username:`fixture_${id}`,title:`Канал ${id}`,url:`https://example.test/account/${id}`,accessMode:"public",enabled:true,publicationCount:2,latestObservedAt:asOf,datasetRevision:revision,asOf,
    stats:{retentionDays:70,postCount:2,monitored:1,medianReactions:aggregate(5),medianViews:aggregate(50),medianComments:aggregate(0),ratingRank:2,ratingPeriod:"2026-Q2",subscriberCount:100,lastError:null,lastCheckedAt:asOf,dailySeries:weekly(),
      previous:{postCount:1,monitored:1,medianReactions:4,medianViews:44,medianComments:0,
                ratingRank:5,ratingPeriod:"2026-Q1"}}};
}
function publication(id:number,type:"posts"|"platform_posts"="posts"):Schema["Publication"] {
  const platform=type === "posts" ? "telegram" : id === 21 ? "vk" : id === 41 ? "rutube" : "max";
  return {publicationId:uuid(type === "posts" ? 5 : 6,id),legacyId:id,legacyType:type,institutionId:"institution-1",platform,publishedAt:"2026-07-01T00:00:00Z",publicationType:"album",deletedAt:id === 1 ? asOf : null,views:counter(50),reactions:counter(5),comments:counter(0),shares:counter(null),quality:"exact",intervalUncertain:false,synthetic:false,historyCompleteness:"complete",datasetRevision:revision,asOf,accountLegacyId:platform === "telegram" || platform === "vk" ? 1 : platform === "rutube" ? 4 : 3,accountLegacyType:type === "posts" ? "channels" : "platform_accounts",accountName:names[0]!,accountUsername:"fixture_1",externalId:String(id+100),displayExternalId:String(id+100),repost:false,joint:false,additionalAuthorCount:0,ambiguousAlbumReactions:false,publicUrl:`https://example.test/post/${id}`};
}
function postItem(id:number,type:"posts"|"platform_posts",day?:string|null):Schema["PublicationListItem"] {
  const p=publication(id,type);
  return {publicationId:p.publicationId,legacyId:id,legacyType:type,legacyRoute:`/${type === "posts" ? "posts" : "platform-posts"}/${id}`,externalId:p.externalId,publishedAt:id===2?"2026-07-02T00:00:00Z":p.publishedAt,publicUrl:p.publicUrl,publicationType:p.publicationType,deletedAt:p.deletedAt,historyCompleteness:"complete",views:p.views,reactions:p.reactions,comments:p.comments,shares:p.shares,title:null,archivedText:null,dailyGrowth:day?{day,reactions:id===1?5:3,views:id===1?50:40}:null,displayExternalId:p.displayExternalId,repost:p.repost,joint:p.joint,additionalAuthorCount:p.additionalAuthorCount,ambiguousAlbumReactions:p.ambiguousAlbumReactions};
}
const historyStart=Date.parse("2026-07-01T00:00:00Z");
const historyAt=(index:number)=>new Date(historyStart+index*3600000).toISOString();
const historyRows:Schema["HistorySnapshot"][] = Array.from({length:160},(_,index) => ({snapshotId:String(index+1),observedAt:historyAt(index),ageHours:index,views:counter(index*10),reactions:counter(index === 159 ? 155 : index),comments:counter(0),shares:counter(null),deltaViews:index ? 10 : null,deltaReactions:index ? index === 159 ? -3 : 1 : null,deltaComments:index ? 0 : null,deltaShares:null,reactionsBreakdown:{"👍":index,"custom:123456":1},reactionsBreakdownEntries:[{reaction:"👍",count:index},{reaction:"custom:123456",count:1}],deltaReactionsBreakdown:index?{"👍":1}:null,deltaReactionsBreakdownEntries:index?[{reaction:"👍",count:1}]:null,synthetic:index === 0,intervalUncertain:index === 40,quality:"exact",rawEvidence:{fingerprint:`fixture-${index}`},collectorInterval:index?{from:historyAt(index-1),to:historyAt(index),successfulPolls:12,failedPolls:0}:null}));
function anomaly(id:number,type:"posts"|"platform_posts"="posts"):Schema["PublicationAnomalyAnalysis"] {
  const base:Schema["PublicationAnomalyAnalysis"]={publicationId:uuid(type === "posts" ? 5 : 6,id),datasetRevision:revision,analysisRevision:3,sourceDatasetRevision:16,
    analyzedAt:asOf,status:"ready",sourceRevisionAt:asOf,suspicionScore:0.82,overallSeverity:"high",
    manualAssessmentPresent:false,affectedMetrics:["views"],activeFindingCount:1,nextCursor:null,
    methodologyVersion:"anomaly-dynamics-v1",disclaimer:"Сигнал сам по себе не доказывает искусственное происхождение активности или действия университета.",
    findings:[{id:uuid(8,id),origin:"automatic",metric:"views",detectorId:"delayed_spike_after_plateau",detectorVersion:"1.0.0",
      suspicionScore:0.82,severity:"high",explanationCode:"large_rate_jump_after_plateau",
      suspiciousStartAt:historyRows[39]!.observedAt,suspiciousEndAt:historyRows[40]!.observedAt,
      startSnapshotId:"40",endSnapshotId:"41",evidence:{delta:500,rateRatio:12},qualityCodes:[],
      alternativeExplanationCodes:["external_referral"],reviewState:"unreviewed"}]};
  if(type!=="posts") {
    // Provider capability differences: VK exposes reposts, Rutube and MAX do not
    // get an unsupported metric invented for them.
    const metric:Schema["AnomalyFinding"]["metric"]=id===21 ? "shares" : id===41 ? "views" : "comments";
    return {...base,affectedMetrics:[metric],findings:base.findings.map(item=>({...item,metric}))};
  }
  if(id===2) return {...base,status:"pending",sourceDatasetRevision:null,analyzedAt:null,sourceRevisionAt:null,suspicionScore:null,overallSeverity:null,affectedMetrics:[],activeFindingCount:0,findings:[]};
  if(id===3) return {...base,status:"partial",suspicionScore:null,overallSeverity:null,affectedMetrics:[],activeFindingCount:0,findings:[]};
  if(id===4) return {...base,status:"stale",suspicionScore:0.52,overallSeverity:"medium",findings:base.findings.map(item=>({...item,suspicionScore:0.52,severity:"medium",reviewState:"explained"}))};
  if(id===5) return {...base,status:"failed",sourceDatasetRevision:null,analyzedAt:null,sourceRevisionAt:null,suspicionScore:null,overallSeverity:null,affectedMetrics:[],activeFindingCount:0,findings:[]};
  if(id===6) return {...base,suspicionScore:0,overallSeverity:"medium",manualAssessmentPresent:true,affectedMetrics:["comments"],findings:[{...base.findings[0]!,id:uuid(8,6),origin:"manual",metric:"comments",detectorId:null,detectorVersion:null,suspicionScore:null,severity:"medium",explanationCode:"operator_context",reviewState:"unresolved"}]};
  return base;
}
const server = createServer(async (request, response) => {
  const url = new URL(request.url!, "http://127.0.0.1");
  const canonical = /^\/api\/v1\/(accounts|publications)\/([0-9a-f-]{36})(\/(publications|history|anomaly-analysis))?$/.exec(url.pathname);
  if (canonical) {
    const id = Number(canonical[2]!.slice(-12));
    const kind = Number(canonical[2]!.slice(0,8));
    const validKind = canonical[1] === "accounts" ? kind >= 1 && kind <= 4 : kind === 5 || kind === 6;
    if (!validKind || id < 1 || id > 1000) { response.writeHead(404,{"Content-Type":"application/json"});response.end(JSON.stringify({status:404}));return; }
    url.pathname = `/api/v1/${canonical[1]}/${id}${canonical[3] ?? ""}`;
    url.searchParams.set("legacyType", canonical[1] === "accounts" ? kind === 1 ? "channels" : "platform_accounts" : kind === 5 ? "posts" : "platform_posts");
  }
  const platform = (url.searchParams.get("platform") ?? "telegram") as Schema["PlatformValue"];
  function json(data: unknown, status = 200) { response.writeHead(status, { "Content-Type": "application/json", ETag: `"fixture-${revision}-${url.search}"`, "Cache-Control": "no-store" }); response.end(JSON.stringify(data)); }
  if (url.pathname === "/api/v1/revision") return json({ datasetRevision: revision, asOf, representationVersion: "a".repeat(64) });
  // Сессия вместо Basic: роль носит непрозрачная кука, как на проде.
  const sessionRole=/(?:^|;\s*)__Host-mranked-admin=fixture-(viewer|editor|admin)(?:;|$)/
    .exec(request.headers.cookie??"")?.[1]??null;
  if(url.pathname==="/api/v1/admin/session") {
    if(request.method==="DELETE") {
      response.setHeader("Set-Cookie","__Host-mranked-admin=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict");
      return json({outcome:"closed"});
    }
    if(request.method!=="POST") return json({detail:"Method not allowed"},405);
    const chunks:Buffer[]=[];
    for await (const chunk of request) { chunks.push(chunk as Buffer); if(Buffer.concat(chunks).length>4096) return json({detail:"Too large"},413); }
    const body=JSON.parse(Buffer.concat(chunks).toString("utf8")||"{}") as {username?:string;password?:string;otp?:string};
    const role=String(body.username??"");
    if(!["viewer","editor","admin"].includes(role)||body.password!=="fixture-password"||!/^\d{6}$/.test(String(body.otp??"")))
      return json({detail:"Неверные учётные данные"},401);
    response.setHeader("Set-Cookie",`__Host-mranked-admin=fixture-${role}; Path=/; Secure; HttpOnly; SameSite=Strict`);
    return json({headerName:"X-XSRF-TOKEN",parameterName:"_csrf",token:"fixture-csrf-token",expiresAt:asOf,canEdit:role!=="viewer",canDelete:role==="admin"},201);
  }
  if(url.pathname.startsWith("/api/v1/admin/catalog/")) {
    const role=sessionRole;
    if(!role) return json({detail:"Требуется вход администратора"},401);
    if(url.pathname.endsWith("/session")) return json({headerName:"X-XSRF-TOKEN",token:"fixture-csrf-token",expiresAt:asOf,canEdit:role!=="viewer",canDelete:role==="admin"});
    const uuid=(index:number)=>`00000000-0000-4000-8000-${String(index).padStart(12,"0")}`;
    const ratings=Object.fromEntries(["all","telegram","vk","max","rutube"].map((platform)=>[platform,{rank:platform==="all"?2:null,score:platform==="all"?50:null}]));
    if(url.pathname.endsWith("/institutions")) return json({items:[1,2].map((id)=>({id:uuid(id),legacyId:id,name:names[id-1],shortName:id===1?"Альфа":"Бета",rowVersion:4,officialRatings:ratings,nextAccountAfter:null,accounts:["telegram","vk","max","rutube"].map((platform,index)=>({id:uuid(id*10+index),legacyId:id*10+index,channelId:platform==="telegram"?id:null,institutionId:uuid(id),platform,externalKey:`${platform}_${id}`,username:`${platform}_${id}`,title:`${platform} ${id}`,url:`https://example.test/${platform}/${id}`,accessMode:"public_api",legacyAccessMode:"public",lastErrorCode:null,enabled:true,rowVersion:7,nativeId:platform==="max"?`-123${id}`:null,subscribers:100}))})),nextAfter:null});
    if(url.pathname.endsWith("/status")) return json({channelCount:2,platformCount:8,institutionCount:2,mRating:{period:"2026-Q2",updatedAt:asOf,error:null},integrations:["telegram","vk","max","rutube"].map((platform)=>({platform,status:platform==="vk"?"missing":"configured",detail:`Источник ${platform}`})),storage:{diskTotalBytes:100*1024**3,diskFreeBytes:40*1024**3,projectBytes:4*1024**3,databaseBytes:3*1024**3}});
    return json({detail:"Unknown fixture catalog route"},404);
  }
  const accountId=/^\/api\/v1\/accounts\/(\d+)$/.exec(url.pathname);
  if(accountId) return Number(accountId[1]) > 1000 ? json({title:"Not Found",status:404},404) : json(account(Number(accountId[1]),url.searchParams.get("legacyType") as "channels"|"platform_accounts"));
  const pubId=/^\/api\/v1\/publications\/(\d+)$/.exec(url.pathname);
  if(pubId) return json(publication(Number(pubId[1]),url.searchParams.get("legacyType") as "posts"|"platform_posts"));
  if(/^\/api\/v1\/accounts\/\d+\/publications$/.test(url.pathname)) {const day=url.searchParams.get("day");return json({items:[postItem(1,url.searchParams.get("legacyType") === "channels" ? "posts" : "platform_posts",day),postItem(2,"posts",day)],nextCursor:null,datasetRevision:revision,asOf} satisfies Schema["AccountPublicationPage"]);}
  const historyId=/^\/api\/v1\/publications\/(\d+)\/history$/.exec(url.pathname);
  if(historyId) {
    const p=publication(Number(historyId[1]),url.searchParams.get("legacyType") as "posts"|"platform_posts");
    const sourceRows=p.legacyId===99 ? Array.from({length:1205},(_,index)=>({...historyRows[index%historyRows.length]!,
      snapshotId:String(index+1),observedAt:new Date(Date.parse("2026-07-01T00:00:00Z")+index*3600000).toISOString(),ageHours:index,
      reactions:counter(index),views:counter(index*10),deltaReactions:index?1:null,deltaViews:index?10:null,synthetic:index===0,
    })) : p.legacyId===7
      // Publication 7 has no saved metric changes for sixty hours, while the
      // independent account-cycle journal remains complete.
      ? historyRows.map(row=>({...row,ageHours:row.ageHours+168})).filter((_row,index)=>index<40||index>=100)
      : historyRows;
    const limit=Math.max(1,Number(url.searchParams.get("limit") ?? 200));
    const visibleRows=sourceRows.slice(-limit);
    const visibleOffset=sourceRows.length-visibleRows.length;
    const trueGap=p.legacyId===8 ? {from:historyAt(100+5/60),to:historyAt(100+55/60),missingSeconds:3000} : null;
    const denseGaps=p.legacyId===98 ? Array.from({length:800},(_,index)=>{
      const from=historyStart+index*(159*3600000/800);
      const to=from+5*60_000;
      return {from:new Date(from).toISOString(),to:new Date(to).toISOString(),missingSeconds:300};
    }) : [];
    const items=visibleRows.map((row,index)=>{
      const previous=sourceRows[visibleOffset+index-1];
      const seconds=previous ? (Date.parse(row.observedAt)-Date.parse(previous.observedAt))/1000 : 0;
      const overlapsGap=trueGap && previous && Date.parse(trueGap.to)>Date.parse(previous.observedAt) && Date.parse(trueGap.from)<Date.parse(row.observedAt);
      return {...row,
      comments:p.platform === "rutube" ? counter(null) : row.comments,
      deltaComments:p.platform === "rutube" ? null : row.deltaComments,
      shares:p.platform === "vk" ? counter(index*2) : row.shares,
      deltaShares:p.platform === "vk" ? index ? 2 : null : row.deltaShares,
      reactionsBreakdown:p.platform === "vk" || p.platform === "rutube" ? {} : row.reactionsBreakdown,
      reactionsBreakdownEntries:p.platform === "vk" || p.platform === "rutube" ? [] : row.reactionsBreakdownEntries,
      deltaReactionsBreakdown:p.platform === "vk" || p.platform === "rutube" ? null : row.deltaReactionsBreakdown,
      deltaReactionsBreakdownEntries:p.platform === "vk" || p.platform === "rutube" ? null : row.deltaReactionsBreakdownEntries,
      collectorInterval:previous?{from:previous.observedAt,to:row.observedAt,successfulPolls:Math.max(0,Math.round(seconds/300)-(overlapsGap?10:0)),failedPolls:0}:null,
    }});
    const coverageFrom=visibleRows[0]?.observedAt??p.publishedAt;
    const coverageThrough=visibleRows.at(-1)?.observedAt??asOf;
    const collectorCoverage:Schema["CollectorCoverage"]={availableFrom:sourceRows[0]?.observedAt??null,through:coverageThrough,expectedIntervalSeconds:p.platform==="rutube"?3600:300,successfulPolls:Math.max(0,Math.round((Date.parse(coverageThrough)-Date.parse(coverageFrom))/(p.platform==="rutube"?3600000:300000))-(trueGap?10:0)),failedPolls:0,gaps:denseGaps.length?denseGaps:trueGap&&Date.parse(trueGap.to)>Date.parse(coverageFrom)?[trueGap]:[]};
    return json({publication:p,items,collectorCoverage,nextCursor:sourceRows.length>limit?"older":null,previousLegacyId:null,nextLegacyId:2,archivedText:"Сохранённый текст <script>без исполнения</script>",datasetRevision:revision,asOf} satisfies Schema["PublicationHistory"]);
  }
  const anomalyId=/^\/api\/v1\/publications\/(\d+)\/anomaly-analysis$/.exec(url.pathname);
  if(anomalyId) return json(anomaly(Number(anomalyId[1]),url.searchParams.get("legacyType") as "posts"|"platform_posts"));
  const institutionId=/^\/api\/v1\/institutions\/(\d+)$/.exec(url.pathname);
  if(institutionId) return json({institutionId:`institution-${institutionId[1]}`,legacyId:Number(institutionId[1]),canonicalName:names[0]!,shortName:null,platform,period:"30d",metrics:{totalReactions:10,totalViews:100,medianReactions:5,medianViews:50,quality:"exact",sampleSize:2,coverage:1,aggregates:{totalReactions:aggregate(10),totalViews:aggregate(100),medianReactions:aggregate(5),medianViews:aggregate(50)}},datasetRevision:revision,asOf} satisfies Schema["Institution"]);
  const accountsId=/^\/api\/v1\/institutions\/(\d+)\/accounts$/.exec(url.pathname);
  if(accountsId) {const ids=accountsId[1] === "3" ? [] : accountsId[1] === "2" ? [1,2] : [1];return json({items:ids.map((id) => account(id,platform === "telegram" ? "channels" : "platform_accounts")),legacyTotalAccountCount:ids.length,nextCursor:null,datasetRevision:revision,asOf} satisfies Schema["InstitutionAccountsPage"]);}
  if (url.pathname === "/api/v1/overview") return json({ items: url.searchParams.get("q") ? [] : (performanceFixture ? selectionIds.slice(0,50).map(id => item(id,platform)) : [item(1, platform), item(2, platform)]), nextCursor: null, datasetRevision: revision, asOf, integrationStatus: "unknown", integrationWarning: null } satisfies Schema["OverviewPage"]);
  if (url.pathname === "/api/v1/compare/candidates") return json({
    items: selectionIds.map((id) => ({ selectionId: `selection-${id}`, selectionType: platform === "telegram" ? "channels" : "institutions",
      selectionLegacyId: id, selectionLabel: names[id - 1]!, selectionDescription: names[id - 1]!, institutionId: `institution-${id}`, canonicalName: names[id - 1]! })),
    nextCursor: null, datasetRevision: revision, asOf,
  } satisfies Schema["ComparisonCandidatePage"]);
  if (url.pathname === "/api/v1/compare") {
    const type = platform === "telegram" ? "channels" : "institutions";
    const requested = url.searchParams.getAll(type).map(Number);
    const selected = (requested.length ? requested : selectionIds).filter((id) => selectionIds.includes(id));
    const points = (performanceFixture ? Array.from({ length: 337 }, (_, hour) => hour) : [0, 1, 2]).map((hourOffset) => ({ hourOffset, value: hourOffset * 3, sampleSize: 2, coverage: 1, quality: "exact" }));
    const series: Schema["ComparisonSeries"][] = selected.map((id) => ({ selectionId: `selection-${id}`, selectionType: type, selectionLegacyId: id, selectionLabel: names[id - 1]!, institutionId: `institution-${id}`, legacyId: id,
      canonicalName: names[id - 1]!, shortName: null, primaryCohortSize: 2, engagementCohortSize: 2, points: performanceFixture ? points.map(point => ({...point, value: point.value * id / 10})) : points, engagementPoints: performanceFixture ? points.map(point => ({...point, value: point.value * id / 100})) : points }));
    return json({ cohortId: "fixture-cohort", nextSelectionCursor: null, platform: platform as "telegram", horizonHours: Number(url.searchParams.get("horizonHours") ?? 72) as 72, includePartial: url.searchParams.get("includePartial") === "true",
      metric: (url.searchParams.get("metric") ?? "reactions") as "reactions", aggregation: "median", selectionType: type, cohortSampleSize: 4, series, datasetRevision: revision, asOf } satisfies Schema["Comparison"]);
  }
  if (url.pathname === "/api/v1/statistics") {
    const selectedPlatform=(url.searchParams.get("platform")??"all") as "all"|"telegram"|"vk"|"max"|"rutube";
    const view=(selectedPlatform==="all"?"publications":url.searchParams.get("view")??"publications") as "publications"|"entities";
    const query=url.searchParams.get("q")??"";
    const platforms=(selectedPlatform==="all"?["telegram","vk","max","rutube"]:[selectedPlatform]) as ("telegram"|"vk"|"max"|"rutube")[];
    const empty=query==="missing";
    const sections=view==="publications"?platforms.map((value)=>({platform:value,capabilities:{reactions:true,comments:value!=="max",shares:value==="vk"},items:empty?[]:Array.from({length:50},(_,index)=>statisticsPublication(index+1,value)),total:empty?0:50,offset:0,hasMore:false,nextCursor:null})):[];
    const entities=view==="entities"&&!empty?Array.from({length:50},(_,index)=>statisticsEntity(index+1,platforms[0]!)):[];
    return json({view,platform:selectedPlatform,period:(url.searchParams.get("period")??"30d") as "30d",q:query,
      publicationSort:(url.searchParams.get("publication_sort")??"erv") as "erv",publicationDirection:(url.searchParams.get("publication_direction")??"desc") as "desc",
      entitySort:(url.searchParams.get("entity_sort")??"erv") as "erv",entityDirection:(url.searchParams.get("entity_direction")??"desc") as "desc",
      sections,entities,limit:50,offset:0,hasMore:false,nextCursor:null,datasetRevision:revision,asOf} satisfies Schema["Statistics"]);
  }
  return json({ title: "Not Found", status: 404, detail: "Unknown fixture route" }, 404);
});
server.listen(18091, "127.0.0.1");
