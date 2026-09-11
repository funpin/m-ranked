import type { AnchorHTMLAttributes } from "react";

type NativeLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  prefetch?: boolean;
  scroll?: boolean;
};

/** Full-page navigation avoids speculative RSC requests against the bounded API. */
export default function NativeLink({ href, prefetch, scroll, ...props }: NativeLinkProps) {
  void prefetch;
  void scroll;
  return <a href={href} {...props} />;
}
