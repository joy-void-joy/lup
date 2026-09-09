// The five routes the wizard answers, each typed against the model the
// server declares. Every route that changes anything replies with the page as
// it stands afterwards, so a component never draws from what it assumed.
import type {
  RowRequest,
  ScopeRequest,
  StepAnswers,
  StepReply,
  WizardView,
} from "../generated/views";

/** The scope a request carries, as the query string the routes read it from. */
export function scopeQuery(scope: string): string {
  return scope === "" ? "" : `?scope=${encodeURIComponent(scope)}`;
}

async function checked<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function readView(scope: string): Promise<WizardView> {
  return checked<WizardView>(await fetch(`api/wizard${scopeQuery(scope)}`));
}

async function post<T>(path: string, body: StepAnswers | RowRequest | ScopeRequest | Record<string, never>): Promise<T> {
  return checked<T>(
    await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

function stepPath(scope: string, slug: string, verb: string): string {
  return `api/wizard/${encodeURIComponent(slug)}/${verb}${scopeQuery(scope)}`;
}

export function runStep(scope: string, slug: string, answers: StepAnswers): Promise<StepReply> {
  return post<StepReply>(stepPath(scope, slug, "run"), answers);
}

export function testStep(scope: string, slug: string): Promise<StepReply> {
  return post<StepReply>(stepPath(scope, slug, "test"), {});
}

export function resetStep(scope: string, slug: string): Promise<StepReply> {
  return post<StepReply>(stepPath(scope, slug, "reset"), {});
}

export function actOnRow(scope: string, slug: string, request: RowRequest): Promise<StepReply> {
  return post<StepReply>(stepPath(scope, slug, "act"), request);
}

export function makeScope(request: ScopeRequest): Promise<StepReply> {
  return post<StepReply>("api/scopes", request);
}
