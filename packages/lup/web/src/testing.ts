// What a mount test stands in for. A surface is written against a browser
// with a server behind `fetch`, an event stream, a socket, a canvas the graph
// and the sign-in screen draw on, and a layout the virtualised lists measure
// themselves against. happy-dom supplies the document and the window and none
// of those, so each is a small fake here that a test installs and reads back
// — the requests a page made, the socket it opened, the stream it follows.
//
// Every fake satisfies the interface it stands in for, so installing one is a
// plain assignment the compiler checks: what a page may call on the real
// thing, it can call on the fake.
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

/** One request a page made, as the fixture server recorded it. */
export type Call = { method: string; path: string; search: string; body: unknown };

/** What a route answers: a body served as JSON, a Response served as is, or a function of the call returning either. */
export type Route = object | ((call: Call) => unknown);

/** A JSON reply with a status, for a route whose answer is not 200. */
export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * The server, keyed by the path a page fetches, relative to the page as the
 * surfaces spell it. A route nobody declared answers 404 with its path, so
 * a page reaching for something the fixture lacks fails saying which. Returns
 * the log every request lands in, in the order they were made.
 */
export function serve(routes: Record<string, Route>): Call[] {
  const calls: Call[] = [];
  const fetch = Object.assign(
    async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
      const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
      const call: Call = {
        method: init?.method ?? "GET",
        path: url.pathname.slice(1),
        search: url.search,
        body: typeof init?.body === "string" ? JSON.parse(init.body) : null,
      };
      calls.push(call);
      const route = routes[call.path];
      if (route === undefined) {
        return json({ detail: `no fixture serves ${call.path}` }, 404);
      }
      const answer = typeof route === "function" ? route(call) : route;
      return answer instanceof Response ? answer : json(answer);
    },
    // Bun's fetch warms a connection ahead of a request; a fixture server has
    // none to warm.
    { preconnect(): void {} },
  );
  globalThis.fetch = fetch;
  return calls;
}

/**
 * A listener as EventTarget takes one. A listener typed to the named event
 * is handed every event under that name as that event, which is the promise
 * the DOM's own overload makes and this one passes on.
 */
function listening<Named extends Event>(
  listener: EventListenerOrEventListenerObject | ((ev: Named) => void),
): EventListenerOrEventListenerObject {
  return typeof listener === "function" ? (ev: Event) => listener(ev as Named) : listener;
}

/**
 * An EventTarget that also takes a listener typed to one event, which the
 * DOM's stream interface offers under any event name and EventTarget's own
 * signature does not. The pages assign `on*` handlers rather than listen, so
 * nothing here does more than EventTarget already does.
 */
class Listened<Named extends Event> extends EventTarget {
  override addEventListener(
    type: string,
    listener: (ev: Named) => void,
    options?: boolean | AddEventListenerOptions,
  ): void;
  override addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | AddEventListenerOptions,
  ): void;
  override addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | ((ev: Named) => void),
    options?: boolean | AddEventListenerOptions,
  ): void {
    super.addEventListener(type, listening(listener), options);
  }

  override removeEventListener(
    type: string,
    listener: (ev: Named) => void,
    options?: boolean | EventListenerOptions,
  ): void;
  override removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | EventListenerOptions,
  ): void;
  override removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | ((ev: Named) => void),
    options?: boolean | EventListenerOptions,
  ): void {
    super.removeEventListener(type, listening(listener), options);
  }
}

/** The event stream a page follows, delivering what a test hands it. */
export class FakeEventSource extends Listened<MessageEvent> implements EventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static opened: FakeEventSource[] = [];
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;
  readonly url: string;
  readonly withCredentials = false;
  readyState = FakeEventSource.CONNECTING;
  onopen: EventSource["onopen"] = null;
  onerror: EventSource["onerror"] = null;
  onmessage: EventSource["onmessage"] = null;

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    FakeEventSource.opened.push(this);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }

  /** The stream connecting, which is when a page re-reads what it shows. */
  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.call(this, new Event("open"));
  }

  /** One entry arriving, as the server's `data:` line would carry it. */
  deliver(entry: unknown): void {
    this.onmessage?.call(this, new MessageEvent("message", { data: JSON.stringify(entry) }));
  }

  /** The stream not yet closed — React's strict mode opens and closes one first. */
  static current(): FakeEventSource {
    const live = FakeEventSource.opened.filter((source) => source.readyState !== FakeEventSource.CLOSED);
    const last = live[live.length - 1];
    if (last === undefined) throw new Error("no event stream is open");
    return last;
  }

  static install(): void {
    FakeEventSource.opened = [];
    globalThis.EventSource = FakeEventSource;
  }
}

/** The socket a streamed browser rides on, recording what the page sends. */
export class FakeWebSocket extends EventTarget implements WebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static opened: FakeWebSocket[] = [];
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;
  readonly url: string;
  readonly bufferedAmount = 0;
  readonly extensions = "";
  readonly protocol = "";
  binaryType: BinaryType = "blob";
  readyState: 0 | 1 | 2 | 3 = FakeWebSocket.OPEN;
  sent: string[] = [];
  onopen: WebSocket["onopen"] = null;
  onerror: WebSocket["onerror"] = null;
  onmessage: WebSocket["onmessage"] = null;
  onclose: WebSocket["onclose"] = null;

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    FakeWebSocket.opened.push(this);
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    if (typeof data !== "string") throw new Error("the screen sends its input as JSON text");
    this.sent.push(data);
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.call(this, new CloseEvent("close"));
  }

  /** One message from the server, as JSON. */
  deliver(message: unknown): void {
    this.onmessage?.call(this, new MessageEvent("message", { data: JSON.stringify(message) }));
  }

  static current(): FakeWebSocket {
    const open = FakeWebSocket.opened.filter((socket) => socket.readyState === FakeWebSocket.OPEN);
    const last = open[open.length - 1];
    if (last === undefined) throw new Error("no socket is open");
    return last;
  }

  static install(): void {
    FakeWebSocket.opened = [];
    globalThis.WebSocket = FakeWebSocket;
  }
}

// A context that answers every call is, statically, every kind of context at
// once: that is the type a Proxy taking any method has, and the one that
// satisfies each of `getContext`'s overloads.
type AnyContext = CanvasRenderingContext2D &
  ImageBitmapRenderingContext &
  WebGLRenderingContext &
  WebGL2RenderingContext;

/**
 * A 2D context that takes every call and measures every text as empty.
 * happy-dom's canvas has no context at all, and both cytoscape and the
 * sign-in screen refuse to draw without one.
 */
export function stubCanvas(): void {
  const held: Record<string | symbol, unknown> = {};
  const context = new Proxy({} as AnyContext, {
    get: (_target, key) => {
      if (key === "measureText") return () => ({ width: 0 });
      return held[key] ?? (() => undefined);
    },
    set: (_target, key, value) => {
      held[key] = value;
      return true;
    },
  });
  HTMLCanvasElement.prototype.getContext = () => context;
}

const VIEWPORT = { width: 1200, height: 4000 };
const ROW = 48;

/** A resize observer under a layout that never moves, so it never reports one. */
class StillLayout implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

/**
 * A layout, which happy-dom does not compute: every element measures as a
 * tall viewport, and one a virtualiser indexes measures as one row, so a
 * virtualised list holds every fixture row it is handed rather than the
 * none a zero-height viewport admits. happy-dom's own resize observer would
 * report every box as empty and undo that, so under this layout nothing
 * resizes. The window's observer is the one a list reaches through the
 * document, the global one what a bare name resolves to.
 */
export function stubLayout(): void {
  const height = (element: Element) => (element.hasAttribute("data-index") ? ROW : VIEWPORT.height);
  Element.prototype.getBoundingClientRect = function rect(this: Element): DOMRect {
    return new DOMRect(0, 0, VIEWPORT.width, height(this));
  };
  // A viewport is read off the box an element lays out, a row off its rect.
  const measuredWidth = { configurable: true, get: () => VIEWPORT.width };
  const measuredHeight = {
    configurable: true,
    get(this: HTMLElement) {
      return height(this);
    },
  };
  Object.defineProperties(HTMLElement.prototype, {
    offsetWidth: measuredWidth,
    offsetHeight: measuredHeight,
    clientWidth: measuredWidth,
    clientHeight: measuredHeight,
  });
  // A browser computes an unstyled length as 0px; happy-dom computes only
  // what a stylesheet declares, so one declares it, and cytoscape's box
  // arithmetic over the container's padding and border reads numbers.
  if (document.getElementById("layout") === null) {
    const sheet = document.createElement("style");
    sheet.id = "layout";
    sheet.textContent = "* { margin: 0; padding: 0; border: 0; }";
    document.head.append(sheet);
  }
  globalThis.ResizeObserver = StillLayout;
  window.ResizeObserver = StillLayout;
}

export type Mounted = { root: HTMLElement; unmount(): void };

/** The page, mounted into a `#root` the way each surface's `main.tsx` mounts it. */
export function mount(element: ReactNode): Mounted {
  const root = document.createElement("div");
  root.id = "root";
  document.body.append(root);
  const reactRoot = createRoot(root);
  act(() => reactRoot.render(element));
  return {
    root,
    unmount() {
      act(() => reactRoot.unmount());
      root.remove();
    },
  };
}

/** Lets every pending fetch, state update and timer land. */
export async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
}

/** Ticks the page until the condition holds, or fails naming what never appeared. */
export async function until(condition: () => boolean, what: string, ticks = 200): Promise<void> {
  for (let tick = 0; tick < ticks; tick += 1) {
    if (condition()) return;
    await settle();
  }
  throw new Error(`${what} never appeared; the page reads:\n${document.body.textContent ?? ""}`);
}

/** The one element the selector names, or a failure naming the selector. */
export function one<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const found = root.querySelector<T>(selector);
  if (found === null) throw new Error(`nothing matches ${selector}`);
  return found;
}

/** The text of every element the selector names, in document order. */
export function texts(root: ParentNode, selector: string): string[] {
  return [...root.querySelectorAll(selector)].map((element) => element.textContent ?? "");
}

/** The one element whose text is exactly this, among those the selector names. */
export function labelled<T extends Element = HTMLElement>(root: ParentNode, selector: string, text: string): T {
  const found = [...root.querySelectorAll<T>(selector)].find((element) => element.textContent === text);
  if (found === undefined) throw new Error(`no ${selector} reads ${JSON.stringify(text)}`);
  return found;
}

export async function click(element: HTMLElement): Promise<void> {
  await act(async () => element.click());
}

/** Types a value the way a keyboard would: through the native setter React watches, then an input event. */
export async function type(input: HTMLInputElement, value: string): Promise<void> {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (setter === undefined) throw new Error("HTMLInputElement has no value setter to type through");
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** Picks an option the way a reader would. */
export async function choose(select: HTMLSelectElement, value: string): Promise<void> {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

/**
 * Goes to a hash route the way the address bar does: the hash moves and the
 * browser announces it with a popstate, which happy-dom leaves to the test.
 */
export async function visit(path: string): Promise<void> {
  await act(async () => {
    window.location.hash = `#${path}`;
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}
