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
function item(id: number, platform: Schema["PlatformValue"], period: Schema["PeriodValue"] = "1d"): Schema["OverviewRow"] {
  const networks:Schema["OverviewAccount"]["platform"][] = platform === "all"
    ? id === 1 ? ["telegram", "vk", "max", "rutube"] : ["telegram", "vk"] : [platform];
  const accounts:Schema["OverviewAccount"][] = networks.map(network => {
    const accountKind = network === "telegram" ? 1 : network === "vk" ? 2 : network === "max" ? 3 : 4;
    return {
    accountId:uuid(accountKind,id),legacyId:id,legacyRoute:platform === "telegram" ? `/channels/${id}` : `/platform-accounts/${id}`,
    platform:network,canonicalExternalId:`external-${id}`,username:`fixture_${id}`,title:`Официальный аккаунт университета с длинным названием ${id}`,
    url:platform === "all" && id === 2 && network === "vk" ? null : `https://example.test/${network}/${id}`,accessMode:"public",enabled:!(platform === "all" && id === 2 && network === "vk"),subscriberCount:100,
    subscriberDisplay:"100",subscriberObservedAt:asOf,latestPollStartedAt:asOf,latestPollCompletedAt:asOf,
    latestPollStatus:"success",latestErrorCode:null,
  }; });
  return { entityId: platform === "telegram" ? uuid(1,id) : uuid(9,id), entityType: platform === "telegram" ? "channels" : "institutions", legacyId: id, legacyRoute: `/institutions/${id}`, institutionId: `institution-${id}`, institutionLegacyId: id,
    canonicalName: names[id - 1]!, shortName: null, platform, period, accounts, accountCount: accounts.length, enabledAccountCount: accounts.filter(a=>a.enabled).length, connectedPlatformCount: accounts.filter(a=>a.enabled).length,
    subscriberCount: 100 * accounts.length, lastCheckedAt: asOf, lastErrorCode: null, statusCode: "connected", ratingRank: id, ratingScore: 90,
    ratingPeriod: "2026-Q2", ratingFetchedAt: asOf, totalPublicationCount: 2 * accounts.length, activityPublicationCount: 2 * accounts.length, newPublicationCount: platform === "all" ? accounts.length : 0,
    anomalyCounts: id === 1 ? {level2:period === "7d" ? 12 : platform === "vk" ? 3 : 2, level3:period === "7d" ? 8 : platform === "vk" ? 1 : 4} : {level2:0,level3:0},
    views: !performanceFixture && period === "30d" ? {...metric, total:12_345_678, totalTrend:null, medianTrend:null, totalMetadata:aggregate(12_345_678)}
      : platform === "all" ? {...metric, total:id === 1 ? 2400 : 12000, totalMetadata:aggregate(id === 1 ? 2400 : 12000)} : metric,
    reactions: !performanceFixture && period === "30d" ? {...metric, total:999_999, totalTrend:null, medianTrend:null, totalMetadata:aggregate(999_999)}
      : platform === "all" ? {...metric, total:84, totalMetadata:aggregate(84)} : metric,
    comments: { ...metric, total: 0, totalTrend:-1, totalMetadata: aggregate(0, 1) }, shares: { ...metric, total: null, totalTrend:null, totalMetadata: aggregate(null, 0) }, asOf };
}
function finding(id: number, platform: "telegram" | "vk" | "max" | "rutube", institution = 1): Schema["Finding"] {
  return {
    publicationId: uuid(5, id), institutionId: uuid(9, institution), institutionLegacyId: institution,
    institutionShortName: `Вуз ${String(institution).padStart(3, "0")}`,
    institutionCanonicalName: `Полное название университета ${String(institution).padStart(3, "0")}`,
    accountId: uuid(1, institution), platform, publicationType: id % 3 === 0 ? "video" : "photo",
    // MAX нумерует посты 18-значными числами: карточка не должна от них разъезжаться.
    externalId: platform === "max" ? `11497403${String(id).padStart(10, "0")}` : String(id), publicUrl: `https://example.test/${id}`, publishedAt: asOf,
    ageHours: id === 2 ? 6 : id === 7 ? 12 : 24, preliminary: id === 2, interactionIndex: id === 4 ? null : 5 - id / 20,
    viewIndex: 1.5, interactionNorm: 20, viewNorm: 1000, normSampleSize: 12,
    interactions: id === 3 ? 0 : 100 - id, reactions: 80, comments: platform === "max" ? null : 15,
    shares: platform === "vk" ? 5 : null, views: 2000, erv: id === 3 ? 0 : 5,
    anomalyLevel: id === 2 || id === 5 ? 1 : id === 6 ? null : 0,
    capabilities: { reactions: true, comments: platform !== "max", shares: platform === "vk" },
  };
}

function statisticsEntity(id: number, platform: "telegram" | "vk" | "max" | "rutube"): Schema["StatisticsEntity"] {
  return { rank:id, legacyRoute:`/institutions/${id}`, accountId:uuid(platform === "telegram" ? 1 : platform === "vk" ? 2 : platform === "max" ? 3 : 4,id), institutionId:uuid(9,id), institutionLegacyId:id,
    canonicalName:id===3?"Мариупольский государственный университет имени А.И. Куинджи":`Полное название университета ${String(id).padStart(3,"0")}`,
    shortName:id===3?"МГУ им. А.И. Куинджи":`Вуз ${String(id).padStart(3,"0")}`,platform,publicationCount:20,
    interactionSampleSize:20,viewSampleSize:20,ervSampleSize:20,medianInteractions:id,
    interactions:id*20,views:id*200,erv:id===2?null:10 };
}
function statisticsPublication(id:number,platform:"telegram"|"vk"|"max"|"rutube"):Schema["StatisticsPublication"] {
  const type=platform==="telegram"?"posts":"platform_posts";
  return {rank:id,publicationId:uuid(7,id),platform,legacyId:id,legacyType:type,legacyRoute:`/${type}/${id}`,
    institutionId:uuid(9,id),institutionLegacyId:id,institutionCanonicalName:`Полное название университета ${String(id).padStart(3,"0")}`,
    institutionShortName:`Вуз ${String(id).padStart(3,"0")}`,accountId:uuid(2,id),accountLegacyId:id,accountUsername:`fixture_${id}`,
    accountTitle:`Аккаунт ${id}`,accountExternalId:`external-${id}`,externalId:platform==="vk"?`№${id}`:String(id),
    publicUrl:`https://example.test/${platform}/${id}`,publishedAt:"2026-07-01T00:00:00Z",deletedAt:null,
    joint:false,additionalAuthorCount:0,repost:false,views:id===2?0:id*100,reactions:id,comments:platform==="max"?null:0,
    shares:platform==="vk"?0:null,interactions:id,erv:id===2?null:1,interactionsAvailable:true,ervEligible:id!==2};
}
const counter = (value:number|null):Schema["CounterMetric"] => ({value,observedAt:asOf,quality:value === null ? "unsupported" : "exact"});
function account(id:number,legacyType:"channels"|"platform_accounts"="channels"):Schema["Account"] {
  const platform=legacyType === "channels" ? "telegram" : id === 3 ? "max" : id === 4 ? "rutube" : "vk";
  return {accountId:uuid(platform === "telegram" ? 1 : platform === "vk" ? 2 : platform === "max" ? 3 : 4,id),legacyId:id,legacyType,channelLegacyId:platform === "telegram" ? id : null,platformAccountLegacyId:id,institutionId:`institution-${id}`,institutionLegacyId:id,institutionName:names[0]!,institutionShortName:null,platform,canonicalExternalId:`external-${id}`,username:`fixture_${id}`,title:`Канал ${id}`,url:`https://example.test/account/${id}`,archiveUrl:platform === "max" ? "https://maxstat.ru/channel/-70908719079458/post" : null,accessMode:"public",enabled:true,publicationCount:2,latestObservedAt:asOf,datasetRevision:revision,asOf,
    institutionProfile:id === 2 ? undefined : {trackingStartedAt:"2026-07-01T22:30:00Z",students:{value:8202,referenceYear:2026,referenceDate:"2026-09-30",approximate:false,sourceUrl:"https://mipt.ru/vikon/sveden/files/eiw/Svedeniya_o_chislennosti_obuchayuschixsya_ot_30.09.2026%281%29.pdf",sourceLabel:"МФТИ · ведомость от 30.09.2026",scope:"Бакалавриат, специалитет и магистратура, все формы обучения. Без филиалов, СПО и аспирантуры.",verifiedAt:"2026-10-02"}},
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
  const signal=(pattern:1|6,metric:"views"|"reactions",from:number,to:number):Schema["AnomalySignal"] => ({
    pattern,symbol:pattern===1?"⟋":"⇅",title:pattern===1?"Линейная подача":"Реакции раньше просмотров",
    family:pattern===1?"velocity":"cross_metric",metric,strength:pattern===1?0.94:0.88,
    startAt:historyRows[from]!.observedAt,endAt:historyRows[to]!.observedAt,scaleSeconds:3600,
    formula:pattern===1?"Δпросмотры ≈ 10·t (t в часах), R² = 0.999, t ∈ [1д15ч; 1д16ч], масштаб 1 ч":"Δреакции = +40 при Δпросмотры = +2 за 2ч (ожидалось ≤ 1)",
    render:pattern===1?{kind:"linear",startAge:from*3600,endAge:to*3600,slope:10,intercept:from*10,r2:0.999}:{kind:"lead",startAge:from*3600,endAge:to*3600,reactionsDelta:40,viewsDelta:2},
    alternatives:[{code:"recommendation_feed",text:"пост долго показывался в рекомендациях с ровным притоком"}],normConfidence:null,
  });
  const base:Schema["PublicationAnomalyAnalysis"]={publicationId:uuid(type === "posts" ? 5 : 6,id),datasetRevision:revision,
    status:"analyzed",level:3,levelLabel:"признаки искусственной активности",levelSymbol:"●",
    originalLevel:3,recheckReason:null,recheckMethodVersion:null,recheckEvidence:null,
    signals:[signal(1,"views",39,40),signal(6,"reactions",36,38)],
    quality:{coverage:1,summary:"замеры полные, покрытие 100%",codes:[],unanalyzable:[]},
    analyzedAt:asOf,lagSeconds:40,normVersion:3,detectorVersions:{linear_feed:"2.0.0",reactions_before_views:"2.0.0"},
    reviewStatus:"unreviewed",methodologyVersion:"anomaly-dynamics-v2",
    disclaimer:"Сигнал аномальной динамики носит информационный характер и сам по себе не доказывает искусственное происхождение активности или действия университета."};
  if(type==="platform_posts" && id===10) return {...base,level:1,originalLevel:1,
    levelLabel:"слабый сигнал",levelSymbol:"◔",signals:([11,12] as const).map(pattern=>({
      pattern,symbol:pattern===11?"↥":"↗",title:pattern===11?"Отклик выше исторического диапазона":"Продолжение отклика выше ожидаемого",
      family:"velocity",metric:"views",strength:0.5,startAt:historyAt(pattern===11?0:24),endAt:historyAt(72),scaleSeconds:259200,
      formula:"Y72=2791 > 2608 (верхняя целая граница); ожидание=2265; общая калибровка четырёх компонент: n=130",
      render:{kind:"reference",startAge:pattern===11?0:86400,endAge:259200,observed:2791,expected:2265,upper:2608,
        fitPosts:266,calibrationPosts:130,referenceStart:"2026-06-06T00:00:00Z",referenceEnd:"2026-06-17T00:00:00Z"},
      alternatives:[{code:"news_event",text:"новостной повод вернул внимание к посту"}],normConfidence:null,
    }))};
  if(type==="posts" && id===11) return {...base,level:0,originalLevel:0,levelLabel:"недостаточно точных данных",
    levelSymbol:"·",signals:[],quality:{coverage:0,summary:"недостаточно точных данных для проверки",
      codes:["no_precise_metrics"],unanalyzable:[]}};
  // Провайдерские различия метрик: у ВК есть репосты, у RuTube и MAX их не выдумываем.
  if(type!=="posts") return {...base,signals:base.signals.map(item=>({...item,metric:id===21 ? "shares" : id===41 ? "views" : "comments"}))};
  if(id===2) return {...base,status:"pending",level:null,originalLevel:null,levelLabel:"ещё не проанализирован",levelSymbol:"·",signals:[],quality:null,analyzedAt:null,lagSeconds:null,normVersion:null,detectorVersions:{}};
  if(id===3) return {...base,level:0,originalLevel:0,levelLabel:"нет признаков",levelSymbol:"○",signals:[]};
  if(id===4) return {...base,level:1,originalLevel:1,levelLabel:"слабый сигнал",levelSymbol:"◔",signals:[{...base.signals[0]!,strength:0.5,normConfidence:0.3}]};
  return base;
}

// Панель сравнения: детерминированные данные на все вузы фикстуры (в замере
// производительности — 207) и четыре площадки. Числа различаются так, чтобы
// рейтинг, карта и выделение имели что показывать.
function dashboard(period: "7d" | "30d"): Schema["ComparisonDashboard"] {
  const networks = ["telegram", "vk", "max", "rutube"] as const;
  const count = Math.max(12, names.length);
  const institutions = Array.from({ length: count }, (_, index) => ({
    institutionId: uuid(9, index + 1), legacyId: index + 1,
    name: names[index] ?? `Университет ${index + 1}`, shortName: index < 2 ? ["Альфа", "Бета"][index]! : null,
    platforms: index % 5 === 4 ? ["telegram", "vk"] : [...networks],
    subscribers: { telegram: 1000 + index * 350, vk: 2000 + index * 500, max: 300 + index * 40, rutube: index % 3 ? 150 + index * 10 : 0 },
    students: index === 0 ? { value: 12345, referenceYear: 2026, approximate: false,
      sourceUrl: "https://example.test/students", sourceLabel: "Официальный отчёт",
      scope: "Все формы обучения", verifiedAt: "2026-10-03" } : null,
  })) as Schema["ComparisonDashboard"]["institutions"];
  const stat = (institutionId: string | null, platform: string, seed: number): Schema["ComparisonDashboardStat"] => {
    const posts = 20 + (seed * 7) % 60;
    const analyzed = posts - 2;
    const level3 = seed % 9 === 0 ? 3 : 0, level2 = seed % 4 === 0 ? 2 : 0, level1 = seed % 3;
    return { institutionId, platform: platform as Schema["PlatformValue"], posts, viewsTotal: posts * (300 + seed * 11),
      reactionsTotal: posts * (10 + seed % 17), commentsTotal: posts, sharesTotal: platform === "vk" ? posts * 2 : null,
      sample24: posts - 4, views24: 150 + (seed * 37) % 900, reactions24: 5 + (seed * 13) % 60, comments24: seed % 4,
      shares24: platform === "vk" ? seed % 6 : null, engagement24: 1 + ((seed * 7) % 90) / 10, analyzed,
      levels: [analyzed - level1 - level2 - level3, level1, level2, level3] };
  };
  const stats: Schema["ComparisonDashboardStat"][] = [];
  institutions.forEach((institution, index) => {
    for (const [offset, network] of networks.entries()) {
      if (institution.platforms.includes(network)) stats.push(stat(institution.institutionId, network, index * 4 + offset + 1));
    }
    stats.push(stat(institution.institutionId, "all", index * 4 + 5));
  });
  for (const [offset, network] of networks.entries()) stats.push(stat(null, network, 100 + offset));
  stats.push(stat(null, "all", 200));
  const hours = [1, 3, 6, 12, 24, 48, 72, 168];
  const curve = (institutionId: string | null, platform: string, scale: number) => ({
    institutionId, platform: platform as Schema["PlatformValue"], samples: hours.map(() => 12),
    views: hours.map((hour) => Math.round(scale * Math.log2(hour + 1) * 40)),
    reactions: hours.map((hour) => Math.round(scale * Math.log2(hour + 1) * 2)),
  });
  const curves = [
    ...institutions.flatMap((institution, index) => networks.filter((n) => institution.platforms.includes(n))
      .map((network) => curve(institution.institutionId, network, 0.5 + (index % 7) / 3))),
    ...networks.map((network) => curve(null, network, 1.2)),
  ];
  const days = period === "7d" ? 7 : 30;
  const daily = Array.from({ length: days }, (_, index) => {
    const day = new Date(Date.UTC(2026, 6, 3 + index)).toISOString().slice(0, 10);
    return [...networks, "all"].map((platform, offset) => ({ platform: platform as Schema["PlatformValue"], day,
      posts: 10 + (index * 3 + offset * 5) % 25, viewsTotal: 5000 + index * 120 + offset * 700,
      reactionsTotal: 200 + index * 7, analyzed: 9 + (index + offset) % 20, anomalous: (index + offset) % 4 }));
  }).flat();
  const timing: Schema["ComparisonDashboard"]["timing"] = [];
  for (const platform of [...networks, "all"]) {
    for (let weekday = 0; weekday < 7; weekday += 1) for (let hour = 0; hour < 24; hour += 1) {
      const posts = hour < 7 ? 0 : (weekday + hour) % 6;
      if (posts) timing.push({ platform: platform as Schema["PlatformValue"], weekday, hour, posts, views24: 200 + hour * 20 });
    }
    for (let hour = 7; hour < 24; hour += 1) timing.push({ platform: platform as Schema["PlatformValue"], weekday: null, hour, posts: 10 + hour, views24: 300 + hour * 15 });
  }
  const types = [...networks, "all"].flatMap((platform) => ["photo", "album", "video", "text"].map((type, index) => ({
    platform: platform as Schema["PlatformValue"], type, posts: 40 - index * 8, views24: 500 + index * 150, engagement24: 3 + index })));
  return { period, hours, datasetRevision: revision, asOf, institutions, stats, curves, daily, timing, types };
}
const server = createServer(async (request, response) => {
  const url = new URL(request.url!, "http://127.0.0.1");
  const canonical = /^\/api\/v1\/(accounts|publications)\/([0-9a-f-]{36})(\/(publications|history|anomaly-analysis|anomaly-levels|tail-profile))?$/.exec(url.pathname);
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
  if(url.pathname==="/api/v1/visit") { response.writeHead(204,{"Cache-Control":"no-store"}); response.end(); return; }
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
  if(url.pathname==="/api/v1/admin/visitors") {
    if(!sessionRole) return json({detail:"Требуется вход администратора"},401);
    const length=url.searchParams.get("range")==="month"?30:7;
    const days=Array.from({length},(_,index)=>{const day=new Date(Date.UTC(2026,8,30-length+1+index));return {day:day.toISOString().slice(0,10),visitors:40+((index*37)%55),views:120+((index*53)%140)};});
    return json({range:length===30?"month":"week",online:3,onlineWindowSeconds:300,today:days[days.length-1],days});
  }
  if(url.pathname==="/api/v1/admin/system") {
    if(!sessionRole) return json({detail:"Требуется вход администратора"},401);
    const week=url.searchParams.get("range")==="week";
    const count=week?168:288,step=week?3600_000:300_000,end=Date.parse("2026-09-30T12:00:00Z");
    const series=Array.from({length:count},(_,index)=>({at:new Date(end-(count-1-index)*step).toISOString(),cpu:20+(index*7)%35,memory:55+(index*3)%20,load:0.4+((index*11)%30)/20,
      requestsPerMinute:30+(index*13)%60,humanErrors:index%41===0?2:0,botRejected:index%17===0?5:0,hitRatio:80+(index*5)%18,p95Ms:120+(index*29)%400,
      analysisLagMinutes:3+(index*7)%25,ingestDelayMinutes:(index*3)%6,collectedOk:200+(index*17)%90,collectedFailed:index%9===0?3:0}));
    const checks=[["collection.telegram","Сбор · Telegram","ok","последний аккаунт 2 мин назад"],["collection.vk","Сбор · ВКонтакте","ok","последний аккаунт 4 мин назад"],
      ["collection.max","Сбор · MAX","warn","последний аккаунт 52 мин назад"],["collection.rutube","Сбор · Rutube","ok","последний аккаунт 31 мин назад"],
      ["ingest","Приём с Сервера 1","ok","последний пакет 1 мин назад"],["analysis","Очередь анализа","ok","отставание 6 мин, в очереди 12"],
      ["units","Службы","ok","все службы работают"],["disk","Диск","ok","свободно 14.4 ГБ (27%)"],["memory","Память","ok","занято 61%"],
      ["backup","Резервная копия","ok","последняя 9.2 ч назад"],["errors","Ошибки для людей","ok","0 ответов 5xx за час"]].map(([key,label,state,detail])=>({key,label,state,detail}));
    return json({range:week?"week":"day",sampledAt:asOf,checks,
      host:{cpuPercent:23.5,cores:2,load:[0.42,0.51,0.48],memoryTotalBytes:4*1024**3,memoryUsedBytes:2.5*1024**3,swapUsedBytes:0,diskTotalBytes:49*1024**3,diskFreeBytes:13.4*1024**3,unitsActive:24,unitsTotal:27,failedUnits:[]},
      pipeline:{ingestAcceptedAt:asOf,analysisLagSeconds:360,analysisBacklog:12,analysisCompletedAt:asOf,normsRunAt:asOf,tailRunAt:asOf,backupAt:asOf},
      restarts:{"m-ranked-target-web.service":1},
      collection:["telegram","vk","max","rutube"].map((platform,index)=>({platform,ok:5000+index*700,failed:index*12,lastOkAt:asOf})),series,
      backups:{files:[{name:"mranked-20260929T233150Z.dump",bytes:2527692123,at:asOf,verified:false},{name:"mranked-20260927T215949Z.dump",bytes:2411927328,at:asOf,verified:true}],running:false,partialBytes:null,requested:false,lastResult:"success",lastExitStatus:0}});
  }
  if(url.pathname.startsWith("/api/v1/admin/catalog/")) {
    const role=sessionRole;
    if(!role) return json({detail:"Требуется вход администратора"},401);
    if(url.pathname.endsWith("/session")) return json({headerName:"X-XSRF-TOKEN",token:"fixture-csrf-token",expiresAt:asOf,canEdit:role!=="viewer",canDelete:role==="admin"});
    const uuid=(index:number)=>`00000000-0000-4000-8000-${String(index).padStart(12,"0")}`;
    const ratings=Object.fromEntries(["all","telegram","vk","max","rutube"].map((platform)=>[platform,{rank:platform==="all"?2:null,score:platform==="all"?50:null}]));
    if(url.pathname.endsWith("/institutions")) return json({items:[1,2].map((id)=>({id:uuid(id),legacyId:id,name:names[id-1],shortName:id===1?"Альфа":"Бета",rowVersion:4,officialRatings:ratings,nextAccountAfter:null,accounts:["telegram","vk","max","rutube"].map((platform,index)=>({id:uuid(id*10+index),legacyId:id*10+index,channelId:platform==="telegram"?id:null,institutionId:uuid(id),platform,externalKey:`${platform}_${id}`,username:`${platform}_${id}`,title:`${platform} ${id}`,url:`https://example.test/${platform}/${id}`,accessMode:"public_api",legacyAccessMode:"public",lastErrorCode:null,enabled:true,rowVersion:7,nativeId:platform==="max"?`-123${id}`:null,subscribers:100}))})),nextAfter:null});
    if(url.pathname.endsWith("/status")) return json({channelCount:2,platformCount:8,institutionCount:2,mRating:{period:"2026-Q2",updatedAt:asOf,error:null},integrations:["telegram","vk","max","rutube"].map((platform)=>({platform,status:platform==="vk"?"missing":"configured",detail:`Источник ${platform}`})),storage:{diskTotalBytes:100*1024**3,diskFreeBytes:40*1024**3,projectBytes:4*1024**3,projectParts:{releasesBytes:1024**3,stateBytes:0.5*1024**3,pageCacheBytes:0.5*1024**3,measuredAt:asOf},databaseBytes:3*1024**3}});
    return json({detail:"Unknown fixture catalog route"},404);
  }
  const accountId=/^\/api\/v1\/accounts\/(\d+)$/.exec(url.pathname);
  if(accountId) return Number(accountId[1]) > 1000 ? json({title:"Not Found",status:404},404) : json(account(Number(accountId[1]),url.searchParams.get("legacyType") as "channels"|"platform_accounts"));
  const pubId=/^\/api\/v1\/publications\/(\d+)$/.exec(url.pathname);
  if(pubId) return json(publication(Number(pubId[1]),url.searchParams.get("legacyType") as "posts"|"platform_posts"));
  if(/^\/api\/v1\/accounts\/\d+\/publications$/.test(url.pathname)) {const day=url.searchParams.get("day");return json({items:[postItem(1,url.searchParams.get("legacyType") === "channels" ? "posts" : "platform_posts",day),postItem(2,"posts",day)],nextCursor:null,datasetRevision:revision,asOf} satisfies Schema["AccountPublicationPage"]);}
  // Уровни аккаунта: первый пост с выраженной аномалией, второй ещё не проанализирован.
  const levelsId=/^\/api\/v1\/accounts\/(\d+)\/anomaly-levels$/.exec(url.pathname);
  if(levelsId) {const type=url.searchParams.get("legacyType") === "channels" ? "posts" : "platform_posts";return json({accountId:uuid(1,Number(levelsId[1])),datasetRevision:revision,items:[{publicationId:publication(1,type).publicationId,level:2,levelLabel:"выраженная аномалия",levelSymbol:"◑"}]} satisfies Schema["AccountAnomalyLevels"]);}
  // Профиль позднего отклика: канал 1 — устойчиво необычный, остальные — воздержание.
  const tailId=/^\/api\/v1\/accounts\/(\d+)\/tail-profile$/.exec(url.pathname);
  if(tailId) {
    const accountNumber=Number(tailId[1]);
    const totals={posts:18,earlyViews:24000,earlyReactions:1300,lateViews:3100,lateReactions:520,earlyRate:0.0542,lateRate:0.1679,ratio:3.1};
    const days=Array.from({length:21},(_,index)=>({day:new Date(Date.parse("2026-09-08T00:00:00Z")+index*86400000).toISOString().slice(0,10),
      observed:index===5?0:12,active:index===5?0:index%3===0?2:9,reactions:index===5?0:index%3===0?2:14}));
    const computed=accountNumber===1;
    return json({accountId:uuid(1,accountNumber),datasetRevision:revision,status:"computed",computedFor:"2026-09-29",
      computedAt:asOf,platform:"telegram",level:computed?2:null,levelLabel:computed?"устойчиво необычный":"недостаточно данных",
      abstainReason:computed?null:"few_posts",
      metrics:{methodVersion:"account-tail-v1",windowStart:days[0]!.day,windowEnd:days[20]!.day,...totals,
        halves:{earlier:{...totals,ratio:2.8},recent:{...totals,ratio:3.4}},days,activeDays:19,activeWeeks:3,wideDays:12,
        breadth:{observed:120,expected:84.5,excess:1.42},roundedPosts:computed?18:0,
        cohort:{accounts:65,median:0.166,p90:0.736,threshold:0.736,rank:0.98},
        ...(computed?{}:{abstainText:"мало постов с точными замерами в первые сутки и после четырёх суток"})},
      history:[{computedFor:"2026-09-28",level:2,ratio:3.0},{computedFor:"2026-09-29",level:computed?2:null,ratio:3.1}],
      methodologyVersion:"account-tail-v1",
      disclaimer:"Поздний отклик сравнивается с другими аккаунтами площадки."} satisfies Schema["AccountTailProfile"]);
  }
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
  if (url.pathname === "/api/v1/overview") {
    const period = (url.searchParams.get("period") ?? "1d") as Schema["PeriodValue"];
    const items = url.searchParams.get("q") ? [] : (performanceFixture ? selectionIds.slice(0,50).map(id => item(id,platform,period)) : [item(1, platform,period), item(2, platform,period)]);
    if ((url.searchParams.get("sort") ?? "anomalies") === "anomalies") {
      const total = (row: Schema["OverviewRow"]) => (row.anomalyCounts?.level2 ?? 0) + (row.anomalyCounts?.level3 ?? 0);
      items.sort((a,b) => (total(a)-total(b)) * (url.searchParams.get("direction") === "asc" ? 1 : -1));
    } else if (url.searchParams.get("sort") === "views") {
      items.sort((a,b)=> (Number(a.views.total)-Number(b.views.total)) * (url.searchParams.get("direction") === "asc" ? 1 : -1));
    }
    return json({ items, nextCursor: null, datasetRevision: revision, asOf, integrationStatus: "unknown", integrationWarning: null } satisfies Schema["OverviewPage"]);
  }
  if (url.pathname === "/api/v1/site/summary") return json({ available: true, trackedInstitutions: 84, ratingInstitutions: 233, institutions: 12, accounts: 40,
    accountsByPlatform: { telegram: 11, vk: 12, max: 9, rutube: 8 }, publications: 1234, snapshots: 98765, computedAt: asOf });
  if (url.pathname === "/api/v1/sitemap") return json({ publicationPages: 1, publications: 2, datasetRevision: revision, asOf,
    accounts: [{ accountId: uuid(1,1), lastModified: "2026-07-07T00:00:00Z" }], institutions: [{ legacyId: 1 }, { legacyId: 2 }] });
  const sitemapPage = /^\/api\/v1\/sitemap\/publications\/(\d+)$/.exec(url.pathname);
  if (sitemapPage) return json({ page: Number(sitemapPage[1]), datasetRevision: revision, asOf, items: Number(sitemapPage[1]) === 0
    ? [{ publicationId: uuid(5,1), lastModified: "2026-07-07T15:00:00Z" }, { publicationId: uuid(5,2), lastModified: "2026-07-08T00:00:00Z" }] : [] });
  if (url.pathname === "/api/v1/compare/dashboard") return json(dashboard(url.searchParams.get("period") === "7d" ? "7d" : "30d"));
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
  if (url.pathname === "/api/v1/findings") {
    const mode = url.searchParams.get("mode") ?? "all";
    const institution = Number(url.searchParams.get("institution") ?? "0") || null;
    if (mode === "institution" && institution !== 1 && institution !== 2) {
      return json({ type: "about:blank", title: "Not Found", status: 404, detail: "вуз не найден" }, 404);
    }
    const platform = (url.searchParams.get("platform") ?? "all") as Schema["Findings"]["platform"];
    const empty = url.searchParams.get("q") === "missing";
    const group = (url.searchParams.get("group") ?? "none") as Schema["Findings"]["group"];
    const rowPlatform = platform === "all" ? "vk" : platform;
    const items = empty ? [] : Array.from({ length: 30 }, (_, index) => finding(index + 1, rowPlatform, mode === "institution" ? institution! : (index % 2) + 1));
    const body: Schema["Findings"] = {
      mode: mode as Schema["Findings"]["mode"], institution, platform,
      period: (url.searchParams.get("period") ?? "7d") as Schema["Findings"]["period"],
      types: url.searchParams.getAll("types") as Schema["Findings"]["types"],
      sort: (url.searchParams.get("sort") ?? "interaction_index") as Schema["Findings"]["sort"],
      direction: (url.searchParams.get("direction") ?? "desc") as Schema["Findings"]["direction"],
      group, q: url.searchParams.get("q") ?? "",
      anomalies: (url.searchParams.get("anomalies") ?? "exclude") as Schema["Findings"]["anomalies"],
      items: group === "none" ? items : [],
      groups: group === "institution" && !empty ? [1, 2].map((number) => ({
        institutionLegacyId: number, institutionShortName: `Вуз ${String(number).padStart(3, "0")}`,
        institutionCanonicalName: `Полное название университета ${String(number).padStart(3, "0")}`,
        findingCount: 15, items: items.filter((item) => item.institutionLegacyId === number).slice(0, 3),
      })) : [],
      total: items.length, hiddenAnomalous: empty ? 0 : 3,
      institutions: [1, 2].map((number) => ({ legacyId: number, shortName: `Вуз ${String(number).padStart(3, "0")}`, canonicalName: `Полное название университета ${String(number).padStart(3, "0")}` })),
      limit: 50, offset: 0, hasMore: false, nextCursor: null, datasetRevision: revision, asOf,
    };
    return json(body);
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
