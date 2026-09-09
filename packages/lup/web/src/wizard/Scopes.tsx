// The selector is drawn only where there is a choice to make, and the create
// affordance only where the project declared a label for it — a deployment
// with one scope it did not name should see neither.
import { useState } from "react";
import type { WizardView } from "../generated/views";

export function Scopes({
  view,
  onChoose,
  onMake,
}: {
  view: WizardView;
  onChoose(name: string): void;
  onMake(name: string): void;
}) {
  const [name, setName] = useState("");
  const labelled = view.scopes.length > 1 || view.creates !== "";
  return (
    <div className="scopes">
      {labelled && <span>{(view.scope_label !== "" ? view.scope_label : "Scope") + ":"}</span>}
      {view.scopes.map((choice) => (
        <button
          key={choice.name}
          type="button"
          className={choice.chosen ? "tab on" : "tab"}
          title={choice.detail}
          onClick={() => onChoose(choice.name)}
        >
          {choice.label}
        </button>
      ))}
      {view.creates !== "" && (
        <>
          <input
            value={name}
            placeholder={view.create_asks !== "" ? view.create_asks : "Name"}
            style={{ maxWidth: "11rem" }}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onMake(name.trim());
            }}
          />
          <button type="button" onClick={() => onMake(name.trim())}>
            {view.creates}
          </button>
        </>
      )}
    </div>
  );
}
