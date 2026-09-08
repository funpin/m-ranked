/** Contract-shaped test double. It proves browser behavior, not PostgreSQL or legacy data parity. */
import { createServer } from "node:http";
import type { components } from "../../contracts/openapi/m-ranked-v1-client";

type Schema = components["schemas"];
const asOf = "2026-08-01T12:00:00Z";
const revision = 17;
const uuid = (kind: number, id: number) => `${String(kind).padStart(8,"0")}-0000-4000-8000-${String(id).padStart(12,"0")}`;

const names = ["Альфа Университет", "Бета Институт"];
const aggregate = (value: number | null, size = 2): Schema["AggregateMetric"] => ({ value, asOf, datasetRevision: revision, sampleSize: size, coverage: size / 2, quality: value === null ? "unsupported" : "exact" });
const metric: Schema["OverviewMetric"] = { total: 12, median: 6, previousTotal: 10, previousMedian: 5, totalTrend: 2, medianTrend: 1,
  totalMetadata: aggregate(12), medianMetadata: aggregate(6), previousTotalMetadata: aggregate(10), previousMedianMetadata: aggregate(5) };
function item(id: number, platform: Schema["PlatformValue"]): Schema["OverviewRow"] {
  return { entityId: platform === "telegram" ? uuid(1,id) : uuid(9,id), entityType: platform === "telegram" ? "channels" : "institutions", legacyId: id, legacyRoute: `/institutions/${id}`, institutionId: `institution-${id}`, institutionLegacyId: id,
    canonicalName: names[id - 1]!, shortName: null, platform, period: "1d", accounts: [], accountCount: 1, enabledAccountCount: 1, connectedPlatformCount: 1,
    subscriberCount: 100, lastCheckedAt: asOf, lastErrorCode: null, statusCode: "connected", ratingRank: id, ratingScore: 90,
    ratingPeriod: "2026-Q2", ratingFetchedAt: asOf, totalPublicationCount: 2, activityPublicationCount: 2, newPublicationCount: 0,
    views: metric, reactions: metric, comments: { ...metric, total: 0, totalMetadata: aggregate(0, 1) }, shares: { ...metric, total: null, totalMetadata: aggregate(null, 0) }, asOf };
}
function entity(id: number, platform: "telegram" | "vk" | "rutube"): Schema["ActivityRatingEntity"] {
  return { entityId: platform === "telegram" ? uuid(1,id) : uuid(9,id), entityType: platform === "telegram" ? "channels" : "institutions", legacyId: id, legacyRoute: platform === "telegram" ? `/channels/${id}` : `/institutions/${id}`,
    institutionId: `institution-${id}`, institutionLegacyId: id, canonicalName: `Университет ${String(id).padStart(3, "0")}`, shortName: null, username: `fixture_${id}`, title: `Университет ${String(id).padStart(3, "0")}`,
    publicationCount: 1, averageReactions: id, averageViews: id * 10, totalReactions: id, totalViews: id * 10, totalComments: id % 2 ? 0 : null, totalShares: null, totalInteractions: id, engagementRate: 1, subscriberCount: 100 };
}
const counter = (value:number|null):Schema["CounterMetric"] => ({value,observedAt:asOf,quality:value === null ? "unsupported" : "exact"});
function account(id:number,legacyType:"channels"|"platform_accounts"="channels"):Schema["Account"] {
  const platform=legacyType === "channels" ? "telegram" : id === 3 ? "max" : id === 4 ? "rutube" : "vk";
  return {accountId:uuid(platform === "telegram" ? 1 : platform === "vk" ? 2 : platform === "max" ? 3 : 4,id),legacyId:id,legacyType,channelLegacyId:platform === "telegram" ? id : null,platformAccountLegacyId:id,institutionId:`institution-${id}`,institutionLegacyId:id,institutionName:names[0]!,institutionShortName:null,platform,canonicalExternalId:`external-${id}`,username:`fixture_${id}`,title:`Канал ${id}`,url:`https://example.test/account/${id}`,accessMode:"public",enabled:true,publicationCount:2,latestObservedAt:asOf,datasetRevision:revision,asOf,
    stats:{retentionDays:70,postCount:2,monitored:1,medianReactions:aggregate(5),medianViews:aggregate(50),medianComments:aggregate(0),ratingRank:2,ratingPeriod:"2026-Q2",subscriberCount:100,lastError:null,lastCheckedAt:asOf}};
}
function publication(id:number,type:"posts"|"platform_posts"="posts"):Schema["Publication"] {
  const platform=type === "posts" ? "telegram" : id === 21 ? "vk" : id === 41 ? "rutube" : "max";
  return {publicationId:uuid(type === "posts" ? 5 : 6,id),legacyId:id,legacyType:type,institutionId:"institution-1",platform,publishedAt:"2026-07-01T00:00:00Z",publicationType:"album",deletedAt:id === 1 ? asOf : null,views:counter(50),reactions:counter(5),comments:counter(0),shares:counter(null),quality:"exact",intervalUncertain:false,synthetic:false,historyCompleteness:"complete",datasetRevision:revision,asOf,accountLegacyId:platform === "telegram" || platform === "vk" ? 1 : platform === "rutube" ? 4 : 3,accountLegacyType:type === "posts" ? "channels" : "platform_accounts",accountName:names[0]!,accountUsername:"fixture_1",externalId:String(id+100),displayExternalId:String(id+100),repost:false,joint:false,additionalAuthorCount:0,ambiguousAlbumReactions:false,publicUrl:`https://example.test/post/${id}`};
}
function postItem(id:number,type:"posts"|"platform_posts"):Schema["PublicationListItem"] {
  const p=publication(id,type);
  return {publicationId:p.publicationId,legacyId:id,legacyType:type,legacyRoute:`/${type === "posts" ? "posts" : "platform-posts"}/${id}`,externalId:p.externalId,publishedAt:p.publishedAt,publicUrl:p.publicUrl,publicationType:p.publicationType,deletedAt:p.deletedAt,historyCompleteness:"complete",views:p.views,reactions:p.reactions,comments:p.comments,shares:p.shares,title:null,archivedText:null,displayExternalId:p.displayExternalId,repost:p.repost,joint:p.joint,additionalAuthorCount:p.additionalAuthorCount,ambiguousAlbumReactions:p.ambiguousAlbumReactions};
}
const historyRows:Schema["HistorySnapshot"][] = Array.from({length:160},(_,index) => ({snapshotId:String(index+1),observedAt:new Date(Date.parse("2026-07-01T00:00:00Z")+index*3600000).toISOString(),ageHours:index,views:counter(index*10),reactions:counter(index === 159 ? 155 : index),comments:counter(0),shares:counter(null),deltaViews:index ? 10 : null,deltaReactions:index ? index === 159 ? -3 : 1 : null,deltaComments:index ? 0 : null,deltaShares:null,reactionsBreakdown:{"👍":index,"custom:123456":1},reactionsBreakdownEntries:[{reaction:"👍",count:index},{reaction:"custom:123456",count:1}],deltaReactionsBreakdown:index?{"👍":1}:null,deltaReactionsBreakdownEntries:index?[{reaction:"👍",count:1}]:null,synthetic:index === 0,intervalUncertain:index === 40,quality:"exact",rawEvidence:{fingerprint:`fixture-${index}`}}));
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
const server = createServer((request, response) => {
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
  if(url.pathname.startsWith("/api/v1/admin/catalog/")) {
    const credentials=Buffer.from((request.headers.authorization??"").replace(/^Basic /,""),"base64").toString();
    const role=credentials.endsWith(":fixture-password")?credentials.split(":")[0]:null;
    if(!role||!["viewer","editor","admin"].includes(role)) {response.setHeader("WWW-Authenticate",'Basic realm="m-ranked"');return json({detail:"Not authenticated"},401);}
    if(url.pathname.endsWith("/session")) return json({headerName:"X-XSRF-TOKEN",token:"fixture-csrf-token",canEdit:role!=="viewer",canDelete:role==="admin"});
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
  if(/^\/api\/v1\/accounts\/\d+\/publications$/.test(url.pathname)) return json({items:[postItem(1,url.searchParams.get("legacyType") === "channels" ? "posts" : "platform_posts"),postItem(2,"posts")],nextCursor:null,datasetRevision:revision,asOf} satisfies Schema["AccountPublicationPage"]);
  const historyId=/^\/api\/v1\/publications\/(\d+)\/history$/.exec(url.pathname);
  if(historyId) {
    const p=publication(Number(historyId[1]),url.searchParams.get("legacyType") as "posts"|"platform_posts");
    const sourceRows=p.legacyId===99 ? Array.from({length:1205},(_,index)=>({...historyRows[index%historyRows.length]!,
      snapshotId:String(index+1),observedAt:new Date(Date.parse("2026-07-01T00:00:00Z")+index*3600000).toISOString(),ageHours:index,
      reactions:counter(index),views:counter(index*10),deltaReactions:index?1:null,deltaViews:index?10:null,synthetic:index===0,
    })) : historyRows;
    const limit=Math.max(1,Number(url.searchParams.get("limit") ?? 200));
    const items=sourceRows.slice(-limit).map((row,index)=>({...row,
      comments:p.platform === "rutube" ? counter(null) : row.comments,
      deltaComments:p.platform === "rutube" ? null : row.deltaComments,
      shares:p.platform === "vk" ? counter(index*2) : row.shares,
      deltaShares:p.platform === "vk" ? index ? 2 : null : row.deltaShares,
      reactionsBreakdown:p.platform === "vk" || p.platform === "rutube" ? {} : row.reactionsBreakdown,
      reactionsBreakdownEntries:p.platform === "vk" || p.platform === "rutube" ? [] : row.reactionsBreakdownEntries,
      deltaReactionsBreakdown:p.platform === "vk" || p.platform === "rutube" ? null : row.deltaReactionsBreakdown,
      deltaReactionsBreakdownEntries:p.platform === "vk" || p.platform === "rutube" ? null : row.deltaReactionsBreakdownEntries,
    }));
    return json({publication:p,items,nextCursor:sourceRows.length>limit?"older":null,previousLegacyId:null,nextLegacyId:2,archivedText:"Сохранённый текст <script>без исполнения</script>",datasetRevision:revision,asOf} satisfies Schema["PublicationHistory"]);
  }
  const anomalyId=/^\/api\/v1\/publications\/(\d+)\/anomaly-analysis$/.exec(url.pathname);
  if(anomalyId) return json(anomaly(Number(anomalyId[1]),url.searchParams.get("legacyType") as "posts"|"platform_posts"));
  const institutionId=/^\/api\/v1\/institutions\/(\d+)$/.exec(url.pathname);
  if(institutionId) return json({institutionId:`institution-${institutionId[1]}`,legacyId:Number(institutionId[1]),canonicalName:names[0]!,shortName:null,platform,period:"30d",metrics:{totalReactions:10,totalViews:100,medianReactions:5,medianViews:50,quality:"exact",sampleSize:2,coverage:1,aggregates:{totalReactions:aggregate(10),totalViews:aggregate(100),medianReactions:aggregate(5),medianViews:aggregate(50)}},datasetRevision:revision,asOf} satisfies Schema["Institution"]);
  const accountsId=/^\/api\/v1\/institutions\/(\d+)\/accounts$/.exec(url.pathname);
  if(accountsId) {const ids=accountsId[1] === "3" ? [] : accountsId[1] === "2" ? [1,2] : [1];return json({items:ids.map((id) => account(id,platform === "telegram" ? "channels" : "platform_accounts")),legacyTotalAccountCount:ids.length,nextCursor:null,datasetRevision:revision,asOf} satisfies Schema["InstitutionAccountsPage"]);}
  if (url.pathname === "/api/v1/overview") return json({ items: url.searchParams.get("q") ? [] : [item(1, platform), item(2, platform)], nextCursor: null, datasetRevision: revision, asOf, integrationStatus: "unknown", integrationWarning: null } satisfies Schema["OverviewPage"]);
  if (url.pathname === "/api/v1/compare/candidates") return json({
    items: [1, 2].map((id) => ({ selectionId: `selection-${id}`, selectionType: platform === "telegram" ? "channels" : "institutions",
      selectionLegacyId: id, selectionLabel: names[id - 1]!, selectionDescription: names[id - 1]!, institutionId: `institution-${id}`, canonicalName: names[id - 1]! })),
    nextCursor: null, datasetRevision: revision, asOf,
  } satisfies Schema["ComparisonCandidatePage"]);
  if (url.pathname === "/api/v1/compare") {
    const type = platform === "telegram" ? "channels" : "institutions";
    const requested = url.searchParams.getAll(type).map(Number);
    const selected = (requested.length ? requested : [1, 2]).filter((id) => id === 1 || id === 2);
    const points = [0, 1, 2].map((hourOffset) => ({ hourOffset, value: hourOffset * 3, sampleSize: 2, coverage: 1, quality: "exact" }));
    const series: Schema["ComparisonSeries"][] = selected.map((id) => ({ selectionId: `selection-${id}`, selectionType: type, selectionLegacyId: id, selectionLabel: names[id - 1]!, institutionId: `institution-${id}`, legacyId: id,
      canonicalName: names[id - 1]!, shortName: null, primaryCohortSize: 2, engagementCohortSize: 2, points, engagementPoints: points }));
    return json({ cohortId: "fixture-cohort", nextSelectionCursor: null, platform: platform as "telegram", horizonHours: Number(url.searchParams.get("horizonHours") ?? 72) as 72, includePartial: url.searchParams.get("includePartial") === "true",
      metric: (url.searchParams.get("metric") ?? "reactions") as "reactions", aggregation: "median", selectionType: type, cohortSampleSize: 4, series, datasetRevision: revision, asOf } satisfies Schema["Comparison"]);
  }
  if (url.pathname === "/api/v1/rating") {
    const cursor = url.searchParams.get("entityCursor");
    if (cursor && cursor !== "fixture-page-2") return json({ title: "Invalid cursor", detail: "Dataset changed", status: 400 }, 400);
    const offset = cursor ? 200 : 0;
    const rows = Array.from({ length: cursor ? 5 : 200 }, (_, index) => entity(offset + index + 1, platform as "telegram"));
    return json({ platform: platform as "telegram", period: (url.searchParams.get("period") ?? "30d") as "30d", entityType: platform === "telegram" ? "channels" : "institutions", publicationLegacyType: platform === "telegram" ? "posts" : "platform_posts",
      channelSort: url.searchParams.get("channel_sort") ?? "engagement", channelDirection: (url.searchParams.get("channel_direction") ?? "desc") as "desc", postSort: url.searchParams.get("post_sort") ?? "view_share", postDirection: (url.searchParams.get("post_direction") ?? "desc") as "desc",
      entities: rows, publications: [], entityLimit: 200, entitiesTruncated: !cursor, entityOffset: offset, nextEntityCursor: cursor ? null : "fixture-page-2", datasetRevision: revision, asOf } satisfies Schema["Rating"]);
  }
  return json({ title: "Not Found", status: 404, detail: "Unknown fixture route" }, 404);
});
server.listen(18091, "127.0.0.1");
