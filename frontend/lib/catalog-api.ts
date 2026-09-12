import createClient from "openapi-fetch";
import type {components,paths} from "../../contracts/openapi/m-ranked-v1-client";
export type ManagedAccount=components["schemas"]["AdminManagedAccount"];
export type ManagedInstitution=components["schemas"]["AdminManagedInstitution"];
export type OfficialRating=components["schemas"]["AdminOfficialRating"];
export type CatalogStatus=components["schemas"]["AdminCatalogStatus"];
export class CatalogApiError extends Error {constructor(readonly status:number,message:string){super(message);}}
type Fetcher=(input:string|URL,init?:RequestInit)=>Promise<Response>;

/** Per-request private reader. Authorization and cookies never enter a cache or a client component. */
export function catalogReader(incoming:Headers,fetcher:Fetcher=fetch,base=process.env.API_BASE_URL ?? "http://127.0.0.1:8080") {
  const origin=new URL(base);
  if(!["http:","https:"].includes(origin.protocol)||origin.username||origin.password) throw new Error("Invalid API origin");
  const headers=new Headers({Accept:"application/json"});
  for(const name of ["authorization","cookie"]) {const value=incoming.get(name);if(value) headers.set(name,value);}
  const client=createClient<paths>({baseUrl:origin.origin,headers,fetch:async(request)=>{
    try {return await fetcher(new URL(request.url),{method:request.method,headers:request.headers,cache:"no-store",redirect:"error",signal:AbortSignal.timeout(8000)});}
    catch {throw new CatalogApiError(0,"Административный API недоступен.");}
  }});
  async function request<T>(result:Promise<{data?:T;response:Response}>):Promise<T> {
    const {data,response}=await result;
    if(!response.ok) throw new CatalogApiError(response.status,response.status===403 ? "Недостаточно прав для просмотра каталога." : `Не удалось загрузить каталог: HTTP ${response.status}.`);
    if(data===undefined) throw new CatalogApiError(502,"API вернул пустой ответ каталога.");
    return data;
  }
  return {
    async institutions():Promise<ManagedInstitution[]> {
      let after=0;const items:ManagedInstitution[]=[];const seen=new Set<string>();
      for(let page=0;page<1000;page++) {
        const result=await request(client.GET("/api/v1/admin/catalog/institutions",{params:{query:{after,limit:200}}}));
        if(!Array.isArray(result.items)||result.items.length>200) throw new CatalogApiError(502,"API вернул некорректную страницу каталога.");
        for(const item of result.items) {
          if(seen.has(item.id)||!Number.isSafeInteger(item.legacyId)||item.legacyId<=after||!Number.isSafeInteger(item.rowVersion)||item.rowVersion<0||!Array.isArray(item.accounts)) throw new CatalogApiError(502,"Каталог изменился во время чтения. Обновите страницу.");
          seen.add(item.id);
          let accountAfter=item.nextAccountAfter;
          const accounts=[...item.accounts];const accountIds=new Set(accounts.map((account)=>account.id));
          for(let accountPage=0;accountAfter!=null;accountPage++) {
            if(accountPage>=1000) throw new CatalogApiError(502,"Список аккаунтов превысил допустимый размер чтения.");
            const page=await request(client.GET("/api/v1/admin/catalog/institutions/{id}/accounts",{params:{path:{id:item.id},query:{after:accountAfter,limit:200}}}));
            if(!Array.isArray(page.items)||page.items.length>200) throw new CatalogApiError(502,"Некорректная страница аккаунтов.");
            for(const account of page.items) {
              if(accountIds.has(account.id)||account.institutionId!==item.id) throw new CatalogApiError(502,"Каталог изменился во время чтения аккаунтов.");
              accountIds.add(account.id);accounts.push(account);
            }
            if(page.nextAfter!==null&&(!Number.isSafeInteger(page.nextAfter)||page.nextAfter<=accountAfter)) throw new CatalogApiError(502,"Некорректное продолжение аккаунтов.");
            accountAfter=page.nextAfter;
          }
          items.push({...item,accounts,nextAccountAfter:null});
        }
        if(result.nextAfter===null) return items;
        if(!Number.isSafeInteger(result.nextAfter)||result.nextAfter<=after) throw new CatalogApiError(502,"API вернул некорректное продолжение каталога.");
        after=result.nextAfter;
      }
      throw new CatalogApiError(502,"Каталог превысил допустимый размер чтения. Полный список не загружен.");
    },
    status:()=>request(client.GET("/api/v1/admin/catalog/status")),
  };
}
