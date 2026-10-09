"use client";

import { REGEXP_ONLY_DIGITS } from "input-otp";
import { InputOTP, InputOTPGroup, InputOTPSeparator, InputOTPSlot } from "@/components/ui/input-otp";

/** Шесть ячеек кода второго фактора. Под ячейками — обычный input с именем
 *  otp: форма отправляет его и без JavaScript, а вставка кода из буфера и
 *  автоподстановка one-time-code работают как в любом поле. */
export function OtpInput({ id, name }: { id: string; name: string }) {
  const slot = "size-10 text-base md:size-11";
  return (
    <InputOTP id={id} name={name} maxLength={6} pattern={REGEXP_ONLY_DIGITS} inputMode="numeric" autoComplete="one-time-code" required
      containerClassName="justify-center gap-2.5">
      <InputOTPGroup>
        {[0, 1, 2].map((index) => <InputOTPSlot key={index} index={index} className={slot} />)}
      </InputOTPGroup>
      <InputOTPSeparator />
      <InputOTPGroup>
        {[3, 4, 5].map((index) => <InputOTPSlot key={index} index={index} className={slot} />)}
      </InputOTPGroup>
    </InputOTP>
  );
}
