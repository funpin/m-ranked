"use client";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import dynamic from "next/dynamic";
import { PlatformChip } from "@/components/platform-chip";
import { useRef, useState, useSyncExternalStore, type ComponentProps, type ReactNode } from "react";
import { Building2, Plus } from "lucide-react";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
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

const subscribeNever = () => () => {};

/** Внутри модального окна у формы нет своей рамки и заголовка: их даёт окно.
 *  Кнопка отправки стоит в подвале рядом с «Отменой». */
type Layout = { inDialog?: boolean; cancel?: ReactNode };

function FormFooter({ inDialog, cancel, children }: Layout & { children: ReactNode }) {
  if (!inDialog) return <>{children}</>;
  return <div className="mt-2 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{cancel}{children}</div>;
}

export function AccountMatrix({institutions,selectedId,csrfToken,correlationId,canEdit,inDialog=false,cancel}:{institutions:ManagedInstitution[];selectedId:number|null;csrfToken:string;correlationId:string;canEdit:boolean}&Layout) {
  const [selected,setSelected]=useState(selectedId ?? institutions[0]?.legacyId ?? null);
  const institution=institutions.find((row)=>row.legacyId===selected);
  const [generation,setGeneration]=useState(0);
  return <form className={cn("grid content-start gap-3 [&_label]:grid [&_label]:gap-1.5 [&_label]:text-sm", !inDialog && "rounded-lg border bg-muted/20 p-4")} method="post" id="accountMatrix" action={institution ? `/manage/institutions/${institution.legacyId}/accounts` : "/manage/institutions"}>
    {inDialog ? null : <><h3 className="font-heading text-base font-semibold">Соцсети вуза</h3><p className="text-xs leading-relaxed text-muted-foreground">Выберите вуз: уже добавленные ссылки появятся в полях.</p></>}
    <Label className="grid gap-1.5 text-sm leading-normal font-normal">Вуз<NativeSelect className="w-full" id="matrixInstitution" required disabled={!canEdit||!institutions.length} value={selected ?? ""} onChange={(event)=>{setSelected(Number(event.target.value));setGeneration((value)=>value+1);}}>{institutions.map((row)=><NativeSelectOption key={row.id} value={row.legacyId}>{row.shortName||row.name} ({row.name})</NativeSelectOption>)}</NativeSelect></Label>
    <div className="grid gap-3 sm:grid-cols-2" key={`${selected}:${generation}`}>{fields.map((field)=>{
      const account=institution?.accounts.find((row)=>row.platform===field.platform);
      const reference=account?.url || (account ? field.platform==="telegram" ? `@${account.username||account.externalKey}` : account.username||account.externalKey : "");
      return <Label key={field.platform} className="grid gap-1.5 text-sm leading-normal font-normal"><PlatformChip className="w-fit" platform={field.platform} label={field.label} /><Input name={field.name} data-platform-field={field.platform} defaultValue={reference} placeholder={field.placeholder} disabled={!canEdit} /></Label>;
    })}</div>
    <input type="hidden" name="csrf_token" value={csrfToken}/><input type="hidden" name="correlation_id" value={correlationId}/><input type="hidden" name="expected_row_version" value={institution?.rowVersion ?? 0}/><input type="hidden" name="expected_account_versions" value={JSON.stringify(Object.fromEntries(institution?.accounts.map((row)=>[row.id,row.rowVersion])??[]))}/>
    <FormFooter inDialog={inDialog} cancel={cancel}><Button type="submit" disabled={!canEdit||!institution}>Сохранить аккаунты</Button></FormFooter>
  </form>;
}

export function NewInstitutionForm({csrfToken,correlationId,canEdit,inDialog=false,cancel}:{csrfToken:string;correlationId:string;canEdit:boolean}&Layout) {
  return <form data-testid="institution-create" method="post" action="/manage/institutions"
    className={cn("grid content-start gap-3 [&_label]:grid [&_label]:gap-1.5 [&_label]:text-sm", !inDialog && "rounded-lg border bg-muted/20 p-4")}>
    {inDialog ? null : <><h3 className="font-heading text-base font-semibold">Новый вуз</h3><p className="text-xs leading-relaxed text-muted-foreground">Полное название показывается в подсказках, сокращение — в компактных карточках.</p></>}
    <Label className="grid gap-1.5 text-sm leading-normal font-normal">Полное название<Input name="name" required placeholder="Полное официальное название" disabled={!canEdit} /></Label>
    <Label className="grid gap-1.5 text-sm leading-normal font-normal">Сокращение<Input name="short_name" placeholder="Например, ВВГУ" disabled={!canEdit} /></Label>
    <input type="hidden" name="csrf_token" value={csrfToken}/><input type="hidden" name="expected_row_version" value={0}/><input type="hidden" name="correlation_id" value={correlationId}/>
    <FormFooter inDialog={inDialog} cancel={cancel}><Button type="submit" disabled={!canEdit}>Добавить вуз</Button></FormFooter>
  </form>;
}

function CatalogDialog({ label, icon, title, description, testId, children }: {
  label: string; icon: ReactNode; title: string; description: string; testId: string;
  children: (cancel: ReactNode) => ReactNode;
}) {
  return <Dialog>
    <DialogTrigger data-testid={testId} render={<Button variant="outline" size="lg" />}>{icon}{label}</DialogTrigger>
    <DialogContent className="sm:max-w-xl">
      <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
      {children(<DialogClose render={<Button variant="outline" />}>Отмена</DialogClose>)}
    </DialogContent>
  </Dialog>;
}

/**
 * Формы каталога — в модальных окнах: на странице только две кнопки, поля
 * появляются по нажатию. Без скриптов окна не откроются, поэтому до
 * гидратации обе формы стоят на странице, как раньше, и отправляются обычным
 * POST; с медиа-запросом scripting они скрыты сразу, без мелькания.
 */
export function CatalogDialogs({institutions,selectedId,csrfToken,correlationIds,canEdit}:{institutions:ManagedInstitution[];selectedId:number|null;csrfToken:string;correlationIds:[string,string];canEdit:boolean}) {
  const hydrated = useSyncExternalStore(subscribeNever, () => true, () => false);
  return <>
    {hydrated ? null : <div className="my-5 grid gap-5 lg:grid-cols-2 [@media(scripting:enabled)]:hidden">
      <AccountMatrix institutions={institutions} selectedId={selectedId} csrfToken={csrfToken} correlationId={correlationIds[0]} canEdit={canEdit} />
      <NewInstitutionForm csrfToken={csrfToken} correlationId={correlationIds[1]} canEdit={canEdit} />
    </div>}
    <div className="my-5 hidden flex-wrap gap-2 [@media(scripting:enabled)]:flex">
      <CatalogDialog testId="open-account-matrix" label="Соцсети вуза" icon={<Building2 data-icon="inline-start" aria-hidden="true" />}
        title="Соцсети вуза" description="Выберите вуз: уже добавленные ссылки появятся в полях.">
        {(cancel) => <AccountMatrix institutions={institutions} selectedId={selectedId} csrfToken={csrfToken} correlationId={correlationIds[0]} canEdit={canEdit} inDialog cancel={cancel} />}
      </CatalogDialog>
      <CatalogDialog testId="open-institution-create" label="Новый вуз" icon={<Plus data-icon="inline-start" aria-hidden="true" />}
        title="Новый вуз" description="Полное название показывается в подсказках, сокращение — в компактных карточках.">
        {(cancel) => <NewInstitutionForm csrfToken={csrfToken} correlationId={correlationIds[1]} canEdit={canEdit} inDialog cancel={cancel} />}
      </CatalogDialog>
    </div>
  </>;
}
