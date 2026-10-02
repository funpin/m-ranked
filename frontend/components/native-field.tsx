/**
 * A segmented control built from real radio inputs.
 *
 * The filter forms submit by GET and depend on the browser restoring their
 * controls on back and forward navigation. shadcn's Tabs and ToggleGroup keep
 * their state in Base UI, which form.reset() and assigning to checked cannot
 * drive, so this control keeps the radios and borrows the TabsList look.
 */
export function NativeSegments({ name, options, value, legend, labelled = true }: {
  name: string;
  legend: string;
  value: string;
  options: readonly { value: string; label: string; title?: string }[];
  /** В компактной панели подпись мешает: набор и так читается по значениям. */
  labelled?: boolean;
}) {
  return (
    <fieldset className="m-0 grid gap-1.5 border-0 p-0">
      <legend className="sr-only">{legend}</legend>
      {labelled ? <span className="text-muted-foreground text-sm font-medium" aria-hidden="true">{legend}</span> : null}
      <div data-testid={`${name}-segments`} className="bg-muted text-muted-foreground flex h-8 w-fit max-w-full items-center overflow-x-auto rounded-lg p-[3px]">
        {options.map((option) => (
          <label key={option.value} className="relative m-0 h-full shrink-0 cursor-pointer" title={option.title}>
            <input type="radio" name={name} value={option.value} defaultChecked={option.value === value} className="peer absolute opacity-0" />
            <span className="text-foreground/60 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground peer-checked:bg-background peer-checked:text-foreground dark:peer-checked:border-input dark:peer-checked:bg-input/30 peer-focus-visible:border-ring peer-focus-visible:ring-ring/50 grid h-full min-w-10 place-items-center rounded-md border border-transparent px-2.5 text-sm font-medium whitespace-nowrap peer-checked:shadow-sm peer-focus-visible:ring-[3px]">
              {option.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
