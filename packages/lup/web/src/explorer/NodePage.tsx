// One node in full: what it says, where it stands and why, its own fields,
// how much rests on it, and every edge in and out — each end a link, so the
// log is walked by clicking.
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { loadNode } from "./api";
import { nodeRoute } from "./router";
import type { EdgeView, NodeDetail } from "../generated/views";
import { Standing } from "./Standing";

function EdgeRow({ edge, end }: { edge: EdgeView; end: "source" | "target" }) {
  const other = end === "source" ? edge.source : edge.target;
  return (
    <li>
      <code>{edge.kind}</code>{" "}
      <Link to="/node/$id" params={{ id: other }}>
        {other}
      </Link>
    </li>
  );
}

function Detail({ detail }: { detail: NodeDetail }) {
  const fields = Object.entries(detail.fields);
  return (
    <article className="node">
      <header>
        <p className="kind">
          <code>{detail.node.kind}</code>
          {detail.node.slug !== "" && <code className="slug">{detail.node.slug}</code>}
          <code className="id">{detail.node.id}</code>
          <span className="muted">moved {detail.node.moved}</span>
        </p>
        <h1 className={detail.node.sound ? "" : "unsound"}>{detail.node.title}</h1>
        <Standing label={detail.node.standing} reason={detail.node.reason} sound={detail.node.sound} />
      </header>
      {detail.node.text !== "" && <p className="text">{detail.node.text}</p>}
      {fields.length > 0 && (
        <section>
          <h2>Fields</h2>
          <dl className="fields">
            {fields.map(([name, value]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>
                  <code>{JSON.stringify(value)}</code>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      <section>
        <h2>Weight</h2>
        {detail.incoming.length === 0 ? (
          <p className="muted">Nothing points at this node.</p>
        ) : (
          <ul className="counts">
            {detail.incoming.map((count) => (
              <li key={count.kind}>
                <strong>{count.count}</strong> <code>{count.kind}</code>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="edges">
        <div>
          <h2>Pointing at it</h2>
          {detail.edges_in.length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <ul>
              {detail.edges_in.map((edge) => (
                <EdgeRow key={`${edge.kind}:${edge.source}`} edge={edge} end="source" />
              ))}
            </ul>
          )}
        </div>
        <div>
          <h2>It points at</h2>
          {detail.edges_out.length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <ul>
              {detail.edges_out.map((edge) => (
                <EdgeRow key={`${edge.kind}:${edge.target}`} edge={edge} end="target" />
              ))}
            </ul>
          )}
        </div>
      </section>
      {detail.attachments.length > 0 && (
        <section>
          <h2>Attachments</h2>
          <ul>
            {detail.attachments.map((digest) => (
              <li key={digest}>
                <code>{digest}</code>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

export function NodePage() {
  const { id } = nodeRoute.useParams();
  const query = useQuery({ queryKey: ["node", id], queryFn: () => loadNode(id) });
  if (query.isPending) return <p className="muted">Reading {id}…</p>;
  if (query.isError) return <p className="error">{String(query.error)}</p>;
  return <Detail detail={query.data} />;
}
