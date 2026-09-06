export type VisualCredentials={username:string;password:string};

export function visualCredentials(environment:Readonly<Record<string,string|undefined>>,prefix:"LEGACY"|"TARGET"):VisualCredentials|null {
  const username=environment[`${prefix}_ADMIN_USERNAME`],password=environment[`${prefix}_ADMIN_PASSWORD`];
  if(!username&&!password)return null;
  if(!username||!password)throw new Error(`${prefix}_ADMIN_USERNAME and ${prefix}_ADMIN_PASSWORD must be supplied together`);
  return {username,password};
}

/** Screenshots remain unmasked. Only secrets in text artifacts are replaced. */
export function redactVisualEvidence(value:string,secrets:readonly string[]):string {
  for(const secret of [...new Set(secrets)].filter(Boolean).sort((a,b)=>b.length-a.length)) {
    const variants=new Set([secret,encodeURIComponent(secret),secret.replaceAll("&","&amp;").replaceAll('"',"&quot;").replaceAll("<","&lt;").replaceAll(">","&gt;")]);
    let escaped=secret,scriptEscaped=secret.replace(/[<>&\u2028\u2029]/g,(char)=>`\\u${char.charCodeAt(0).toString(16).padStart(4,"0")}`);
    for(let layer=0;layer<3;layer++){escaped=JSON.stringify(escaped).slice(1,-1);variants.add(escaped);variants.add(scriptEscaped);scriptEscaped=JSON.stringify(scriptEscaped).slice(1,-1);}
    for(const variant of [...variants].sort((a,b)=>b.length-a.length)) {
      value=value.replaceAll(variant,"[REDACTED_SECRET]");
    }
  }
  return value;
}
