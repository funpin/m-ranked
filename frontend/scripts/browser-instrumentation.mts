import type { Page } from "@playwright/test";
import assert from "node:assert/strict";

// Plain JavaScript is intentional: serialized TSX callbacks can contain an outer
// __name helper that does not exist in the browser's execution context.
export function visualInitScript(clock:string):{content:string} {
  const now=Date.parse(clock);
  if(!Number.isFinite(now))throw new Error("Visual fixture clock must be valid");
  return {content:`(() => {
    try { localStorage.setItem("m-ranked-theme", "dark"); } catch {}
    const now = ${now};
    const NativeDate = window.Date;
    window.Date = new Proxy(NativeDate, {
      construct(target, args, newTarget) { return Reflect.construct(target, args.length ? args : [now], newTarget); },
      apply() { return new NativeDate(now).toString(); },
      get(target, key, receiver) { return key === "now" ? () => now : Reflect.get(target, key, receiver); }
    });
    const state = { initialized: false, clock: now, supported: PerformanceObserver.supportedEntryTypes.includes("layout-shift"), cls: 0 };
    window.__visualCapture = state;
    if (!state.supported) throw new Error("Layout Shift observer is unavailable");
    let sessionStart = 0, lastShift = 0, sessionValue = 0;
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        if (entry.startTime - lastShift < 1000 && entry.startTime - sessionStart < 5000) sessionValue += entry.value;
        else { sessionStart = entry.startTime; sessionValue = entry.value; }
        lastShift = entry.startTime;
        state.cls = Math.max(state.cls, sessionValue);
      }
    }).observe({ type: "layout-shift", buffered: true });
    state.initialized = true;
  })();`};
}

// A fixed wall clock must never leave Chart.js in a perpetual animation. This
// legacy-only still-capture hook runs before the original local library loads.
// It does not rewrite the library, data, scales, callbacks or pointer selection.
export const legacyChartStillInit={content:`(() => {
  let library = window.Chart;
  const state = { installed: true, assignments: 0, configured: false };
  window.__legacyChartStill = state;
  function configure(value) {
    if (value && value.defaults) { value.defaults.animation = false; state.configured = true; }
    return value;
  }
  configure(library);
  Object.defineProperty(window, "Chart", {
    configurable: true, enumerable: true,
    get() { return library; },
    set(value) { state.assignments++; library = configure(value); }
  });
})();`};

export type VisualCaptureState={initialized:boolean;clock:number;supported:boolean;cls:number;now:number};
export async function readVisualState(page:Page,clock:string):Promise<VisualCaptureState> {
  const state=await page.evaluate(`(() => {
    const state = window.__visualCapture;
    if (!state || !state.initialized || !state.supported || !Number.isFinite(state.cls))
      throw new Error("Visual clock/CLS instrumentation did not initialize");
    return { ...state, now: Date.now() };
  })()`) as VisualCaptureState;
  assert.equal(state.clock,Date.parse(clock),"Visual observer is bound to a different fixture clock");
  assert.equal(state.now,state.clock,"Visual browser clock was not frozen");
  return state;
}

// Only animation is disabled for final-state stills. Data, axes, tooltip content
// and point selection are unchanged. Performance runs never use this helper.
export async function settleLegacyCharts(page:Page):Promise<number> {
  return page.evaluate(`(() => {
    const charts = Object.values(window.Chart?.instances ?? {});
    for (const chart of charts) {
      chart.stop();
      chart.options.animation = false;
      chart.update("none");
    }
    return charts.length;
  })()`);
}

export const mobileObserverInit={content:`(() => {
  const supported = ["largest-contentful-paint", "layout-shift", "event"].every(name => PerformanceObserver.supportedEntryTypes.includes(name));
  const metrics = { initialized: false, supported, lcp: 0, cls: 0, interactions: {} };
  window.__mobileLab = metrics;
  if (!supported) throw new Error("Required mobile PerformanceObserver entries are unavailable");
  new PerformanceObserver(list => { for (const entry of list.getEntries()) metrics.lcp = entry.startTime; }).observe({type:"largest-contentful-paint",buffered:true});
  let sessionStart=0,lastShift=0,sessionValue=0;
  new PerformanceObserver(list => {
    for (const entry of list.getEntries()) {
      if (entry.hadRecentInput) continue;
      if (entry.startTime-lastShift<1000 && entry.startTime-sessionStart<5000) sessionValue+=entry.value;
      else { sessionStart=entry.startTime; sessionValue=entry.value; }
      lastShift=entry.startTime;
      metrics.cls=Math.max(metrics.cls,sessionValue);
    }
  }).observe({type:"layout-shift",buffered:true});
  new PerformanceObserver(list => {
    for (const entry of list.getEntries()) if (entry.interactionId)
      metrics.interactions[String(entry.interactionId)] = Math.max(metrics.interactions[String(entry.interactionId)] ?? 0,entry.duration);
  }).observe({type:"event",buffered:true,durationThreshold:16});
  metrics.initialized = true;
})();`};

export type MobileMetrics={initialized:boolean;supported:boolean;lcp:number;cls:number;interactions:Record<string,number>};
export async function readMobileMetrics(page:Page):Promise<MobileMetrics> {
  const metrics=await page.evaluate(`(() => {
    const metrics=window.__mobileLab;
    if (!metrics || !metrics.initialized || !metrics.supported || !Number.isFinite(metrics.lcp) || !Number.isFinite(metrics.cls))
      throw new Error("Mobile performance instrumentation did not initialize");
    return metrics;
  })()`) as MobileMetrics;
  return metrics;
}
