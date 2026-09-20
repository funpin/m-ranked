import logoMarkDark from "../assets/logo-mark-dark.svg";
import logoMarkLight from "../assets/logo-mark-light.svg";

/**
 * Narrow screens only have room for the mark. On desktop the name is real
 * text instead of raster-traced letter outlines: it stays crisp at every
 * zoom level and uses the same Geologica face as the rest of the interface.
 */
export function BrandLogo() {
  return (
    <span className="text-foreground inline-flex h-7 shrink-0 items-center gap-2" aria-hidden="true">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img data-testid="brand-logo-mark-light" src={logoMarkLight.src} alt="" className="size-7 object-contain dark:hidden" />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img data-testid="brand-logo-mark-dark" src={logoMarkDark.src} alt="" className="hidden size-7 object-contain dark:block" />
      <strong data-testid="brand-logo-wordmark" className="font-heading hidden text-base font-bold tracking-tight min-[781px]:inline">
        m-ranked
      </strong>
    </span>
  );
}
