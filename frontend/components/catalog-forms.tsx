"use client";
import { NativeButton } from "@/components/native-field";
import { NativeSelect } from "@/components/native-field";
import { NativeInput as Input } from "@/components/native-field";
import dynamic from "next/dynamic";
import { PlatformChip } from "@/components/platform-chip";
import { useRef, useState, type ComponentProps } from "react";
import type { ManagedInstitution } from "@/lib/catalog-api";

const DeleteDialog = dynamic(() => import("./catalog-delete-dialog"), { ssr: false });

export function DeleteCatalogForm(props: ComponentProps<"form">) {
  const form = useRef<HTMLFormElement>(null);
  const submitter = useRef<HTMLButtonElement | HTMLInputElement | null>(null);
  const approved = useRef(false);
  const [open, setOpen] = useState(false);
  return <>
    <form {...props} ref={form} onSubmit={(event) => {
      props.onSubmit?.(event);
      if (event.defaultPrevented || approved.current) return;
      event.preventDefault();
      submitter.current = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | HTMLInputElement | null;
      setOpen(true);
    }} />
    {open ? <DeleteDialog onCancel={() => {
      setOpen(false);
      submitter.current?.focus();
    }} onConfirm={() => {
      approved.current = true;
      form.current?.requestSubmit(submitter.current);
      approved.current = false;
      setOpen(false);
    }} /> : null}
  </>;
}
const fields=[{platform:"telegram",name:"telegram",label:"Telegram",placeholder:"@channel или t.me/channel"},{platform:"vk",name:"vk",label:"VK",placeholder:"vk.com/community"},{platform:"max",name:"max_account",label:"MAX",placeholder:"Ссылка или имя канала"},{platform:"rutube",name:"rutube",label:"Rutube",placeholder:"Ссылка или имя канала"}] as const;

export function AccountMatrix({institutions,selectedId,csrfToken,correlationId,canEdit}:{institutions:ManagedInstitution[];selectedId:number|null;csrfToken:string;correlationId:string;canEdit:boolean}) {
  const [selected,setSelected]=useState(selectedId ?? institutions[0]?.legacyId ?? null);
  const institution=institutions.find((row)=>row.legacyId===selected);
  const [generation,setGeneration]=useState(0);
  return <form className="grid content-start gap-3 rounded-lg border bg-muted/20 p-4 [&_label]:grid [&_label]:gap-1.5 [&_label]:text-sm" method="post" id="accountMatrix" action={institution ? `/manage/institutions/${institution.legacyId}/accounts` : "/manage/institutions"}>
    <h3 className="font-heading text-base font-semibold">Соцсети вуза</h3><p className="text-xs leading-relaxed text-muted-foreground">Выберите вуз: уже добавленные ссылки появятся в полях.</p>
    <label>Вуз<NativeSelect id="matrixInstitution" required disabled={!canEdit||!institutions.length} value={selected ?? ""} onChange={(event)=>{setSelected(Number(event.target.value));setGeneration((value)=>value+1);}}>{institutions.map((row)=><option key={row.id} value={row.legacyId}>{row.shortName||row.name} ({row.name})</option>)}</NativeSelect></label>
    <div className="grid gap-3 sm:grid-cols-2" key={`${selected}:${generation}`}>{fields.map((field)=>{
      const account=institution?.accounts.find((row)=>row.platform===field.platform);
      const reference=account?.url || (account ? field.platform==="telegram" ? `@${account.username||account.externalKey}` : account.username||account.externalKey : "");
      return <label key={field.platform}><PlatformChip className="w-fit" platform={field.platform} label={field.label} /><Input name={field.name} data-platform-field={field.platform} defaultValue={reference} placeholder={field.placeholder} disabled={!canEdit} /></label>;
    })}</div>
    <input type="hidden" name="csrf_token" value={csrfToken}/><input type="hidden" name="correlation_id" value={correlationId}/><input type="hidden" name="expected_row_version" value={institution?.rowVersion ?? 0}/><input type="hidden" name="expected_account_versions" value={JSON.stringify(Object.fromEntries(institution?.accounts.map((row)=>[row.id,row.rowVersion])??[]))}/>
    <NativeButton type="submit" disabled={!canEdit||!institution}>Сохранить аккаунты</NativeButton>
  </form>;
}
