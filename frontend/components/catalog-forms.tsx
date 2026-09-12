"use client";
import { useState, type ComponentProps } from "react";
import type { ManagedInstitution } from "@/lib/catalog-api";

export function DeleteCatalogForm(props:ComponentProps<"form">) {
  return <form {...props} onSubmit={(event)=>{if(!window.confirm("Удалить аккаунт и все собранные по нему данные? Восстановить их будет нельзя.")) event.preventDefault();}} />;
}
const fields=[{platform:"telegram",name:"telegram",label:"Telegram",placeholder:"@channel или t.me/channel"},{platform:"vk",name:"vk",label:"VK",placeholder:"vk.com/community"},{platform:"max",name:"max_account",label:"MAX",placeholder:"Ссылка или имя канала"},{platform:"rutube",name:"rutube",label:"Rutube",placeholder:"Ссылка или имя канала"}] as const;

export function AccountMatrix({institutions,selectedId,csrfToken,correlationId,canEdit}:{institutions:ManagedInstitution[];selectedId:number|null;csrfToken:string;correlationId:string;canEdit:boolean}) {
  const [selected,setSelected]=useState(selectedId ?? institutions[0]?.legacyId ?? null);
  const institution=institutions.find((row)=>row.legacyId===selected);
  const [generation,setGeneration]=useState(0);
  return <form className="platform-form account-matrix" method="post" id="accountMatrix" action={institution ? `/manage/institutions/${institution.legacyId}/accounts` : "/manage/institutions"}>
    <h3>Соцсети вуза</h3><p className="form-note">Выберите вуз: уже добавленные ссылки появятся в полях.</p>
    <label className="institution-select">Вуз<select id="matrixInstitution" required disabled={!canEdit||!institutions.length} value={selected ?? ""} onChange={(event)=>{setSelected(Number(event.target.value));setGeneration((value)=>value+1);}}>{institutions.map((row)=><option key={row.id} value={row.legacyId}>{row.shortName||row.name} ({row.name})</option>)}</select></label>
    <div className="account-fields" key={`${selected}:${generation}`}>{fields.map((field)=>{
      const account=institution?.accounts.find((row)=>row.platform===field.platform);
      const reference=account?.url || (account ? field.platform==="telegram" ? `@${account.username||account.externalKey}` : account.username||account.externalKey : "");
      return <label key={field.platform}><span className={`platform-chip${field.platform==="telegram" ? "" : ` platform-${field.platform}`}`}>{field.label}</span><input name={field.name} data-platform-field={field.platform} defaultValue={reference} placeholder={field.placeholder} disabled={!canEdit} /></label>;
    })}</div>
    <input type="hidden" name="csrf_token" value={csrfToken}/><input type="hidden" name="correlation_id" value={correlationId}/><input type="hidden" name="expected_row_version" value={institution?.rowVersion ?? 0}/><input type="hidden" name="expected_account_versions" value={JSON.stringify(Object.fromEntries(institution?.accounts.map((row)=>[row.id,row.rowVersion])??[]))}/>
    <button type="submit" disabled={!canEdit||!institution}>Сохранить аккаунты</button>
  </form>;
}
