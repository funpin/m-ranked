import { ArrowDownWideNarrow, ArrowUpWideNarrow } from "lucide-react";
import { NativeSegments } from "@/components/native-field";

export function SortDirection({ name, value, legend = "Порядок" }: {
  name: string; value: string; legend?: string;
}) {
  return <NativeSegments name={name} value={value} legend={legend} labelled={false} stretch options={[
    {value:"desc",label:"По убыванию",icon:<ArrowDownWideNarrow className="size-4" aria-hidden="true" />},
    {value:"asc",label:"По возрастанию",icon:<ArrowUpWideNarrow className="size-4" aria-hidden="true" />},
  ]} />;
}
